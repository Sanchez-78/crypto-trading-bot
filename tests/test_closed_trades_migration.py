"""Audit PR3 — additive, idempotent migration of closed_trades (outcome +
metrics_contract_version), backward-compatible with legacy schema lacking
`side`/`outcome`. No drop table, no row deletion.
"""
import sqlite3

import pytest

import src.services.local_persistent_cache as lpc
from src.core.trade_metrics_contract import METRICS_CONTRACT_VERSION, classify_outcome


def _columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(closed_trades)")}
    finally:
        conn.close()


def _make_legacy_db(path):
    """closed_trades as it existed before the side/outcome migrations."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE closed_trades (
            id INTEGER PRIMARY KEY,
            trade_id TEXT UNIQUE,
            symbol TEXT,
            entry_ts REAL, exit_ts REAL,
            entry_price REAL, exit_price REAL,
            pnl_usd REAL, pnl_pct REAL, win INTEGER,
            exit_reason TEXT, regime TEXT, mfe REAL, mae REAL,
            created_at REAL DEFAULT CURRENT_TIMESTAMP,
            synced_to_firebase INTEGER DEFAULT 0
        )
    """)
    conn.execute(
        "INSERT INTO closed_trades (trade_id, symbol, pnl_usd, pnl_pct, win) "
        "VALUES ('legacy-1', 'BTCUSDT', 0.41, 0.82, 1)"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def cache_db(tmp_path, monkeypatch):
    db = tmp_path / "cache.sqlite"
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", str(db))
    return db


def test_migration_adds_columns_and_preserves_legacy_rows(cache_db):
    _make_legacy_db(cache_db)
    assert "outcome" not in _columns(cache_db)

    lpc._init_db()  # run migration

    cols = _columns(cache_db)
    assert {"side", "outcome", "metrics_contract_version"} <= cols
    # legacy row survived, unmodified, with NULL new columns
    conn = sqlite3.connect(str(cache_db))
    row = conn.execute(
        "SELECT trade_id, pnl_pct, outcome, metrics_contract_version "
        "FROM closed_trades WHERE trade_id='legacy-1'"
    ).fetchone()
    conn.close()
    assert row == ("legacy-1", 0.82, None, None)
    # a reader can still derive the canonical outcome from stored net pct
    assert classify_outcome(row[1]).value == "WIN"


def test_migration_is_idempotent(cache_db):
    _make_legacy_db(cache_db)
    lpc._init_db()
    lpc._init_db()  # must not raise or duplicate columns
    cols = [c for c in _columns(cache_db)]
    assert cols.count("outcome") == 1
    assert cols.count("metrics_contract_version") == 1


def test_save_persists_canonical_outcome_and_version(cache_db):
    lpc._init_db()
    lpc.save_closed_trade({
        "trade_id": "t-win", "symbol": "ETHUSDT", "side": "BUY",
        "net_pnl_pct": 0.82, "pnl_usd": 0.41, "win": 1, "outcome": "WIN",
    })
    conn = sqlite3.connect(str(cache_db))
    row = conn.execute(
        "SELECT outcome, metrics_contract_version FROM closed_trades WHERE trade_id='t-win'"
    ).fetchone()
    conn.close()
    assert row == ("WIN", METRICS_CONTRACT_VERSION)


def test_migration_adds_f8_excursion_columns(cache_db):
    _make_legacy_db(cache_db)
    lpc._init_db()
    cols = _columns(cache_db)
    for c in ("mfe_gross_pct", "mae_gross_pct", "mfe_gross_bps", "mae_gross_bps",
              "time_to_mfe_ms", "time_to_mae_ms", "excursion_policy_version"):
        assert c in cols, c


def test_save_persists_f8_excursion(cache_db):
    lpc._init_db()
    lpc.save_closed_trade({
        "trade_id": "t-exc", "symbol": "BTCUSDT", "side": "BUY",
        "net_pnl_pct": 0.10, "pnl_usd": 0.01, "win": 1, "outcome": "WIN",
        "mfe_gross_pct": 0.30, "mae_gross_pct": -0.12,
        "mfe_gross_bps": 30.0, "mae_gross_bps": -12.0,
        "time_to_mfe_ms": 4200, "time_to_mae_ms": 9100,
        "excursion_policy_version": 1,
    })
    conn = sqlite3.connect(str(cache_db))
    row = conn.execute(
        "SELECT mfe_gross_pct, mae_gross_pct, mfe_gross_bps, mae_gross_bps, "
        "time_to_mfe_ms, time_to_mae_ms, excursion_policy_version "
        "FROM closed_trades WHERE trade_id='t-exc'").fetchone()
    conn.close()
    assert row == (0.30, -0.12, 30.0, -12.0, 4200, 9100, 1)


def test_save_derives_outcome_when_absent(cache_db):
    lpc._init_db()
    # no 'outcome' key -> derive from net pct via the canonical classifier
    lpc.save_closed_trade({
        "trade_id": "t-loss", "symbol": "ADAUSDT", "side": "SELL",
        "net_pnl_pct": -0.08, "pnl_usd": -0.04, "win": 0,
    })
    conn = sqlite3.connect(str(cache_db))
    row = conn.execute(
        "SELECT outcome, metrics_contract_version FROM closed_trades WHERE trade_id='t-loss'"
    ).fetchone()
    conn.close()
    assert row == ("LOSS", METRICS_CONTRACT_VERSION)
