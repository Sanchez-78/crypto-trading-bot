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
    _min_valid_tp_bps,
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


# ---------------------------------------------------------------------------
# 2026-08-14 (_workspace/25_learned_tp_below_cost_floor.md): validate_tp_sl_
# cost_floor() only ever ran once at module import against the static
# defaults -- it never validated the value actually used to open a position
# (env override / learned TP / dynamic ATR). Confirmed live: the learned-TP
# path had settled at 18bps for SOLUSDT/BEAR_TREND against an 18bps
# round-trip cost (net win ~0bps), and the live env-configured TP (35bps)
# was itself violating (needs ~46.7bps given sl=25/cost=18/max_breakeven=
# 60%). _min_valid_tp_bps() + the open_paper_position() clamp close this.
# ---------------------------------------------------------------------------

def test_min_valid_tp_bps_matches_the_live_violation_found_2026_08_14():
    """sl=25bps, cost=18bps, max_breakeven=60% -- the exact geometry running
    live in production at discovery time -- requires ~46.7bps TP, not the
    36bps a naive "2x cost" shortcut would suggest."""
    floor = _min_valid_tp_bps(25.0, 18.0, 0.60)
    assert floor == pytest.approx(46.667, abs=0.01)
    # And the live TP (35bps) must fail against that floor, while the floor
    # itself (rounded up) must pass.
    ok_at_35, _ = validate_tp_sl_cost_floor(35, 25, 18.0, 0.60)
    assert not ok_at_35
    ok_at_floor, _ = validate_tp_sl_cost_floor(round(floor) + 1, 25, 18.0, 0.60)
    assert ok_at_floor


def test_min_valid_tp_bps_returns_a_value_that_validate_accepts():
    """For a range of sl/cost combinations, the tp _min_valid_tp_bps returns
    (rounded up by 1bp to clear a >= boundary) must itself pass
    validate_tp_sl_cost_floor -- the two functions must agree."""
    for sl, cost, max_share in [(25, 18, 0.60), (10, 4, 0.60), (40, 4, 0.50), (25, 18, 0.80)]:
        floor = _min_valid_tp_bps(sl, cost, max_share)
        ok, reason = validate_tp_sl_cost_floor(round(floor) + 1, sl, cost, max_share)
        assert ok, f"floor={floor} for sl={sl} cost={cost} max_share={max_share} did not validate: {reason}"


def test_min_valid_tp_bps_picks_the_binding_constraint():
    """When the break-even-share condition requires more than the bare 2x
    cost condition, the larger (binding) value wins -- this is the specific
    gap a naive "tp_bps >= 2*cost_bps" floor would miss."""
    # sl=25, cost=18: 2x-cost floor is 36, but break-even-share floor is
    # ~46.7 -- the binding constraint.
    floor = _min_valid_tp_bps(25.0, 18.0, 0.60)
    assert floor > 2 * 18.0

    # A very small sl relative to cost can flip which constraint binds.
    floor_small_sl = _min_valid_tp_bps(1.0, 18.0, 0.60)
    assert floor_small_sl >= 2 * 18.0


def test_open_paper_position_clamps_a_cost_floor_violating_tp(monkeypatch):
    """End-to-end: a request that would open at the live-observed violating
    geometry (env TP=35bps against sl=25bps/cost=18bps) gets clamped up to
    a geometry that actually clears the cost floor."""
    import time as _time
    import src.services.paper_trade_executor as pte

    monkeypatch.setenv("PAPER_TP_ZONE_BPS", "35")
    monkeypatch.setenv("PAPER_SL_ZONE_BPS", "25")
    monkeypatch.setattr(pte, "_ROUND_TRIP_COST_BPS", 18.0)
    monkeypatch.setattr(pte, "_MAX_BREAKEVEN_TP_SHARE", 0.60)
    pte.reset_paper_positions()

    signal = {
        "symbol": "XRPUSDT", "action": "BUY", "regime": "BULL_TREND",
        "ev": 0.05, "score": 0.25, "p": 0.55, "coh": 0.70, "af": 0.80,
    }
    result = pte.open_paper_position(signal, 100.0, _time.time(), "RDE_TAKE")
    assert result.get("status") == "opened", result

    positions = pte.get_open_positions()
    trade = positions.get(result["trade_id"])
    assert trade is not None

    tp_bps = trade["tp_zone_bps_at_entry"]
    sl_bps = trade["sl_zone_bps_at_entry"]
    # The clamp must have raised the requested 35bps TP.
    assert tp_bps > 35, f"expected the cost-floor clamp to raise tp above 35bps, got {tp_bps}"
    ok, reason = validate_tp_sl_cost_floor(tp_bps, sl_bps, 18.0, 0.60)
    assert ok, f"opened position tp={tp_bps}bps sl={sl_bps}bps still violates cost floor: {reason}"

    pte.reset_paper_positions()
