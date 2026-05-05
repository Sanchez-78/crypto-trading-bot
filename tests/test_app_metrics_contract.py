"""
Tests for app_metrics_contract.py — pure snapshot builder.

All tests are offline (no Firebase, no runtime imports at module level).
"""

import math
import time
import pytest
from src.services.app_metrics_contract import (
    APP_METRICS_SCHEMA_VERSION,
    APP_METRICS_WINDOW_LIMIT,
    APP_METRICS_STALE_SIGNAL_S,
    build_app_metrics_snapshot,
    _extract_profit,
    _classify_outcome,
    _safe_float,
    _safe_int,
    _json_safe,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trade(profit=0.0, exit_reason="TP", symbol="BTCUSDT", regime="RANGING", ts=None):
    return {
        "profit": profit,
        "close_reason": exit_reason,
        "symbol": symbol,
        "regime": regime,
        "timestamp": ts or time.time(),
    }


def _empty_snapshot(**kwargs):
    defaults = dict(
        closed_trades=[],
        session_metrics={},
        open_positions=[],
        last_signals={},
        all_time_stats=None,
        runtime=None,
        firebase_health=None,
        quota_status=None,
        now=1000000.0,
    )
    defaults.update(kwargs)
    return build_app_metrics_snapshot(**defaults)


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_app_metrics_snapshot_schema_version():
    s = _empty_snapshot()
    assert s["schema_version"] == APP_METRICS_SCHEMA_VERSION


def test_app_metrics_snapshot_has_required_keys():
    s = _empty_snapshot()
    for key in ("kpis", "runtime", "health", "window", "learning", "open_positions",
                "symbols", "regimes", "exits", "recommendations", "recent", "app_context_cs"):
        assert key in s, f"Missing key: {key}"


def test_app_metrics_snapshot_json_safe():
    import json
    s = _empty_snapshot()
    # Should not raise
    json.dumps(s)


def test_app_metrics_snapshot_no_nan():
    import json
    trades = [_trade(profit=float("nan")), _trade(profit=float("inf"))]
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    raw = json.dumps(s)
    assert "NaN" not in raw
    assert "Infinity" not in raw


# ── KPI correctness ───────────────────────────────────────────────────────────

def test_app_metrics_snapshot_has_all_time_and_window_counts():
    all_time = {"trades": 500, "wins": 300, "losses": 200}
    window = [_trade(0.01) for _ in range(10)] + [_trade(-0.005) for _ in range(5)]
    s = build_app_metrics_snapshot(
        closed_trades=window, session_metrics={}, open_positions=[], last_signals={},
        all_time_stats=all_time, now=1e6
    )
    assert s["kpis"]["trades_total_all_time"] == 500
    assert s["kpis"]["window_trades"] == 15


def test_app_metrics_snapshot_does_not_label_window_as_all_time():
    # If all_time_stats provided, source should be "system_stats", not "session_metrics"
    s = build_app_metrics_snapshot(
        closed_trades=[_trade(0.01)],
        session_metrics={"trades": 1},
        open_positions=[],
        last_signals={},
        all_time_stats={"trades": 999},
        now=1e6,
    )
    assert s["kpis"]["all_time_source"] == "system_stats"
    assert s["kpis"]["window_source"] == "load_history"


def test_app_metrics_snapshot_winrate():
    trades = [_trade(0.01)] * 7 + [_trade(-0.005)] * 3
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    assert abs(s["kpis"]["window_winrate"] - 0.7) < 0.01


def test_neutral_timeout_not_counted_as_loss():
    trades = [_trade(profit=-0.0001, exit_reason="TIMEOUT")]  # tiny loss on TIMEOUT → FLAT
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    assert s["kpis"]["window_flats"] == 1
    assert s["kpis"]["window_losses"] == 0


def test_tiny_positive_timeout_not_counted_as_win():
    trades = [_trade(profit=0.00005, exit_reason="TIMEOUT")]  # tiny gain → FLAT
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    assert s["kpis"]["window_flats"] == 1
    assert s["kpis"]["window_wins"] == 0


def test_per_symbol_counts_sum_to_total():
    trades = [_trade(0.01, symbol="BTCUSDT")] * 3 + [_trade(-0.005, symbol="ETHUSDT")] * 2
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    sym_total = sum(v["count"] for v in s["symbols"].values())
    assert sym_total == s["kpis"]["window_trades"]


def test_per_exit_counts_sum_to_total():
    trades = [_trade(0.01, exit_reason="TP")] * 3 + [_trade(-0.005, exit_reason="SL")] * 2
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    exit_total = sum(v["count"] for v in s["exits"].values())
    assert exit_total == s["kpis"]["window_trades"]


# ── Open positions ────────────────────────────────────────────────────────────

def test_app_metrics_snapshot_limits_open_positions():
    from src.services.app_metrics_contract import APP_METRICS_MAX_OPEN_POSITIONS
    ops = [{"trade_id": str(i), "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": 1e6}
           for i in range(APP_METRICS_MAX_OPEN_POSITIONS + 10)]
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=ops, last_signals={}, now=1e6
    )
    assert s["open_positions"]["count"] <= APP_METRICS_MAX_OPEN_POSITIONS
    assert len(s["open_positions"]["items"]) <= APP_METRICS_MAX_OPEN_POSITIONS


def test_app_metrics_snapshot_normalizes_dict_open_positions():
    ops = {
        "a": {"trade_id": "a", "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": 1e6},
        "b": {"trade_id": "b", "symbol": "ETHUSDT", "entry_price": 3000.0, "entry_ts": 1e6},
    }
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=ops, last_signals={}, now=1e6
    )
    assert s["open_positions"]["count"] == 2


# ── Recommendations ───────────────────────────────────────────────────────────

def test_recommendation_hold_when_no_signal():
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=[], last_signals={}, now=1e6
    )
    # No signals → recommendations dict is empty (no HOLD entries without known symbols)
    assert isinstance(s["recommendations"], dict)


def test_recommendation_stale_signal():
    now = 1e6
    last_signals = {
        "BTCUSDT": {"action": "BUY", "ts": now - APP_METRICS_STALE_SIGNAL_S - 1, "confidence": 0.8}
    }
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=[], last_signals=last_signals, now=now
    )
    rec = s["recommendations"]["BTCUSDT"]
    assert rec["action"] == "HOLD"
    assert rec["reason"] == "stale_signal"


def test_recommendation_fresh_signal():
    now = 1e6
    last_signals = {
        "BTCUSDT": {"action": "BUY", "ts": now - 10, "confidence": 0.8}
    }
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=[], last_signals=last_signals, now=now
    )
    rec = s["recommendations"]["BTCUSDT"]
    assert rec["action"] == "BUY"
    assert rec["reason"] == "latest_signal"


def test_recommendation_hold_in_safe_mode():
    now = 1e6
    last_signals = {
        "BTCUSDT": {"action": "BUY", "ts": now - 10, "confidence": 0.8}
    }
    runtime = {"safe_mode": True}
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=[], last_signals=last_signals,
        runtime=runtime, now=now
    )
    rec = s["recommendations"]["BTCUSDT"]
    assert rec["action"] == "HOLD"
    assert rec["reason"] == "safe_mode"


# ── Context string ────────────────────────────────────────────────────────────

def test_app_context_cs_present():
    s = _empty_snapshot()
    assert "app_context_cs" in s
    cs = s["app_context_cs"]
    assert "trades_total_all_time" in cs
    assert "winrate_all_time" in cs
    assert "profit_factor" in cs


# ── Profit extraction ─────────────────────────────────────────────────────────

def test_extract_profit_profit_field():
    assert _extract_profit({"profit": 0.05}) == 0.05


def test_extract_profit_pnl_field():
    assert _extract_profit({"pnl": -0.02}) == -0.02


def test_extract_profit_net_pnl_field():
    assert _extract_profit({"net_pnl": 0.03}) == pytest.approx(0.03)


def test_extract_profit_evaluation_nested():
    assert _extract_profit({"evaluation": {"profit": 0.01}}) == pytest.approx(0.01)


def test_extract_profit_priority():
    # profit takes priority over pnl
    assert _extract_profit({"profit": 0.05, "pnl": -0.99}) == pytest.approx(0.05)


# ── Safe helpers ──────────────────────────────────────────────────────────────

def test_safe_float_nan():
    assert _safe_float(float("nan")) == 0.0


def test_safe_float_inf():
    assert _safe_float(float("inf")) == 0.0


def test_safe_float_valid():
    assert _safe_float(3.14) == pytest.approx(3.14)


def test_safe_int_none():
    assert _safe_int(None) == 0


def test_safe_int_valid():
    assert _safe_int("42") == 42


def test_json_safe_removes_nan():
    result = _json_safe({"x": float("nan"), "y": [float("inf"), 1.0]})
    assert result["x"] == 0.0
    assert result["y"][0] == 0.0
    assert result["y"][1] == 1.0


# ── validate_learning_loop.py tests ──────────────────────────────────────────

def test_validate_learning_loop_ok():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from scripts.validate_learning_loop import scan_lines

    lines = [
        "[SIGNAL_RAW] sym=BTCUSDT",
        "[RDE_CANDIDATE] ev=0.02",
        "[TRAINING_SAMPLER_CHECK] bucket=C_WEAK_EV_TRAIN",
        "[PAPER_ENTRY_ATTEMPT] symbol=BTCUSDT",
        "[PAPER_TRAIN_ENTRY] trade_id=paper_abc123",
        "[PAPER_TIMEOUT_SCAN] scanning open_positions=1",
        "[PAPER_CLOSE_PATH] trade_id=paper_abc123 reason=TIMEOUT",
        "[PAPER_EXIT] symbol=BTCUSDT reason=TIMEOUT net_pnl_pct=-0.1234",
        "[LEARNING_UPDATE] source=paper_closed_trade ok=True",
        "[PAPER_TRAIN_CLOSED] bucket=C_WEAK_EV_TRAIN outcome=LOSS",
    ]
    ok, missing, counts = scan_lines(lines)
    assert ok is True
    assert missing == []


def test_validate_learning_loop_missing_stage():
    from scripts.validate_learning_loop import scan_lines

    lines = [
        "[SIGNAL_RAW] sym=BTCUSDT",
        "[RDE_CANDIDATE] ev=0.02",
        # TRAINING_SAMPLER_CHECK missing
        "[PAPER_ENTRY_ATTEMPT] symbol=BTCUSDT",
        "[PAPER_TRAIN_ENTRY] trade_id=paper_abc123",
        "[PAPER_TIMEOUT_SCAN] scanning",
        "[PAPER_CLOSE_PATH] trade_id=paper_abc123",
        "[PAPER_EXIT] symbol=BTCUSDT",
        "[LEARNING_UPDATE] ok=True",
        "[PAPER_TRAIN_CLOSED] bucket=C_WEAK_EV_TRAIN",
    ]
    ok, missing, _ = scan_lines(lines)
    assert ok is False
    assert "TRAINING_SAMPLER_CHECK" in missing
