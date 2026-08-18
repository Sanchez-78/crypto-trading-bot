"""Tests for local_persistent_cache.py's closed-trade attribution
persistence (_workspace/39_closed_trade_attribution_write_bug.md).

Found live 2026-08-18: save_closed_trade()'s INSERT statement never
included bucket/source/paper_source/learning_source/tp_sl_profile/
readiness_eligible/tags_json -- every trade's attribution was correctly
computed and present on the in-memory position at open time (confirmed
via the [PAPER_TRAIN_QUALITY_ENTRY] log line) but silently lost on the
way to persistent SQLite storage. Not caused by any of this session's
other 2026-08-18 changes -- confirmed via forensics that this session
never touched this module before this fix.
"""
import json
import sqlite3

import pytest

from src.services import local_persistent_cache as lpc


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_cache.sqlite")
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", db_path)
    lpc._init_db()
    return db_path


def _read_trade(db_path, trade_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(closed_trades)")
    cols = [r[1] for r in cursor.fetchall()]
    cursor.execute("SELECT * FROM closed_trades WHERE trade_id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(cols, row))


def _full_trade(**overrides):
    trade = dict(
        trade_id="paper_test1",
        symbol="ETHUSDT",
        side="BUY",
        entry_ts=1_700_000_000.0,
        exit_ts=1_700_000_300.0,
        entry_price=2000.0,
        exit_price=2010.0,
        pnl_usd=1.0,
        pnl_pct=0.5,
        win=True,
        exit_reason="TP",
        regime="BULL_TREND",
        mfe=None,
        mae=None,
        source="strict_take",
        tp_sl_profile="dynamic_trend_exit_v1",
        bucket="A_STRICT_TAKE",
        training_bucket="A_STRICT_TAKE",
        explore_bucket=None,
        paper_source="paper_evidence_collection",
        learning_source="trend_cost_aware_v1",
        readiness_eligible=False,
        real_readiness_eligible=False,
        paper_learning_only=True,
        learning_shadow_only=False,
        tags=["tag1", "tag2"],
    )
    trade.update(overrides)
    return trade


def test_bucket_and_source_attribution_persists(temp_db):
    lpc.save_closed_trade(_full_trade())
    stored = _read_trade(temp_db, "paper_test1")
    assert stored is not None
    assert stored["bucket"] == "A_STRICT_TAKE"
    assert stored["training_bucket"] == "A_STRICT_TAKE"
    assert stored["source"] == "strict_take"
    assert stored["paper_source"] == "paper_evidence_collection"
    assert stored["learning_source"] == "trend_cost_aware_v1"
    assert stored["tp_sl_profile"] == "dynamic_trend_exit_v1"


def test_bucket_falls_back_to_training_then_explore(temp_db):
    """Matches the same precedence trade_executor.py's own readers
    already use elsewhere (`bucket or training_bucket or explore_bucket`)."""
    lpc.save_closed_trade(_full_trade(
        trade_id="paper_test2", bucket=None, training_bucket=None, explore_bucket="D_NEG_EV_CONTROL",
    ))
    stored = _read_trade(temp_db, "paper_test2")
    assert stored["bucket"] == "D_NEG_EV_CONTROL"


def test_boolean_fields_stored_as_0_1_not_python_bool(temp_db):
    lpc.save_closed_trade(_full_trade(
        trade_id="paper_test3",
        readiness_eligible=True, real_readiness_eligible=False,
        paper_learning_only=None, learning_shadow_only=True,
    ))
    stored = _read_trade(temp_db, "paper_test3")
    assert stored["readiness_eligible"] == 1
    assert stored["real_readiness_eligible"] == 0
    assert stored["paper_learning_only"] is None  # unknown stays unknown, not coerced to False
    assert stored["learning_shadow_only"] == 1


def test_tags_serialized_as_json(temp_db):
    lpc.save_closed_trade(_full_trade(trade_id="paper_test4", tags=["a", "b", "c"]))
    stored = _read_trade(temp_db, "paper_test4")
    assert json.loads(stored["tags_json"]) == ["a", "b", "c"]


def test_empty_tags_list_stores_null_not_empty_json_array(temp_db):
    """An empty list is falsy -- stored as NULL, not "[]", matching how
    every other optional field here uses NULL for 'not set'."""
    lpc.save_closed_trade(_full_trade(trade_id="paper_test5", tags=[]))
    stored = _read_trade(temp_db, "paper_test5")
    assert stored["tags_json"] is None


def test_missing_attribution_fields_do_not_crash_and_store_null(temp_db):
    """A trade dict that never had these keys at all (e.g. a very old
    legacy position) must not raise -- absent fields store NULL, same as
    before this fix, just via .get() defaults rather than omission."""
    minimal_trade = dict(
        trade_id="paper_test6", symbol="ETHUSDT", side="BUY",
        entry_ts=1_700_000_000.0, exit_ts=1_700_000_300.0,
        entry_price=2000.0, exit_price=2010.0, pnl_usd=1.0, pnl_pct=0.5,
        win=True, exit_reason="TP", regime="BULL_TREND",
    )
    lpc.save_closed_trade(minimal_trade)  # must not raise
    stored = _read_trade(temp_db, "paper_test6")
    assert stored is not None
    assert stored["bucket"] is None
    assert stored["tags_json"] is None


def test_core_fields_unaffected_by_this_fix(temp_db):
    """Regression pin: the pre-existing core fields (pnl/outcome/exit
    reason/etc.) must be completely unaffected by adding the new columns."""
    lpc.save_closed_trade(_full_trade(trade_id="paper_test7", pnl_pct=1.23, exit_reason="SL"))
    stored = _read_trade(temp_db, "paper_test7")
    assert stored["pnl_pct"] == pytest.approx(1.23)
    assert stored["exit_reason"] == "SL"
    assert stored["symbol"] == "ETHUSDT"


def test_insert_or_replace_updates_attribution_on_rewrite(temp_db):
    """A second save_closed_trade() call for the same trade_id (e.g. a
    retry) must correctly update attribution too, not just the first
    write."""
    lpc.save_closed_trade(_full_trade(trade_id="paper_test8", bucket="A_STRICT_TAKE"))
    lpc.save_closed_trade(_full_trade(trade_id="paper_test8", bucket="C_WEAK_EV_TRAIN"))
    stored = _read_trade(temp_db, "paper_test8")
    assert stored["bucket"] == "C_WEAK_EV_TRAIN"


def test_fresh_database_creates_attribution_columns(tmp_path, monkeypatch):
    """_init_db()'s migration must create these columns on a database
    that never had them (e.g. a fresh local/test environment) -- not
    just tolerate them already existing on a previously-migrated one."""
    db_path = str(tmp_path / "fresh.sqlite")
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", db_path)
    lpc._init_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(closed_trades)")
    cols = {r[1] for r in cursor.fetchall()}
    conn.close()
    for expected in (
        "source", "tp_sl_profile", "bucket", "training_bucket", "explore_bucket",
        "paper_source", "learning_source", "readiness_eligible",
        "real_readiness_eligible", "paper_learning_only", "learning_shadow_only",
        "tags_json",
    ):
        assert expected in cols, f"migration did not create column {expected!r}"


def test_init_db_is_idempotent_on_already_migrated_database(temp_db):
    """Calling _init_db() a second time (e.g. on every process restart)
    against an already-migrated database must not raise."""
    lpc._init_db()  # must not raise (the fixture already called it once)
