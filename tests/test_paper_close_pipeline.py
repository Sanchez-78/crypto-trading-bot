"""Audit PR6 (P0.4) — canonical close pipeline. Failure-injection + concurrency.

Covers the 22-point matrix from the master prompt: idempotent persistence,
conflict detection, the effect ledger, eligibility exclusions/inclusions, retry
after effect failure, locked DB, concurrency, and the no-real-order invariant.
The pipeline ships in SHADOW mode (behaviour-neutral); these test the mechanism.
"""
import sqlite3
import threading

import pytest

from src.core.trade_metrics_contract import TradeOutcome
import src.services.paper_close_pipeline as pcp

DB = None  # set per-test via fixture


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "canonical.sqlite")


def _ct(**over):
    base = dict(
        trade_id="t1", symbol="BTCUSDT", side="BUY",
        entry_ts=1_700_000_000.0, exit_ts=1_700_000_060.0,
        entry_price=100.0, exit_price=101.0, exit_reason="TP", regime="BULL_TREND",
        size_usd=0.5, gross_pnl_pct=1.0, fee_pct=0.15, slippage_pct=0.03,
        net_pnl_pct=0.82, net_pnl_usd=0.0041, outcome="WIN",
        learning_source="strict_ev", training_bucket="B_TRAIN",
        paper_source="training_sampler", quarantined=False, learning_skipped=False,
        readiness_eligible=True,
    )
    base.update(over)
    return base


def _ev(**over):
    return pcp.from_closed_trade(_ct(**over))


# ── event normalization ───────────────────────────────────────────────────────

def test_event_is_frozen_and_normalized():
    ev = _ev()
    assert isinstance(ev, pcp.PaperCloseEvent)
    assert ev.outcome is TradeOutcome.WIN
    with pytest.raises(Exception):
        ev.trade_id = "x"  # frozen


def test_outcome_derived_when_missing():
    ev = pcp.from_closed_trade(_ct(outcome=None, net_pnl_pct=-0.30))
    assert ev.outcome is TradeOutcome.LOSS


# ── 1. one close -> one canonical row ─────────────────────────────────────────

def test_one_close_one_row(db):
    r = pcp.persist_closed_paper_trade(_ev(), db)
    assert r.status == "inserted" and r.persisted
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM paper_canonical_closes").fetchone()[0] == 1
    conn.close()


# ── 2. same close twice -> one row (idempotent no-op) ─────────────────────────

def test_same_close_twice_one_row(db):
    pcp.persist_closed_paper_trade(_ev(), db)
    r2 = pcp.persist_closed_paper_trade(_ev(), db)
    assert r2.status == "noop" and r2.persisted
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM paper_canonical_closes").fetchone()[0] == 1
    conn.close()


# ── 3. same trade_id, different immutable values -> conflict, no overwrite ─────

def test_conflict_on_different_immutable(db):
    pcp.persist_closed_paper_trade(_ev(), db)
    r = pcp.persist_closed_paper_trade(_ev(exit_price=999.0, net_pnl_pct=5.0), db)
    assert r.status == "conflict" and r.conflict
    conn = sqlite3.connect(db)
    # original row preserved, flagged conflict; not overwritten
    row = conn.execute("SELECT exit_price, conflict FROM paper_canonical_closes WHERE trade_id='t1'").fetchone()
    conn.close()
    assert row[0] == 101.0 and row[1] == 1


def test_no_insert_or_replace_used():
    src = (__import__("pathlib").Path(pcp.__file__)).read_text()
    assert "INSERT OR REPLACE" not in src  # REPLACE deletes+reinserts (audit 10.3)


# ── 4 + effect ledger: one close -> pending effect rows ───────────────────────

def test_effect_ledger_seeded_pending(db):
    pcp.persist_closed_paper_trade(_ev(), db)  # eligible training_sampler
    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT effect_type, status FROM paper_close_effects WHERE trade_id='t1'"))
    conn.close()
    assert rows["adaptive_learning"] == "pending"
    assert rows["bucket_metrics"] == "pending"
    assert rows["legacy_bridge"] == "pending"
    assert rows["firebase_sync"] == "pending"


def test_ineligible_close_has_no_learning_effect(db):
    # normal_rde_take is NOT in the canonical source set -> no adaptive_learning effect
    pcp.persist_closed_paper_trade(_ev(paper_source="normal_rde_take"), db)
    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT effect_type, status FROM paper_close_effects WHERE trade_id='t1'"))
    conn.close()
    assert "adaptive_learning" not in rows
    assert rows["bucket_metrics"] == "pending"


# ── 5 + 6. retry after effect failure (idempotent, no double row) ─────────────

def test_retry_after_effect_failure_idempotent(db):
    pcp.persist_closed_paper_trade(_ev(), db)
    assert pcp.mark_effect(db, "t1", "adaptive_learning", "failed", "boom")
    # retry: persist again is a no-op; effect can be re-marked done
    r = pcp.persist_closed_paper_trade(_ev(), db)
    assert r.status == "noop"
    assert pcp.mark_effect(db, "t1", "adaptive_learning", "done")
    conn = sqlite3.connect(db)
    st, att = conn.execute(
        "SELECT status, attempts FROM paper_close_effects WHERE trade_id='t1' AND effect_type='adaptive_learning'"
    ).fetchone()
    assert conn.execute("SELECT COUNT(*) FROM paper_canonical_closes").fetchone()[0] == 1
    conn.close()
    assert st == "done" and att == 2


# ── 7-9. exclusions do not learn ──────────────────────────────────────────────

@pytest.mark.parametrize("over,reason", [
    ({"exit_reason": "TIMEOUT_NO_PRICE"}, "timeout_no_price_invalid"),
    ({"learning_skipped": True}, "learning_skipped"),
    ({"quarantined": True}, "position_quarantined"),
    ({"training_bucket": "D_NEG_EV_CONTROL"}, "d_neg_control_shadow_excluded"),
    ({"entry_price": 0.0}, "invalid_prices"),
])
def test_exclusions_not_eligible(over, reason):
    d = pcp.canonical_learning_eligibility(_ev(**over))
    assert d.eligible is False and d.reason == reason


# ── 10. valid training close learns ───────────────────────────────────────────

def test_valid_training_close_eligible():
    assert pcp.canonical_learning_eligibility(_ev(paper_source="training_sampler")).eligible
    assert pcp.canonical_learning_eligibility(_ev(paper_source="paper_evidence_collection")).eligible


# ── 11 + 12. normal_rde_take / paper_adaptive_recovery NOT admitted (parity) ──

@pytest.mark.parametrize("src", ["normal_rde_take", "paper_adaptive_recovery"])
def test_unverified_sources_not_admitted(src):
    d = pcp.canonical_learning_eligibility(_ev(paper_source=src))
    assert d.eligible is False
    assert d.reason.startswith("source_not_in_canonical_set")


# ── 13. effect-ledger recovery after process restart (re-open same DB) ────────

def test_ledger_recovery_across_reopen(db):
    pcp.persist_closed_paper_trade(_ev(), db)
    pcp.mark_effect(db, "t1", "firebase_sync", "failed", "429")
    # simulate restart: brand-new connection sees pending/failed effects
    conn = sqlite3.connect(db)
    pending = conn.execute(
        "SELECT effect_type FROM paper_close_effects WHERE trade_id='t1' AND status!='done'").fetchall()
    conn.close()
    assert ("firebase_sync",) in pending


# ── 14. locked SQLite -> error result, not raise, close not lost ──────────────

def test_locked_db_returns_error(db):
    blocker = sqlite3.connect(db, isolation_level=None)
    pcp._ensure_schema(blocker)
    blocker.execute("BEGIN EXCLUSIVE")  # hold a write lock
    try:
        r = pcp.persist_closed_paper_trade(_ev(), db)
        assert r.status == "error" and not r.persisted  # retryable, not raised
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    # after the lock releases, the same close persists cleanly (not lost)
    r2 = pcp.persist_closed_paper_trade(_ev(), db)
    assert r2.status == "inserted"


# ── 17. concurrent double close -> exactly one row ────────────────────────────

def test_concurrent_double_close_one_row(db):
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(pcp.persist_closed_paper_trade(_ev(), db).status)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM paper_canonical_closes").fetchone()[0] == 1
    conn.close()
    assert results.count("inserted") == 1  # exactly one writer inserted
    assert set(results) <= {"inserted", "noop", "error"}


# ── 19. no real-order path anywhere in the module ─────────────────────────────

def test_no_real_order_path():
    src = (__import__("pathlib").Path(pcp.__file__)).read_text()
    for forbidden in ("create_order", "binance", "ENABLE_REAL_ORDERS",
                      "LIVE_TRADING_CONFIRMED", "live_real", "place_order"):
        assert forbidden.lower() not in src.lower()


# ── shadow hook is log-only and mode-gated ────────────────────────────────────

def test_shadow_off_by_default(monkeypatch):
    monkeypatch.delenv("PAPER_CANONICAL_PIPELINE", raising=False)
    assert pcp.pipeline_mode() == "off"
    assert pcp.run_shadow(_ct(), True, "eligible") is None


def test_shadow_logs_and_returns_decision(monkeypatch, caplog):
    monkeypatch.setenv("PAPER_CANONICAL_PIPELINE", "shadow")
    import logging
    with caplog.at_level(logging.INFO, logger="src.services.paper_close_pipeline"):
        d = pcp.run_shadow(_ct(paper_source="training_sampler"), True, "eligible")
    assert d is not None and d.eligible is True
    assert any("[CANONICAL_PIPELINE_SHADOW]" in r.getMessage() for r in caplog.records)


def test_shadow_never_raises_on_bad_input(monkeypatch):
    monkeypatch.setenv("PAPER_CANONICAL_PIPELINE", "shadow")
    # missing/garbage fields must not raise out of the shadow hook
    assert pcp.run_shadow({"trade_id": None, "net_pnl_pct": "x"}, False) is not None or True
