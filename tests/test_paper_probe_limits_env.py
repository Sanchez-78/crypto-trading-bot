"""Operator overrides for PAPER probe sampling limits; defaults unchanged, invalid fails closed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services import paper_learning_budget as budget
from src.services import paper_source_learning as learning

NOW_MS = 1_800_000_000_000
HOUR_MS = 3_600_000
LIMIT_KEYS = ("PAPER_PROBE_HOURLY_ENTRIES", "PAPER_PROBE_DAILY_ENTRIES",
              "PAPER_PROBE_SYMBOL_COOLDOWN_S", "PAPER_PROBE_MIN_NET_BPS")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in LIMIT_KEYS:
        monkeypatch.delenv(key, raising=False)


def entry(index, *, age_ms=60_000, symbol=None):
    return budget.Entry(f"trade-{index}", symbol or f"SYMBOL{index}USDT", NOW_MS - age_ms)


def test_unset_env_keeps_original_limits():
    assert budget.limits({}) == budget.Limits(6, 48, 1_800_000)
    assert budget.limits() == budget.Limits(6, 48, 1_800_000)
    assert learning.min_probe_net_bps({}) == -15.0


def test_env_overrides_are_parsed():
    env = {"PAPER_PROBE_HOURLY_ENTRIES": "30", "PAPER_PROBE_DAILY_ENTRIES": "480",
           "PAPER_PROBE_SYMBOL_COOLDOWN_S": "300", "PAPER_PROBE_MIN_NET_BPS": "-25"}
    assert budget.limits(env) == budget.Limits(30, 480, 300_000)
    assert learning.min_probe_net_bps(env) == -25.0


def test_blank_value_means_default():
    assert budget.limits({"PAPER_PROBE_DAILY_ENTRIES": "  "}).daily == 48


@pytest.mark.parametrize("key,value", [
    ("PAPER_PROBE_HOURLY_ENTRIES", "0"), ("PAPER_PROBE_HOURLY_ENTRIES", "x"),
    ("PAPER_PROBE_HOURLY_ENTRIES", "6.5"), ("PAPER_PROBE_DAILY_ENTRIES", "901"),
    ("PAPER_PROBE_DAILY_ENTRIES", "-1"), ("PAPER_PROBE_SYMBOL_COOLDOWN_S", "-5"),
    ("PAPER_PROBE_SYMBOL_COOLDOWN_S", "86401"),
])
def test_invalid_limits_fail_closed(key, value):
    with pytest.raises(ValueError, match="invalid_paper_probe_limit"):
        budget.limits({key: value})


@pytest.mark.parametrize("value", ["1", "-100.5", "nan", "inf", "abc"])
def test_invalid_min_net_fails_closed(value):
    with pytest.raises(ValueError, match="invalid_paper_probe_min_net"):
        learning.min_probe_net_bps({"PAPER_PROBE_MIN_NET_BPS": value})


def test_raised_hourly_limit_allows_more_entries(monkeypatch):
    rows = [entry(i) for i in range(6)]
    assert budget.pacing_reason(rows, symbol="NEW", now_ms=NOW_MS) == "rolling_hour_limit"
    monkeypatch.setenv("PAPER_PROBE_HOURLY_ENTRIES", "30")
    assert budget.pacing_reason(rows, symbol="NEW", now_ms=NOW_MS) == "allow"
    full = [entry(i) for i in range(30)]
    assert budget.pacing_reason(full, symbol="NEW", now_ms=NOW_MS) == "rolling_hour_limit"


def test_raised_daily_limit_allows_more_entries(monkeypatch):
    older = [entry(i, age_ms=2 * HOUR_MS + i * 1000) for i in range(48)]
    assert budget.pacing_reason(older, symbol="NEW", now_ms=NOW_MS) == "rolling_day_limit"
    monkeypatch.setenv("PAPER_PROBE_DAILY_ENTRIES", "480")
    assert budget.pacing_reason(older, symbol="NEW", now_ms=NOW_MS) == "allow"


def test_shorter_cooldown(monkeypatch):
    rows = [entry(0, age_ms=10 * 60_000, symbol="ETHUSDT")]
    assert budget.pacing_reason(rows, symbol="ETHUSDT", now_ms=NOW_MS) == "symbol_cooldown"
    monkeypatch.setenv("PAPER_PROBE_SYMBOL_COOLDOWN_S", "300")
    assert budget.pacing_reason(rows, symbol="ETHUSDT", now_ms=NOW_MS) == "allow"
    recent = [entry(0, age_ms=4 * 60_000, symbol="ETHUSDT")]
    assert budget.pacing_reason(recent, symbol="ETHUSDT", now_ms=NOW_MS) == "symbol_cooldown"


def test_explicit_limit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv("PAPER_PROBE_HOURLY_ENTRIES", "30")
    rows = [entry(i) for i in range(6)]
    assert budget.pacing_reason(rows, symbol="NEW", now_ms=NOW_MS,
                                limit=budget.Limits(6, 48, 1_800_000)) == "rolling_hour_limit"


def test_min_net_override_changes_probe_cost_decision(monkeypatch):
    monkeypatch.setattr(learning, "probe_signal_valid", lambda signal: True)
    edge = SimpleNamespace(gross_expected_move_bps=2.0, all_in_cost_bps=9.0, net_expected_edge_bps=-20.0)
    assert learning.probe_cost_allowed(object(), edge) is False
    monkeypatch.setenv("PAPER_PROBE_MIN_NET_BPS", "-25")
    assert learning.probe_cost_allowed(object(), edge) is True
    edge_cost = SimpleNamespace(gross_expected_move_bps=2.0, all_in_cost_bps=21.0, net_expected_edge_bps=-19.0)
    assert learning.probe_cost_allowed(object(), edge_cost) is False


def _paper_env(**extra):
    env = {"TRADING_MODE": "paper_train", "PAPER_ONLY_MODE": "true", "ENABLE_REAL_ORDERS": "false",
           "REAL_ORDERS_ALLOWED": "false", "LIVE_TRADING_CONFIRMED": "false",
           "PAPER_TP_ZONE_BPS": "35", "PAPER_SL_ZONE_BPS": "25", "PAPER_MAX_POSITION_AGE_S": "900",
           "PAPER_FEE_PCT": "0.0008", "PAPER_SLIPPAGE_PCT": "0.0001",
           "PAPER_UNIFIED_ENGINE_ENABLED": "true", "PAPER_P0_8_PLUS_LIVE_ENABLED": "true",
           "PAPER_ADAPTIVE_EXPLORATION_ENABLED": "true", "PAPER_COMPLETED_CANDLE_LEARNING_ENABLED": "true",
           "PAPER_COST_EXPLORATION_ENABLED": "true"}
    env.update(extra)
    return env


def test_validate_config_rejects_invalid_overrides_at_startup():
    learning.validate_config(_paper_env(PAPER_PROBE_DAILY_ENTRIES="480", PAPER_PROBE_MIN_NET_BPS="-25"))
    with pytest.raises(ValueError, match="invalid_paper_probe_limit"):
        learning.validate_config(_paper_env(PAPER_PROBE_DAILY_ENTRIES="5000"))
    with pytest.raises(ValueError, match="invalid_paper_probe_min_net"):
        learning.validate_config(_paper_env(PAPER_PROBE_MIN_NET_BPS="5"))


def _ctx():
    return learning.LearningContext("trend_cost_aware_v1", "1", "dynamic_trend_exit_v1",
                                    "a" * 64, "ETHUSDT", "BULL_TREND", "BUY")


def _losses(ctx, n=20, value=-30.0):
    return [learning.ClosedOutcome(f"t{i}", ctx.key, NOW_MS - 100000 + i * 1000,
                                   NOW_MS - 50000 + i * 1000, value) for i in range(n)]


def test_control_fraction_default_and_validation(monkeypatch):
    monkeypatch.delenv("PAPER_LEARNING_CONTROL_FRACTION", raising=False)
    assert learning.control_fraction({}) == 0.2
    assert learning.control_fraction({"PAPER_LEARNING_CONTROL_FRACTION": "1"}) == 1.0
    for bad in ("-0.1", "1.01", "nan", "x"):
        with pytest.raises(ValueError, match="invalid_paper_learning_control_fraction"):
            learning.control_fraction({"PAPER_LEARNING_CONTROL_FRACTION": bad})
    with pytest.raises(ValueError, match="invalid_paper_learning_control_fraction"):
        learning.validate_config(_paper_env(PAPER_LEARNING_CONTROL_FRACTION="2"))


def test_full_control_admits_every_candidate_and_keeps_estimate(monkeypatch):
    ctx = _ctx()
    rows = _losses(ctx)
    held = [learning.decide(ctx, rows, decision_id=str(i), as_of_ms=NOW_MS) for i in range(200)]
    assert any(d.action == "HOLD" for d in held)
    monkeypatch.setenv("PAPER_LEARNING_CONTROL_FRACTION", "1")
    full = [learning.decide(ctx, rows, decision_id=str(i), as_of_ms=NOW_MS) for i in range(200)]
    assert all(d.allowed and d.action == "CONTROL" for d in full)
    # The learner estimate is logged unchanged; only the admission action differs.
    assert [d.mean_net_bps for d in full] == [d.mean_net_bps for d in held]
    assert all(d.mean_net_bps < -20 for d in full)
    monkeypatch.setenv("PAPER_LEARNING_CONTROL_FRACTION", "0")
    none = [learning.decide(ctx, rows, decision_id=str(i), as_of_ms=NOW_MS) for i in range(200)]
    assert not any(d.action == "CONTROL" for d in none)
