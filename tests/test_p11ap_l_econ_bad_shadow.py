#!/usr/bin/env python3
"""
P1.1AP-L: Post-Bootstrap ECON_BAD Near-Miss Shadow Sampler

Tests for E_ECON_BAD_NEAR_MISS_SHADOW diagnostic bucket:
- Weak-positive near-miss candidates rejected under ECON_BAD
- Shadow-only route (no canonical learning)
- Rate caps and lifetime caps
- No stealing B/C priority
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from src.services.paper_exploration import (
    paper_exploration_override,
    reset_exploration_caps,
    get_exploration_stats,
    _econ_bad_shadow_state,
    _ECON_BAD_SHADOW_NEAR_MISS_FLOOR_EV,
    _ECON_BAD_SHADOW_MAX_LIFETIME_CLOSED,
)
from src.services.paper_trade_executor import (
    _is_econ_bad_near_miss_shadow_trade,
)


class TestP11APL_EconBadShadowActivation:
    """Test activation conditions for E_ECON_BAD_NEAR_MISS_SHADOW bucket."""

    def setup_method(self):
        """Reset exploration caps before each test."""
        reset_exploration_caps()
        _econ_bad_shadow_state["lifetime_closed"] = 0
        _econ_bad_shadow_state["entry_times_10m"].clear()

    def test_econ_bad_near_miss_shadow_activation_weak_positive(self):
        """Test activation: ECON_BAD rejection, weak positive EV, no B/C eligibility → E-shadow admitted."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.0348,  # Between 0.030 and 0.038 threshold
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        assert ov["allowed"] is True
        assert ov["bucket"] == "E_ECON_BAD_NEAR_MISS_SHADOW"
        assert ov["route_trigger"] == "postbootstrap_econ_bad_shadow"
        assert ov["size_mult"] == 0.05
        assert ov["max_hold_s"] == 600
        assert "diagnostic" in ov["tags"]
        assert "shadow" in ov["tags"]

    def test_econ_bad_no_activation_below_near_miss_floor(self):
        """Test no activation when EV below near-miss floor (0.030)."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.0299,  # Below 0.030 floor
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        assert ov["allowed"] is False
        assert ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"

    def test_econ_bad_no_activation_negative_ev(self):
        """Test no activation for negative EV; D_NEG remains owner."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.005,
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "negative_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        # D_NEG should be checked before E_ECON_BAD
        assert ov["allowed"] is False or ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"

    def test_econ_bad_no_activation_non_econ_bad_rejection(self):
        """Test no activation when original_decision is not ECON_BAD."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.0348,
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_WEAK_EV",  # Not ECON_BAD
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        assert ov["allowed"] is False or ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"

    def test_econ_bad_no_stealing_b_recovery(self):
        """Test: valid B_RECOVERY_READY candidate remains B, not E-shadow."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.038,  # At B_RECOVERY threshold
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        # Should be B_RECOVERY_READY, not E-shadow
        assert ov["bucket"] == "B_RECOVERY_READY" or ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"

    def test_econ_bad_lifetime_cap_blocks_after_20(self):
        """Test: lifetime cap blocks E-shadow entry after 20 closed samples."""
        _econ_bad_shadow_state["lifetime_closed"] = 20

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.0348,
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        assert ov["allowed"] is False
        assert ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"


class TestP11APL_EconBadShadowCaps:
    """Test rate caps and concurrency limits for E_ECON_BAD_NEAR_MISS_SHADOW."""

    def setup_method(self):
        """Reset exploration caps before each test."""
        reset_exploration_caps()
        _econ_bad_shadow_state["lifetime_closed"] = 0
        _econ_bad_shadow_state["entry_times_10m"].clear()

    def test_econ_bad_rate_cap_2_per_30m(self):
        """Test: max 2 E-shadow entries per 30-minute window."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.0348,
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_ECON_BAD_ENTRY",
            "recovery_ready": False,
            "probe_ready": False,
        }

        # First entry: allowed
        ov1 = paper_exploration_override(signal, ctx)
        assert ov1["allowed"] is True

        # Second entry: allowed (up to 2 per 30m)
        signal["symbol"] = "ETHUSDT"
        ov2 = paper_exploration_override(signal, ctx)
        assert ov2["allowed"] is True

        # Third entry: rate cap exceeded
        signal["symbol"] = "XRPUSDT"
        ov3 = paper_exploration_override(signal, ctx)
        assert ov3["allowed"] is False
        assert ov3["reason"] == "rate_cap_exceeded"


class TestP11APL_ShadowTradeDetection:
    """Test detection of shadow-only trades for learning skip."""

    def test_is_econ_bad_near_miss_shadow_trade_bucket_field(self):
        """Test detection via bucket field."""
        trade = {
            "bucket": "E_ECON_BAD_NEAR_MISS_SHADOW",
            "symbol": "BTCUSDT",
            "profit": 0.0001,
        }
        assert _is_econ_bad_near_miss_shadow_trade(trade) is True

    def test_is_econ_bad_near_miss_shadow_trade_explore_bucket_field(self):
        """Test detection via explore_bucket field."""
        trade = {
            "explore_bucket": "E_ECON_BAD_NEAR_MISS_SHADOW",
            "symbol": "BTCUSDT",
            "profit": 0.0001,
        }
        assert _is_econ_bad_near_miss_shadow_trade(trade) is True

    def test_is_econ_bad_near_miss_shadow_trade_negative(self):
        """Test non-shadow trade returns False."""
        trade = {
            "bucket": "B_RECOVERY_READY",
            "symbol": "BTCUSDT",
            "profit": 0.0001,
        }
        assert _is_econ_bad_near_miss_shadow_trade(trade) is False


class TestP11APL_Isolation:
    """Test isolation: D_NEG/B/C behavior unchanged, live/real not affected."""

    def setup_method(self):
        """Reset exploration caps before each test."""
        reset_exploration_caps()

    def test_d_neg_ev_control_still_works(self):
        """Test: D_NEG_EV_CONTROL bucket still functions independently."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.005,
            "score": 0.18,
            "p": 0.0,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
        }
        ctx = {
            "reject_reason": "NEGATIVE",
            "original_decision": "REJECT_NEGATIVE_EV",
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        assert ov["bucket"] == "D_NEG_EV_CONTROL"

    def test_c_weak_ev_cost_edge_check_unchanged(self):
        """Test: C_WEAK_EV cost-edge check works as before (rejects when edge too low)."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.003,  # Positive but weak
            "score": 0.18,
            "p": 0.1,  # Some quality
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": "BULL_TREND",
            "atr": 100.0,
            "last_price": 50000.0,
        }
        ctx = {
            "reject_reason": "weak_ev",
            "original_decision": "REJECT_WEAK_EV",  # Not ECON_BAD
            "recovery_ready": False,
            "probe_ready": False,
        }

        ov = paper_exploration_override(signal, ctx)

        # Should try C_WEAK_EV path (might be rejected due to cost_edge, but not routed to E-shadow because not ECON_BAD)
        assert ov["bucket"] != "E_ECON_BAD_NEAR_MISS_SHADOW"


class TestP11APL_ExplorationStats:
    """Test exploration stats reporting includes E_ECON_BAD_NEAR_MISS_SHADOW."""

    def test_exploration_stats_includes_econ_bad_shadow(self):
        """Test: get_exploration_stats returns E_ECON_BAD_NEAR_MISS_SHADOW stats."""
        stats = get_exploration_stats()

        assert "E_ECON_BAD_NEAR_MISS_SHADOW" in stats
        assert "count" in stats["E_ECON_BAD_NEAR_MISS_SHADOW"]
        assert "max" in stats["E_ECON_BAD_NEAR_MISS_SHADOW"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
