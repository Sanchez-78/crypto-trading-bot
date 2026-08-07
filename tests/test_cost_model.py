"""P0.7 (Evidence-First Strategy Expansion v2, §9 + §22.1) — cost model tests.

Covers the document's mandatory §22.1 "Costs" checklist: long taker entry,
short taker entry, maker estimate, entry/exit fees, spread calculations,
slippage floor, latency buffer, funding crossing, no-funding horizon, NaN
rejection, negative cost rejection, net edge threshold.
"""
import math

import pytest

from src.services import cost_model as cm


# ---------------------------------------------------------------------------
# entry_spread_cost_bps -- long/short taker entry, sign conventions
# ---------------------------------------------------------------------------

def test_entry_spread_cost_long_taker():
    # bid=100, ask=100.10 -> mid=100.05, ask-mid = 0.05 -> 0.05/100.05*10000 ~= 4.998
    cost = cm.entry_spread_cost_bps("BUY", best_bid=100.0, best_ask=100.10)
    assert cost == pytest.approx(4.9975, abs=1e-3)
    assert cost > 0


def test_entry_spread_cost_short_taker():
    cost = cm.entry_spread_cost_bps("SELL", best_bid=100.0, best_ask=100.10)
    assert cost == pytest.approx(4.9975, abs=1e-3)
    assert cost > 0


def test_entry_spread_cost_long_and_short_equal_for_symmetric_book():
    long_cost = cm.entry_spread_cost_bps("BUY", best_bid=100.0, best_ask=100.10)
    short_cost = cm.entry_spread_cost_bps("SELL", best_bid=100.0, best_ask=100.10)
    assert long_cost == pytest.approx(short_cost)


def test_entry_spread_cost_rejects_crossed_book():
    with pytest.raises(ValueError):
        cm.entry_spread_cost_bps("BUY", best_bid=100.10, best_ask=100.0)


def test_entry_spread_cost_rejects_zero_or_negative_prices():
    with pytest.raises(ValueError):
        cm.entry_spread_cost_bps("BUY", best_bid=0.0, best_ask=100.0)
    with pytest.raises(ValueError):
        cm.entry_spread_cost_bps("BUY", best_bid=-1.0, best_ask=100.0)


def test_entry_spread_cost_rejects_unknown_side():
    with pytest.raises(ValueError):
        cm.entry_spread_cost_bps("SIDEWAYS", best_bid=100.0, best_ask=100.1)


def test_side_case_insensitive():
    a = cm.entry_spread_cost_bps("buy", best_bid=100.0, best_ask=100.1)
    b = cm.entry_spread_cost_bps("BUY", best_bid=100.0, best_ask=100.1)
    assert a == b


# ---------------------------------------------------------------------------
# slippage_estimate_bps -- floor, size pressure, volatility component
# ---------------------------------------------------------------------------

def test_slippage_floor_applies_with_zero_pressure_and_zero_vol():
    s = cm.slippage_estimate_bps(
        requested_notional=0.0, visible_top_notional=1000.0,
        spread_bps=0.0, realized_volatility_bps=0.0, floor_bps=0.5,
    )
    assert s == pytest.approx(0.5)


def test_slippage_increases_with_size_pressure():
    small = cm.slippage_estimate_bps(
        requested_notional=10.0, visible_top_notional=1000.0,
        spread_bps=5.0, realized_volatility_bps=0.0,
    )
    large = cm.slippage_estimate_bps(
        requested_notional=900.0, visible_top_notional=1000.0,
        spread_bps=5.0, realized_volatility_bps=0.0,
    )
    assert large > small


def test_slippage_size_pressure_capped_when_no_visible_liquidity():
    s = cm.slippage_estimate_bps(
        requested_notional=100.0, visible_top_notional=0.0,
        spread_bps=5.0, realized_volatility_bps=0.0,
    )
    # size_pressure clamps to 1.0 (maximal), not infinite/NaN from div-by-zero
    assert math.isfinite(s)
    assert s > cm.SLIPPAGE_FLOOR_BPS


def test_slippage_increases_with_volatility():
    low_vol = cm.slippage_estimate_bps(
        requested_notional=10.0, visible_top_notional=1000.0,
        spread_bps=1.0, realized_volatility_bps=1.0,
    )
    high_vol = cm.slippage_estimate_bps(
        requested_notional=10.0, visible_top_notional=1000.0,
        spread_bps=1.0, realized_volatility_bps=100.0,
    )
    assert high_vol > low_vol


def test_slippage_rejects_negative_notionals():
    with pytest.raises(ValueError):
        cm.slippage_estimate_bps(
            requested_notional=-1.0, visible_top_notional=100.0,
            spread_bps=1.0, realized_volatility_bps=1.0,
        )


# ---------------------------------------------------------------------------
# latency_cost_bps -- buffer floor
# ---------------------------------------------------------------------------

def test_latency_cost_floor_at_zero_latency():
    c = cm.latency_cost_bps(decision_latency_ms=0.0, realized_volatility_bps_per_second=0.0, floor_bps=0.5)
    assert c == pytest.approx(0.5)


def test_latency_cost_increases_with_latency_and_volatility():
    fast = cm.latency_cost_bps(decision_latency_ms=10.0, realized_volatility_bps_per_second=2.0)
    slow = cm.latency_cost_bps(decision_latency_ms=5000.0, realized_volatility_bps_per_second=2.0)
    assert slow > fast


def test_latency_cost_rejects_negative_latency():
    with pytest.raises(ValueError):
        cm.latency_cost_bps(decision_latency_ms=-1.0, realized_volatility_bps_per_second=1.0)


# ---------------------------------------------------------------------------
# funding_cost_bps -- crossing vs no-funding horizon
# ---------------------------------------------------------------------------

def test_funding_zero_when_position_closes_before_settlement():
    """§9.7: 'expected funding may often be zero because the position closes
    before settlement' -- horizon shorter than time-to-next-funding."""
    c = cm.funding_cost_bps(
        side="BUY", expected_horizon_seconds=60.0,
        seconds_to_next_funding=3600.0, current_funding_rate_bps=5.0,
    )
    assert c == 0.0


def test_funding_charged_when_horizon_spans_settlement():
    c = cm.funding_cost_bps(
        side="BUY", expected_horizon_seconds=7200.0,
        seconds_to_next_funding=60.0, current_funding_rate_bps=5.0,
    )
    assert c > 0.0


def test_funding_favorable_direction_floored_at_zero_not_negative():
    """A long position with a negative funding rate (longs get paid) must
    not turn into a negative *cost* (i.e. a discount) -- §9.7/§9.2 only ever
    subtract cost, never add a funding-driven bonus to admission."""
    c = cm.funding_cost_bps(
        side="BUY", expected_horizon_seconds=7200.0,
        seconds_to_next_funding=60.0, current_funding_rate_bps=-5.0,
    )
    assert c >= 0.0


def test_funding_unknown_returns_buffer_only():
    c = cm.funding_cost_bps(
        side="BUY", expected_horizon_seconds=100.0,
        seconds_to_next_funding=None, current_funding_rate_bps=None,
    )
    assert c == cm.FUNDING_BUFFER_BPS


def test_funding_rejects_negative_horizon():
    with pytest.raises(ValueError):
        cm.funding_cost_bps(
            side="BUY", expected_horizon_seconds=-1.0,
            seconds_to_next_funding=10.0, current_funding_rate_bps=1.0,
        )


# ---------------------------------------------------------------------------
# evaluate_edge -- full composition, maker vs taker, NaN/negative rejection,
# net edge admission threshold
# ---------------------------------------------------------------------------

def _base_kwargs(**overrides):
    kwargs = dict(
        side="BUY",
        gross_expected_move_bps=30.0,
        best_bid=100.0,
        best_ask=100.10,
        requested_notional=25.0,
        visible_top_notional=1000.0,
        realized_volatility_bps=10.0,
        realized_volatility_bps_per_second=0.5,
        decision_latency_ms=50.0,
        expected_horizon_seconds=300.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_evaluate_edge_taker_entry_and_exit_fees():
    ev = cm.evaluate_edge(**_base_kwargs(expected_exit_order_type="taker"))
    assert ev.cost.entry_fee_bps == cm.TAKER_FEE_BPS
    assert ev.cost.expected_exit_fee_bps == cm.TAKER_FEE_BPS


def test_evaluate_edge_maker_exit_is_cheaper_than_taker_exit():
    taker_ev = cm.evaluate_edge(**_base_kwargs(expected_exit_order_type="taker"))
    maker_ev = cm.evaluate_edge(**_base_kwargs(expected_exit_order_type="maker"))
    assert maker_ev.cost.expected_exit_fee_bps == cm.MAKER_FEE_BPS
    assert maker_ev.all_in_cost_bps < taker_ev.all_in_cost_bps


def test_evaluate_edge_maker_exit_spread_not_zero():
    """§9.4: 'For a maker plan, do not automatically set spread cost to
    zero.'"""
    maker_ev = cm.evaluate_edge(**_base_kwargs(expected_exit_order_type="maker"))
    assert maker_ev.cost.expected_exit_spread_cost_bps > 0.0


def test_evaluate_edge_rejects_invalid_exit_order_type():
    with pytest.raises(ValueError):
        cm.evaluate_edge(**_base_kwargs(expected_exit_order_type="iceberg"))


def test_evaluate_edge_rejects_nan_gross_move():
    with pytest.raises(ValueError):
        cm.evaluate_edge(**_base_kwargs(gross_expected_move_bps=float("nan")))


def test_evaluate_edge_rejects_infinite_volatility():
    with pytest.raises(ValueError):
        cm.evaluate_edge(**_base_kwargs(realized_volatility_bps=float("inf")))


@pytest.mark.parametrize("field", [
    "gross_expected_move_bps", "best_bid", "best_ask", "requested_notional",
    "visible_top_notional", "realized_volatility_bps",
    "realized_volatility_bps_per_second", "decision_latency_ms",
    "expected_horizon_seconds",
])
def test_evaluate_edge_rejects_nan_in_every_numeric_field(field):
    with pytest.raises(ValueError):
        cm.evaluate_edge(**_base_kwargs(**{field: float("nan")}))


def test_evaluate_edge_all_costs_non_negative():
    ev = cm.evaluate_edge(**_base_kwargs())
    assert ev.cost.entry_fee_bps >= 0
    assert ev.cost.expected_exit_fee_bps >= 0
    assert ev.cost.entry_spread_cost_bps >= 0
    assert ev.cost.expected_exit_spread_cost_bps >= 0
    assert ev.cost.expected_entry_slippage_bps >= 0
    assert ev.cost.expected_exit_slippage_bps >= 0
    assert ev.cost.expected_funding_bps >= 0
    assert ev.cost.latency_adverse_move_bps >= 0
    assert ev.all_in_cost_bps >= 0


def test_evaluate_edge_net_edge_below_gross_move():
    """Property invariant (§22.7): net expected edge <= gross expected move."""
    ev = cm.evaluate_edge(**_base_kwargs())
    assert ev.net_expected_edge_bps <= ev.gross_expected_move_bps


def test_evaluate_edge_admission_threshold_true_when_edge_clears():
    ev = cm.evaluate_edge(**_base_kwargs(
        gross_expected_move_bps=1000.0,  # comfortably clears any realistic cost
        minimum_net_edge_bps=0.0,
    ))
    assert ev.admitted is True


def test_evaluate_edge_admission_threshold_false_when_edge_thin():
    ev = cm.evaluate_edge(**_base_kwargs(
        gross_expected_move_bps=0.01,  # essentially zero gross move
        minimum_net_edge_bps=0.0,
    ))
    assert ev.admitted is False
    assert ev.net_expected_edge_bps < 0


def test_evaluate_edge_admission_respects_configured_minimum():
    """A positive net edge can still be rejected if it doesn't clear a
    configured minimum_net_edge_bps buffer."""
    ev = cm.evaluate_edge(**_base_kwargs(
        gross_expected_move_bps=20.0,
        minimum_net_edge_bps=1000.0,  # deliberately unreachable
    ))
    assert ev.admitted is False


def test_required_edge_bps_is_cost_plus_both_buffers():
    ev = cm.evaluate_edge(**_base_kwargs(
        uncertainty_buffer_bps=3.0, minimum_edge_buffer_bps=2.0,
    ))
    assert ev.required_edge_bps == pytest.approx(ev.all_in_cost_bps + 3.0 + 2.0)


def test_evaluate_edge_side_symmetry_long_short_same_book():
    """Long and short candidates against a symmetric book should produce the
    same all-in cost (document §10.4: 'test long and short separately' --
    this confirms no accidental sign-flip bug for the symmetric case)."""
    long_ev = cm.evaluate_edge(**_base_kwargs(side="BUY"))
    short_ev = cm.evaluate_edge(**_base_kwargs(side="SELL"))
    assert long_ev.all_in_cost_bps == pytest.approx(short_ev.all_in_cost_bps)


# ---------------------------------------------------------------------------
# CostBreakdown / EdgeEvaluation are frozen (immutable per document §7)
# ---------------------------------------------------------------------------

def test_cost_breakdown_is_frozen():
    cb = cm.CostBreakdown(0, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(Exception):
        cb.entry_fee_bps = 999  # type: ignore[misc]


def test_edge_evaluation_is_frozen():
    ev = cm.evaluate_edge(**_base_kwargs())
    with pytest.raises(Exception):
        ev.gross_expected_move_bps = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# §9.3 config logging -- must not raise, must not touch secrets
# ---------------------------------------------------------------------------

def test_log_effective_cost_config_does_not_raise():
    import logging

    log = logging.getLogger("test.cost_model")
    cm.log_effective_cost_config(log)  # must not raise
