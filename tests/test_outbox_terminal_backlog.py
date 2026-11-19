# -*- coding: utf-8 -*-
"""Terminal outbox backlog visibility (2026-11-18 post-C1 audit, P1).

Rows at retry_count >= OUTBOX_MAX_RETRIES are never replayed and pending_count()
does not show them. These tests pin: the terminal rows are visible, pending_count()
keeps its meaning, no Firebase write results from reporting, and the same trade key
under paper_open/paper_close is two events, not a duplicate trade.
"""
import logging
import sqlite3
from unittest.mock import MagicMock

import pytest

from src.services.v5_legacy_bridge import config
from src.services.v5_legacy_bridge.outbox import DurableOutbox
from src.services.v5_legacy_bridge.outbox_flush_worker import OutboxFlushWorker


@pytest.fixture
def outbox(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(config, "V5_OUTBOX_DB_PATH", str(tmp_path / "outbox.sqlite"))
    return DurableOutbox()


def _set_retry(outbox, event_type, key, retry, created_at=None):
    conn = sqlite3.connect(outbox.db_path)
    conn.execute("UPDATE outbox SET retry_count=?, created_at=COALESCE(?, created_at) "
                 "WHERE event_type=? AND idempotency_key=?", (retry, created_at, event_type, key))
    conn.commit()
    conn.close()


def _seed(outbox):
    for event_type in ("paper_open", "paper_close", "learning_update"):
        assert outbox.enqueue(event_type, "paper_abc", {"trade_id": "paper_abc", "t": event_type})
    assert outbox.enqueue("paper_open", "paper_new", {"trade_id": "paper_new"})
    terminal = config.OUTBOX_MAX_RETRIES
    _set_retry(outbox, "paper_open", "paper_abc", terminal, "2026-06-02T10:29:05.000000")
    _set_retry(outbox, "paper_close", "paper_abc", terminal + 1, "2026-08-29T06:49:03.000000")
    _set_retry(outbox, "learning_update", "paper_abc", terminal)


def test_terminal_rows_are_visible_and_pending_count_unchanged(outbox):
    _seed(outbox)
    assert outbox.pending_count() == 1  # unchanged meaning: only replay-eligible rows
    stats = outbox.backlog_stats()
    assert stats["replayable_pending"] == 1
    assert stats["terminal_unsynced"] == 3
    assert stats["by_type"]["paper_open"] == {"replayable": 1, "terminal": 1}
    assert stats["by_type"]["paper_close"] == {"replayable": 0, "terminal": 1}
    assert stats["by_type"]["learning_update"] == {"replayable": 0, "terminal": 1}
    assert stats["oldest_terminal_created_at"] == "2026-06-02T10:29:05.000000"
    assert stats["oldest_terminal_age_s"] > 0
    assert stats["max_retries"] == config.OUTBOX_MAX_RETRIES


def test_stats_contain_no_ids_or_payloads(outbox):
    _seed(outbox)
    text = repr(outbox.backlog_stats())
    assert "paper_abc" not in text and "paper_new" not in text and "trade_id" not in text


def test_same_key_across_open_and_close_is_not_a_duplicate(outbox):
    _seed(outbox)
    # UNIQUE(event_type, idempotency_key): one trade's open/close/learning are three events.
    conn = sqlite3.connect(outbox.db_path)
    dup = conn.execute("SELECT COUNT(*) FROM (SELECT event_type, idempotency_key, COUNT(*) c "
                       "FROM outbox GROUP BY 1, 2 HAVING c > 1)").fetchone()[0]
    conn.close()
    assert dup == 0
    stats = outbox.backlog_stats()
    assert stats["terminal_unsynced"] + stats["replayable_pending"] == 4  # 4 rows, 2 trades
    # Re-enqueueing the same (type, key) is ignored (INSERT OR IGNORE): counts stay the same.
    # Compare counts only -- oldest_terminal_age_s grows with wall time (was a flaky check).
    outbox.enqueue("paper_open", "paper_abc", {"again": True})
    after = outbox.backlog_stats()
    assert (after["terminal_unsynced"], after["replayable_pending"], after["by_type"]) == \
        (stats["terminal_unsynced"], stats["replayable_pending"], stats["by_type"])


def test_reporting_never_writes_to_firebase_or_replays_terminal_rows(outbox, caplog):
    _seed(outbox)
    writer = MagicMock()
    writer.firebase_client = MagicMock()
    worker = OutboxFlushWorker(outbox, writer)
    with caplog.at_level(logging.WARNING):
        worker._report_terminal_backlog()
        worker._report_terminal_backlog()  # unchanged count -> no second line
        status = worker.get_status()
    lines = [r.getMessage() for r in caplog.records if "[V5_BRIDGE_OUTBOX_TERMINAL]" in r.getMessage()]
    assert len(lines) == 1
    assert "terminal_unsynced=3" in lines[0] and "paper_abc" not in lines[0]
    assert status["terminal_unsynced"] == 3 and status["pending_count"] == 1
    assert status["terminal_by_type"] == {"paper_open": 1, "paper_close": 1, "learning_update": 1}
    writer.flush_outbox.assert_not_called()
    writer.firebase_client.set.assert_not_called()
    # get_pending (the replay source) still excludes terminal rows.
    assert [e.idempotency_key for e in outbox.get_pending(limit=100)] == ["paper_new"]


def test_worker_start_reports_terminal_backlog_once(outbox, caplog, monkeypatch):
    import threading
    _seed(outbox)
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)  # no real flush loop
    writer = MagicMock()
    worker = OutboxFlushWorker(outbox, writer)
    with caplog.at_level(logging.WARNING):
        worker.start()
    lines = [r.getMessage() for r in caplog.records if "[V5_BRIDGE_OUTBOX_TERMINAL]" in r.getMessage()]
    assert len(lines) == 1 and "terminal_unsynced=3" in lines[0]
    writer.flush_outbox.assert_not_called()


def test_stats_fail_soft_on_db_error(outbox, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", boom)
    stats = outbox.backlog_stats()
    assert stats["error"] == "OperationalError" and stats["terminal_unsynced"] == 0
    # The status must expose the failure instead of a silent zero backlog.
    worker = OutboxFlushWorker(outbox, MagicMock())
    monkeypatch.setattr(outbox, "pending_count", lambda: 0)
    monkeypatch.setattr(outbox, "get_pending", lambda limit=1000: [])
    status = worker.get_status()
    assert status["backlog_error"] == "OperationalError" and status["terminal_unsynced"] == 0
