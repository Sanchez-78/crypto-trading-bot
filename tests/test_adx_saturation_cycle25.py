"""
Unit tests for ADX behaviour on monotone trends.

CYCLE 51: The Cycle 25 symmetric DI floor (min_di = max(min_di, max_di*0.01))
was removed because it CREATED saturation (forced ADX=98) instead of preventing
it. These tests now verify natural behaviour: on synthetic monotone data the
minority DI is 0 and ADX saturates to ~100 (correct — real market data is never
perfectly monotone, so it never pins to the floor in production).
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.signal_generator import _adx


def test_adx_monotone_uptrend_saturation():
    """Test ADX on monotone uptrend (di_p high, di_m→0 without floor)."""
    # Monotone uptrend: prices always increasing
    monotone_up = [100.0 + i * 0.1 for i in range(100)]

    adx_val, di_p, di_m = _adx(monotone_up, n=14)

    # Verify ADX is bounded and naturally saturates near 100 on pure monotone
    assert 0 <= adx_val <= 100.0, f"ADX out of bounds: {adx_val}"
    assert adx_val > 99.0, f"ADX should saturate near 100 on monotone uptrend, got {adx_val}"

    # Minority DI is naturally 0 on pure monotone data (no floor anymore)
    assert di_m == 0, f"di_m should be 0 on pure uptrend (floor removed), got {di_m}"

    # Verify regime detection unaffected (BULL_TREND if di_p > di_m)
    assert di_p > di_m, "Uptrend should have di_p > di_m (BULL_TREND)"


def test_adx_monotone_downtrend_saturation():
    """Test ADX on monotone downtrend (di_m high, di_p→0 without floor)."""
    # Monotone downtrend: prices always decreasing
    monotone_down = [100.0 - i * 0.1 for i in range(100)]

    adx_val, di_p, di_m = _adx(monotone_down, n=14)

    # Verify ADX is bounded and naturally saturates near 100 on pure monotone
    assert 0 <= adx_val <= 100.0, f"ADX out of bounds: {adx_val}"
    assert adx_val > 99.0, f"ADX should saturate near 100 on monotone downtrend, got {adx_val}"

    # Minority DI is naturally 0 on pure monotone data (no floor anymore)
    assert di_p == 0, f"di_p should be 0 on pure downtrend (floor removed), got {di_p}"

    # Verify regime detection unaffected (BEAR_TREND if di_m > di_p)
    assert di_m > di_p, "Downtrend should have di_m > di_p (BEAR_TREND)"


def test_adx_natural_saturation_on_monotone():
    """CYCLE 51: pure monotone synthetic data saturates ADX to ~100 naturally.

    The Cycle 25 floor artificially capped this near 98, which masked the real
    indicator value and produced false BULL_TREND on flat markets. With the
    floor removed, synthetic monotone data correctly reaches ~100. Real market
    data is never perfectly monotone, so production ADX varies across 0-100.
    """
    # Two monotone extremes
    monotone_up = [100.0 + i * 0.1 for i in range(100)]
    monotone_down = [100.0 - i * 0.1 for i in range(100)]

    adx_up, _, _ = _adx(monotone_up, n=14)
    adx_down, _, _ = _adx(monotone_down, n=14)

    # Both saturate near 100 on pure monotone series (no artificial cap)
    assert adx_up > 99.0, f"Uptrend ADX {adx_up} should saturate near 100"
    assert adx_down > 99.0, f"Downtrend ADX {adx_down} should saturate near 100"


def test_adx_regime_stability_after_floor():
    """Verify regime classification (BULL/BEAR/RANGING) is stable across floor."""
    # Moderate uptrend
    moderate_up = [100.0 + i * 0.01 for i in range(100)]
    adx_mod_up, di_p_mod, di_m_mod = _adx(moderate_up, n=14)

    # Regime should still be BULL (di_p > di_m)
    assert di_p_mod > di_m_mod, "Floor should not invert uptrend regime"

    # Moderate downtrend
    moderate_down = [100.0 - i * 0.01 for i in range(100)]
    adx_mod_down, di_p_md, di_m_md = _adx(moderate_down, n=14)

    # Regime should still be BEAR (di_m > di_p)
    assert di_m_md > di_p_md, "Floor should not invert downtrend regime"


if __name__ == "__main__":
    # Run tests
    test_adx_monotone_uptrend_saturation()
    print("✓ test_adx_monotone_uptrend_saturation PASS")

    test_adx_monotone_downtrend_saturation()
    print("✓ test_adx_monotone_downtrend_saturation PASS")

    test_adx_natural_saturation_on_monotone()
    print("✓ test_adx_natural_saturation_on_monotone PASS")

    test_adx_regime_stability_after_floor()
    print("✓ test_adx_regime_stability_after_floor PASS")

    print("\n✅ All ADX saturation tests PASS")
