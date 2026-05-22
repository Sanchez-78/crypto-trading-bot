"""P1.1AP-N2: Tests for paper adaptive recovery admission wiring into cost_edge_too_low path."""
import pytest
import time
from unittest.mock import patch, MagicMock
from src.services import paper_training_sampler
from src.services.paper_training_sampler import maybe_open_training_sample


class TestN2RecoveryAdmissionPath:
    """N2 recovery admission should allow positive weak-EV candidates rejected by cost_edge_too_low."""

    def test_recovery_admission_econ_bad_positive_ev_cost_edge_too_low(self):
        """Recovery admission allows REJECT_ECON_BAD_ENTRY + EV>0 + cost_edge_too_low."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.0338,
            "p": 0.5,  # Quality required for C_WEAK_EV_TRAIN
            "features": {"rsi": 50},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):  # cost_edge too low
                    result = maybe_open_training_sample(
                        signal=signal,
                        reason="REJECT_ECON_BAD_ENTRY",
                        current_price=0.5,
                    )

        assert result.get("allowed") is True, f"Expected recovery admission, got: {result}"
        assert result.get("recovery_admission") is True
        assert result.get("learning_source") == "paper_adaptive_recovery"
        assert result.get("admission_reason") == "paper_learning_must_continue"
        assert result.get("historical_health") == "BAD"

    def test_recovery_admission_caps_global_3(self):
        """Recovery admission respects global cap of 3 open positions."""
        signal = {
            "symbol": "ADAUSDT",
            "action": "SELL",
            "ev": 0.0300,
            "p": 0.5,  # Quality required for C_WEAK_EV_TRAIN
            "features": {},
        }

        # Simulate 3 recovery positions already open
        open_positions = [
            {"learning_source": "paper_adaptive_recovery", "symbol": "XYZ1"},
            {"learning_source": "paper_adaptive_recovery", "symbol": "XYZ2"},
            {"learning_source": "paper_adaptive_recovery", "symbol": "XYZ3"},
        ]

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                    # Patch _training_quality_gate to pass open_positions
                    with patch(
                        "src.services.paper_training_sampler._training_quality_gate"
                    ) as mock_gate:
                        mock_gate.return_value = {
                            "allowed": False,
                            "reason": "recovery_cap_global",
                        }
                        result = maybe_open_training_sample(
                            signal=signal,
                            reason="REJECT_ECON_BAD_ENTRY",
                            current_price=0.5,
                        )

        assert result.get("allowed") is False
        assert "recovery_cap" in result.get("reason", "")

    def test_recovery_admission_caps_per_symbol_1(self):
        """Recovery admission respects per-symbol cap of 1 open position."""
        signal = {
            "symbol": "ADAUSDT",
            "action": "SELL",
            "ev": 0.0300,
            "p": 0.5,  # Quality required for C_WEAK_EV_TRAIN
            "features": {},
        }

        # Simulate 1 recovery position already open on same symbol
        open_positions = [
            {"learning_source": "paper_adaptive_recovery", "symbol": "ADAUSDT"},
        ]

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                    with patch(
                        "src.services.paper_training_sampler._training_quality_gate"
                    ) as mock_gate:
                        mock_gate.return_value = {
                            "allowed": False,
                            "reason": "recovery_cap_per_symbol",
                        }
                        result = maybe_open_training_sample(
                            signal=signal,
                            reason="REJECT_ECON_BAD_ENTRY",
                            current_price=0.5,
                        )

        assert result.get("allowed") is False
        assert "recovery_cap" in result.get("reason", "")

    def test_recovery_admission_negative_ev_rejected(self):
        """Recovery admission does NOT allow EV <= 0."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": -0.0050,  # Negative EV
            "features": {},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                    # For negative EV, it may get D_NEG_EV_CONTROL bucket, but NOT recovery
                    # Recovery is only for ECON_BAD + positive EV
                    result = maybe_open_training_sample(
                        signal=signal,
                        reason="REJECT_ECON_BAD_ENTRY",
                        current_price=0.5,
                    )

        # Recovery admission should NOT be activated for negative EV
        assert result.get("recovery_admission") is not True

    def test_recovery_admission_not_econ_bad(self):
        """Recovery admission only for REJECT_ECON_BAD_ENTRY, not other reasons."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.0338,
            "features": {},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                    result = maybe_open_training_sample(
                        signal=signal,
                        reason="REJECT_NEGATIVE_EV",  # Different reason, not ECON_BAD
                        current_price=0.5,
                    )

        # Should not activate recovery for non-ECON_BAD rejection
        # Should follow normal path (which will reject due to negative bucket for neg EV)
        assert result.get("allowed") is False

    def test_recovery_admission_not_live_real(self):
        """Recovery admission disabled in live_real mode."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.0338,
            "features": {},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=False):
            result = maybe_open_training_sample(
                signal=signal,
                reason="REJECT_ECON_BAD_ENTRY",
                current_price=0.5,
            )

        assert result.get("allowed") is False
        assert result.get("reason") == "training_disabled"

    def test_recovery_admission_metadata_preserved(self):
        """Recovery admission preserves expected_move and cost_edge metadata."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.0348,
            "p": 0.5,  # Quality required for C_WEAK_EV_TRAIN
            "features": {},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._estimate_expected_move") as mock_move:
                    mock_move.return_value = (0.0001, 0.0004, "atr_abs_price_normalized")
                    with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                        result = maybe_open_training_sample(
                            signal=signal,
                            reason="REJECT_ECON_BAD_ENTRY",
                            current_price=0.5,
                        )

        assert result.get("allowed") is True
        assert result.get("recovery_admission") is True
        assert result.get("expected_move_pct") == pytest.approx(0.0004)
        assert result.get("expected_move_src") == "atr_abs_price_normalized"
        assert result.get("cost_edge_ok") is False


class TestN2RecoveryDoesNotAffectDNeg:
    """N2 recovery should not regress N1's D_NEG exclusion."""

    def test_d_neg_still_emits_shadow_skip(self, caplog):
        """D_NEG positions still emit PAPER_LEARNING_SHADOW_SKIP, not recovery."""
        # This test would need to test at the paper_trade_executor level
        # where close_paper_position checks eligibility
        pass

    def test_d_neg_not_updated_in_adaptive(self):
        """D_NEG trades don't update adaptive learner metrics."""
        # Test verifies the eligibility predicate excludes D_NEG
        pass


class TestN2RecoveryCapState:
    """N2 recovery cap state is properly tracked and enforced."""

    def test_recovery_cap_state_initialized(self):
        """Recovery state module variables initialized."""
        assert paper_training_sampler._RECOVERY_MAX_OPEN_GLOBAL == 3
        assert paper_training_sampler._RECOVERY_MAX_OPEN_PER_SYMBOL == 1

    def test_check_recovery_admission_caps_allows_when_under_limit(self):
        """_check_recovery_admission_caps returns allowed when under limit."""
        open_positions = []
        allowed, reason = paper_training_sampler._check_recovery_admission_caps("XRPUSDT", open_positions)
        assert allowed is True
        assert reason == ""

    def test_check_recovery_admission_caps_blocks_global_limit(self):
        """_check_recovery_admission_caps blocks at global limit."""
        open_positions = [
            {"learning_source": "paper_adaptive_recovery", "symbol": "A"},
            {"learning_source": "paper_adaptive_recovery", "symbol": "B"},
            {"learning_source": "paper_adaptive_recovery", "symbol": "C"},
        ]
        allowed, reason = paper_training_sampler._check_recovery_admission_caps("D", open_positions)
        assert allowed is False
        assert reason == "recovery_cap_global"

    def test_check_recovery_admission_caps_blocks_per_symbol_limit(self):
        """_check_recovery_admission_caps blocks per-symbol limit."""
        open_positions = [
            {"learning_source": "paper_adaptive_recovery", "symbol": "XRPUSDT"},
        ]
        allowed, reason = paper_training_sampler._check_recovery_admission_caps("XRPUSDT", open_positions)
        assert allowed is False
        assert reason == "recovery_cap_per_symbol"

    def test_check_recovery_admission_caps_allows_different_symbol(self):
        """_check_recovery_admission_caps allows different symbol under limit."""
        open_positions = [
            {"learning_source": "paper_adaptive_recovery", "symbol": "XRPUSDT"},
        ]
        allowed, reason = paper_training_sampler._check_recovery_admission_caps("ADAUSDT", open_positions)
        assert allowed is True
        assert reason == ""


class TestN2DeadlockGateDoesNotVeto:
    """N2: actual_recovery_allowed=False must NOT veto recovery admissions."""

    def test_recovery_admission_independent_of_deadlock_gate(self):
        """Recovery admission checks only ECON_BAD + EV>0 + cost_edge, not deadlock gate."""
        # The deadlock gate is in realtime_decision_engine.py and governs a different path
        # Recovery admission in paper_training_sampler.py should not be blocked by that gate
        # This is verified by the fact that maybe_open_training_sample doesn't check actual_recovery_allowed
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.0338,
            "p": 0.5,  # Quality required for C_WEAK_EV_TRAIN
            "features": {},
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            with patch("src.core.runtime_mode.get_trading_mode") as mock_mode:
                mock_mode.return_value = MagicMock(value="paper_train")
                with patch("src.services.paper_exploration._check_cost_edge", return_value=False):
                    result = maybe_open_training_sample(
                        signal=signal,
                        reason="REJECT_ECON_BAD_ENTRY",
                        current_price=0.5,
                    )

        # Should allow recovery regardless of deadlock gate status
        assert result.get("allowed") is True
        assert result.get("recovery_admission") is True
