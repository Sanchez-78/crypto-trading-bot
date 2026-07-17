"""Unit tests for the canonical trade-metrics contract (audit PR3)."""
import math

import pytest

from src.core.trade_metrics_contract import (
    OUTCOME_POLICY_VERSION,
    PROFIT_FACTOR_CAP,
    TradeOutcome,
    bps_to_pct,
    classify_outcome,
    compute_profit_factor,
    compute_win_rate,
    fraction_to_pct,
    pct_to_bps,
    pct_to_fraction,
    pct_to_usd,
)

# ── classify_outcome: boundary is ±0.05pp on net, exactly ±0.05 -> FLAT ────────

@pytest.mark.parametrize("net_pct,expected", [
    (0.82, TradeOutcome.WIN),
    (0.06, TradeOutcome.WIN),
    (0.0500001, TradeOutcome.WIN),
    (0.05, TradeOutcome.FLAT),      # boundary -> FLAT (strict >)
    (0.02, TradeOutcome.FLAT),
    (0.0, TradeOutcome.FLAT),
    (-0.05, TradeOutcome.FLAT),     # boundary -> FLAT (strict <)
    (-0.08, TradeOutcome.LOSS),
    (-1.18, TradeOutcome.LOSS),
])
def test_classify_outcome_boundary(net_pct, expected):
    assert classify_outcome(net_pct) is expected


def test_outcome_enum_is_str():
    assert TradeOutcome.WIN == "WIN"
    assert TradeOutcome.LOSS.value == "LOSS"


# ── unit converters + round-trips ─────────────────────────────────────────────

def test_pct_fraction_roundtrip():
    assert pct_to_fraction(0.20) == pytest.approx(0.002)
    assert fraction_to_pct(0.002) == pytest.approx(0.20)
    for v in (0.0, 0.05, 0.2, 1.5, -0.37):
        assert fraction_to_pct(pct_to_fraction(v)) == pytest.approx(v)


def test_pct_bps_roundtrip():
    assert pct_to_bps(0.20) == pytest.approx(20.0)
    assert bps_to_pct(20.0) == pytest.approx(0.20)
    for v in (0.0, 0.05, 0.2, 1.5, -0.37):
        assert bps_to_pct(pct_to_bps(v)) == pytest.approx(v)


def test_pct_to_usd():
    # +0.20% on a $500 position = $1.00
    assert pct_to_usd(0.20, 500.0) == pytest.approx(1.0)
    assert pct_to_usd(-0.18, 250.0) == pytest.approx(-0.45)


# ── profit factor ─────────────────────────────────────────────────────────────

def test_profit_factor_two_wins_two_losses():
    # gains 0.8+0.6=1.4 ; losses |-0.5-0.2|=0.7 -> PF 2.0
    assert compute_profit_factor([0.8, 0.6, -0.5, -0.2]) == pytest.approx(2.0)


def test_profit_factor_only_wins_is_capped():
    assert compute_profit_factor([0.8, 0.6]) == PROFIT_FACTOR_CAP


def test_profit_factor_only_losses():
    assert compute_profit_factor([-0.8, -0.2]) == pytest.approx(0.0)


def test_profit_factor_only_flats_is_zero():
    assert compute_profit_factor([0.0, 0.0]) == 0.0


def test_profit_factor_empty_is_zero():
    assert compute_profit_factor([]) == 0.0


def test_profit_factor_is_json_safe():
    assert math.isfinite(compute_profit_factor([1.0, 2.0]))


def test_profit_factor_is_not_count_ratio():
    # one big win, three tiny losses: count ratio would be 1/3; magnitude PF is 10/3
    pf = compute_profit_factor([10.0, -1.0, -1.0, -1.0])
    assert pf == pytest.approx(10.0 / 3.0)


# ── win rate: WIN / (WIN+LOSS+FLAT), FLAT kept in denominator ──────────────────

def test_win_rate_keeps_flat_in_denominator():
    outcomes = [TradeOutcome.WIN, TradeOutcome.WIN, TradeOutcome.LOSS, TradeOutcome.FLAT]
    assert compute_win_rate(outcomes) == pytest.approx(0.5)


def test_win_rate_accepts_strings():
    assert compute_win_rate(["WIN", "LOSS", "flat", "win"]) == pytest.approx(0.5)


def test_win_rate_empty_is_zero():
    assert compute_win_rate([]) == 0.0


def test_policy_version_present():
    assert isinstance(OUTCOME_POLICY_VERSION, int)
