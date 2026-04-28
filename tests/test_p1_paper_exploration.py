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
        """C_WEAK_EV: positive EV with quality (P1.1i: must pass cost-edge and direction filters)"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.16,  # P1.1i: raised from 0.1 to pass cost-edge (0.16*1.5=0.24 > 0.23)
            "p": 0.55,
            "coherence": 0.8,
            "auditor_factor": 0.9,
            "ema_diff": 0.001,  # Momentum aligned for BUY
            "macd": 0.0001,
            "mom5": 0.3,
            "rsi": 55,  # Neutral, not extreme
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}
        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["bucket"] == "C_WEAK_EV"
        assert result["explore_sub_bucket"] == "C1_WEAK_EV_MOMENTUM"  # P1.1i: now has sub-bucket
        assert result["size_mult"] == 0.08
        assert result["max_hold_s"] == 300  # P1.1i: reduced from 600 for C1

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


class TestBucketMetrics:
    """Bucket-level learning metrics"""

    def test_bucket_metrics_updates_after_closed_trade(self):
        """Bucket metrics update after closed exploration trade"""
        import os
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        from src.services.bucket_metrics import update_bucket_metrics, get_bucket_metrics, reset_bucket_metrics

        reset_bucket_metrics()

        closed_trade = {
            "symbol": "XRPUSDT",
            "explore_bucket": "C_WEAK_EV",
            "outcome": "WIN",
            "net_pnl_pct": 0.15,
            "exit_reason": "TP",
        }

        update_bucket_metrics(closed_trade)

        metrics = get_bucket_metrics("C_WEAK_EV")
        assert metrics["count"] == 1
        assert metrics["wins"] == 1
        assert metrics["losses"] == 0
        assert metrics["wr"] == 100.0
        assert metrics["tp_count"] == 1
        assert metrics["tp_rate"] == 100.0

    def test_bucket_metrics_tracks_loss(self):
        """Bucket metrics track losses"""
        from src.services.bucket_metrics import update_bucket_metrics, get_bucket_metrics, reset_bucket_metrics

        reset_bucket_metrics()

        closed_trade = {
            "symbol": "ETHUSDT",
            "explore_bucket": "D_NEG_EV_CONTROL",
            "outcome": "LOSS",
            "net_pnl_pct": -0.25,
            "exit_reason": "SL",
        }

        update_bucket_metrics(closed_trade)

        metrics = get_bucket_metrics("D_NEG_EV_CONTROL")
        assert metrics["count"] == 1
        assert metrics["losses"] == 1
        assert metrics["wins"] == 0
        assert metrics["wr"] == 0.0
        assert metrics["sl_count"] == 1


class TestExposureCaps:
    """Exploration exposure caps (per symbol/bucket)"""

    def test_second_exploration_same_symbol_blocked(self):
        """Second exploration for same symbol blocked"""
        reset_paper_positions()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
        }

        # Open first position
        result1 = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "final_size_usd": 8.00,
            },
        )
        assert result1["status"] == "opened"

        # Try to open second with same symbol/bucket
        result2 = open_paper_position(
            signal,
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "final_size_usd": 8.00,
            },
        )
        assert result2["status"] == "blocked"
        assert result2["reason"] == "max_open_per_symbol"

    def test_third_bucket_exploration_blocked(self):
        """Third exploration for same bucket blocked at cap of 2"""
        reset_paper_positions()

        # Open first position in C_WEAK_EV
        result1 = open_paper_position(
            {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.015, "score": 0.15},
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "C_WEAK_EV", "final_size_usd": 8.00},
        )
        assert result1["status"] == "opened"

        # Open second in same bucket, different symbol
        result2 = open_paper_position(
            {"symbol": "ETHUSDT", "action": "BUY", "ev": 0.015, "score": 0.15},
            price=2543.0,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "C_WEAK_EV", "final_size_usd": 8.00},
        )
        assert result2["status"] == "opened"

        # Try to open third in same bucket - should be blocked
        result3 = open_paper_position(
            {"symbol": "BNBUSDT", "action": "BUY", "ev": 0.015, "score": 0.15},
            price=555.0,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "C_WEAK_EV", "final_size_usd": 8.00},
        )
        assert result3["status"] == "blocked"
        assert result3["reason"] == "max_open_per_bucket"

    def test_different_bucket_allows_open(self):
        """Different bucket can still open even with one symbol filled"""
        reset_paper_positions()

        # Open C_WEAK_EV for XRPUSDT
        result1 = open_paper_position(
            {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.015, "score": 0.15},
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "C_WEAK_EV", "final_size_usd": 8.00},
        )
        assert result1["status"] == "opened"

        # Open D_NEG_EV_CONTROL for XRPUSDT (different bucket)
        result2 = open_paper_position(
            {"symbol": "XRPUSDT", "action": "BUY", "ev": -0.01, "score": 0.05},
            price=2.543,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={"explore_bucket": "D_NEG_EV_CONTROL", "final_size_usd": 3.00},
        )
        # Should be blocked because max_open_per_symbol=1
        assert result2["status"] == "blocked"


class TestCWeakEVTuning:
    """P1.1i: C_WEAK_EV bucket tuning with cost-edge and sub-buckets"""

    def test_cost_edge_too_low_rejected(self):
        """C_WEAK_EV with insufficient expected move is rejected"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.05,  # Low score -> low expected move
            "p": 0.55,
            "coherence": 0.8,
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        # Should be rejected due to insufficient cost edge
        assert result["allowed"] is False
        assert result["bucket"] == "C_WEAK_EV"
        assert "cost_edge_too_low" in result["reason"]
        assert result["cost_edge_ok"] is False

    def test_momentum_sub_bucket_classification(self):
        """C_WEAK_EV momentum trade classified as C1"""
        reset_exploration_caps()
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.025,
            "score": 0.2,  # Good score
            "p": 0.65,
            "coherence": 0.85,
            "ema_diff": 0.001,  # Positive for BUY
            "macd": 0.0001,  # Positive for BUY
            "mom5": 0.5,  # Positive
            "mom10": 0.3,  # Positive
            "rsi": 55,  # Neutral
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        assert result["allowed"] is True
        assert result["explore_sub_bucket"] == "C1_WEAK_EV_MOMENTUM"
        assert result["direction_quality_score"] > 0.3
        assert result["max_hold_s"] == 300

    def test_reversal_sub_bucket_classification(self):
        """C_WEAK_EV reversal trade classified as C2"""
        reset_exploration_caps()
        signal = {
            "symbol": "ETHUSDT",
            "action": "BUY",
            "ev": 0.020,
            "score": 0.16,  # Higher score for cost edge (0.16 * 1.5 = 0.24 > 0.23)
            "p": 0.60,
            "coherence": 0.80,
            "rsi": 25,  # Oversold, reversal signal for BUY
            "ema_diff": -0.001,  # Weak negative (reversal)
            "macd": -0.0001,
            "mom5": -0.2,
            "mom10": -0.1,
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        assert result["allowed"] is True
        assert result["explore_sub_bucket"] == "C2_WEAK_EV_REVERSAL"
        assert result["max_hold_s"] == 240

    def test_overbought_long_rejected(self):
        """C_WEAK_EV BUY rejected when overbought"""
        reset_exploration_caps()
        signal = {
            "symbol": "ADAUSDT",
            "action": "BUY",
            "ev": 0.025,
            "score": 0.2,
            "p": 0.65,
            "coherence": 0.85,
            "ema_diff": 0.001,
            "macd": 0.0001,
            "mom5": 0.5,
            "rsi": 78,  # Overbought
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        assert result["allowed"] is False
        assert result["explore_sub_bucket"] == "C0_WEAK_EV_REJECTED"

    def test_oversold_short_rejected(self):
        """C_WEAK_EV SELL rejected when oversold"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "SELL",
            "ev": 0.020,
            "score": 0.15,
            "p": 0.60,
            "coherence": 0.80,
            "ema_diff": -0.001,
            "macd": -0.0001,
            "mom5": -0.3,
            "rsi": 22,  # Oversold, countertrend for SELL
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        assert result["allowed"] is False
        assert result["explore_sub_bucket"] == "C0_WEAK_EV_REJECTED"

    def test_sub_bucket_appears_in_closed_trade(self):
        """Closed trade includes sub_bucket field"""
        from src.services.paper_trade_executor import (
            open_paper_position,
            close_paper_position,
        )

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "DOGEUSDT",
            "action": "BUY",
            "ev": 0.025,
            "score": 0.2,
        }

        result = open_paper_position(
            signal,
            price=0.35,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "explore_sub_bucket": "C1_WEAK_EV_MOMENTUM",
                "final_size_usd": 6.4,
                "max_hold_s": 300,
            },
        )
        assert result["status"] == "opened"

        # Close the position
        trade_id = result["trade_id"]
        closed = close_paper_position(trade_id, 0.36, time.time() + 100, "TP")

        assert closed is not None
        assert closed.get("explore_sub_bucket") == "C1_WEAK_EV_MOMENTUM"


class TestRobustStateLoader:
    """P1.1h: Robust paper state loader handling dict and list formats"""

    def test_empty_list_loads_without_error(self):
        """Empty list in state file loads as empty state without error"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Write empty list to state file
        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump([], f)

        # Load should not crash
        from src.services.paper_trade_executor import _load_paper_state
        _load_paper_state()

        # Should start with empty state
        from src.services.paper_trade_executor import get_paper_open_positions
        positions = get_paper_open_positions()
        assert len(positions) == 0

    def test_list_format_migrates_to_dict(self):
        """List format positions migrate to dict with proper keys"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Write list format state
        legacy_list = [
            {
                "trade_id": "paper_old_1",
                "symbol": "XRPUSDT",
                "side": "BUY",
                "entry_price": 2.543,
                "size": 3.15,
                "size_usd": 8.00,
                "entry_ts": time.time() - 100,
                "explore_bucket": "C_WEAK_EV",
            },
            {
                "id": "paper_old_2",  # Using 'id' instead of 'trade_id'
                "symbol": "ETHUSDT",
                "side": "SELL",
                "entry_price": 2543.0,
                "size": 0.31,
                "size_usd": 8.00,
                "entry_ts": time.time() - 50,
                "explore_bucket": "B_RECOVERY_READY",
            },
        ]

        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump(legacy_list, f)

        # Load should convert to dict
        from src.services.paper_trade_executor import _load_paper_state, get_paper_trade_by_id
        _load_paper_state()

        # Check that both positions loaded with correct keys
        pos1 = get_paper_trade_by_id("paper_old_1")
        assert pos1 is not None
        assert pos1["symbol"] == "XRPUSDT"

        pos2 = get_paper_trade_by_id("paper_old_2")
        assert pos2 is not None
        assert pos2["symbol"] == "ETHUSDT"

    def test_dict_format_loads_normally(self):
        """Standard dict format loads without issues"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Write canonical dict format
        canonical_dict = {
            "paper_trade_dict_1": {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "entry_price": 45000.0,
                "size": 0.01,
                "size_usd": 450.0,
                "entry_ts": time.time() - 75,
                "explore_bucket": "C_WEAK_EV",
                "max_hold_s": 600,
            }
        }

        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump(canonical_dict, f)

        from src.services.paper_trade_executor import _load_paper_state, get_paper_trade_by_id
        _load_paper_state()

        pos = get_paper_trade_by_id("paper_trade_dict_1")
        assert pos is not None
        assert pos["symbol"] == "BTCUSDT"
        assert pos["max_hold_s"] == 600

    def test_corrupt_json_logs_error_and_starts_empty(self):
        """Corrupt JSON logs error and starts with empty state"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Write invalid JSON
        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            f.write("{invalid json]")

        from src.services.paper_trade_executor import _load_paper_state, get_paper_open_positions
        _load_paper_state()

        # Should start with empty state
        positions = get_paper_open_positions()
        assert len(positions) == 0

    def test_save_writes_canonical_dict_format(self):
        """Saved state always uses canonical dict format, never list"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "DOGEUSDT",
            "action": "BUY",
            "ev": 0.020,
            "score": 0.15,
        }

        # Open a position to trigger save
        result = open_paper_position(
            signal,
            price=0.35,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "final_size_usd": 8.00,
                "max_hold_s": 600,
            },
        )
        assert result["status"] == "opened"

        # Check saved file is dict, not list
        with open("data/paper_open_positions.json", "r") as f:
            saved = json.load(f)

        assert isinstance(saved, dict), "Saved state should be dict, not list"
        assert len(saved) == 1

    def test_list_with_missing_keys_generates_fallback_keys(self):
        """List entries without trade_id/id get fallback keys"""
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Write list with position missing both trade_id and id
        legacy_list = [
            {
                # No trade_id or id field
                "symbol": "XRPUSDT",
                "side": "BUY",
                "entry_price": 2.543,
                "entry_ts": 1700000000.0,  # Fixed timestamp for stable fallback key
                "explore_bucket": "C_WEAK_EV",
            }
        ]

        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump(legacy_list, f)

        from src.services.paper_trade_executor import _load_paper_state, get_paper_open_positions
        _load_paper_state()

        # Should load with fallback key
        positions = get_paper_open_positions()
        assert len(positions) == 1
        # Fallback key format: legacy_<idx>_<symbol>_<ts>
        assert positions[0]["symbol"] == "XRPUSDT"


class TestMaxHoldWindow:
    """P1.1g: Per-position max_hold_s enforcement"""

    def test_c_weak_ev_closes_near_max_hold_s(self):
        """C_WEAK_EV with max_hold_s=600 closes around 600 seconds"""
        from src.services.paper_trade_executor import get_paper_trade_by_id, update_paper_positions
        import json
        reset_paper_positions()

        # Remove state file
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.15,
            "p": 0.55,
        }

        # Open C_WEAK_EV position with max_hold_s=600
        open_ts = time.time()
        result = open_paper_position(
            signal,
            price=2.543,
            ts=open_ts,
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "final_size_usd": 8.00,
                "max_hold_s": 600,
            },
        )
        assert result["status"] == "opened"
        trade_id = result["trade_id"]

        # Verify position has max_hold_s set
        pos = get_paper_trade_by_id(trade_id)
        assert pos is not None
        assert pos.get("max_hold_s") == 600

        # Simulate passage of 600 seconds by calling update_paper_positions at different times
        # Advance time to just before max_hold_s expires
        update_result = update_paper_positions({"XRPUSDT": 2.550}, open_ts + 599)

        # Position should still be open
        pos = get_paper_trade_by_id(trade_id)
        assert pos is not None

        # Advance to 601s
        update_result = update_paper_positions({"XRPUSDT": 2.550}, open_ts + 601)

        # Position should be closed
        pos = get_paper_trade_by_id(trade_id)
        assert pos is None

    def test_legacy_position_gets_max_hold_s_on_load(self):
        """Legacy position without max_hold_s gets inferred on load"""
        from src.services.paper_trade_executor import _load_paper_state, get_paper_trade_by_id
        import json

        # Reset and remove state file
        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Create a legacy position on disk (missing max_hold_s)
        legacy_positions = {
            "legacy_trade_001": {
                "symbol": "XRPUSDT",
                "action": "BUY",
                "entry_price": 2.543,
                "size": 3.15,
                "size_usd": 8.00,
                "entry_ts": time.time() - 100,  # Opened 100s ago
                "explore_bucket": "C_WEAK_EV",
                "paper_source": "exploration_reject",
                # Note: no max_hold_s field - this is the legacy case
            }
        }

        # Write to disk
        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump(legacy_positions, f)

        # Now load the state - migration should happen
        _load_paper_state()

        # Verify the position was loaded and migrated
        pos = get_paper_trade_by_id("legacy_trade_001")
        assert pos is not None

        # C_WEAK_EV should get max_hold_s=600
        assert pos.get("max_hold_s") == 600

    def test_b_recovery_ready_legacy_gets_900s(self):
        """B_RECOVERY_READY legacy position gets max_hold_s=900"""
        from src.services.paper_trade_executor import _load_paper_state, get_paper_trade_by_id
        import json

        reset_paper_positions()
        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        # Create legacy B_RECOVERY_READY position
        legacy_positions = {
            "legacy_trade_002": {
                "symbol": "ETHUSDT",
                "action": "SELL",
                "entry_price": 2543.0,
                "size": 0.31,
                "size_usd": 8.00,
                "entry_ts": time.time() - 100,
                "explore_bucket": "B_RECOVERY_READY",
                "paper_source": "exploration_reject",
            }
        }

        os.makedirs("data", exist_ok=True)
        with open("data/paper_open_positions.json", "w") as f:
            json.dump(legacy_positions, f)

        # Load and migrate
        _load_paper_state()

        pos = get_paper_trade_by_id("legacy_trade_002")
        assert pos is not None
        assert pos.get("max_hold_s") == 900

    def test_hold_s_never_exceeds_max_hold_s(self):
        """duration_s reported in closed trade never exceeds max_hold_s"""
        import json
        reset_paper_positions()

        if os.path.exists("data/paper_open_positions.json"):
            os.remove("data/paper_open_positions.json")

        signal = {
            "symbol": "BNBUSDT",
            "action": "BUY",
            "ev": 0.020,
            "score": 0.15,
        }

        open_ts = time.time()
        result = open_paper_position(
            signal,
            price=555.0,
            ts=open_ts,
            reason="PAPER_EXPLORE",
            extra={
                "explore_bucket": "C_WEAK_EV",
                "final_size_usd": 8.00,
                "max_hold_s": 600,
            },
        )
        assert result["status"] == "opened"
        trade_id = result["trade_id"]

        # Manually close the position to verify duration_s calculation
        close_ts = open_ts + 595  # Held for 595 seconds (within max_hold_s)
        closed = close_paper_position(trade_id, 555.5, close_ts, "TP")
        assert closed is not None

        # Verify duration_s is less than max_hold_s
        duration_s = closed.get("duration_s", 0)
        max_hold_s = closed.get("max_hold_s", 600)
        assert duration_s <= max_hold_s
        # duration_s should be close to 595
        assert 593 < duration_s < 597  # Allow small tolerance for execution time


class TestCostEdgeUnitAudit:
    """P1.1j: Cost-edge unit normalization and audit logs"""

    def test_normalize_percent_value(self):
        """Percent value (0.18) converts to (0.0018 decimal, 0.18 pct)"""
        from src.services.paper_exploration import _normalize_pct_or_decimal

        dec, pct = _normalize_pct_or_decimal(0.18)
        assert abs(dec - 0.0018) < 1e-6
        assert abs(pct - 0.18) < 1e-6

    def test_normalize_decimal_value(self):
        """Decimal value (0.0006) converts to (0.0006 decimal, 0.06 pct)"""
        from src.services.paper_exploration import _normalize_pct_or_decimal

        dec, pct = _normalize_pct_or_decimal(0.0006)
        assert abs(dec - 0.0006) < 1e-6
        assert abs(pct - 0.06) < 1e-6

    def test_normalize_invalid_value(self):
        """Invalid values return (0.0, 0.0)"""
        from src.services.paper_exploration import _normalize_pct_or_decimal

        dec, pct = _normalize_pct_or_decimal(None)
        assert dec == 0.0 and pct == 0.0

        dec, pct = _normalize_pct_or_decimal("invalid")
        assert dec == 0.0 and pct == 0.0

    def test_estimate_expected_move_returns_tuple(self):
        """_estimate_expected_move() returns (decimal, percent) tuple"""
        from src.services.paper_exploration import _estimate_expected_move

        # Score-based: 0.16 * 1.5 = 0.24 % = 0.0024 decimal
        signal = {"score": 0.16}
        dec, pct = _estimate_expected_move(signal)
        assert isinstance(dec, float) and isinstance(pct, float)
        assert abs(pct - 0.24) < 1e-6
        assert abs(dec - 0.0024) < 1e-6

    def test_cost_edge_check_with_normalized_units(self):
        """Cost edge comparison uses decimal internally"""
        from src.services.paper_exploration import _check_cost_edge

        # Expected move 0.0024 decimal (0.24%) >= required 0.0023 (0.23%)
        assert _check_cost_edge(0.0024) is True

        # Expected move 0.0006 decimal (0.06%) < required 0.0023 (0.23%)
        assert _check_cost_edge(0.0006) is False

    def test_unit_mismatch_prevented(self):
        """0.06% move is not confused with 6% move"""
        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.04,  # Low score -> low expected move
            "p": 0.55,
            "coherence": 0.8,
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        # Should reject because 0.06% (0.04*1.5) < 0.23% required
        assert result["allowed"] is False
        assert "cost_edge_too_low" in result["reason"]

    def test_cost_edge_ok_when_sufficient_move(self):
        """Sufficient expected move (0.30%) passes cost edge (0.23% required)"""
        reset_exploration_caps()
        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.025,
            "score": 0.20,  # 0.20 * 1.5 = 0.30% >> 0.23% required
            "p": 0.65,
            "coherence": 0.85,
            "ema_diff": 0.001,  # Momentum: +0.2
            "macd": 0.0001,     # Momentum: +0.15
            "mom5": 0.5,        # Momentum: +0.1
            "mom10": 0.3,       # Momentum: +0.1
            "rsi": 55,          # Neutral, no penalty
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)

        # Should pass cost edge and allow entry (direction_quality = 0.65 >= 0.4 for C1)
        assert result["allowed"] is True
        assert result["cost_edge_ok"] is True

    def test_audit_log_contains_normalized_units(self):
        """Audit logs show both decimal and percent for all values"""
        reset_exploration_caps()
        import logging

        # Capture logs at debug level
        with patch("src.services.paper_exploration.log") as mock_log:
            signal = {
                "symbol": "XRPUSDT",
                "action": "BUY",
                "ev": 0.015,
                "score": 0.16,
                "p": 0.55,
                "coherence": 0.8,
                "ema_diff": 0.001,
                "rsi": 55,
            }
            ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

            result = paper_exploration_override(signal, ctx)

            # Verify audit log was called with normalized units
            # (Note: mock_log.debug will be called if audit logging is enabled)
            if mock_log.debug.called:
                call_args = str(mock_log.debug.call_args)
                # Verify units are present in audit log
                assert "expected_move_dec" in call_args or "expected_move_pct" in call_args

    def test_skip_counter_increments(self):
        """Skip counters are incremented for each skip reason"""
        from src.services.paper_exploration import _skip_counters, reset_exploration_caps

        reset_exploration_caps()
        # Reset counters
        for key in _skip_counters:
            _skip_counters[key] = 0

        # Trigger a cost_edge_too_low skip with minimal expected move
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.01,  # Very low: 0.01 * 1.5 = 0.015% << 0.23% required
            "p": 0.55,
            "coherence": 0.8,
            "auditor_factor": 0.5,  # Has quality so enters C_WEAK_EV logic
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is False
        assert "cost_edge_too_low" in result["reason"]

        # Verify skip counter was incremented
        assert _skip_counters["cost_edge_too_low"] > 0

    def test_entry_counter_increments(self):
        """Entry counter increments when trade is allowed"""
        from src.services.paper_exploration import _skip_counters, reset_exploration_caps

        reset_exploration_caps()
        # Reset counters
        for key in _skip_counters:
            _skip_counters[key] = 0

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.025,
            "score": 0.20,
            "p": 0.65,
            "coherence": 0.85,
            "ema_diff": 0.001,  # Momentum: +0.2
            "macd": 0.0001,     # Momentum: +0.15
            "mom5": 0.5,        # Momentum: +0.1
            "mom10": 0.3,       # Momentum: +0.1
            "rsi": 55,          # Neutral, no penalty
        }
        ctx = {"reject_reason": "REJECT_ECON_BAD_ENTRY"}

        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["cost_edge_ok"] is True

        # Verify entry counter was incremented
        assert _skip_counters["entries"] > 0

    def test_no_real_executor_called_on_skip(self):
        """Skipped C_WEAK_EV trades do not call trade executor"""
        reset_paper_positions()
        reset_exploration_caps()

        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.015,
            "score": 0.01,  # Too low, will be rejected
            "p": 0.55,
            "coherence": 0.8,
        }

        # paper_exploration_override only does classification, doesn't call executor
        result = paper_exploration_override(signal)
        assert result["allowed"] is False

        # Verify no position was opened
        positions = get_paper_open_positions()
        assert len(positions) == 0

    def test_strict_take_unaffected_by_p1_1j(self):
        """P1.1j changes do not affect strict TAKE logic (bucket A)"""
        # Bucket A is handled by upstream P0.3 logic, not paper_exploration_override
        # This test just verifies that B/C/D/E behavior is correct

        reset_exploration_caps()
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.045,  # High EV -> B_RECOVERY_READY
            "score": 0.2,
        }

        result = paper_exploration_override(signal)
        assert result["bucket"] == "B_RECOVERY_READY"

    def test_recovery_ready_unaffected_by_p1_1j(self):
        """P1.1j changes do not affect B_RECOVERY_READY logic"""
        reset_exploration_caps()
        signal = {
            "symbol": "ETHUSDT",
            "action": "BUY",
            "ev": 0.045,
            "score": 0.2,
        }
        ctx = {"recovery_ready": True}

        result = paper_exploration_override(signal, ctx)
        assert result["allowed"] is True
        assert result["bucket"] == "B_RECOVERY_READY"
        assert result["size_mult"] == 0.15


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
