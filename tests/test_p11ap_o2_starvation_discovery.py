"""Tests for P1.1AP-O2 PAPER starvation discovery route.

This test module verifies that REJECT_NEGATIVE_EV candidates can open
bounded PAPER discovery trades during sustained starvation, without
contaminating D_NEG, readiness, or REAL paths.

All discovery outcomes are marked LEGACY_SPOT_EXECUTION_UNVERIFIED and
readiness_eligible=false per specification.
"""
import pytest
import time
import logging
from unittest.mock import patch, MagicMock
from collections import deque

import src.services.paper_training_sampler as pts
from src.services.paper_training_sampler import (
    maybe_open_training_sample,
    _get_training_bucket,
    _is_starvation_discovery_idle,
    _check_starvation_discovery_caps,
    _update_starvation_discovery_idle,
)

log = logging.getLogger(__name__)


@pytest.fixture
def clean_sampler_state():
    """Reset all paper training sampler state for test isolation."""
    # Clear entry tracking
    for attr in ["_entry_times_minute", "_entry_times_hour"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear deduplication
    for attr in ["_recent_dedupe", "_recent_dup_candidate"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear skip logs
    for attr in ["_LAST_SKIP_LOG_TS", "_SKIP_COUNTERS"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear throttles
    for attr in ["_BYPASS_FLOW_LAST_LOG", "_RATE_CAP_STATE_LAST_LOG"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Reset starvation discovery state
    pts._starvation_discovery_state["open_global"] = 0
    pts._starvation_discovery_state["open_by_symbol"] = {}
    pts._starvation_discovery_state["entry_times_15m"].clear()
    pts._starvation_discovery_state["last_eligible_entry_ts"] = 0.0
    pts._starvation_discovery_state["idle_s"] = 0.0
    pts._starvation_discovery_state["valid_negative_candidates"] = 0
    pts._starvation_discovery_state["last_state_log_ts"] = 0.0

    # Reset adaptive starvation state
    pts._ADAPTIVE_STARVATION_STATE["window_start_ts"] = 0.0
    pts._ADAPTIVE_STARVATION_STATE["positive_candidates"] = 0
    pts._ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 0
    pts._ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 0
    pts._ADAPTIVE_STARVATION_STATE["canonical_closes"] = 0
    pts._ADAPTIVE_STARVATION_STATE["policy_reads"] = 0
    pts._ADAPTIVE_STARVATION_STATE["last_log_ts"] = 0.0

    # Reset probe state
    if hasattr(pts, "_probe_state"):
        pts._probe_state["entry_times_10m"].clear()

    yield

    # Cleanup after test
    for attr in ["_entry_times_minute", "_entry_times_hour"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()
    for attr in ["_recent_dedupe", "_recent_dup_candidate"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()
    for attr in ["_LAST_SKIP_LOG_TS", "_SKIP_COUNTERS"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()
    for attr in ["_BYPASS_FLOW_LAST_LOG", "_RATE_CAP_STATE_LAST_LOG"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()

    pts._starvation_discovery_state["open_global"] = 0
    pts._starvation_discovery_state["open_by_symbol"] = {}
    pts._starvation_discovery_state["entry_times_15m"].clear()
    pts._starvation_discovery_state["last_eligible_entry_ts"] = 0.0
    pts._starvation_discovery_state["idle_s"] = 0.0
    pts._starvation_discovery_state["valid_negative_candidates"] = 0
    pts._starvation_discovery_state["last_state_log_ts"] = 0.0

    pts._ADAPTIVE_STARVATION_STATE["window_start_ts"] = 0.0
    pts._ADAPTIVE_STARVATION_STATE["positive_candidates"] = 0
    pts._ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 0
    pts._ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 0
    pts._ADAPTIVE_STARVATION_STATE["canonical_closes"] = 0
    pts._ADAPTIVE_STARVATION_STATE["policy_reads"] = 0
    pts._ADAPTIVE_STARVATION_STATE["last_log_ts"] = 0.0

    if hasattr(pts, "_probe_state"):
        pts._probe_state["entry_times_10m"].clear()


class TestStarvationDiscoveryBucketRouting:
    """Test that REJECT_NEGATIVE_EV routes to PAPER_STARVATION_DISCOVERY during idle."""

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=False)
    @patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
    def test_reject_negative_ev_blocked_without_starvation(self, mock_cold, mock_idle, mock_training, clean_sampler_state):
        """REJECT_NEGATIVE_EV does NOT route to discovery when idle < 600s."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,  # NEGATIVE
            "score": 0.30,
            "p": 0.60,
            "coherence": 0.75,
            "auditor_factor": 0.85,
        }
        bucket, size_mult = _get_training_bucket(signal, {}, "REJECT_NEGATIVE_EV")
        # Should not route to discovery (idle=False), not to D_NEG (reject_reason is REJECT_NEGATIVE_EV),
        # not to probe (cold_start=False), so should be empty
        assert bucket == "", f"Expected empty bucket when not idle, got {bucket}"
        assert size_mult == 0.0

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
    def test_reject_negative_ev_routes_to_discovery_during_starvation(self, mock_idle, mock_training, clean_sampler_state):
        """REJECT_NEGATIVE_EV routes to PAPER_STARVATION_DISCOVERY when idle >= 600s."""
        signal = {
            "symbol": "ETHUSDT",
            "action": "SELL",
            "ev": -0.020,  # NEGATIVE
            "score": 0.25,
            "p": 0.50,
            "coherence": 0.65,
            "auditor_factor": 0.75,
        }
        bucket, size_mult = _get_training_bucket(signal, {}, "REJECT_NEGATIVE_EV")
        assert bucket == "PAPER_STARVATION_DISCOVERY", f"Expected PAPER_STARVATION_DISCOVERY, got {bucket}"
        assert size_mult == 0.02

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
    def test_positive_ev_still_uses_weak_ev_train_during_starvation(self, mock_idle, mock_training, clean_sampler_state):
        """Positive EV still routes to C_WEAK_EV_TRAIN, NOT discovery, even during starvation."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.010,  # POSITIVE
            "score": 0.20,
            "p": 0.55,
            "coherence": 0.70,
            "auditor_factor": 0.80,
        }
        with patch("src.services.paper_training_sampler._ALLOW_WEAK_EV", True):
            bucket, size_mult = _get_training_bucket(signal, {}, "REJECT_ECON_BAD")
            assert bucket == "C_WEAK_EV_TRAIN", f"Positive EV should use C_WEAK_EV_TRAIN, got {bucket}"


class TestStarvationDiscoveryCaps:
    """Test that discovery respects caps: max 2 global, max 1 per symbol, max 4 per 15min."""

    def test_global_cap_blocks_third_discovery_position(self, clean_sampler_state):
        """Cannot open 3rd discovery position when global cap is 2."""
        # Simulate 2 open discovery positions
        open_positions = [
            {"learning_source": "paper_starvation_discovery", "symbol": "BTCUSDT"},
            {"learning_source": "paper_starvation_discovery", "symbol": "ETHUSDT"},
        ]
        allowed, reason = _check_starvation_discovery_caps("XRPUSDT", open_positions)
        assert not allowed, "Should block 3rd global position"
        assert reason == "discovery_cap_global"

    def test_per_symbol_cap_blocks_second_discovery_position(self, clean_sampler_state):
        """Cannot open 2nd discovery position for same symbol when per-symbol cap is 1."""
        open_positions = [
            {"learning_source": "paper_starvation_discovery", "symbol": "BTCUSDT"},
        ]
        allowed, reason = _check_starvation_discovery_caps("BTCUSDT", open_positions)
        assert not allowed, "Should block 2nd position for same symbol"
        assert reason == "discovery_cap_per_symbol"

    def test_rate_cap_blocks_fifth_entry_per_15min(self, clean_sampler_state):
        """Cannot open 5th discovery entry within 15 minutes."""
        # Simulate 4 entries in the 15-min window
        now = time.time()
        for i in range(4):
            pts._starvation_discovery_state["entry_times_15m"].append(now - (i * 10))

        allowed, reason = _check_starvation_discovery_caps("BTCUSDT", [])
        assert not allowed, "Should block 5th entry in 15-min window"
        assert reason == "discovery_rate_cap_15m"


class TestStarvationDiscoveryMetadata:
    """Test that discovery outcomes have correct metadata labels."""

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
    @patch("src.services.paper_training_sampler._training_quality_gate")
    def test_discovery_metadata_in_result(self, mock_gate, mock_idle, mock_training, clean_sampler_state):
        """Result includes discovery metadata: learning_source, execution_truth_class, readiness_eligible."""
        mock_gate.return_value = {"allowed": True, "reason": "ok"}

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,
            "score": 0.30,
            "p": 0.60,
            "coherence": 0.75,
            "auditor_factor": 0.85,
        }

        result = maybe_open_training_sample(
            signal=signal,
            ctx={},
            reason="REJECT_NEGATIVE_EV",
            current_price=45000.00,
        )

        assert result.get("allowed"), "Should allow discovery admission"
        assert result.get("learning_source") == "paper_starvation_discovery"
        assert result.get("evaluation_role") == "DISCOVERY"
        assert result.get("execution_truth_class") == "LEGACY_SPOT_EXECUTION_UNVERIFIED"
        assert result.get("readiness_eligible") is False
        assert result.get("source_reject") == "REJECT_NEGATIVE_EV"


class TestDiscoveryDoesNotContaminateControl:
    """Test that discovery admission does NOT affect D_NEG_EV_CONTROL or readiness."""

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
    def test_discovery_separate_from_d_neg_control(self, mock_idle, mock_training, clean_sampler_state):
        """D_NEG_EV_CONTROL and PAPER_STARVATION_DISCOVERY are distinct buckets."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,
            "score": 0.30,
        }

        # Discovery bucket
        bucket, size = _get_training_bucket(signal, {}, "REJECT_NEGATIVE_EV")
        assert bucket == "PAPER_STARVATION_DISCOVERY"

        # D_NEG_EV_CONTROL should only appear via its own path
        bucket2, size2 = _get_training_bucket(signal, {}, "UNKNOWN")
        assert bucket2 == "D_NEG_EV_CONTROL" or bucket2 == ""  # Not discovery


class TestIdleTimeTracking:
    """Test idle time calculation and updates."""

    def test_idle_time_initialized_on_first_call(self, clean_sampler_state):
        """Idle time initializes to 0 on first call."""
        before_state = pts._starvation_discovery_state["last_eligible_entry_ts"]
        assert before_state == 0.0, "Should start at 0"

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            maybe_open_training_sample(
                signal=signal,
                ctx={},
                reason="REJECT_NEGATIVE_EV",
                current_price=45000.00,
            )

        # After first call, last_eligible_entry_ts should be set
        after_state = pts._starvation_discovery_state["last_eligible_entry_ts"]
        assert after_state > 0, "Should be initialized after call"

    def test_idle_seconds_updated_on_successful_entry(self, clean_sampler_state):
        """Idle seconds should reset to 0 after successful discovery entry."""
        # Start with idle time in past
        past_time = time.time() - 700  # 700 seconds ago
        _update_starvation_discovery_idle(past_time)
        assert pts._starvation_discovery_state["idle_s"] >= 700

        # Update to now
        _update_starvation_discovery_idle(time.time())
        assert pts._starvation_discovery_state["idle_s"] < 10  # Should be very recent

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    @patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
    @patch("src.services.paper_training_sampler._training_quality_gate")
    def test_is_starvation_discovery_idle_reflects_time(self, mock_gate, mock_idle, mock_training, clean_sampler_state):
        """_is_starvation_discovery_idle() returns True when idle >= 600s."""
        # Set last entry 700 seconds ago
        past_time = time.time() - 700
        pts._starvation_discovery_state["last_eligible_entry_ts"] = past_time

        # Direct check
        idle_check = _is_starvation_discovery_idle()
        assert idle_check is True, "Should be idle after 700 seconds"


class TestCounterTracking:
    """Test that discovery tracks valid negative candidates."""

    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
    def test_valid_negative_candidates_incremented_on_reject(self, mock_training, clean_sampler_state):
        """valid_negative_candidates counter increments for each REJECT_NEGATIVE_EV."""
        before = pts._starvation_discovery_state["valid_negative_candidates"]
        assert before == 0

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,
        }

        with patch("src.services.paper_training_sampler._is_training_enabled", return_value=True):
            maybe_open_training_sample(
                signal=signal,
                ctx={},
                reason="REJECT_NEGATIVE_EV",
                current_price=45000.00,
            )

        after = pts._starvation_discovery_state["valid_negative_candidates"]
        assert after > before, "Should increment valid_negative_candidates"


class TestRealPathNotTouched:
    """Test that discovery does not affect REAL/live trading."""

    @patch("src.core.runtime_mode.get_trading_mode")
    @patch("src.services.paper_training_sampler._is_training_enabled", return_value=False)
    def test_discovery_disabled_when_training_disabled(self, mock_training, mock_mode, clean_sampler_state):
        """Discovery does not activate if training is disabled (e.g., in REAL mode)."""
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.015,
        }

        result = maybe_open_training_sample(
            signal=signal,
            ctx={},
            reason="REJECT_NEGATIVE_EV",
            current_price=45000.00,
        )

        assert not result.get("allowed"), "Should not allow discovery when training disabled"
        assert result.get("reason") == "training_disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
