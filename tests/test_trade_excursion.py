"""Audit F8 — gross MFE/MAE excursion contract (observability only)."""
import pytest

from src.services.trade_excursion import (
    EXCURSION_POLICY_VERSION,
    compute_excursion,
    empty_excursion,
    favorable_first,
)


def test_buy_excursion_units_and_signs():
    e = compute_excursion("BUY", 100.0, max_seen=102.0, min_seen=99.0)
    assert e["mfe_gross_pct"] == pytest.approx(2.0)
    assert e["mae_gross_pct"] == pytest.approx(-1.0)
    assert e["mfe_gross_bps"] == pytest.approx(200.0)
    assert e["mae_gross_bps"] == pytest.approx(-100.0)
    assert e["mfe_gross_fraction"] == pytest.approx(0.02)
    assert e["max_favorable_price"] == 102.0 and e["max_adverse_price"] == 99.0
    assert e["mfe_gross_pct"] >= 0 and e["mae_gross_pct"] <= 0
    assert e["excursion_policy_version"] == EXCURSION_POLICY_VERSION


def test_sell_excursion_is_side_aware():
    # short: favorable = price falls (toward min), adverse = price rises (max)
    e = compute_excursion("SELL", 100.0, max_seen=102.0, min_seen=99.0)
    assert e["mfe_gross_pct"] == pytest.approx(1.0)     # (100-99)/100
    assert e["mae_gross_pct"] == pytest.approx(-2.0)    # (100-102)/100
    assert e["max_favorable_price"] == 99.0 and e["max_adverse_price"] == 102.0


def test_signs_enforced_when_extremes_degenerate():
    # entry never exceeded (max==min==entry): zero excursion, correct signs
    e = compute_excursion("BUY", 100.0, max_seen=100.0, min_seen=100.0)
    assert e["mfe_gross_pct"] == 0.0 and e["mae_gross_pct"] == 0.0


def test_invalid_entry_price_returns_empty():
    assert compute_excursion("BUY", 0.0, 1, 1) == empty_excursion()
    assert compute_excursion("BUY", None, 1, 1) == empty_excursion()


# ── ordering: the whole point of F8 (TP-before-SL vs SL-before-TP) ────────────

def test_favorable_first_ordering_buy():
    # favorable extreme (max) reached at t=5, adverse (min) at t=10 -> favorable first
    e = compute_excursion("BUY", 100.0, 102.0, 99.0,
                          entry_ts=0.0, max_seen_ts=5.0, min_seen_ts=10.0)
    assert e["time_to_mfe_ms"] == 5000 and e["time_to_mae_ms"] == 10000
    assert favorable_first(e) is True


def test_adverse_first_ordering_same_magnitudes():
    # identical MFE/MAE magnitudes but the adverse extreme came FIRST -> opposite
    # counterfactual. This is exactly why MFE/MAE alone is insufficient.
    e = compute_excursion("BUY", 100.0, 102.0, 99.0,
                          entry_ts=0.0, max_seen_ts=10.0, min_seen_ts=3.0)
    assert e["time_to_mfe_ms"] == 10000 and e["time_to_mae_ms"] == 3000
    assert favorable_first(e) is False


def test_favorable_first_none_when_timing_unknown():
    e = compute_excursion("BUY", 100.0, 102.0, 99.0)  # no timestamps
    assert e["time_to_mfe_ms"] is None and e["time_to_mae_ms"] is None
    assert favorable_first(e) is None
