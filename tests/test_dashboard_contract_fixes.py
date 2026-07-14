# -*- coding: utf-8 -*-
"""Tests for the dashboard/API fixes from _workspace/dashboard_audit.md (2026-07-14).

Covers:
  1. Never-500 degraded JSON on /api/dashboard/metrics + readiness/learning-state (Fix 1/5)
  2. side + net_pnl_pct persistence in local_persistent_cache.save_closed_trade (Fix 8a, C8)
  3. Legacy-row sign heuristic + stored-side display in the dashboard reader (Fix 8b, C8)
  4. Android contract fields (closed_today, total_trades, learning_status,
     recommendation, last_update_utc) and ms-precision timestamps (Fix 2/4)
"""
import json
import os
import re
import sqlite3
import time

import pytest

pytest.importorskip("flask")

from src.services import dashboard_web
import src.services.local_persistent_cache as lpc

MS_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

ANDROID_CONTRACT_KEYS = (
    "open_positions", "closed_today", "total_trades", "win_rate_pct",
    "profit_factor", "learning_status", "recommendation", "last_update_utc",
)


def _hide_opt_cryptomaster(monkeypatch):
    """Make the dashboard use cwd-relative paths even if /opt/cryptomaster exists."""
    real_exists = os.path.exists
    monkeypatch.setattr(
        dashboard_web.os.path, "exists",
        lambda p: False if str(p).startswith("/opt/cryptomaster") else real_exists(p),
    )


# ---------------------------------------------------------------------------
# 1. Never-500 degraded paths
# ---------------------------------------------------------------------------

def test_metrics_endpoint_degrades_to_200_json_on_failure(monkeypatch):
    def _boom():
        raise RuntimeError("forced: missing DB/table/JSON")

    monkeypatch.setattr(dashboard_web, "get_live_metrics_from_cache", _boom)
    client = dashboard_web.app.test_client()
    resp = client.get("/api/dashboard/metrics")

    assert resp.status_code == 200, "metrics endpoint must never return 500"
    data = resp.get_json()
    assert data["degraded"] is True
    for key in ANDROID_CONTRACT_KEYS:
        assert key in data, f"degraded payload missing contract key {key!r}"
    assert data["learning_status"] == "VYPNUTO"
    assert data["recommendation"] == "ČEKAT"
    assert data["open_positions_list"] == []
    assert data["closed_trades_list"] == []
    assert MS_ISO_RE.match(data["last_update_utc"]), data["last_update_utc"]


def test_readiness_endpoints_degrade_to_200(monkeypatch):
    import src.services.readiness_monitor as rm
    import src.services.trading_readiness_checker as trc

    def _boom(*a, **k):
        raise RuntimeError("forced readiness failure")

    monkeypatch.setattr(rm, "get_current_metrics", _boom)
    monkeypatch.setattr(trc, "get_readiness_status", _boom)
    client = dashboard_web.app.test_client()

    resp = client.get("/api/dashboard/readiness")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_ready_for_trading"] is False
    assert data["readiness_score"] == 0
    assert data["blocker_reasons"] == ["service_degraded"]

    resp = client.get("/api/dashboard/readiness/status")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "degraded"


def test_learning_state_endpoint_degrades_to_200_on_malformed_json(tmp_path, monkeypatch):
    state_dir = tmp_path / "server_local_backups"
    state_dir.mkdir()
    (state_dir / "paper_adaptive_learning_state.json").write_text("{not valid json !!")
    monkeypatch.chdir(tmp_path)

    client = dashboard_web.app.test_client()
    resp = client.get("/api/dashboard/learning-state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "error"
    assert data["learning_enabled"] is False
    assert data["regime_tp_strategy"] == {}
    assert data["lifetime_closes"] == 0


# ---------------------------------------------------------------------------
# 2. side / net_pnl_pct persistence (Fix 8a)
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(lpc, "LOCAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", str(db_path))
    monkeypatch.setattr(lpc, "LOCAL_STATE_DIR", str(tmp_path / "state"))
    lpc._init_db()
    return db_path


def test_save_closed_trade_persists_side_and_net_pnl_pct(cache_db):
    # Executor emits net_pnl_pct (side-aware) — no bare pnl_pct key historically.
    lpc.save_closed_trade({
        "trade_id": "t_short", "symbol": "ETHUSDT", "side": "SELL",
        "entry_ts": 1.0, "exit_ts": 2.0,
        "entry_price": 1881.365, "exit_price": 1874.265,
        "pnl_usd": 0.001687, "net_pnl_pct": 0.3374, "win": 1,
        "exit_reason": "TP", "regime": "TREND",
    })
    row = sqlite3.connect(str(cache_db)).execute(
        "SELECT side, pnl_pct, win FROM closed_trades WHERE trade_id='t_short'"
    ).fetchone()
    assert row[0] == "SELL"
    assert row[1] == pytest.approx(0.3374)
    assert row[2] == 1


def test_save_closed_trade_side_fallbacks_and_pnl_pct_priority(cache_db):
    # 'action' used when 'side' missing; explicit pnl_pct wins over net_pnl_pct.
    lpc.save_closed_trade({
        "trade_id": "t_action", "symbol": "ADAUSDT", "action": "SELL",
        "pnl_usd": -0.001, "pnl_pct": -0.2, "net_pnl_pct": -0.3, "win": 0,
    })
    # Neither side nor action -> BUY default.
    lpc.save_closed_trade({
        "trade_id": "t_default", "symbol": "BTCUSDT",
        "pnl_usd": 0.001, "net_pnl_pct": 0.2, "win": 1,
    })
    conn = sqlite3.connect(str(cache_db))
    side, pp = conn.execute(
        "SELECT side, pnl_pct FROM closed_trades WHERE trade_id='t_action'").fetchone()
    assert (side, pp) == ("SELL", pytest.approx(-0.2))
    side, pp = conn.execute(
        "SELECT side, pnl_pct FROM closed_trades WHERE trade_id='t_default'").fetchone()
    assert (side, pp) == ("BUY", pytest.approx(0.2))


def test_init_db_migrates_legacy_schema_without_side_column(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE closed_trades (
            id INTEGER PRIMARY KEY, trade_id TEXT UNIQUE, symbol TEXT,
            entry_ts REAL, exit_ts REAL, entry_price REAL, exit_price REAL,
            pnl_usd REAL, pnl_pct REAL, win INTEGER, exit_reason TEXT,
            regime TEXT, mfe REAL, mae REAL,
            created_at REAL DEFAULT CURRENT_TIMESTAMP,
            synced_to_firebase INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(lpc, "LOCAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", str(db_path))
    monkeypatch.setattr(lpc, "LOCAL_STATE_DIR", str(tmp_path / "state"))
    lpc._init_db()   # must ALTER TABLE ... ADD COLUMN side
    lpc._init_db()   # and be idempotent (OperationalError guarded)

    cols = [c[1] for c in sqlite3.connect(str(db_path)).execute(
        "PRAGMA table_info(closed_trades)")]
    assert cols.count("side") == 1


# ---------------------------------------------------------------------------
# 3+4. Dashboard reader: stored side, legacy sign heuristic, contract fields
# ---------------------------------------------------------------------------

def _write_learning_state(root, lifetime_n=3, learning_enabled=True):
    now = time.time()
    state = {
        "lifetime_n": lifetime_n,
        "lifetime_pf": 1.2,
        "lifetime_expectancy": 0.05,
        "regime_tp_learning_enabled": learning_enabled,
        "rolling50": [
            [0.1431, "WIN", "ADAUSDT:TREND:SELL", now - 60, "paper", "A"],
            [0.3374, "WIN", "ETHUSDT:TREND:SELL", now - 120, "paper", "A"],
            [-0.1766, "LOSS", "ETHUSDT:TREND:BUY", now - 180, "paper", "A"],
        ],
    }
    d = root / "server_local_backups"
    d.mkdir(exist_ok=True)
    (d / "paper_adaptive_learning_state.json").write_text(json.dumps(state))


def _make_cache_db(root, with_side_column=True):
    d = root / "local_learning_storage"
    d.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(d / "cache.sqlite"))
    side_col = "side TEXT," if with_side_column else ""
    conn.execute(f"""
        CREATE TABLE closed_trades (
            id INTEGER PRIMARY KEY, trade_id TEXT UNIQUE, symbol TEXT, {side_col}
            entry_ts REAL, exit_ts REAL, entry_price REAL, exit_price REAL,
            pnl_usd REAL, pnl_pct REAL, win INTEGER, exit_reason TEXT,
            regime TEXT, mfe REAL, mae REAL,
            created_at REAL DEFAULT CURRENT_TIMESTAMP,
            synced_to_firebase INTEGER DEFAULT 0
        )
    """)
    return conn


def test_reader_uses_stored_side_and_legacy_sign_heuristic(tmp_path, monkeypatch):
    _write_learning_state(tmp_path)
    conn = _make_cache_db(tmp_path, with_side_column=True)
    now = time.time()
    # Legacy short row (pre-Fix-8a): side NULL, pnl_pct NULL, price fell,
    # side-aware pnl_usd positive -> heuristic must flip the long-formula sign.
    conn.execute(
        "INSERT INTO closed_trades (trade_id, symbol, side, entry_ts, exit_ts,"
        " entry_price, exit_price, pnl_usd, pnl_pct, win, exit_reason, regime)"
        " VALUES ('legacy_short','ADAUSDT',NULL,?,?,0.16385,0.16355,0.0007155,NULL,1,'TP','TREND')",
        (now - 300, now - 200))
    # New short row: side stored, pnl_pct NULL -> long formula sign-corrected by side.
    conn.execute(
        "INSERT INTO closed_trades (trade_id, symbol, side, entry_ts, exit_ts,"
        " entry_price, exit_price, pnl_usd, pnl_pct, win, exit_reason, regime)"
        " VALUES ('new_short','ETHUSDT','SELL',?,?,100.0,99.0,0.005,NULL,1,'TP','TREND')",
        (now - 150, now - 100))
    # New long row with stored net pnl_pct: used verbatim.
    conn.execute(
        "INSERT INTO closed_trades (trade_id, symbol, side, entry_ts, exit_ts,"
        " entry_price, exit_price, pnl_usd, pnl_pct, win, exit_reason, regime)"
        " VALUES ('new_long','ETHUSDT','BUY',?,?,1866.475,1863.925,-0.000883,-0.1766,0,'SL','TREND')",
        (now - 90, now - 50))
    conn.commit()
    conn.close()

    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)
    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    trades = {t["trade_id"]: t for t in metrics["closed_trades_list"]}
    assert set(trades) == {"legacy_short", "new_short", "new_long"}

    # C8 verification: sign(pnl_pct) == sign(pnl_usd), win matches pnl_usd > 0.
    for t in trades.values():
        if t["pnl_usd"]:
            assert t["pnl_pct"] * t["pnl_usd"] > 0, f"inverted sign: {t}"
        assert t["win"] == (1 if t["pnl_usd"] > 0 else 0)

    assert trades["legacy_short"]["side"] == "BUY"  # unknown -> documented default
    assert trades["legacy_short"]["pnl_pct"] == pytest.approx(0.18309, abs=1e-3)
    assert trades["new_short"]["side"] == "SELL"
    assert trades["new_short"]["pnl_pct"] == pytest.approx(1.0)
    assert trades["new_long"]["side"] == "BUY"
    assert trades["new_long"]["pnl_pct"] == pytest.approx(-0.1766)


def test_reader_survives_legacy_db_without_side_column(tmp_path, monkeypatch):
    _write_learning_state(tmp_path)
    conn = _make_cache_db(tmp_path, with_side_column=False)
    now = time.time()
    conn.execute(
        "INSERT INTO closed_trades (trade_id, symbol, entry_ts, exit_ts,"
        " entry_price, exit_price, pnl_usd, pnl_pct, win, exit_reason, regime)"
        " VALUES ('old_row','ETHUSDT',?,?,1881.365,1874.265,0.001687,NULL,1,'TP','TREND')",
        (now - 300, now - 200))
    conn.commit()
    conn.close()

    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)
    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    (t,) = metrics["closed_trades_list"]
    assert t["trade_id"] == "old_row"
    assert t["side"] == "BUY"
    # Sign heuristic still applies via pnl_usd (short win recorded pre-migration).
    assert t["pnl_pct"] > 0


def test_live_metrics_carry_android_contract_fields(tmp_path, monkeypatch):
    _write_learning_state(tmp_path, lifetime_n=7, learning_enabled=True)
    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)

    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    for key in ANDROID_CONTRACT_KEYS:
        assert key in metrics, f"live payload missing contract key {key!r}"
    assert metrics["total_trades"] == 7
    assert metrics["closed_today"] >= 0
    # All 3 rolling entries have today's timestamps.
    assert metrics["closed_today"] == 3
    assert metrics["learning_status"] == "UČENÍ"
    assert metrics["recommendation"] in ("KOUPIT", "PRODAT", "ČEKAT", "POČKAT")
    assert MS_ISO_RE.match(metrics["last_update_utc"]), metrics["last_update_utc"]
    assert metrics["last_update_utc"] == metrics["timestamp"] == metrics["last_update"]


def test_learning_status_czech_labels(tmp_path, monkeypatch):
    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)

    _write_learning_state(tmp_path, lifetime_n=5, learning_enabled=False)
    assert dashboard_web._android_contract_fields()["learning_status"] == "PŘIPRAVEN"
    _write_learning_state(tmp_path, lifetime_n=0, learning_enabled=False)
    assert dashboard_web._android_contract_fields()["learning_status"] == "VYPNUTO"
    # No state file at all
    assert dashboard_web._android_contract_fields(state={})["learning_status"] == "VYPNUTO"


def test_open_positions_have_real_side_aware_pnl_and_contract_keys(tmp_path, monkeypatch):
    _write_learning_state(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    now = time.time()
    positions = {
        "paper_long0001": {
            "symbol": "BTCUSDT", "side": "BUY", "entry_price": 100.0,
            "last_price": 101.0, "tp": 102.0, "sl": 99.0,
            "entry_ts": now - 120, "regime": "TREND", "size_usd": 0.5,
        },
        "paper_short001": {
            "symbol": "ETHUSDT", "side": "SELL", "entry_price": 100.0,
            "last_price": 99.0, "tp": 98.0, "sl": 101.0,
            "entry_ts": now - 60, "regime": "TREND", "size_usd": 0.5,
        },
    }
    (data_dir / "paper_open_positions.json").write_text(json.dumps(positions))

    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)
    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    pos = {p["symbol"]: p for p in metrics["open_positions_list"]}
    # M8: pnl_pct no longer hardcoded 0.0; side-aware for shorts.
    assert pos["BTCUSDT"]["pnl_pct"] == pytest.approx(1.0)
    assert pos["ETHUSDT"]["pnl_pct"] == pytest.approx(1.0)  # short, price fell -> profit
    assert pos["ETHUSDT"]["side"] == "SELL"
    # M7: contract keys alongside the legacy ones.
    for p in pos.values():
        assert p["age_s"] == p["age_seconds"]
        assert p["hold_s"] == p["current_hold_s"]
        assert MS_ISO_RE.match(p["entry_timestamp"])
