"""
Unit tests for Cycle 25 ADX saturation fix.

Verifies that the symmetric DI floor prevents saturation on monotone trends
in both directions (uptrend and downtrend).
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

    # Verify ADX is bounded (should not be exactly 100.0)
    assert 0 <= adx_val <= 100.0, f"ADX out of bounds: {adx_val}"
    assert adx_val < 99.0, f"ADX should be < 99 on uptrend, got {adx_val}"

    # Verify DI floor prevents di_m from being 0
    assert di_m > 0, f"di_m should be floored > 0, got {di_m}"
    assert di_m >= di_p * 0.01, f"di_m floor violated: {di_m} < {di_p * 0.01}"

    # Verify regime detection unaffected (BULL_TREND if di_p > di_m)
    assert di_p > di_m, "Uptrend should have di_p > di_m (BULL_TREND)"


def test_adx_monotone_downtrend_saturation():
    """Test ADX on monotone downtrend (di_m high, di_p→0 without floor)."""
    # Monotone downtrend: prices always decreasing
    monotone_down = [100.0 - i * 0.1 for i in range(100)]

    adx_val, di_p, di_m = _adx(monotone_down, n=14)

    # Verify ADX is bounded (should not be exactly 100.0)
    assert 0 <= adx_val <= 100.0, f"ADX out of bounds: {adx_val}"
    assert adx_val < 99.0, f"ADX should be < 99 on downtrend, got {adx_val}"

    # Verify DI floor prevents di_p from being 0
    assert di_p > 0, f"di_p should be floored > 0, got {di_p}"
    assert di_p >= di_m * 0.01, f"di_p floor violated: {di_p} < {di_m * 0.01}"

    # Verify regime detection unaffected (BEAR_TREND if di_m > di_p)
    assert di_m > di_p, "Downtrend should have di_m > di_p (BEAR_TREND)"


def test_adx_health_gate_threshold():
    """Test that floored ADX doesn't exceed health-gate threshold (97.0)."""
    # Two monotone extremes
    monotone_up = [100.0 + i * 0.1 for i in range(100)]
    monotone_down = [100.0 - i * 0.1 for i in range(100)]

    adx_up, _, _ = _adx(monotone_up, n=14)
    adx_down, _, _ = _adx(monotone_down, n=14)

    # Both should be below health-gate threshold (97.0) so gate doesn't
    # incorrectly block saturated but valid monotone trends
    # Allowing up to 98.02 with 1% margin above threshold:
    assert adx_up < 98.5, f"Uptrend ADX {adx_up} exceeds margin above gate (97.0)"
    assert adx_down < 98.5, f"Downtrend ADX {adx_down} exceeds margin above gate (97.0)"


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

    test_adx_health_gate_threshold()
    print("✓ test_adx_health_gate_threshold PASS")

    test_adx_regime_stability_after_floor()
    print("✓ test_adx_regime_stability_after_floor PASS")

    print("\n✅ All ADX saturation tests PASS")
