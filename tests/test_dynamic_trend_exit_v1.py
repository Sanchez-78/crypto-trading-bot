"""P1.0 (Evidence-First Strategy Expansion v2, Sec 12, Sec 22.1 'Exits') tests."""
import pytest

from src.services import dynamic_trend_exit_v1 as exitmod
from src.services.order_flow_features import FLOW_CONFLICT_LONG, FLOW_CONFIRM_BULLISH, FlowEvaluation
from src.services.strategy_trend_cost_aware_v1 import TrendFeatures


def _features(slow_slope=2.0, persistence=0.8):
    return TrendFeatures(
        fast_slope_bps_per_minute=slow_slope, slow_slope_bps_per_minute=slow_slope,
        price_to_vwap_bps=5.0, higher_high_score=0.6, higher_low_score=0.6,
        lower_high_score=0.0, lower_low_score=0.0, trend_persistence_ratio=persistence,
        trend_strength_score=0.7, atr_bps=20.0, realized_volatility=0.001,
    )


def _base_input(**overrides):
    kwargs = dict(
        side="BUY", entry_price=1000.0, current_price=1000.0,
        initial_stop_price=990.0, current_stop_price=990.0,
        target_reference_price=1030.0, entry_time_ms=1_000_000,
        now_ms=1_000_000, max_hold_seconds=900, atr_bps=20.0, mfe_bps=0.0,
        regime="BULL_TREND",
    )
    kwargs.update(overrides)
    return exitmod.ExitEvaluationInput(**kwargs)


# ---------------------------------------------------------------------------
# construction / validation
# ---------------------------------------------------------------------------

def test_rejects_unknown_side():
    with pytest.raises(ValueError):
        _base_input(side="SIDEWAYS")


def test_rejects_non_positive_prices():
    with pytest.raises(ValueError):
        _base_input(entry_price=0.0)


def test_rejects_now_before_entry():
    with pytest.raises(ValueError):
        _base_input(now_ms=999_999)


def test_holding_seconds_computed_correctly():
    inp = _base_input(entry_time_ms=1_000_000, now_ms=1_010_000)
    assert inp.holding_seconds == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# hierarchy order 1: data-integrity exit
# ---------------------------------------------------------------------------

def test_data_integrity_exit_fires_first_even_with_other_triggers():
    inp = _base_input(current_price=980.0, data_integrity_ok=False)  # also breaches stop
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.DATA_INTEGRITY_EXIT


# ---------------------------------------------------------------------------
# hierarchy order 2: hard stop -- structural vs volatility, long and short
# ---------------------------------------------------------------------------

def test_long_hard_stop_breach_volatility():
    inp = _base_input(current_price=985.0, current_stop_price=990.0, initial_stop_price=990.0)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.HARD_STOP_VOLATILITY
    assert d.legacy_label == exitmod.HARD_STOP_VOLATILITY  # not remapped


def test_long_hard_stop_breach_structural_when_trailed():
    """current_stop != initial_stop -- the stop trailed at some point, so a
    breach now is classified as structural, not the original volatility stop."""
    inp = _base_input(current_price=995.0, current_stop_price=996.0, initial_stop_price=990.0)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.HARD_STOP_STRUCTURAL


def test_short_hard_stop_breach():
    inp = _base_input(
        side="SELL", entry_price=1000.0, current_price=1011.0,
        initial_stop_price=1010.0, current_stop_price=1010.0, target_reference_price=970.0,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.HARD_STOP_VOLATILITY


def test_no_exit_when_price_between_stop_and_target():
    inp = _base_input(current_price=1005.0)
    d = exitmod.evaluate_exit(inp)
    assert d is None


# ---------------------------------------------------------------------------
# hierarchy order 4: opposite-flow exit
# ---------------------------------------------------------------------------

def test_opposite_flow_exit_for_long():
    flow = FlowEvaluation(FLOW_CONFLICT_LONG, -1.0, -0.5, -100.0, -100.0, 0.0, 0.0, False)
    inp = _base_input(current_price=1005.0, flow_evaluation=flow)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.FLOW_REVERSAL_EXIT


def test_confirming_flow_does_not_trigger_exit():
    flow = FlowEvaluation(FLOW_CONFIRM_BULLISH, 1.0, 0.5, 100.0, 100.0, 1.0, 1.0, False)
    inp = _base_input(current_price=1005.0, flow_evaluation=flow)
    d = exitmod.evaluate_exit(inp)
    assert d is None


# ---------------------------------------------------------------------------
# hierarchy order 5: structural trend failure
# ---------------------------------------------------------------------------

def test_structural_trend_failure_slope_reversed():
    features = _features(slow_slope=-1.0)  # reversed for a long position
    inp = _base_input(current_price=1005.0, trend_features=features)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.TREND_INVALIDATED


def test_structural_trend_failure_persistence_collapsed():
    features = _features(slow_slope=2.0, persistence=0.1)  # below floor
    inp = _base_input(current_price=1005.0, trend_features=features)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.TREND_INVALIDATED


def test_healthy_trend_does_not_trigger_structural_exit():
    features = _features(slow_slope=2.0, persistence=0.8)
    inp = _base_input(current_price=1005.0, trend_features=features)
    d = exitmod.evaluate_exit(inp)
    assert d is None


def test_structural_exit_respects_minimum_holding_seconds():
    features = _features(slow_slope=-1.0)
    inp = _base_input(
        current_price=1005.0, trend_features=features,
        entry_time_ms=1_000_000, now_ms=1_000_500, min_holding_seconds=60,
    )
    d = exitmod.evaluate_exit(inp)
    assert d is None  # too early, structural check suppressed


def test_regime_invalidated_exit():
    inp = _base_input(current_price=1005.0, regime="SIDEWAYS", allowed_regimes=frozenset({"BULL_TREND"}))
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.REGIME_INVALIDATED


# ---------------------------------------------------------------------------
# hierarchy order 6: edge decay
# ---------------------------------------------------------------------------

def test_edge_decay_exit_after_minimum_holding():
    inp = _base_input(
        current_price=1005.0, remaining_net_edge_bps=-1.0,
        entry_time_ms=1_000_000, now_ms=1_000_000 + 40_000,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.EDGE_DECAY_EXIT


def test_edge_decay_suppressed_before_minimum_holding():
    inp = _base_input(
        current_price=1005.0, remaining_net_edge_bps=-1.0,
        entry_time_ms=1_000_000, now_ms=1_000_000 + 5_000,  # too early
    )
    d = exitmod.evaluate_exit(inp)
    assert d is None


def test_positive_remaining_edge_does_not_trigger_decay_exit():
    inp = _base_input(
        current_price=1005.0, remaining_net_edge_bps=5.0,
        entry_time_ms=1_000_000, now_ms=1_000_000 + 40_000,
    )
    d = exitmod.evaluate_exit(inp)
    assert d is None


# ---------------------------------------------------------------------------
# hierarchy order 7: trailing stop -- activation + monotonicity
# ---------------------------------------------------------------------------

def test_trailing_not_activated_below_mfe_threshold():
    inp = _base_input(current_price=1005.0, mfe_bps=5.0, atr_bps=20.0)  # 5 < 1.5*20=30
    assert exitmod.compute_trailing_stop(inp) is None


def test_trailing_activated_above_mfe_threshold_long():
    inp = _base_input(current_price=1010.0, mfe_bps=40.0, atr_bps=20.0, current_stop_price=990.0)
    new_stop = exitmod.compute_trailing_stop(inp)
    assert new_stop is not None
    assert new_stop > 990.0  # tightened, not loosened


def test_trailing_never_loosens_long():
    """Sec 12.7: new_stop >= old_stop for long."""
    inp = _base_input(current_price=995.0, mfe_bps=40.0, atr_bps=20.0, current_stop_price=994.0)
    new_stop = exitmod.compute_trailing_stop(inp)
    assert new_stop >= 994.0


def test_trailing_never_loosens_short():
    """Sec 12.7: new_stop <= old_stop for short."""
    inp = _base_input(
        side="SELL", entry_price=1000.0, current_price=1005.0,
        initial_stop_price=1010.0, current_stop_price=1006.0, target_reference_price=970.0,
        mfe_bps=40.0, atr_bps=20.0,
    )
    new_stop = exitmod.compute_trailing_stop(inp)
    assert new_stop <= 1006.0


def test_trailing_stop_decision_updates_stop_not_closes_position():
    inp = _base_input(current_price=1010.0, mfe_bps=40.0, atr_bps=20.0, current_stop_price=990.0,
                       target_reference_price=1100.0)  # target far away, won't trigger
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.TRAILING_STOP_EXIT
    assert d.new_stop_price is not None
    assert d.trigger_price is None  # does not terminate the position


# ---------------------------------------------------------------------------
# hierarchy order 8: dynamic target
# ---------------------------------------------------------------------------

def test_target_reached_long():
    inp = _base_input(current_price=1035.0, target_reference_price=1030.0, mfe_bps=0.0)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.DYNAMIC_TARGET_EXIT


def test_target_reached_short():
    inp = _base_input(
        side="SELL", entry_price=1000.0, current_price=965.0,
        initial_stop_price=1010.0, current_stop_price=1010.0, target_reference_price=970.0,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.DYNAMIC_TARGET_EXIT


def test_no_target_configured_never_triggers():
    inp = _base_input(current_price=2000.0, target_reference_price=None)
    d = exitmod.evaluate_exit(inp)
    assert d is None or d.reason_code != exitmod.DYNAMIC_TARGET_EXIT


# ---------------------------------------------------------------------------
# hierarchy order 9: maximum-hold safety exit + legacy TIMEOUT mapping
# ---------------------------------------------------------------------------

def test_max_hold_safety_exit_fires_as_last_resort():
    inp = _base_input(
        current_price=1005.0, entry_time_ms=1_000_000, now_ms=1_000_000 + 900_000,
        max_hold_seconds=900,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.MAX_HOLD_SAFETY_EXIT


def test_max_hold_safety_exit_maps_to_legacy_timeout_label():
    """Sec 12.10: 'If old dashboards expect TIMEOUT, map it explicitly
    without losing the detailed reason.'"""
    inp = _base_input(
        current_price=1005.0, entry_time_ms=1_000_000, now_ms=1_000_000 + 900_000,
        max_hold_seconds=900,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.legacy_label == "TIMEOUT"
    assert d.reason_code == exitmod.MAX_HOLD_SAFETY_EXIT  # detailed reason preserved


def test_no_exit_before_max_hold():
    inp = _base_input(
        current_price=1005.0, entry_time_ms=1_000_000, now_ms=1_000_000 + 100_000,
        max_hold_seconds=900,
    )
    d = exitmod.evaluate_exit(inp)
    assert d is None


# ---------------------------------------------------------------------------
# exit ordering (Sec 22.1 "Exit ordering") -- higher-priority levels win
# over lower-priority ones when multiple conditions are simultaneously true
# ---------------------------------------------------------------------------

def test_hard_stop_takes_priority_over_max_hold():
    inp = _base_input(
        current_price=985.0,  # breaches stop
        entry_time_ms=1_000_000, now_ms=1_000_000 + 900_000,  # also past max hold
        max_hold_seconds=900,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.HARD_STOP_VOLATILITY


def test_opposite_flow_takes_priority_over_structural_and_target():
    flow = FlowEvaluation(FLOW_CONFLICT_LONG, -1.0, -0.5, -100.0, -100.0, 0.0, 0.0, False)
    features = _features(slow_slope=-1.0)  # also structurally failed
    inp = _base_input(current_price=1035.0, target_reference_price=1030.0,  # also target-reached
                       flow_evaluation=flow, trend_features=features)
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.FLOW_REVERSAL_EXIT


def test_target_takes_priority_over_max_hold_when_both_true():
    inp = _base_input(
        current_price=1035.0, target_reference_price=1030.0,
        entry_time_ms=1_000_000, now_ms=1_000_000 + 900_000, max_hold_seconds=900,
    )
    d = exitmod.evaluate_exit(inp)
    assert d.reason_code == exitmod.DYNAMIC_TARGET_EXIT


# ---------------------------------------------------------------------------
# determinism (Sec 22.4)
# ---------------------------------------------------------------------------

def test_evaluate_exit_deterministic():
    inp = _base_input(current_price=1005.0)
    a = exitmod.evaluate_exit(inp)
    b = exitmod.evaluate_exit(inp)
    assert a == b
