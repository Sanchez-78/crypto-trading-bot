"""Tests for the P1.0 dynamic_trend_exit_v1 wiring into
paper_trade_executor.py (_workspace/36_dynamic_trend_exit_wiring.md).

Scope: _evaluate_p0_8_plus_dynamic_exit() (the routing helper) and
update_paper_positions()'s branch that calls it only for
trend_cost_aware_v1-sourced P0.8+ positions, leaving every other position
(including the other two P0.8+ strategies) on the unchanged generic
TP/SL/timeout path.
"""
import time
import types
from unittest.mock import patch

import pytest

from src.services import paper_trade_executor as pte
from src.services import dynamic_trend_exit_v1 as dyn_exit
from src.services.paper_trade_executor import (
    _evaluate_p0_8_plus_dynamic_exit,
    reset_paper_positions,
    update_paper_positions,
)


@pytest.fixture
def clean_positions():
    reset_paper_positions()
    yield
    reset_paper_positions()


def _p0_8_plus_trend_position(**overrides) -> dict:
    now = time.time()
    pos = {
        "trade_id": "paper_dyn1",
        "symbol": "ETHUSDT",
        "side": "BUY",
        "entry_price": 2000.0,
        "entry_ts": now - 60,
        "tp": 2040.0,
        "sl": 1980.0,
        "max_seen": 2010.0,
        "min_seen": 1995.0,
        "timeout_s": 600,
        "regime": "BULL_TREND",
        "explore_bucket": "P0_8_PLUS_EVIDENCE_COLLECTION",
        "training_bucket": "P0_8_PLUS_EVIDENCE_COLLECTION",
        "strategy_id": "trend_cost_aware",
    }
    pos.update(overrides)
    return pos


def _fake_trend_features(atr_bps=10.0, slow_slope=1.0, persistence=0.8):
    return types.SimpleNamespace(
        atr_bps=atr_bps,
        slow_slope_bps_per_minute=slow_slope,
        trend_persistence_ratio=persistence,
    )


# ---------------------------------------------------------------------------
# _evaluate_p0_8_plus_dynamic_exit
# ---------------------------------------------------------------------------

def test_returns_none_when_no_candle_history(clean_positions):
    """Fails closed / stays open (not: falls back to generic exit) when
    there isn't enough candle history to compute features yet."""
    pos = _p0_8_plus_trend_position()
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    with patch("src.services.candle_cache_v1.get_default_cache") as mock_cache:
        mock_cache.return_value.get_candles.return_value = []  # far below MIN_CANDLES
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert result is None


def test_never_raises_on_internal_exception(clean_positions):
    pos = _p0_8_plus_trend_position()
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    with patch.object(dyn_exit, "evaluate_exit", side_effect=RuntimeError("boom")), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert result is None


def test_terminal_decision_returns_legacy_mapped_reason(clean_positions):
    pos = _p0_8_plus_trend_position()
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    decision = dyn_exit.ExitDecision(
        reason_code=dyn_exit.MAX_HOLD_SAFETY_EXIT,
        legacy_label=dyn_exit.LEGACY_TIMEOUT_LABEL,
        trigger_price=2005.0,
        new_stop_price=None,
        detail="test",
    )
    with patch.object(dyn_exit, "evaluate_exit", return_value=decision), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    # legacy_exit_label maps MAX_HOLD_SAFETY_EXIT -> "TIMEOUT"
    assert result == "TIMEOUT"


def test_terminal_decision_non_timeout_reason_passes_through_unmapped(clean_positions):
    pos = _p0_8_plus_trend_position()
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    decision = dyn_exit.ExitDecision(
        reason_code=dyn_exit.TREND_INVALIDATED,
        legacy_label=dyn_exit.TREND_INVALIDATED,
        trigger_price=2005.0,
        new_stop_price=None,
        detail="test",
    )
    with patch.object(dyn_exit, "evaluate_exit", return_value=decision), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert result == dyn_exit.TREND_INVALIDATED


def test_non_terminal_trailing_stop_update_stays_open_and_mutates_sl(clean_positions):
    pos = _p0_8_plus_trend_position(sl=1980.0)
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    decision = dyn_exit.ExitDecision(
        reason_code=dyn_exit.TRAILING_STOP_EXIT,
        legacy_label=dyn_exit.TRAILING_STOP_EXIT,
        trigger_price=None,
        new_stop_price=1995.0,
        detail="test trail",
    )
    with patch.object(dyn_exit, "evaluate_exit", return_value=decision), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert result is None  # stays open
    assert pte._POSITIONS[pos["trade_id"]]["sl"] == 1995.0  # stop actually updated


def test_none_decision_keeps_position_open(clean_positions):
    pos = _p0_8_plus_trend_position()
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    with patch.object(dyn_exit, "evaluate_exit", return_value=None), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        result = _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert result is None


def test_initial_stop_snapshotted_once_and_not_overwritten_by_trailing(clean_positions):
    """The hierarchy needs to tell a trailed stop apart from the original
    one (HARD_STOP_VOLATILITY vs HARD_STOP_STRUCTURAL) -- confirm
    dynamic_exit_initial_stop is captured once and survives a later sl
    mutation."""
    pos = _p0_8_plus_trend_position(sl=1980.0)
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    with patch.object(dyn_exit, "evaluate_exit", return_value=None), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2005.0, time.time())
    assert pte._POSITIONS[pos["trade_id"]]["dynamic_exit_initial_stop"] == 1980.0

    # Simulate a later trailing update mutating sl -- initial snapshot must not move.
    pte._POSITIONS[pos["trade_id"]]["sl"] = 1995.0
    with patch.object(dyn_exit, "evaluate_exit", return_value=None), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 2010.0, time.time())
    assert pte._POSITIONS[pos["trade_id"]]["dynamic_exit_initial_stop"] == 1980.0


def test_mfe_bps_computed_side_aware(clean_positions):
    """BUY: favorable direction is UP (max_seen); SELL: favorable
    direction is DOWN (min_seen). Confirmed via the actual value passed
    into ExitEvaluationInput (captured via a spy)."""
    captured = {}

    def _spy_evaluate_exit(inp):
        captured["mfe_bps"] = inp.mfe_bps
        return None

    pos = _p0_8_plus_trend_position(side="SELL", entry_price=2000.0, min_seen=1960.0, max_seen=2005.0, tp=1900.0, sl=2050.0)
    pte._POSITIONS[pos["trade_id"]] = dict(pos)
    with patch.object(dyn_exit, "evaluate_exit", side_effect=_spy_evaluate_exit), \
         patch("src.services.candle_cache_v1.get_default_cache") as mock_cache, \
         patch("src.services.strategy_trend_cost_aware_v1.compute_trend_features", return_value=_fake_trend_features()):
        mock_cache.return_value.get_candles.return_value = [{}] * 250
        _evaluate_p0_8_plus_dynamic_exit(pos["trade_id"], pte._POSITIONS[pos["trade_id"]], 1990.0, time.time())
    # SELL favorable move: entry 2000 -> min_seen 1960 = 40/2000 = 200bps
    assert captured["mfe_bps"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# update_paper_positions() routing
# ---------------------------------------------------------------------------

def test_update_paper_positions_routes_trend_cost_aware_p0_8_plus_to_dynamic_exit(clean_positions):
    pos = _p0_8_plus_trend_position()
    trade_id = pos["trade_id"]
    with pte._POSITION_LOCK:
        pte._POSITIONS[trade_id] = dict(pos)

    with patch.object(pte, "_evaluate_p0_8_plus_dynamic_exit", return_value=None) as mock_dyn:
        update_paper_positions({"ETHUSDT": 2005.0}, time.time())

    mock_dyn.assert_called_once()
    assert mock_dyn.call_args.args[0] == trade_id


def test_update_paper_positions_dynamic_exit_closes_position_on_terminal_reason(clean_positions):
    pos = _p0_8_plus_trend_position()
    trade_id = pos["trade_id"]
    with pte._POSITION_LOCK:
        pte._POSITIONS[trade_id] = dict(pos)

    with patch.object(pte, "_evaluate_p0_8_plus_dynamic_exit", return_value="TREND_INVALIDATED"):
        closed = update_paper_positions({"ETHUSDT": 2005.0}, time.time())

    assert len(closed) == 1
    assert trade_id not in pte._POSITIONS


def test_update_paper_positions_other_p0_8_plus_strategy_uses_generic_exit(clean_positions):
    """sideways_mean_reversion_v1/volatility_breakout_v1 positions (same
    bucket, different strategy_id) must NOT be routed to the trend exit
    hierarchy -- dynamic_trend_exit_v1 imports TrendFeatures specifically
    and isn't designed for these strategies."""
    pos = _p0_8_plus_trend_position(strategy_id="sideways_mean_reversion")
    trade_id = pos["trade_id"]
    with pte._POSITION_LOCK:
        pte._POSITIONS[trade_id] = dict(pos)

    with patch.object(pte, "_evaluate_p0_8_plus_dynamic_exit") as mock_dyn:
        update_paper_positions({"ETHUSDT": 2005.0}, time.time())

    mock_dyn.assert_not_called()


def test_update_paper_positions_non_p0_8_plus_position_uses_generic_exit(clean_positions):
    """A normal (non-P0.8+) position must be completely unaffected."""
    pos = _p0_8_plus_trend_position(explore_bucket=None, training_bucket=None, strategy_id=None)
    trade_id = pos["trade_id"]
    with pte._POSITION_LOCK:
        pte._POSITIONS[trade_id] = dict(pos)

    with patch.object(pte, "_evaluate_p0_8_plus_dynamic_exit") as mock_dyn:
        update_paper_positions({"ETHUSDT": 2005.0}, time.time())

    mock_dyn.assert_not_called()
