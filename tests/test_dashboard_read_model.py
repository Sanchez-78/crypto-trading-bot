"""Audit PR4 — single dashboard read model. Test matrix per master prompt 8.8."""
import json
import sqlite3
from pathlib import Path

import pytest

import src.services.dashboard_read_model as rm

# ── fixture builders ──────────────────────────────────────────────────────────

MODERN_COLS = ("trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
               "exit_reason, entry_ts, exit_ts, regime, win, side, outcome")


def _make_cache(path, rows, schema="modern"):
    """rows: list of dicts. schema: modern | no_outcome | no_side."""
    cols = {
        "modern": "side TEXT, outcome TEXT",
        "no_outcome": "side TEXT",
        "no_side": "",
    }[schema]
    extra = f", {cols}" if cols else ""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE closed_trades (id INTEGER PRIMARY KEY, trade_id TEXT UNIQUE, "
        "symbol TEXT, entry_ts REAL, exit_ts REAL, entry_price REAL, exit_price REAL, "
        f"pnl_usd REAL, pnl_pct REAL, win INTEGER, exit_reason TEXT, regime TEXT, "
        f"mfe REAL, mae REAL{extra})"
    )
    for r in rows:
        keys = ["trade_id", "symbol", "entry_ts", "exit_ts", "entry_price", "exit_price",
                "pnl_usd", "pnl_pct", "win", "exit_reason", "regime"]
        if schema in ("modern", "no_outcome"):
            keys.append("side")
        if schema == "modern":
            keys.append("outcome")
        placeholders = ",".join("?" for _ in keys)
        conn.execute(f"INSERT INTO closed_trades ({','.join(keys)}) VALUES ({placeholders})",
                     tuple(r.get(k) for k in keys))
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    cache = tmp_path / "cache.sqlite"
    state = tmp_path / "state.json"
    pos = tmp_path / "pos.json"
    monkeypatch.setattr(rm, "_paths", lambda: (str(cache), str(state), str(pos)))
    return {"cache": cache, "state": state, "pos": pos}


def _row(tid, side, net_pct, pnl_usd, outcome=None, reason="TP", ts=1_700_000_000):
    return {"trade_id": tid, "symbol": "BTCUSDT", "entry_ts": ts - 60, "exit_ts": ts,
            "entry_price": 100.0, "exit_price": 100.0 + net_pct, "pnl_usd": pnl_usd,
            "pnl_pct": net_pct, "win": 1 if pnl_usd > 0 else 0, "exit_reason": reason,
            "regime": "BULL_TREND", "side": side, "outcome": outcome}


# ── 1. modern cache with side + outcome ───────────────────────────────────────

def test_modern_cache_headline(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.82, 0.41, "WIN"),
        _row("b", "SELL", -0.30, -0.15, "LOSS"),
        _row("c", "BUY", 0.02, 0.01, "FLAT"),
    ])
    d = rm.get_metrics()
    assert d["degraded"] is False
    assert d["recent"]["wins"] == 1 and d["recent"]["losses"] == 1 and d["recent"]["flats"] == 1
    assert d["win_rate_pct"] == pytest.approx(33.33, abs=0.01)  # 1 WIN / 3
    assert d["win_rate_window"] == 3


# ── 2. legacy cache without side ──────────────────────────────────────────────

def test_legacy_cache_no_side(env):
    _make_cache(env["cache"], [_row("a", None, 0.82, 0.41)], schema="no_side")
    d = rm.get_metrics()
    assert d["degraded"] is False
    assert d["closed_trades_list"][0]["side"] == "BUY"  # default when column absent


# ── 3. legacy row without outcome -> derived ──────────────────────────────────

def test_legacy_row_no_outcome_derived(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.82, 0.41), _row("b", "BUY", -0.30, -0.15),
    ], schema="no_outcome")
    d = rm.get_metrics()
    # outcomes derived via canonical classifier from net pct
    assert d["recent"]["wins"] == 1 and d["recent"]["losses"] == 1


# ── 4. empty cache + learning JSON fallback ───────────────────────────────────

def test_empty_cache_json_fallback(env):
    _make_cache(env["cache"], [])
    env["state"].write_text(json.dumps({
        "lifetime_n": 5, "lifetime_pf": 1.2,
        "rolling100": [[0.5, "WIN", "BTCUSDT:BULL_TREND:BUY", 1_700_000_000]],
    }))
    d = rm.get_metrics()
    assert d["total_trades"] == 5
    assert len(d["closed_trades_list"]) == 1  # rebuilt from rolling window
    assert d["closed_trades_list"][0]["outcome"] == "WIN"


# ── 5. no cache + no JSON -> degraded but valid ───────────────────────────────

def test_no_sources_degraded_valid(env):
    d = rm.get_metrics()
    assert d["degraded"] is True
    assert "cache_missing" in d["errors"]
    # still fully shaped
    for k in ("win_rate_pct", "profit_factor", "open_positions_list", "timestamp"):
        assert k in d


# ── 6. locked / unreadable SQLite -> degraded, never raises ───────────────────

def test_corrupt_sqlite_degraded(env):
    env["cache"].write_text("this is not a sqlite database")
    d = rm.get_metrics()  # must not raise
    assert d["degraded"] is True


# ── 7. broken JSON -> degraded flag, still valid ──────────────────────────────

def test_broken_json_degraded(env):
    _make_cache(env["cache"], [_row("a", "BUY", 0.82, 0.41, "WIN")])
    env["state"].write_text("{ broken json ")
    env["pos"].write_text("{ also broken ")
    d = rm.get_metrics()
    assert "learning_state_unreadable" in d["errors"]
    assert "positions_unreadable" in d["errors"]
    assert d["degraded"] is True
    assert d["open_positions_list"] == []


# ── 8 + 9. BUY/SELL and WIN/LOSS/FLAT ─────────────────────────────────────────

def test_buy_sell_win_loss_flat(env):
    _make_cache(env["cache"], [
        _row("w", "BUY", 0.82, 0.41, "WIN"),
        _row("l", "SELL", -0.82, -0.41, "LOSS"),
        _row("f", "SELL", 0.0, 0.0, "FLAT"),
    ])
    d = rm.get_metrics()
    sides = {t["trade_id"]: t["side"] for t in d["closed_trades_list"]}
    assert sides["w"] == "BUY" and sides["l"] == "SELL"
    outs = {t["trade_id"]: t["outcome"] for t in d["closed_trades_list"]}
    assert outs == {"w": "WIN", "l": "LOSS", "f": "FLAT"}


# ── 10. only wins -> PF cap ───────────────────────────────────────────────────

def test_only_wins_pf_capped(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.8, 0.4, "WIN"), _row("b", "BUY", 0.6, 0.3, "WIN"),
    ])
    d = rm.get_metrics()
    assert d["profit_factor"] == rm.compute_profit_factor([0.8, 0.6])  # == PROFIT_FACTOR_CAP
    assert d["profit_factor"] == 999.0


# ── 11. exit distribution ─────────────────────────────────────────────────────

def test_exit_distribution(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.8, 0.4, "WIN", reason="TP"),
        _row("b", "SELL", -0.8, -0.4, "LOSS", reason="SL"),
        _row("c", "BUY", 0.0, 0.0, "FLAT", reason="TIMEOUT"),
    ])
    d = rm.get_metrics()
    assert d["exit_distribution"]["tp"] == 1
    assert d["exit_distribution"]["sl"] == 1
    assert d["exit_distribution"]["timeout"] == 1


# ── 12. main and enhanced identical headline ──────────────────────────────────

def test_main_and_enhanced_identical_headline(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.82, 0.41, "WIN"), _row("b", "SELL", -0.30, -0.15, "LOSS"),
    ])
    d = rm.get_metrics()
    e = rm.get_enhanced_metrics()
    for k in ("profit_factor", "win_rate_pct", "win_rate_window", "net_pnl", "net_pnl_window"):
        assert d[k] == e[k]
    assert e["enhanced"]["profit_factor"] == d["recent"]["recent_profit_factor"]


# ── 13. recent endpoint reflects same DB ──────────────────────────────────────

def test_recent_endpoint_same_db(env):
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.82, 0.41, "WIN"), _row("b", "SELL", -0.30, -0.15, "LOSS"),
    ])
    trades = rm.get_recent_trades(30)
    assert {t["trade_id"] for t in trades} == {"a", "b"}


# ── 14 + 15. no dead sources in request path (static) ─────────────────────────

REPO = Path(__file__).resolve().parents[1]


def test_no_learning_database_in_active_code():
    for f in ("src/services/dashboard_read_model.py", "src/services/dashboard_web.py"):
        src = (REPO / f).read_text()
        # allow the word in comments/docstrings that say it's NOT used
        code_lines = [ln for ln in src.splitlines()
                      if "learning_database.sqlite" in ln and "sqlite3.connect" in ln]
        assert code_lines == [], f"{f} still connects to learning_database.sqlite"


def _strip_module_docstring(src):
    """Return source with the leading module docstring removed (comment/doc mentions
    of forbidden sources are fine; only executable references matter)."""
    parts = src.split('"""')
    return "".join(parts[2:]) if len(parts) >= 3 else src


def test_no_shellout_in_request_path():
    src = (REPO / "src/services/dashboard_web.py").read_text()
    assert "journalctl" not in src
    assert "os.system" not in src
    assert "import subprocess" not in src
    # In the read model, forbidden tokens may appear only in the module docstring.
    body = _strip_module_docstring((REPO / "src/services/dashboard_read_model.py").read_text())
    for token in ("subprocess", "journalctl", "os.system", "learning_database"):
        assert token not in body, f"read model body must not reference {token}"


# ── 16. never-500 across failure modes ────────────────────────────────────────

@pytest.mark.parametrize("setup", [
    "nothing", "corrupt_db", "broken_json", "empty_db",
    "nondict_state_list", "nondict_state_int", "nondict_positions",
])
def test_never_raises(env, setup):
    if setup == "corrupt_db":
        env["cache"].write_text("nope")
    elif setup == "broken_json":
        env["state"].write_text("{bad")
        env["pos"].write_text("{bad")
    elif setup == "empty_db":
        _make_cache(env["cache"], [])
    elif setup == "nondict_state_list":
        # valid JSON but not an object -> the exact former 500 escape path
        env["state"].write_text("[1, 2, 3]")
    elif setup == "nondict_state_int":
        env["state"].write_text("42")
    elif setup == "nondict_positions":
        _make_cache(env["cache"], [_row("a", "BUY", 0.82, 0.41, "WIN")])
        env["pos"].write_text("123")
    d = rm.get_metrics()           # must not raise
    e = rm.get_enhanced_metrics()  # must not raise
    t = rm.get_recent_trades()     # must not raise (unguarded Flask wrapper)
    assert isinstance(d, dict) and isinstance(e, dict) and isinstance(t, list)
    assert "timestamp" in d


def test_bad_positions_does_not_collapse_payload(env):
    """A corrupt positions file must degrade ONLY positions, not wipe the metrics."""
    _make_cache(env["cache"], [
        _row("a", "BUY", 0.82, 0.41, "WIN"), _row("b", "SELL", -0.30, -0.15, "LOSS"),
    ])
    env["pos"].write_text("123")  # valid JSON, not a dict/list
    d = rm.get_metrics()
    assert "positions_unreadable" in d["errors"]
    assert d["open_positions_list"] == []
    # cache-derived metrics survive intact
    assert d["win_rate_window"] == 2
    assert len(d["closed_trades_list"]) == 2
    assert d["data_source"] == "learning_state+cache.sqlite"  # NOT the degraded envelope


def test_genuine_zero_pnl_pct_not_recomputed(env):
    """A stored 0.0 pnl_pct (with outcome) must be left as 0.0, not recomputed."""
    _make_cache(env["cache"], [
        {"trade_id": "flat", "symbol": "BTCUSDT", "entry_ts": 1, "exit_ts": 2,
         "entry_price": 100.0, "exit_price": 101.0, "pnl_usd": 0.0, "pnl_pct": 0.0,
         "win": 0, "exit_reason": "TIMEOUT", "regime": "BULL_TREND",
         "side": "BUY", "outcome": "FLAT"},
    ])
    t = rm.get_recent_trades(30)
    assert t[0]["pnl_pct"] == 0.0  # NOT recomputed to (101/100-1)*100 = 1.0


# ── 17. Android contract: timestamps + Czech statuses ─────────────────────────

def test_android_contract_timestamps_and_status(env):
    _make_cache(env["cache"], [_row("a", "BUY", 0.82, 0.41, "WIN")])
    env["state"].write_text(json.dumps({"lifetime_n": 3, "regime_tp_learning_enabled": True}))
    d = rm.get_metrics()
    assert d["timestamp"].endswith("Z") and "T" in d["timestamp"]
    assert "." in d["timestamp"].split("T")[1]  # millisecond precision
    assert d["learning_status"] == "UČENÍ"
    assert d["recommendation"] == "ČEKAT"


def test_czech_status_pripraven_and_vypnuto(env):
    _make_cache(env["cache"], [])
    env["state"].write_text(json.dumps({"lifetime_n": 10}))
    assert rm.get_metrics()["learning_status"] == "PŘIPRAVEN"
    env["state"].write_text(json.dumps({"lifetime_n": 0}))
    assert rm.get_metrics()["learning_status"] == "VYPNUTO"
