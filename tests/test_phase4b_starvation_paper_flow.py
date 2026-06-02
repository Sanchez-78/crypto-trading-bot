"""Phase 4B: Starvation Admission Bypass Tests

Tests for PAPER-only training flow during starvation when cost-edge rejects all candidates.
Verifies that the bot can recover from entry starvation by accepting bounded PAPER learning trades
while keeping REAL orders disabled and maintaining learning eligibility constraints.

CRITICAL BEHAVIORS:
1. Starvation bypass accepts PAPER trades when idle_s >= 600 and cost_edge_ok=False
2. REAL orders remain disabled (ENABLE_REAL_ORDERS=false)
3. Accepted trades marked with cost_edge_bypassed=True, readiness_eligible=False
4. Global cap: max 2 starvation positions, per-symbol cap: max 1
5. Cooldown: 10 min per symbol/side/bucket
6. Works for both PAPER_STARVATION_DISCOVERY and C_WEAK_EV_TRAIN buckets
7. Normal cost-edge behavior unchanged when not in starvation
"""

import pytest
import time
import os
from unittest.mock import patch, MagicMock, PropertyMock
from src.services import paper_training_sampler as pts


class TestStarvationAdmissionBypass:
    """Test suite for Phase 4B starvation bypass feature."""

    def setup_method(self):
        """Reset global state before each test."""
        pts._starvation_discovery_state["last_eligible_entry_ts"] = time.time()
        pts._starvation_discovery_state["idle_s"] = 0.0
        pts._recent_dup_candidate.clear()
        pts._entry_times_minute.clear()
        pts._entry_times_hour.clear()

    def test_starvation_idle_gate(self):
        """Verify idle_s >= 600 threshold is required for starvation bypass."""
        now = time.time()

        # idle_s < 600: should NOT be starvation
        pts._starvation_discovery_state["last_eligible_entry_ts"] = now
        pts._starvation_discovery_state["idle_s"] = 100.0
        assert not pts._is_starvation_discovery_idle(), "Should require idle_s >= 600"

        # idle_s >= 600: should be starvation
        pts._starvation_discovery_state["last_eligible_entry_ts"] = now - 610
        pts._starvation_discovery_state["idle_s"] = 610.0
        assert pts._is_starvation_discovery_idle(), "Should detect starvation at idle_s=610"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false", "PAPER_TRAINING_ENABLED": "true"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_accepts_paper_training_sample(self, mock_mode, mock_idle):
        """Verify starvation bypass accepts PAPER learning trade during starvation."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        now = time.time()
        pts._starvation_discovery_state["last_eligible_entry_ts"] = now - 610

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,  # Normally rejected
            open_positions=[],
        )

        assert result.get("allowed"), f"Starvation bypass should accept, got reason: {result.get('reason')}"
        assert result.get("cost_edge_bypassed"), "Should mark as bypassed"
        assert result.get("cost_edge_bypass_reason") == "paper_starvation_learning"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "true"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_blocked_when_real_enabled(self, mock_mode, mock_idle):
        """Verify starvation bypass rejects when REAL orders are enabled."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )

        assert not result.get("allowed"), "REAL orders enabled should block bypass"
        assert result.get("reason") == "cost_edge_false_without_bypass"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_respects_global_cap(self, mock_mode, mock_idle):
        """Verify starvation bypass respects global position cap (max 2)."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        now = time.time()

        # 2 starvation positions already open
        open_positions = [
            {"cost_edge_bypassed": True, "cost_edge_bypass_reason": "paper_starvation_learning", "symbol": "BTC"},
            {"cost_edge_bypassed": True, "cost_edge_bypass_reason": "paper_starvation_learning", "symbol": "ETH"},
        ]

        result = pts._training_quality_gate(
            symbol="XRP",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=open_positions,
        )

        assert not result.get("allowed"), "Global cap reached should block"
        # Should log that it's blocked by global cap

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_respects_per_symbol_cap(self, mock_mode, mock_idle):
        """Verify starvation bypass respects per-symbol cap (max 1)."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        # 1 starvation position already open for BTC
        open_positions = [
            {"cost_edge_bypassed": True, "cost_edge_bypass_reason": "paper_starvation_learning", "symbol": "BTC"},
        ]

        result = pts._training_quality_gate(
            symbol="BTC",  # Same symbol
            side="SELL",   # Different side
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=open_positions,
        )

        assert not result.get("allowed"), "Per-symbol cap reached should block"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_respects_cooldown(self, mock_mode, mock_idle):
        """Verify starvation bypass enforces 10-min cooldown per symbol/side/bucket."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        now = time.time()
        cooldown_key = "BTC:BUY:PAPER_STARVATION_DISCOVERY:starvation"

        # First entry should succeed
        result1 = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )
        assert result1.get("allowed"), "First entry should be allowed"

        # Second entry immediately after should be blocked by cooldown
        result2 = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )
        assert not result2.get("allowed"), "Second entry within cooldown should be blocked"
        assert result2.get("reason") == "cost_edge_false_without_bypass"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_works_for_weak_ev_train_bucket(self, mock_mode, mock_idle):
        """Verify starvation bypass works for C_WEAK_EV_TRAIN bucket too."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="C_WEAK_EV_TRAIN",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )

        assert result.get("allowed"), "Starvation bypass should work for C_WEAK_EV_TRAIN"
        assert result.get("cost_edge_bypass_reason") == "paper_starvation_learning"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_returns_correct_gate_metadata(self, mock_mode, mock_idle):
        """Verify gate result includes cost_edge_bypassed=True and bypass_reason."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )

        # Check gate metadata
        assert result.get("allowed"), "Starvation bypass should allow"
        assert result.get("cost_edge_bypassed") == True, "Should mark cost_edge_bypassed=True"
        assert result.get("cost_edge_bypass_reason") == "paper_starvation_learning"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_normal_cost_edge_unchanged_when_not_starvation(self, mock_mode, mock_idle):
        """Verify normal cost-edge rejection when idle_s < 600 (not in starvation)."""
        mock_idle.return_value = False  # NOT in starvation
        mock_mode.return_value = MagicMock(value="paper_train")

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="C_WEAK_EV_TRAIN",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )

        assert not result.get("allowed"), "Normal cost-edge should reject when not in starvation"
        assert result.get("reason") == "cost_edge_too_low", "Should use cost_edge_too_low for C_WEAK_EV_TRAIN"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_requires_valid_source_reject(self, mock_mode, mock_idle):
        """Verify starvation bypass only accepts REJECT_NEGATIVE_EV or REJECT_ECON_BAD_ENTRY."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        # Invalid source: should still reject
        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_FREQUENCY_CAP",  # Not allowed for starvation bypass
            cost_edge_ok=False,
            open_positions=[],
        )

        assert not result.get("allowed"), "Starvation bypass requires REJECT_NEGATIVE_EV or REJECT_ECON_BAD_ENTRY"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_works_with_econ_bad_reject(self, mock_mode, mock_idle):
        """Verify starvation bypass accepts REJECT_ECON_BAD_ENTRY source."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="C_WEAK_EV_TRAIN",
            source_reject="REJECT_ECON_BAD_ENTRY",
            cost_edge_ok=False,
            open_positions=[],
        )

        assert result.get("allowed"), "Starvation bypass should work with REJECT_ECON_BAD_ENTRY"
        assert result.get("cost_edge_bypass_reason") == "paper_starvation_learning"

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_full_validation(self, mock_mode, mock_idle):
        """Verify all aspects of starvation bypass validation."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        # Test with caps enforcement
        open_positions = []  # No positions open

        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=open_positions,
        )

        assert result.get("allowed"), "Should be allowed with no position caps hit"
        assert result.get("cost_edge_bypassed") == True, "Should mark cost_edge_bypassed=True"
        assert result.get("cost_edge_bypass_reason") == "paper_starvation_learning"


class TestStarvationBypassSafety:
    """Safety tests to ensure starvation bypass doesn't contaminate real-readiness."""

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_only_for_paper_buckets(self, mock_mode, mock_idle):
        """Verify starvation bypass only applies to PAPER_STARVATION_DISCOVERY and C_WEAK_EV_TRAIN."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        # Test with non-allowed bucket
        result = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="D_NEG_EV_CONTROL",  # Not a learning bucket
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )

        assert not result.get("allowed"), "Starvation bypass should NOT apply to non-learning buckets"


class TestStarvationBypassIntegration:
    """Integration tests with quality gates flow."""

    @patch.dict(os.environ, {"ENABLE_REAL_ORDERS": "false"})
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle")
    @patch("src.core.runtime_mode.get_trading_mode")
    def test_starvation_bypass_with_multiple_conditions(self, mock_mode, mock_idle):
        """Integration: starvation bypass works for both buckets."""
        mock_idle.return_value = True
        mock_mode.return_value = MagicMock(value="paper_train")

        # Test PAPER_STARVATION_DISCOVERY
        result1 = pts._training_quality_gate(
            symbol="BTC",
            side="BUY",
            bucket="PAPER_STARVATION_DISCOVERY",
            source_reject="REJECT_NEGATIVE_EV",
            cost_edge_ok=False,
            open_positions=[],
        )
        assert result1.get("allowed"), "Should accept PAPER_STARVATION_DISCOVERY"
        assert result1.get("cost_edge_bypassed"), "Should bypass for PAPER_STARVATION_DISCOVERY"

        # Test C_WEAK_EV_TRAIN with different symbol to avoid cooldown
        result2 = pts._training_quality_gate(
            symbol="ETH",
            side="SELL",
            bucket="C_WEAK_EV_TRAIN",
            source_reject="REJECT_ECON_BAD_ENTRY",
            cost_edge_ok=False,
            open_positions=[],
        )
        assert result2.get("allowed"), "Should accept C_WEAK_EV_TRAIN"
        assert result2.get("cost_edge_bypassed"), "Should bypass for C_WEAK_EV_TRAIN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
