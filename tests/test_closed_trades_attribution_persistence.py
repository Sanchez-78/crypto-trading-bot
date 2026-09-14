"""Production-linked RED gate: canonical_admit() attribution must persist.

Phase 0 found the six attribution fields Phase 2 mandates are absent from the
`closed_trades` schema entirely:

    code_version, config_version, segment_key,
    admission_route, admission_reason, effective_hold_s

`canonical_admit()` stamps all of them onto the position at open time, but with
no columns to land in they are dropped at persistence -- the same class of bug
as the 2026-08-18 attribution write bug, where bucket/source/paper_source were
correct in memory and silently lost by the INSERT.

Without these columns there is no way to build the version-homogeneous
post-fix cohort Phase 4 requires, so no WR >50 claim can ever be substantiated.

PAPER-only: writes only to the redirected test sink (see tests/conftest.py).
"""

import sqlite3

import pytest

from src.services import local_persistent_cache as lpc

REQUIRED_COLUMNS = (
    "code_version",
    "config_version",
    "segment_key",
    "admission_route",
    "admission_reason",
    "effective_hold_s",
)


@pytest.fixture()
def cache_db(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    monkeypatch.setattr(lpc, "LOCAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", str(db))
    monkeypatch.setattr(lpc, "LOCAL_STATE_DIR", str(tmp_path / "state"))
    lpc._init_db()
    return str(db)


def _columns(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(closed_trades)")}
    finally:
        conn.close()


def _row(db, trade_id):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM closed_trades WHERE trade_id=?", (trade_id,)
        ).fetchone()
    finally:
        conn.close()


def test_migration_adds_the_six_phase2_columns(cache_db):
    """RED-1: the schema carries every Phase 2 attribution column."""
    cols = _columns(cache_db)
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    assert not missing, f"closed_trades is missing Phase 2 columns: {missing}"


def test_attribution_round_trips_through_save_closed_trade(cache_db):
    """RED-2: what canonical_admit() stamped is what lands in the row."""
    lpc.save_closed_trade({
        "trade_id": "paper_attr01",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "pnl_pct": 0.5,
        "win": 1,
        "exit_reason": "TP",
        "code_version": "abc123",
        "config_version": "cfg7",
        "segment_key": "BTCUSDT|BULL_TREND|BUY",
        "admission_route": "RDE_TAKE",
        "admission_reason": "RDE_TAKE",
        "effective_hold_s": 300.0,
    })

    row = _row(cache_db, "paper_attr01")
    assert row is not None
    assert row["code_version"] == "abc123"
    assert row["config_version"] == "cfg7"
    assert row["segment_key"] == "BTCUSDT|BULL_TREND|BUY"
    assert row["admission_route"] == "RDE_TAKE"
    assert row["admission_reason"] == "RDE_TAKE"
    assert row["effective_hold_s"] == pytest.approx(300.0)


def test_missing_attribution_stays_null_and_is_never_invented(cache_db):
    """RED-3: absent attribution is NULL, not back-filled with a guess.

    Phase 2 rule 4: a trade whose attribution the system genuinely does not
    have is UNQUALIFIED. Defaulting it to the current build would silently
    credit legacy rows to a code version that never produced them.
    """
    lpc.save_closed_trade({
        "trade_id": "paper_attr02",
        "symbol": "ETHUSDT",
        "side": "BUY",
        "pnl_pct": -0.2,
        "win": 0,
        "exit_reason": "TIMEOUT",
    })

    row = _row(cache_db, "paper_attr02")
    assert row is not None
    for col in REQUIRED_COLUMNS:
        assert row[col] is None, f"{col} was invented as {row[col]!r}"


def test_migration_is_idempotent(cache_db):
    """RED-4: re-running init must not fail or drop data (additive only)."""
    lpc.save_closed_trade({
        "trade_id": "paper_attr03", "symbol": "BTCUSDT", "side": "BUY",
        "pnl_pct": 0.1, "win": 1, "exit_reason": "TP",
        "admission_route": "P0_GATE",
    })
    lpc._init_db()
    lpc._init_db()

    row = _row(cache_db, "paper_attr03")
    assert row is not None and row["admission_route"] == "P0_GATE"
    assert all(c in _columns(cache_db) for c in REQUIRED_COLUMNS)
