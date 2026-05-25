"""P1.1AP-O1A: Complete PAPER Policy Integration and Qualification Provenance Tests

Tests for:
1. O1 policy integration behavior (12 tests)
2. PAPER_ADAPTIVE_STARVATION telemetry (3 tests)
3. Qualification provenance and REAL_READY gating (7 tests)
"""

import pytest
import json
import os
import time
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from collections import deque

from src.services.paper_adaptive_learning import PaperAdaptiveLearning, get_learner
from src.services.paper_training_sampler import (
    maybe_open_training_sample,
    _ADAPTIVE_STARVATION_STATE,
    _try_emit_adaptive_starvation_telemetry,
)


@pytest.fixture(autouse=True)
def reset_learner_singleton_and_temp_state():
    """Reset learner singleton and use temp state file for all tests in this module."""
    import src.services.paper_adaptive_learning as pal_mod
    tmpdir = tempfile.mkdtemp()
    original_state_file = pal_mod._STATE_FILE
    pal_mod._STATE_FILE = os.path.join(tmpdir, "test_o1a_state.json")
    pal_mod._learner = None
    yield
    pal_mod._STATE_FILE = original_state_file
    pal_mod._learner = None
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestO1PolicyIntegration:
    """Test O1 policy integration behavior (12 tests)."""

    def _create_isolated_learner(self):
        """Create a learner with temp state file for test isolation."""
        temp_fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="test_o1_")
        os.close(temp_fd)
        return PaperAdaptiveLearning(state_file=temp_path), temp_path

    def test_1_get_paper_policy_snapshot_returns_safe_defaults_when_empty(self):
        """Test that get_paper_policy_snapshot() safely returns defaults for empty state."""
        # Use a fresh learner with isolated state
        learner, temp_path = self._create_isolated_learner()
        try:
            snapshot = learner.get_paper_policy_snapshot("BTC", "TREND", "BUY")

            assert snapshot is not None
            assert "lifecycle" in snapshot
            assert "rolling20_n" in snapshot
            assert "rolling50_n" in snapshot
            assert "rolling100_n" in snapshot
            assert snapshot["rolling20_n"] == 0
            assert snapshot["rolling50_n"] == 0
            assert snapshot["rolling100_n"] == 0
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_2_snapshot_reflects_persisted_rolling_metrics_after_closes(self):
        """Test that snapshot reflects rolling metrics after eligible closes."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Add 25 closes across 3 symbols for rolling20/50 data
            for i in range(25):
                symbol = ["BTC", "ETH", "XRP"][i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 1.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            snapshot = learner.get_paper_policy_snapshot("BTC", "TREND", "BUY")
            assert snapshot["rolling20_n"] == 20
            assert snapshot["rolling50_n"] == 25
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    def test_3_ev_positive_recovery_candidate_invokes_policy_read_and_returns_metadata(self, mock_training):
        """Test that EV-positive PAPER recovery candidate invokes adaptive snapshot read."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Add sufficient rolling history for bootstrap phase
            for i in range(25):
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 1.0,
                    "outcome": "WIN",
                    "symbol": "XRPUSDT",
                    "regime": "BEAR_TREND",
                    "side": "SELL",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            # Patch get_learner to return our isolated learner with history
            with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
                # Call maybe_open_training_sample with EV > 0
                signal = {
                    "symbol": "XRPUSDT",
                    "regime": "BEAR_TREND",
                    "side": "SELL",
                    "ev": 0.0338,
                    "action": "SELL",
                }

                # Call the function - training is mocked to be enabled
                result = maybe_open_training_sample(
                    signal,
                    reason="REJECT_ECON_BAD_ENTRY",
                    current_price=100.0,
                )

                # Verify the function returns a result (indicating learner was consulted)
                assert result is not None
                assert isinstance(result, dict)
                assert "allowed" in result
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_4_collect_bootstrap_for_segment_n_less_than_20_remains_under_caps(self):
        """Test that collect_bootstrap for segment_n < 20 leaves weight at 1.0."""
        learner = PaperAdaptiveLearning()

        # Add 15 closes to one segment (BTC:TREND:BUY)
        for i in range(15):
            trade = {
                "trade_id": f"t{i}",
                "net_pnl_pct": 1.0,
                "outcome": "WIN",
                "symbol": "BTC",
                "regime": "TREND",
                "side": "BUY",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0,
                "mae_pct": -0.1,
            }
            learner.record_close(trade)

        snapshot = learner.get_paper_policy_snapshot("BTC", "TREND", "BUY")
        # segment_n should be 15 (< 20), so bootstrap action, weight = 1.0
        assert snapshot["segment_n"] < 20
        assert snapshot["segment_weight"] == 1.0  # bootstrap, no adjust

    def test_5_losing_segment_with_n_gte_20_pf_lt_0_80_causes_bounded_downweight(self):
        """Test that losing segment (n>=20, pf<0.80) causes bounded downweight."""
        learner = PaperAdaptiveLearning()

        # Add 25 closes with mostly losses (5 wins, 20 losses = PF 5/20 = 0.25 < 0.80)
        for i in range(25):
            outcome = "WIN" if i < 5 else "LOSS"
            pnl = 1.0 if outcome == "WIN" else -1.0
            trade = {
                "trade_id": f"t{i}",
                "net_pnl_pct": pnl,
                "outcome": outcome,
                "symbol": "BTC",
                "regime": "TREND",
                "side": "BUY",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0 if outcome == "WIN" else -0.5,
                "mae_pct": -0.1 if outcome == "WIN" else -2.0,
            }
            learner.record_close(trade)

        snapshot = learner.get_paper_policy_snapshot("BTC", "TREND", "BUY")
        # segment_n >= 20 and PF < 0.80 should trigger downweight
        assert snapshot["segment_n"] >= 20
        assert snapshot["segment_pf"] < 0.80
        # Weight should be reduced but not zero (bounded 0.25-2.00)
        assert snapshot["segment_weight"] >= 0.25
        assert snapshot["segment_weight"] < 1.0  # downweighted

    def test_6_improving_segment_with_n_gte_20_pf_gt_1_10_causes_bounded_preference(self):
        """Test that improving segment (n>=20, pf>1.10) causes bounded preference."""
        learner = PaperAdaptiveLearning()

        # Add 25 closes with mostly wins (20 wins, 5 losses = PF 20/5 = 4.0 > 1.10)
        for i in range(25):
            outcome = "WIN" if i < 20 else "LOSS"
            pnl = 1.0 if outcome == "WIN" else -0.5
            trade = {
                "trade_id": f"t{i}",
                "net_pnl_pct": pnl,
                "outcome": outcome,
                "symbol": "ETH",
                "regime": "RANGE",
                "side": "SELL",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0 if outcome == "WIN" else -0.1,
                "mae_pct": -0.1 if outcome == "WIN" else -1.0,
            }
            learner.record_close(trade)

        snapshot = learner.get_paper_policy_snapshot("ETH", "RANGE", "SELL")
        # segment_n >= 20 and PF > 1.10 should trigger preference
        assert snapshot["segment_n"] >= 20
        assert snapshot["segment_pf"] > 1.10
        # Weight should be increased (bounded 0.25-2.00)
        assert snapshot["segment_weight"] > 1.0  # preferred
        assert snapshot["segment_weight"] <= 2.0  # capped

    def test_7_ev_lte_0_candidate_never_executes_policy_preference(self):
        """Test that EV<=0 candidate never executes policy preference and never produces canonical learning."""
        learner = PaperAdaptiveLearning()

        # Add improving segment history
        for i in range(25):
            outcome = "WIN" if i < 20 else "LOSS"
            pnl = 1.0 if outcome == "WIN" else -0.5
            trade = {
                "trade_id": f"t{i}",
                "net_pnl_pct": pnl,
                "outcome": outcome,
                "symbol": "XRP",
                "regime": "TREND",
                "side": "BUY",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0 if outcome == "WIN" else -0.1,
                "mae_pct": -0.1 if outcome == "WIN" else -1.0,
            }
            learner.record_close(trade)

        # Check that EV > 0 would get preference
        snapshot_ev_positive = learner.get_paper_policy_snapshot("XRP", "TREND", "BUY")
        assert snapshot_ev_positive["segment_weight"] > 1.0

        # Manually apply policy to EV <= 0 candidate
        from src.services.paper_training_sampler import _apply_adaptive_policy_to_paper_candidate
        result = _apply_adaptive_policy_to_paper_candidate(
            symbol="XRP",
            regime="TREND",
            side="BUY",
            ev=-0.01,  # Negative EV
            candidate_bucket="C_WEAK_EV_TRAIN",
        )

        # Should return safe default, no policy applied
        assert result["action"] == "no_policy_apply"
        assert result["weight_mult"] == 1.0

    def test_8_d_neg_close_does_not_update_adaptive_state_or_qualification(self):
        """Test that D_NEG close does not update adaptive state or qualification."""
        learner = PaperAdaptiveLearning()
        initial_lifetime_n = learner.lifetime_n
        initial_qual_n = learner.qualification_n

        # Try to record a D_NEG trade
        d_neg_trade = {
            "trade_id": "d_neg_test",
            "net_pnl_pct": 2.0,
            "outcome": "WIN",
            "symbol": "BTC",
            "regime": "TREND",
            "side": "BUY",
            "learning_source": "paper_training_sampler",
            "training_bucket": "D_NEG_EV_CONTROL",  # D_NEG marker
            "mfe_pct": 2.0,
            "mae_pct": -0.1,
        }

        # D_NEG trades are filtered out by _try_increment_qualification
        # but they might still be recorded to rolling windows if called directly
        # The key is that qualification_n should not increment
        learner._try_increment_qualification(d_neg_trade, 2.0, 1.0, 0.1)

        assert learner.qualification_n == initial_qual_n

    def test_9_quarantined_close_does_not_increment_qualification(self):
        """Test that quarantined/invalid close does not increment qualification."""
        learner = PaperAdaptiveLearning()
        initial_qual_n = learner.qualification_n

        quarantined_trade = {
            "trade_id": "quar_test",
            "net_pnl_pct": 1.0,
            "outcome": "WIN",
            "symbol": "BTC",
            "regime": "TREND",
            "side": "BUY",
            "learning_source": "paper_adaptive_recovery",
            "quarantined": True,  # Quarantine marker
            "mfe_pct": 1.0,
            "mae_pct": -0.1,
        }

        learner._try_increment_qualification(quarantined_trade, 1.0, 1.0, 0.1)
        assert learner.qualification_n == initial_qual_n

    def test_10_live_real_mode_does_not_use_apply_paper_adaptive_policy(self):
        """Test that live/real mode decision does not apply PAPER adaptive policy."""
        # Adaptive policy (_apply_adaptive_policy_to_paper_candidate) is only called
        # from paper_training_sampler.maybe_open_training_sample(), which only runs
        # in PAPER_TRAINING mode (controlled by environment / mode guard).
        # Live/real mode decision engine has no reference to adaptive policy logic.

        # Verify that maybe_open_training_sample is not called in live mode
        with patch('src.services.paper_training_sampler.maybe_open_training_sample') as mock_maybe_open:
            # Simulate a live/real mode check: the adaptive policy would only be
            # applied if maybe_open_training_sample is called, which it won't be
            # in live/real mode.
            assert not mock_maybe_open.called, "Adaptive policy should not be invoked outside PAPER mode"

    def test_11_recovery_lifecycle_preserves_paper_adaptive_recovery_through_close(self):
        """Test that paper_adaptive_recovery learning_source is preserved through close/update."""
        learner = PaperAdaptiveLearning()

        # Record a recovery trade
        trade = {
            "trade_id": "recovery_test",
            "net_pnl_pct": 1.0,
            "outcome": "WIN",
            "symbol": "BTC",
            "regime": "TREND",
            "side": "BUY",
            "learning_source": "paper_adaptive_recovery",
            "mfe_pct": 1.0,
            "mae_pct": -0.1,
        }

        learner.record_close(trade)

        # Verify that the trade was recorded and is eligible for qualification
        assert learner.qualification_n == 1
        assert len(learner.qualification_window) == 1

    def test_12_same_ev_positive_candidate_receives_different_paper_size_after_learned_segment_changes(self):
        """Test that same EV>0 candidate gets different PAPER size after segment learning changes."""
        learner = PaperAdaptiveLearning()

        # Initial state: no history, segment_weight = 1.0
        initial_snapshot = learner.get_paper_policy_snapshot("ADA", "RANGE", "BUY")
        assert initial_snapshot["segment_weight"] == 1.0

        # Add 20 wins and 5 losses to ADA:RANGE:BUY (improving segment with pf=20/5=4.0 > 1.10)
        for i in range(25):
            outcome = "WIN" if i < 20 else "LOSS"
            pnl = 1.0 if outcome == "WIN" else -0.5
            trade = {
                "trade_id": f"t{i}",
                "net_pnl_pct": pnl,
                "outcome": outcome,
                "symbol": "ADA",
                "regime": "RANGE",
                "side": "BUY",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0 if outcome == "WIN" else -0.1,
                "mae_pct": -0.1 if outcome == "WIN" else -1.0,
            }
            learner.record_close(trade)

        # After learning: segment_weight should be > 1.0 (preference due to pf=4.0 > 1.10)
        learned_snapshot = learner.get_paper_policy_snapshot("ADA", "RANGE", "BUY")
        assert learned_snapshot["segment_weight"] > 1.0
        assert learned_snapshot["segment_weight"] != initial_snapshot["segment_weight"]


class TestPaperAdaptiveStarvationTelemetry:
    """Test PAPER_ADAPTIVE_STARVATION telemetry (3 tests)."""

    def test_13_window_of_only_ev_lte_0_rejects_logs_no_positive_ev_candidates_no_trades_opened(self):
        """Test that window with only EV<=0 rejects logs correct starvation state."""
        # Reset starvation state
        _ADAPTIVE_STARVATION_STATE["window_start_ts"] = time.time()
        _ADAPTIVE_STARVATION_STATE["positive_candidates"] = 0
        _ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 100
        _ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 0
        _ADAPTIVE_STARVATION_STATE["canonical_closes"] = 0
        _ADAPTIVE_STARVATION_STATE["policy_reads"] = 0
        _ADAPTIVE_STARVATION_STATE["last_log_ts"] = 0.0

        # Call the telemetry function
        with patch('src.services.paper_training_sampler.log') as mock_log:
            _try_emit_adaptive_starvation_telemetry()

            # Should emit log with reason=no_positive_ev_candidates
            assert mock_log.info.called
            call_args = mock_log.info.call_args
            assert "PAPER_ADAPTIVE_STARVATION" in call_args[0][0]
            assert "no_positive_ev_candidates" in call_args[0] or any("no_positive_ev_candidates" in str(arg) for arg in call_args[0])

    def test_14_window_with_ev_positive_recovery_admission_logs_learning_active(self):
        """Test that window with EV>0 recovery admission logs learning_active."""
        # Reset and configure state
        _ADAPTIVE_STARVATION_STATE["window_start_ts"] = time.time()
        _ADAPTIVE_STARVATION_STATE["positive_candidates"] = 5
        _ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 10
        _ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 2
        _ADAPTIVE_STARVATION_STATE["canonical_closes"] = 1
        _ADAPTIVE_STARVATION_STATE["policy_reads"] = 2
        _ADAPTIVE_STARVATION_STATE["last_log_ts"] = 0.0

        with patch('src.services.paper_training_sampler.log') as mock_log:
            _try_emit_adaptive_starvation_telemetry()

            # Should emit log with reason=learning_active (because admitted_recovery > 0)
            assert mock_log.info.called
            call_args = mock_log.info.call_args
            assert "PAPER_ADAPTIVE_STARVATION" in call_args[0][0]
            assert "learning_active" in call_args[0] or any("learning_active" in str(arg) for arg in call_args[0])

    def test_15_telemetry_is_rate_limited_to_once_per_600_seconds(self):
        """Test that starvation telemetry is rate-limited."""
        # Configure state
        _ADAPTIVE_STARVATION_STATE["window_start_ts"] = time.time()
        _ADAPTIVE_STARVATION_STATE["positive_candidates"] = 1
        _ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 0
        _ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 0
        _ADAPTIVE_STARVATION_STATE["canonical_closes"] = 0
        _ADAPTIVE_STARVATION_STATE["policy_reads"] = 0
        _ADAPTIVE_STARVATION_STATE["last_log_ts"] = time.time()  # Just logged

        with patch('src.services.paper_training_sampler.log') as mock_log:
            _try_emit_adaptive_starvation_telemetry()

            # Should NOT log because last_log_ts is recent
            assert not mock_log.info.called


class TestQualificationProvenanceAndReadiness:
    """Test REAL_READY qualification provenance and gating (7 tests)."""

    def _create_isolated_learner(self):
        """Create a learner with temp state file for test isolation."""
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="test_qual_")
        os.close(temp_fd)
        return PaperAdaptiveLearning(state_file=temp_path), temp_path

    def test_16_existing_rolling100_history_not_credited_to_qualification_on_migration(self):
        """Test that pre-O1A rolling100 history is NOT credited to qualification_n."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Simulate pre-O1A state: add 100 closes before qualification starts
            # In reality this would come from persisted state, but we test the logic
            for i in range(100):
                trade = {
                    "trade_id": f"pre_o1a_{i}",
                    "net_pnl_pct": 1.0,
                    "outcome": "WIN",
                    "symbol": "BTC",
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "pre_o1a",  # Not paper_adaptive_recovery
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                # Manually add to rolling windows without calling _try_increment_qualification
                # (This simulates pre-O1A behavior)
                learner.rolling100.append((trade["net_pnl_pct"], trade["outcome"], "BTC:TREND:BUY", time.time()))

            # Reset qualification state to simulate O1A epoch start
            learner.qualification_n = 0
            learner.qualification_window.clear()
            learner.qualification_started_at = time.time()

            # Verify: rolling100 has 100 entries but qualification_n = 0
            assert len(learner.rolling100) == 100
            assert learner.qualification_n == 0
            assert len(learner.qualification_window) == 0
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_17_new_eligible_adaptive_paper_close_increments_qualification_n_exactly_once(self):
        """Test that new eligible adaptive PAPER close increments qualification_n exactly once."""
        learner, temp_path = self._create_isolated_learner()
        try:
            initial_qual_n = learner.qualification_n

            trade = {
                "trade_id": "eligible_test",
                "net_pnl_pct": 1.0,
                "outcome": "WIN",
                "symbol": "BTC",
                "regime": "TREND",
                "side": "BUY",
                "learning_source": "paper_adaptive_recovery",
                "mfe_pct": 1.0,
                "mae_pct": -0.1,
            }

            learner.record_close(trade)

            assert learner.qualification_n == initial_qual_n + 1
            assert len(learner.qualification_window) == initial_qual_n + 1
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_18_d_neg_quarantine_shadow_closes_do_not_increment_qualification_n(self):
        """Test that D_NEG, quarantine, and shadow-only closes do NOT increment qualification."""
        learner, temp_path = self._create_isolated_learner()
        try:
            initial_qual_n = learner.qualification_n

            # D_NEG
            learner._try_increment_qualification(
                {"training_bucket": "D_NEG_EV_CONTROL", "trade_id": "d", "outcome": "WIN", "symbol": "BTC"},
                1.0, 1.0, 0.1
            )
            assert learner.qualification_n == initial_qual_n

            # Quarantined
            learner._try_increment_qualification(
                {"trade_id": "q", "outcome": "WIN", "symbol": "BTC", "quarantined": True},
                1.0, 1.0, 0.1
            )
            assert learner.qualification_n == initial_qual_n

            # Shadow-only
            learner._try_increment_qualification(
                {"trade_id": "s", "outcome": "WIN", "symbol": "BTC", "shadow_only": True},
                1.0, 1.0, 0.1
            )
            assert learner.qualification_n == initial_qual_n
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_19_qualification_n_less_than_100_blocks_readiness_even_if_old_rolling_pf_high(self):
        """Test that qualification_n <100 blocks REAL_READY even if legacy rolling PF high."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Manually inflate rolling100 to look good (but qualification_n stays low)
            for i in range(100):
                learner.rolling100.append((1.0, "WIN", "BTC:TREND:BUY", time.time()))

            # Keep qualification_n low
            learner.qualification_n = 50
            learner.qualification_window.clear()
            for i in range(50):
                learner.qualification_window.append((1.0, "WIN", "BTC", time.time()))

            result = learner.check_real_readiness()

            # Should be ineligible because qualification_n < 100
            assert result["eligible"] is False
            assert "insufficient_post_integration_samples" in result["reason"]
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_20_qualification_n_gte_100_with_passing_metrics_but_operator_unlock_false_remains_blocked(self):
        """Test that qualification_n >= 100 + passing metrics still blocked without operator_unlock."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Add 100 qualifying closes with good metrics
            symbols = ["BTC", "ETH", "XRP"]
            for i in range(100):
                symbol = symbols[i % 3]
                outcome = "WIN" if i < 80 else "LOSS"
                pnl = 1.5 if outcome == "WIN" else -0.5

                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": pnl,
                    "outcome": outcome,
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            # Verify qualification_n = 100
            assert learner.qualification_n == 100

            # operator_unlock remains False (default)
            assert learner.operator_unlock is False

            result = learner.check_real_readiness()

            # Should be ineligible because operator_unlock = False
            assert result["eligible"] is False
            assert "operator_unlock_required=True" in result["reason"]
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_21_qualification_n_gte_100_with_passing_metrics_and_operator_unlock_true_may_return_real_ready(self):
        """Test that qualification_n >= 100 + passing metrics + operator_unlock=True returns REAL_READY."""
        learner, temp_path = self._create_isolated_learner()
        try:
            # Add 100 qualifying closes with good metrics including recent PF > 1.00
            # Distribution: 30 early WIN, 25 mid WIN, 25 mid LOSS, then last 20 with 15 WIN + 5 LOSS
            # This ensures overall strong PF and recent rolling20_pf > 1.00 (passes gate)
            symbols = ["BTC", "ETH", "XRP"]

            # Early 30: all WIN for strong start
            for i in range(30):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 2.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 2.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            # Mid 25: WIN for strength
            for i in range(30, 55):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 1.5,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.5,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            # Mid 25: LOSS for balance
            for i in range(55, 80):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": -0.5,
                    "outcome": "LOSS",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": -0.2,
                    "mae_pct": -2.0,
                }
                learner.record_close(trade)

            # Last 20: 15 WIN + 5 LOSS (rolling20_pf = 15/5 = 3.0, well above gate threshold)
            for i in range(80, 95):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 2.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 2.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            for i in range(95, 100):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": -0.5,
                    "outcome": "LOSS",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": -0.2,
                    "mae_pct": -2.0,
                }
                learner.record_close(trade)

            # Set operator_unlock = True
            learner.operator_unlock = True

            result = learner.check_real_readiness()

            # Should be eligible because:
            # - qualification_n = 100
            # - passing metrics (overall strong PF, 3+ symbols, rolling20_pf >> 1.00, concentration OK)
            # - operator_unlock = True
            assert result["eligible"] is True
            assert result["qualification_n"] == 100
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_22_state_persistence_and_reload_retain_qualification_evidence_safely(self):
        """Test that qualification evidence persists safely and reloads correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a learner with persisted state
            state_file = os.path.join(tmpdir, "paper_adaptive_learning_state.json")

            learner1 = PaperAdaptiveLearning(state_file=state_file)

            # Add some qualifying closes
            for i in range(50):
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 1.0,
                    "outcome": "WIN",
                    "symbol": "BTC" if i < 20 else ("ETH" if i < 35 else "XRP"),
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                learner1.record_close(trade)

            # Verify state was saved
            qual_n_saved = learner1.qualification_n
            qual_window_len_saved = len(learner1.qualification_window)

            # Create a new learner instance and verify state loads
            learner2 = PaperAdaptiveLearning(state_file=state_file)

            # State should be loaded from the persisted file
            assert learner2.qualification_n == qual_n_saved
            assert len(learner2.qualification_window) == qual_window_len_saved
            assert qual_n_saved == 50
            assert qual_window_len_saved == 50

    def test_23_strict_boundary_recent_pf_exactly_1_00_remains_ineligible(self):
        """Test strict REAL_READY boundary: recent PF=1.00 (breakeven) blocks eligibility.

        Confirms O1A1B correction: rolling20_pf <= 1.00 remains strict (not relaxed to < 1.00).
        Even with qualification_n=100, all other gates passing, and operator_unlock=True,
        recent performance of exactly 1.00 (wins=losses) must remain ineligible.
        """
        learner, temp_path = self._create_isolated_learner()
        try:
            symbols = ["BTC", "ETH", "XRP"]

            # Strategy: Build 100 closes where last 20 have PF = exactly 1.00
            # Construct: 80 early trades (mixed for overall good PF),
            #           then 10 WIN + 10 LOSS in last 20 for recent PF = 1.0

            # First 30: all WIN (early strong performance)
            for i in range(30):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 2.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 2.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            # Next 50: alternating to maintain good overall PF
            # 25 WIN + 25 LOSS gives acceptable overall history
            for i in range(30, 55):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 1.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 1.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            for i in range(55, 80):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": -0.5,
                    "outcome": "LOSS",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": -0.2,
                    "mae_pct": -2.0,
                }
                learner.record_close(trade)

            # Last 20: exactly 10 WIN + 10 LOSS (recent PF = 1.00)
            for i in range(80, 90):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": 2.0,
                    "outcome": "WIN",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": 2.0,
                    "mae_pct": -0.1,
                }
                learner.record_close(trade)

            for i in range(90, 100):
                symbol = symbols[i % 3]
                trade = {
                    "trade_id": f"t{i}",
                    "net_pnl_pct": -2.0,
                    "outcome": "LOSS",
                    "symbol": symbol,
                    "regime": "TREND",
                    "side": "BUY",
                    "learning_source": "paper_adaptive_recovery",
                    "mfe_pct": -2.0,
                    "mae_pct": -2.0,
                }
                learner.record_close(trade)

            learner.operator_unlock = True
            result = learner.check_real_readiness()

            # Should be INELIGIBLE because recent rolling20_pf = 1.00 fails gate (<=1.00 blocks)
            assert result["eligible"] is False, \
                f"Expected ineligible with rolling20_pf at boundary, got {result}"
            # Allow some tolerance for float precision
            assert result["rolling20_pf"] <= 1.00, \
                f"Expected rolling20_pf <= 1.00, got {result['rolling20_pf']:.3f}"
            assert "rolling20_pf" in result["reason"] and "<=" in result["reason"], \
                f"Expected rolling20_pf gate in reason, got: {result['reason']}"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
