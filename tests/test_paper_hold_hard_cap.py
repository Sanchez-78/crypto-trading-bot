"""Regression: no paper position's effective hold can exceed the absolute hard
ceiling _HARD_MAX_AGE_S, whatever its per-position timeout_s / max_hold_s say.

Backstory (2026-07-20): a position was observed open ~14.5h — far past the 20min
_MAX_AGE_S — because _effective_paper_hold_s derived the hold from an oversized
per-position field with no upper bound, so check_and_close_timeout_positions never
saw it expire. The hard cap closes that class of stuck-forever positions.
"""
from src.services import paper_trade_executor as m


def test_hard_cap_bounds_non_exploration_timeout():
    pos = {"timeout_s": 10_000_000, "symbol": "ETHUSDT"}  # absurd timeout
    assert m._effective_paper_hold_s(pos) <= m._HARD_MAX_AGE_S


def test_hard_cap_bounds_exploration_max_hold():
    pos = {"explore_bucket": "C_WEAK_EV", "max_hold_s": 10_000_000, "symbol": "ETHUSDT"}
    assert m._effective_paper_hold_s(pos) <= m._HARD_MAX_AGE_S


def test_hard_cap_default_is_sane_and_above_max_age():
    # generous vs the 20-min soft cap, but a hard bound (not infinite)
    assert m._MAX_AGE_S < m._HARD_MAX_AGE_S < 24 * 3600


def test_normal_holds_unchanged():
    # a normal position well under the cap is returned as-is (no clipping)
    pos = {"timeout_s": 900, "symbol": "ETHUSDT"}
    assert m._effective_paper_hold_s(pos) == 900

    train = {"training_bucket": "C_WEAK_EV_TRAIN", "max_hold_s": 300, "timeout_s": 300}
    assert m._effective_paper_hold_s(train) <= m._MAX_AGE_S


def test_a_14h_position_would_now_expire():
    """The observed stuck case: age 14.5h must exceed the effective hold so the
    timeout scan closes it, for any plausible per-position field."""
    age_s = 14.5 * 3600
    for pos in (
        {"timeout_s": 10_000_000},
        {"explore_bucket": "C_WEAK_EV", "max_hold_s": 10_000_000},
        {"timeout_s": 0},
    ):
        assert age_s >= m._effective_paper_hold_s(pos), pos
