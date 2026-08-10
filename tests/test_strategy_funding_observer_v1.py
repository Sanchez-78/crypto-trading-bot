"""P1.3 (Evidence-First Strategy Expansion v2, §15) -- funding_observer_v1 tests."""
import math

import pytest

from src.services import strategy_funding_observer_v1 as fo


# ---------------------------------------------------------------------------
# normalize_funding_rate -- §15.2
# ---------------------------------------------------------------------------

def test_normalize_funding_rate_8h_to_24h_triples():
    per_24h, _ = fo.normalize_funding_rate(rate_bps_per_interval=1.0, funding_interval_seconds=8 * 3600.0)
    assert per_24h == pytest.approx(3.0)


def test_normalize_funding_rate_annualized_is_linear_extrapolation():
    per_24h, annualized_pct = fo.normalize_funding_rate(rate_bps_per_interval=1.0, funding_interval_seconds=8 * 3600.0)
    assert annualized_pct == pytest.approx(per_24h * 365.0 / 100.0)


def test_normalize_funding_rate_rejects_non_positive_interval():
    with pytest.raises(ValueError):
        fo.normalize_funding_rate(rate_bps_per_interval=1.0, funding_interval_seconds=0.0)


def test_normalize_funding_rate_rejects_nonfinite_rate():
    with pytest.raises(ValueError):
        fo.normalize_funding_rate(rate_bps_per_interval=float("nan"), funding_interval_seconds=28800.0)


def test_normalize_funding_rate_negative_funding_sign_preserved():
    """Negative funding (longs receive) must not be clamped to zero here --
    §15.1 collects the raw rate; clamping is a §15.3 opportunity-score
    concern, not a normalization concern."""
    per_24h, annualized_pct = fo.normalize_funding_rate(rate_bps_per_interval=-2.0, funding_interval_seconds=8 * 3600.0)
    assert per_24h < 0
    assert annualized_pct < 0


# ---------------------------------------------------------------------------
# expected_net_funding_return_bps -- §15.3
# ---------------------------------------------------------------------------

def test_expected_net_return_subtracts_all_five_terms():
    net = fo.expected_net_funding_return_bps(
        expected_funding_capture_bps=10.0, entry_cost_bps=3.0, exit_cost_bps=3.0,
        basis_risk_buffer_bps=1.0, execution_risk_buffer_bps=0.5,
    )
    assert net == pytest.approx(10.0 - 3.0 - 3.0 - 1.0 - 0.5)


def test_expected_net_return_can_go_negative():
    net = fo.expected_net_funding_return_bps(
        expected_funding_capture_bps=1.0, entry_cost_bps=5.0, exit_cost_bps=5.0,
    )
    assert net < 0


def test_expected_net_return_rejects_nonfinite_input():
    with pytest.raises(ValueError):
        fo.expected_net_funding_return_bps(
            expected_funding_capture_bps=float("inf"), entry_cost_bps=1.0, exit_cost_bps=1.0,
        )


def test_expected_net_return_default_buffers_are_conservative_not_zero():
    """§15.3's buffers must not silently default to zero -- that would
    understate risk exactly like the funding-carry research thread's own
    early v2 headline (see module docstring's scope-distinction note)."""
    assert fo.DEFAULT_BASIS_RISK_BUFFER_BPS > 0
    assert fo.DEFAULT_EXECUTION_RISK_BUFFER_BPS > 0


# ---------------------------------------------------------------------------
# basis_bps
# ---------------------------------------------------------------------------

def test_basis_bps_positive_when_mark_above_index():
    assert fo.basis_bps(mark_price=101.0, index_price=100.0) == pytest.approx(100.0)


def test_basis_bps_none_when_index_unavailable():
    assert fo.basis_bps(mark_price=101.0, index_price=None) is None


def test_basis_bps_none_when_index_non_positive():
    assert fo.basis_bps(mark_price=101.0, index_price=0.0) is None


# ---------------------------------------------------------------------------
# observe_funding_opportunity -- integration
# ---------------------------------------------------------------------------

def test_observe_funding_opportunity_builds_valid_observation():
    obs = fo.observe_funding_opportunity(
        symbol="BTCUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=1.5, mark_price=65000.0,
        estimated_entry_cost_bps=2.0, estimated_exit_cost_bps=2.0,
        index_price=64990.0, spread_bps=0.5, liquidity_proxy=1_000_000.0,
        realized_volatility_bps=20.0,
    )
    assert obs.symbol == "BTCUSDT"
    assert obs.current_funding_rate_bps == 1.5
    assert obs.expected_funding_capture_bps_per_interval == 1.5
    assert obs.expected_funding_capture_bps_per_24h == pytest.approx(4.5)
    assert obs.basis_bps is not None
    assert math.isfinite(obs.expected_net_funding_return_bps)


def test_observe_funding_opportunity_net_return_matches_manual_calc():
    obs = fo.observe_funding_opportunity(
        symbol="ETHUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=5.0, mark_price=3000.0,
        estimated_entry_cost_bps=3.0, estimated_exit_cost_bps=3.0,
    )
    expected = 5.0 - 3.0 - 3.0 - fo.DEFAULT_BASIS_RISK_BUFFER_BPS - fo.DEFAULT_EXECUTION_RISK_BUFFER_BPS
    assert obs.expected_net_funding_return_bps == pytest.approx(expected)


def test_observe_funding_opportunity_missing_index_price_yields_none_basis():
    obs = fo.observe_funding_opportunity(
        symbol="ETHUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=1.0, mark_price=3000.0,
        estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
    )
    assert obs.basis_bps is None
    assert obs.index_price is None


def test_observe_funding_opportunity_rejects_empty_symbol():
    with pytest.raises(ValueError):
        fo.observe_funding_opportunity(
            symbol="", observed_at_ms=1_700_000_000_000,
            current_funding_rate_bps=1.0, mark_price=3000.0,
            estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
        )


def test_observe_funding_opportunity_rejects_non_positive_mark_price():
    with pytest.raises(ValueError):
        fo.observe_funding_opportunity(
            symbol="ETHUSDT", observed_at_ms=1_700_000_000_000,
            current_funding_rate_bps=1.0, mark_price=0.0,
            estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
        )


def test_observe_funding_opportunity_predicted_rate_kept_distinct_from_current():
    """§15.1: predicted/next funding rate is a distinct field, never
    silently substituted for the current rate used in the capture estimate."""
    obs = fo.observe_funding_opportunity(
        symbol="ETHUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=1.0, mark_price=3000.0,
        estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
        predicted_funding_rate_bps=9.0,
    )
    assert obs.predicted_funding_rate_bps == 9.0
    assert obs.expected_funding_capture_bps_per_interval == 1.0  # not 9.0


def test_observe_funding_opportunity_deterministic():
    kwargs = dict(
        symbol="ETHUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=1.0, mark_price=3000.0,
        estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
    )
    a = fo.observe_funding_opportunity(**kwargs)
    b = fo.observe_funding_opportunity(**kwargs)
    assert a == b
