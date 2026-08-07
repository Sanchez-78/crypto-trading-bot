"""Cost-floor invariant for the paper TP/SL geometry.

Regression guard for the 2026-07-31 WR collapse. Production ran TP=12bps /
SL=10bps against a 4bps round-trip cost, delivered via an untracked systemd
drop-in. Because _calculate_pnl subtracts the round-trip cost from BOTH legs,
that geometry nets +8bps on a win and -14bps on a loss, requiring a 63.6%
TP-hit-share to break even. The realised share was 50.5% (347 TP vs 340 SL over
1314 closed trades, 2026-08-01..08-07); PF fell to 0.34-0.56, WR to 14-38%.

No test asserted this invariant, so nothing blocked the change. This is that
test.
"""
import pytest

from src.services.paper_trade_executor import (
    _ROUND_TRIP_COST_BPS,
    _SHIPPED_SL_ZONE_BPS,
    _SHIPPED_TP_ZONE_BPS,
    validate_tp_sl_cost_floor,
)

# The two cost models the code must survive: the shipped default
# (_FEE_PCT 0.0015 + _SLIPPAGE_PCT 0.0003 = 18bps) and the value production
# actually runs (PAPER_FEE_PCT=0.0004, PAPER_SLIPPAGE_PCT=0.0 => 4bps).
SHIPPED_COST_BPS = 18.0
PRODUCTION_COST_BPS = 4.0


def test_shipped_defaults_hold_the_invariant_under_both_cost_models():
    """The TP/SL geometry this repo ships must never be structurally losing.

    Asserts on _SHIPPED_* rather than _DEFAULT_* so an ambient PAPER_TP_ZONE_BPS
    in the developer's or CI's environment cannot mask a bad shipped value.
    """
    for cost in (SHIPPED_COST_BPS, PRODUCTION_COST_BPS):
        ok, reason = validate_tp_sl_cost_floor(
            _SHIPPED_TP_ZONE_BPS, _SHIPPED_SL_ZONE_BPS, cost
        )
        assert ok, (
            f"shipped defaults TP={_SHIPPED_TP_ZONE_BPS} SL={_SHIPPED_SL_ZONE_BPS} "
            f"violate the cost floor at cost={cost}bps: {reason}"
        )


def test_the_regression_geometry_is_rejected():
    """TP=12/SL=10 must fail at the cost it actually ran against, and at the shipped cost."""
    for cost in (PRODUCTION_COST_BPS, SHIPPED_COST_BPS):
        ok, reason = validate_tp_sl_cost_floor(12, 10, cost)
        assert not ok, f"TP=12/SL=10 wrongly accepted at cost={cost}bps"
        assert reason


@pytest.mark.parametrize(
    "tp,sl,cost",
    [
        (12, 10, 4),      # the 2026-07-31 regression
        (7, 40, 18),      # Cycle 27: TP below the cost floor entirely
        (20, 20, 18),     # TP clears cost but net win < fees paid
        (35, 40, 18),     # symmetric-looking, but break-even share 77.3%
    ],
)
def test_known_bad_geometries_are_rejected(tp, sl, cost):
    ok, _ = validate_tp_sl_cost_floor(tp, sl, cost)
    assert not ok, f"TP={tp}/SL={sl} at cost={cost}bps should violate the invariant"


@pytest.mark.parametrize(
    "tp,sl,cost",
    [
        (0, 0, 0),        # all-zero: 0/0 in the break-even ratio
        (0, 0, 4),
        (0, 0, 18),
        (-5, -5, 0),      # negative bands from a malformed env var
        (-40, 40, 0),     # tp_net + sl_net == 0 exactly
    ],
)
def test_degenerate_input_returns_a_verdict_instead_of_raising(tp, sl, cost):
    """The validator runs at module scope — raising would be an import-time crash.

    It must always return (ok, reason), never propagate ZeroDivisionError.
    """
    ok, reason = validate_tp_sl_cost_floor(tp, sl, cost)
    assert ok is False
    assert reason


def test_breakeven_share_is_the_documented_formula():
    """Guard the arithmetic the invariant rests on: 12/10 @4bps needs 63.6%."""
    tp_net = 12 - 4
    sl_net = 10 + 4
    assert sl_net / (tp_net + sl_net) == pytest.approx(0.63636, abs=1e-4)


def test_round_trip_cost_is_derived_from_the_fee_and_slippage_config():
    """_ROUND_TRIP_COST_BPS must track _FEE_PCT/_SLIPPAGE_PCT, not a hardcoded literal."""
    from src.services.paper_trade_executor import _FEE_PCT, _SLIPPAGE_PCT

    assert _ROUND_TRIP_COST_BPS == pytest.approx((_FEE_PCT + _SLIPPAGE_PCT) * 10000.0)
