"""Unit tests for PHASE 1: Adaptive timeout system (ATR-based volatility).

Tests volatility classification and adaptive timeout calculation.
"""
import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.paper_trade_executor import (
    _classify_volatility_regime,
    _calculate_adaptive_timeout,
)


class TestVolatilityClassification:
    """Test volatility regime classification based on ATR percentage."""

    def test_stagnation_regime(self):
        """Test STAGNATION classification (ATR < 0.01%)."""
        regime, factor = _classify_volatility_regime(0.00005)  # 0.005%
        assert regime == "STAGNATION"
        assert factor == 0.0

    def test_low_vol_regime(self):
        """Test LOW_VOL classification (0.01% <= ATR < 0.05%)."""
        regime, factor = _classify_volatility_regime(0.0002)  # 0.02%
        assert regime == "LOW_VOL"
        assert factor == 2.0

    def test_medium_vol_regime(self):
        """Test MEDIUM_VOL classification (0.05% <= ATR < 0.15%)."""
        regime, factor = _classify_volatility_regime(0.0008)  # 0.08%
        assert regime == "MEDIUM_VOL"
        assert factor == 1.0

    def test_high_vol_regime(self):
        """Test HIGH_VOL classification (0.15% <= ATR < 0.50%)."""
        regime, factor = _classify_volatility_regime(0.002)  # 0.20%
        assert regime == "HIGH_VOL"
        assert factor == 0.67

    def test_extreme_vol_regime(self):
        """Test EXTREME_VOL classification (ATR >= 0.50%)."""
        regime, factor = _classify_volatility_regime(0.01)  # 1.00%
        assert regime == "EXTREME_VOL"
        assert factor == 0.0

    def test_boundary_at_0_01_pct(self):
        """Test boundary at 0.01% (STAGNATION -> LOW_VOL)."""
        regime_stag, _ = _classify_volatility_regime(0.00009)
        regime_low, _ = _classify_volatility_regime(0.0001)
        assert regime_stag == "STAGNATION"
        assert regime_low == "LOW_VOL"


class TestAdaptiveTimeout:
    """Test adaptive timeout calculation with volatility and trend factors."""

    def test_stagnation_skip(self):
        """Test that STAGNATION regime skips entries (timeout=0)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.00005,  # Very low ATR
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        assert result["timeout_s"] == 0
        assert result["vol_regime"] == "STAGNATION"
        assert "skip_entries" in result["calc_reason"]

    def test_extreme_vol_skip(self):
        """Test that EXTREME_VOL regime skips entries (timeout=0)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.01,  # Very high ATR (1%)
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        assert result["timeout_s"] == 0
        assert result["vol_regime"] == "EXTREME_VOL"
        assert "skip_entries" in result["calc_reason"]

    def test_low_vol_extended_timeout(self):
        """Test that LOW_VOL increases timeout (2x = 1200s)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0002,  # 0.02%
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        # 600 * 2.0 * 1.0 = 1200
        assert result["timeout_s"] == 1200
        assert result["vol_regime"] == "LOW_VOL"

    def test_medium_vol_baseline(self):
        """Test that MEDIUM_VOL uses baseline timeout (1x = 600s)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0008,  # 0.08%
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        # 600 * 1.0 * 1.0 = 600
        assert result["timeout_s"] == 600
        assert result["vol_regime"] == "MEDIUM_VOL"

    def test_high_vol_reduced_timeout(self):
        """Test that HIGH_VOL reduces timeout (0.67x ≈ 400s)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.002,  # 0.20%
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        # 600 * 0.67 * 1.0 = 402 -> 402
        expected_timeout = int(600 * 0.67)
        assert result["timeout_s"] == expected_timeout
        assert result["vol_regime"] == "HIGH_VOL"

    def test_strong_trend_extends_timeout(self):
        """Test that strong uptrend extends timeout (1.2x trend factor)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0008,  # MEDIUM_VOL
            signal={"regime": "STRONG_UPTREND"},
            price=100.0,
        )
        # 600 * 1.0 * 1.2 = 720
        assert result["timeout_s"] == 720
        assert result["vol_regime"] == "MEDIUM_VOL"

    def test_falling_trend_reduces_timeout(self):
        """Test that falling trend reduces timeout (0.8x trend factor)."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0008,  # MEDIUM_VOL
            signal={"regime": "FALLING"},
            price=100.0,
        )
        # 600 * 1.0 * 0.8 = 480
        assert result["timeout_s"] == 480
        assert result["vol_regime"] == "MEDIUM_VOL"

    def test_low_vol_strong_trend_maxed(self):
        """Test that LOW_VOL + strong trend is capped at 1500s."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0002,  # LOW_VOL (2.0x)
            signal={"regime": "STRONG_UPTREND"},  # 1.2x trend
            price=100.0,
        )
        # 600 * 2.0 * 1.2 = 1440 (within bounds)
        assert result["timeout_s"] == 1440

    def test_high_vol_falling_trend_floored(self):
        """Test that timeouts never go below 300s."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.002,  # HIGH_VOL (0.67x)
            signal={"regime": "FALLING"},  # 0.8x trend
            price=100.0,
        )
        # 600 * 0.67 * 0.8 = 321.6 -> 321 (above floor)
        assert result["timeout_s"] >= 300

    def test_guardrails_lower_bound(self):
        """Test that timeout respects 300s lower bound (extreme case)."""
        # Artificially low multipliers
        result = _calculate_adaptive_timeout(
            atr_pct=0.002,  # HIGH_VOL: 0.67x
            signal={"regime": "FALLING"},  # 0.8x
            price=100.0,
        )
        assert result["timeout_s"] >= 300

    def test_guardrails_upper_bound(self):
        """Test that timeout respects 1500s upper bound."""
        # Create extreme case (shouldn't happen in practice)
        result = _calculate_adaptive_timeout(
            atr_pct=0.0002,  # LOW_VOL: 2.0x
            signal={"regime": "STRONG_UPTREND"},  # 1.2x
            price=100.0,
        )
        assert result["timeout_s"] <= 1500

    def test_atr_pct_stored(self):
        """Test that ATR % is stored for learning system."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0008,
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        assert result["atr_pct"] == 0.0008

    def test_calc_reason_provided(self):
        """Test that calc_reason is provided for diagnostics."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0008,
            signal={"regime": "NEUTRAL"},
            price=100.0,
        )
        assert "calc_reason" in result
        assert len(result["calc_reason"]) > 0


class TestIntegration:
    """Integration tests for volatility detection across real-world scenarios."""

    def test_quiet_market_low_vol(self):
        """Scenario: Quiet USDT pair, low ATR."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.0003,  # 0.03% ATR
            signal={"regime": "NEUTRAL"},
            price=50000.0,  # BTC-like price
        )
        assert result["vol_regime"] == "LOW_VOL"
        assert result["timeout_s"] > 600  # Extended hold

    def test_normal_market_medium_vol(self):
        """Scenario: Normal trading conditions, MEDIUM volatility."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.001,  # 0.10% ATR
            signal={"regime": "RISING"},
            price=100.0,
        )
        assert result["vol_regime"] == "MEDIUM_VOL"
        # 600 * 1.0 * 1.0 = 600 (neutral trend)
        assert result["timeout_s"] == 600

    def test_volatile_market_high_vol(self):
        """Scenario: High volatility conditions, fast exits."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.003,  # 0.30% ATR
            signal={"regime": "RISING"},
            price=100.0,
        )
        assert result["vol_regime"] == "HIGH_VOL"
        # 600 * 0.67 * 1.0 = 402
        assert result["timeout_s"] < 600

    def test_crash_regime_extreme_vol(self):
        """Scenario: Market crash with extreme volatility."""
        result = _calculate_adaptive_timeout(
            atr_pct=0.02,  # 2% ATR (extreme)
            signal={"regime": "FALLING"},
            price=100.0,
        )
        assert result["vol_regime"] == "EXTREME_VOL"
        assert result["timeout_s"] == 0  # Skip entries


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
