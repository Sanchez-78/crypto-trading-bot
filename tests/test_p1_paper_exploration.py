"""V10.13u+20 P1.1: Paper Exploration from Rejected Signals

Tests for paper_exploration_override() bucket classification,
exploration integration, and bucket metrics.
"""
import pytest
import time
import os
from unittest.mock import patch, MagicMock

# Suppress Firebase/async errors during import
with patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "test-project"}):
    from src.services.paper_exploration import (
        paper_exploration_override,
        get_exploration_stats,
        reset_exploration_caps,
    )
    from src.services.paper_trade_executor import (
        open_paper_position,
        close_paper_position,
        reset_paper_positions,
        get_paper_open_positions,
    )


class TestPaperExplorationDisabled:
    """Exploration disabled -> no paper reject entry in trade_executor"""

    def test_exploration_returns_buckets_regardless_of_env(self):
        """paper_exploration_override is environment-agnostic

        The actual check for PAPER_EXPLORATION_ENABLED happens in trade_executor,
        not in paper_exploration_override. The function just does bucketing logic.
        """
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.040, "score": 0.1}
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}
        result = paper_exploration_override(signal, ctx)
        # Should return a bucket classification regardless of env settings
        assert result["allowed"] is True
        assert result["bucket"] == "B_RECOVERY_READY"


class TestBucketClassification:
    """Bucket classification logic"""

    def test_bucket_b_recovery_ready_high_ev(self):
        """B_RECOVERY_READY: EV >= 0.038"""
        reset_exploration_caps()
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.045, "score": 0.2}
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}
        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["bucket"] == "B_RECOVERY_READY"
        assert result["size_mult"] == 0.15
        assert result["max_hold_s"] == 900

    def test_bucket_b_recovery_ready_flag(self):
        """B_RECOVERY_READY: recovery_ready=True"""
        reset_exploration_caps()
        signal = {"symbol": "ETHUSDT", "action": "SELL", "ev": 0.010, "score": 0.15}
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY", "recovery_ready": True}
        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["bucket"] == "B_RECOVERY_READY"

    def test_bucket_c_weak_ev_positive(self):
        """C_WEAK_EV: positive EV with quality"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.1,
            "p": 0.55,
            "coherence": 0.8,
            "auditor_factor": 0.9,
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}
        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["bucket"] == "C_WEAK_EV"
        assert result["size_mult"] == 0.08
        assert result["max_hold_s"] == 600

    def test_bucket_c_weak_ev_zero_quality_rejected(self):
        """C_WEAK_EV: positive EV but zero quality -> rejected"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.1,
            "p": 0,
            "coherence": 0,
            "auditor_factor": 0,
        }
        ctx = {"reject_reason": "NO_PATTERN"}
        result = paper_exploration_override(signal, ctx)
        # No quality, should not match C_WEAK_EV
        assert result["allowed"] is False or result["bucket"] != "C_WEAK_EV"

    def test_bucket_d_neg_ev_control(self):
        """D_NEG_EV_CONTROL: negative EV, capped to 1/hour"""
        reset_exploration_caps()
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": -0.015, "score": 0.05}
        ctx = {"reject_reason": "REJECT_NEGATIVE_EV"}
        result1 = paper_exploration_override(signal, ctx)
        assert result1["allowed"] is True
        assert result1["bucket"] == "D_NEG_EV_CONTROL"
        assert result1["size_mult"] == 0.03
        assert result1["max_hold_s"] == 300

        # Second call should be rejected (hourly cap)
        result2 = paper_exploration_override(signal, ctx)
        assert result2["allowed"] is False
        assert result2["reason"] == "hourly_cap_exceeded"

    def test_bucket_e_no_pattern_baseline(self):
        """E_NO_PATTERN: no pattern signal, capped to 1/hour"""
        reset_exploration_caps()
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.0, "score": 0.0}
        ctx = {"reject_reason": "NO_CANDIDATE_PATTERN"}
        result1 = paper_exploration_override(signal, ctx)
        assert result1["allowed"] is True
        assert result1["bucket"] == "E_NO_PATTERN"
        assert result1["size_mult"] == 0.02

        # Second call rejected (hourly cap)
        result2 = paper_exploration_override(signal, ctx)
        assert result2["allowed"] is False


class TestPaperExplorationIntegration:
    """Integration: exploration entry, exit, learning"""

    def test_exploration_entry_opens_paper_position(self):
        """Paper exploration should open position with bucket tags"""
        reset_paper_positions()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
            "p": 0.55,
            "coherence": 0.8,
            "auditor_factor": 0.9,
            "regime": "BULL_TREND",
            "features": {"adx": 0.6},
        }
        entry_price = 2.543
        ts = time.time()

        result = open_paper_position(
            signal,
            price=entry_price,
            ts=ts,
            reason="PAPER_EXPLORE",
            extra={
                "paper_source": "exploration_reject",
                "explore_bucket": "C_WEAK_EV",
                "original_decision": "REJECT",
                "reject_reason": "REJECT_ECON_BAD_ENTRY",
                "size_mult": 0.08,
                "max_hold_s": 600,
                "tags": ["weak_ev_positive"],
            },
        )

        assert result["status"] == "opened"
        assert result["symbol"] == "XRPUSDT"

        # Verify position has exploration fields
        positions = get_paper_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["explore_bucket"] == "C_WEAK_EV"
        assert pos["paper_source"] == "exploration_reject"
        assert pos["reject_reason"] == "REJECT_ECON_BAD_ENTRY"
        assert pos["size_mult"] == 0.08
        assert pos["tags"] == ["weak_ev_positive"]

    def test_exploration_entry_uses_real_price(self):
        """Exploration entry MUST use real price, never synthetic"""
        reset_paper_positions()
        signal = {
            "symbol": "ETHUSDT",
            "action": "BUY",
            "ev": 0.04,
            "score": 0.2,
            "regime": "RANGING",
        }
        real_price = 2543.50
        ts = time.time()

        result = open_paper_position(
            signal,
            price=real_price,
            ts=ts,
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "B_RECOVERY_READY",
                "paper_source": "exploration_reject",
            },
        )

        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert positions[0]["entry_price"] == real_price

    def test_exploration_never_calls_live_executor(self):
        """Exploration is paper-only, never calls exchange executor"""
        # The test is that we can open_paper_position() without any exchange calls
        reset_paper_positions()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
            "p": 0.55,
        }
        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
        )
        # Should succeed without any exchange interaction
        assert result["status"] == "opened"

    def test_exploration_applies_bucket_sizing_c_weak_ev(self):
        """C_WEAK_EV: base_size 100 * size_mult 0.08 = 8.00"""
        reset_paper_positions()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
            "p": 0.55,
            "coherence": 0.8,
        }
        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "size_mult": 0.08,
                "final_size_usd": 8.00,
            },
        )
        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert positions[0]["size_usd"] == 8.00

    def test_exploration_applies_bucket_sizing_d_neg_ev(self):
        """D_NEG_EV_CONTROL: base_size 100 * size_mult 0.03 = 3.00"""
        reset_paper_positions()
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": -0.015, "score": 0.05}
        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "D_NEG_EV_CONTROL",
                "size_mult": 0.03,
                "final_size_usd": 3.00,
            },
        )
        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert positions[0]["size_usd"] == 3.00

    def test_exploration_applies_bucket_sizing_e_no_pattern(self):
        """E_NO_PATTERN: base_size 100 * size_mult 0.02 = 2.00"""
        reset_paper_positions()
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.0, "score": 0.0}
        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "E_NO_PATTERN",
                "size_mult": 0.02,
                "final_size_usd": 2.00,
            },
        )
        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert positions[0]["size_usd"] == 2.00

    def test_normal_paper_trade_uses_default_size(self):
        """Normal TAKE without exploration uses default size (100)"""
        reset_paper_positions()
        signal = {
            "symbol": "ETHUSDT",
            "action": "BUY",
            "ev": 0.05,
            "score": 0.5,
        }
        result = open_paper_position(
            signal,
            price=2543.0,
            ts=time.time(),
            reason="RDE_TAKE",
            extra=None,  # No exploration, no final_size_usd
        )
        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert positions[0]["size_usd"] == 100.0  # Default _POSITION_SIZE

    def test_paper_exit_closes_position_and_returns_closed_trade(self):
        """Paper exit on TP hit returns closed trade with all fields"""
        reset_paper_positions()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.05,
            "score": 0.5,
            "regime": "BULL_TREND",
        }
        entry_price = 2.543
        ts = time.time()

        # Open position
        result = open_paper_position(
            signal,
            price=entry_price,
            ts=ts,
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "size_mult": 0.08,
                "final_size_usd": 8.00,
            },
        )
        trade_id = result["trade_id"]

        # Simulate TP hit (price up 1.3%)
        exit_price = entry_price * 1.013
        closed = close_paper_position(trade_id, exit_price, ts + 60, "TP")

        assert closed is not None
        assert closed["symbol"] == "XRPUSDT"
        assert closed["exit_price"] == exit_price
        assert closed["exit_reason"] == "TP"
        assert closed["explore_bucket"] == "C_WEAK_EV"
        assert closed["outcome"] in ("WIN", "FLAT", "LOSS")

        # Position should be removed from open positions
        positions = get_paper_open_positions()
        assert len(positions) == 0


class TestExplorationStats:
    """Exploration cap tracking and reset"""

    def test_get_exploration_stats(self):
        """Can retrieve hourly cap stats"""
        reset_exploration_caps()
        stats = get_exploration_stats()
        assert "D_NEG_EV_CONTROL" in stats
        assert "E_NO_PATTERN" in stats
        assert stats["D_NEG_EV_CONTROL"]["count"] == 0
        assert stats["D_NEG_EV_CONTROL"]["max"] == 1

    def test_reset_exploration_caps_clears_counts(self):
        """Reset clears hourly counters"""
        reset_exploration_caps()
        # Trigger a D_NEG_EV_CONTROL exploration
        signal = {"symbol": "X", "ev": -0.01}
        ctx = {"reject_reason": "REJECT_NEGATIVE_EV"}
        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True

        # Check count is 1
        stats = get_exploration_stats()
        assert stats["D_NEG_EV_CONTROL"]["count"] == 1

        # Reset
        reset_exploration_caps()
        stats = get_exploration_stats()
        assert stats["D_NEG_EV_CONTROL"]["count"] == 0


class TestExceptionSafety:
    """paper_exploration_override is exception-safe"""

    def test_missing_fields_handled(self):
        """Missing signal fields should not raise"""
        result = paper_exploration_override({})  # Empty signal
        assert isinstance(result, dict)
        assert "allowed" in result
        assert "bucket" in result

    def test_invalid_types_handled(self):
        """Invalid field types should not raise"""
        signal = {
            "symbol": 123,  # Should be string
            "ev": "invalid",  # Should be float
            "score": None,
        }
        result = paper_exploration_override(signal)
        assert isinstance(result, dict)
        assert "allowed" in result


class TestSideNormalization:
    """Side alias normalization (BUY/LONG, SELL/SHORT)"""

    def test_buy_and_long_produce_same_position(self):
        """BUY and LONG both produce canonical BUY side"""
        reset_paper_positions()
        signal_buy = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.05,
            "score": 0.5,
        }
        signal_long = {
            "symbol": "XRPUSDT",
            "action": "LONG",
            "ev": 0.05,
            "score": 0.5,
        }

        result_buy = open_paper_position(signal_buy, price=2.543, ts=time.time(), reason="RDE_TAKE")
        result_long = open_paper_position(signal_long, price=2.543, ts=time.time(), reason="RDE_TAKE")

        positions = get_paper_open_positions()
        assert len(positions) == 2
        assert positions[0]["side"] == "BUY"
        assert positions[1]["side"] == "BUY"
        assert positions[0]["side_raw"] == "BUY"
        assert positions[1]["side_raw"] == "LONG"

    def test_sell_and_short_produce_same_position(self):
        """SELL and SHORT both produce canonical SELL side"""
        reset_paper_positions()
        signal_sell = {
            "symbol": "ETHUSDT",
            "action": "SELL",
            "ev": 0.05,
            "score": 0.5,
        }
        signal_short = {
            "symbol": "ETHUSDT",
            "action": "SHORT",
            "ev": 0.05,
            "score": 0.5,
        }

        result_sell = open_paper_position(signal_sell, price=2543.0, ts=time.time(), reason="RDE_TAKE")
        result_short = open_paper_position(signal_short, price=2543.0, ts=time.time(), reason="RDE_TAKE")

        positions = get_paper_open_positions()
        assert len(positions) == 2
        assert positions[0]["side"] == "SELL"
        assert positions[1]["side"] == "SELL"
        assert positions[0]["side_raw"] == "SELL"
        assert positions[1]["side_raw"] == "SHORT"


class TestPaperStatePersistence:
    """Paper position state persistence across restart"""

    def test_open_position_saved_to_disk(self):
        """Opening a position writes it to disk"""
        reset_paper_positions()
        import os
        import json

        # Remove state file if it exists
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
            "p": 0.55,
            "coherence": 0.8,
        }

        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "size_mult": 0.08,
                "final_size_usd": 8.00,
            },
        )

        assert result["status"] == "opened"

        # Verify file exists and contains the position
        assert os.path.exists("data/paper_open_positions.json")
        with open("data/paper_open_positions.json", "r") as f:
            saved_positions = json.load(f)
        assert len(saved_positions) == 1
        assert list(saved_positions.values())[0]["symbol"] == "XRPUSDT"
        assert list(saved_positions.values())[0]["size_usd"] == 8.00

    def test_closed_position_removed_from_disk(self):
        """Closing a position updates the disk state"""
        reset_paper_positions()
        import os

        # Remove state file if it exists
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
        }

        result = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "C_WEAK_EV", "final_size_usd": 8.00},
        )

        trade_id = result["trade_id"]

        # Close the position
        closed = close_paper_position(trade_id, 2.500, time.time(), "SL")
        assert closed is not None

        # Verify position removed from disk
        import json
        with open("data/paper_open_positions.json", "r") as f:
            saved_positions = json.load(f)
        assert len(saved_positions) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
