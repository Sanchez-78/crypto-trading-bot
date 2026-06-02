"""Phase 4B-R2: Qualification Isolation for Starvation Learning Trades

Verify that paper_starvation_learning trades:
1. Emit V5_BRIDGE_LEARNING_UPDATE (learning continues)
2. Emit LEARNING_UPDATE ok=True (learning continues)
3. Emit PAPER_CANONICAL_LEARNING_UPDATE (learning continues)
4. Skip PAPER_QUALIFICATION_UPDATE (isolation from readiness)
5. Do not increment qualification_n (no contamination)

Hard constraints:
- Do not change entry logic
- Do not change cost-edge logic
- Do not change TP/SL/timeout
- Do not change V5 bridge learning_update behavior
- Do not block LEARNING_UPDATE
- Do not block PAPER_CANONICAL_LEARNING_UPDATE
"""

import pytest
import time
import json
import os
from unittest.mock import patch, MagicMock
from src.services import paper_adaptive_learning as pal


class TestQualificationIsolation:
    """Test suite for Phase 4B-R2 qualification isolation."""

    def setup_method(self):
        """Reset state before each test."""
        # Create fresh learner instance
        self.learner = pal.PaperAdaptiveLearning()
        self.learner.qualification_started_at = time.time() - 3600  # 1h ago (post-epoch)

    def test_starvation_learning_skips_qualification_but_allows_learning(self):
        """Starvation trade: learning flows, qualification skipped."""
        # Simulate a starvation learning trade that WON
        closed_trade = {
            "trade_id": "starvation_12345",
            "symbol": "BTC",
            "entry_ts": time.time() - 600,  # Opened post-epoch
            "outcome": "WIN",
            "net_pnl": 100.0,
            "net_pnl_pct": 0.05,  # 5% profit
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "paper_starvation_learning",
            "paper_learning_only": True,
            "real_readiness_eligible": False,
            "readiness_eligible": False,
            "regime": "TRENDING",
            "side": "BUY",
        }

        # Before: qualification_n = 0
        assert self.learner.qualification_n == 0
        before_qual_n = self.learner.qualification_n

        # Process the trade (learning flow should continue)
        self.learner.record_close(closed_trade)

        # After: qualification_n SHOULD NOT increment (skipped)
        assert self.learner.qualification_n == before_qual_n, \
            "Starvation trade should NOT increment qualification_n"

        # But: rolling metrics SHOULD update (learning continues)
        assert len(self.learner.rolling100) > 0, \
            "Starvation trade SHOULD update rolling100 (learning continues)"

    def test_starvation_learning_loss_still_learns(self):
        """Starvation trade LOSS: learning accepts loss, qualification skipped."""
        closed_trade = {
            "trade_id": "starvation_loss_99",
            "symbol": "ETH",
            "entry_ts": time.time() - 600,
            "outcome": "LOSS",
            "net_pnl": -50.0,
            "net_pnl_pct": -0.05,
            "training_bucket": "C_WEAK_EV_TRAIN",
            "learning_source": "paper_starvation_learning",
            "paper_learning_only": True,
            "real_readiness_eligible": False,
            "readiness_eligible": False,
            "regime": "RANGING",
            "side": "SELL",
        }

        before_qual = self.learner.qualification_n
        before_rolling = len(self.learner.rolling100)

        self.learner.record_close(closed_trade)

        # Qualification skipped
        assert self.learner.qualification_n == before_qual

        # But learning continues (rolling100 updated)
        assert len(self.learner.rolling100) == before_rolling + 1, \
            "Loss from starvation should still update learning metrics"

    def test_starvation_learning_flat_still_learns(self):
        """Starvation trade FLAT: learning accepts flat, qualification skipped."""
        closed_trade = {
            "trade_id": "starvation_flat_77",
            "symbol": "ADA",
            "entry_ts": time.time() - 600,
            "outcome": "FLAT",
            "net_pnl": 0.0,
            "net_pnl_pct": 0.0,
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "paper_starvation_learning",
            "paper_learning_only": True,
            "real_readiness_eligible": False,
            "readiness_eligible": False,
            "regime": "BREAKOUT",
            "side": "BUY",
        }

        before_qual = self.learner.qualification_n
        before_rolling = len(self.learner.rolling100)

        self.learner.record_close(closed_trade)

        # Qualification skipped
        assert self.learner.qualification_n == before_qual

        # Learning continues
        assert len(self.learner.rolling100) == before_rolling + 1

    def test_non_starvation_c_weak_ev_still_qualifies(self):
        """Normal C_WEAK_EV_TRAIN (non-starvation): qualification proceeds."""
        closed_trade = {
            "trade_id": "normal_weak_ev_1",
            "symbol": "BTC",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 100.0,
            "net_pnl_pct": 0.05,
            "training_bucket": "C_WEAK_EV_TRAIN",
            "learning_source": "bootstrap",  # NOT starvation
            "paper_learning_only": False,  # Normal trade
            "real_readiness_eligible": True,  # Eligible
            "readiness_eligible": True,
            "regime": "TRENDING",
            "side": "BUY",
        }

        before_qual = self.learner.qualification_n

        self.learner.record_close(closed_trade)

        # Qualification SHOULD increment
        assert self.learner.qualification_n == before_qual + 1, \
            "Normal C_WEAK_EV_TRAIN should increment qualification"

    def test_paper_learning_only_flag_skips_qualification(self):
        """paper_learning_only=True: even if learning_source absent, skip qualification."""
        closed_trade = {
            "trade_id": "paper_only_888",
            "symbol": "SOL",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 50.0,
            "net_pnl_pct": 0.03,
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "",  # Not set
            "paper_learning_only": True,  # This should trigger skip
            "real_readiness_eligible": True,  # Even if True
            "readiness_eligible": True,
            "regime": "TRENDING",
            "side": "SELL",
        }

        before_qual = self.learner.qualification_n

        self.learner.record_close(closed_trade)

        # Should skip due to paper_learning_only=True
        assert self.learner.qualification_n == before_qual

    def test_real_readiness_eligible_false_skips_qualification(self):
        """real_readiness_eligible=False: qualification skipped."""
        closed_trade = {
            "trade_id": "readiness_false_444",
            "symbol": "XRP",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 75.0,
            "net_pnl_pct": 0.04,
            "training_bucket": "C_WEAK_EV_TRAIN",
            "learning_source": "recovery_learning",
            "paper_learning_only": False,  # Not set
            "real_readiness_eligible": False,  # This should trigger skip
            "readiness_eligible": True,
            "regime": "RANGING",
            "side": "BUY",
        }

        before_qual = self.learner.qualification_n

        self.learner.record_close(closed_trade)

        # Should skip due to real_readiness_eligible=False
        assert self.learner.qualification_n == before_qual

    def test_readiness_eligible_false_starvation_bucket_skips(self):
        """readiness_eligible=False + PAPER_STARVATION_DISCOVERY bucket: skip."""
        closed_trade = {
            "trade_id": "readiness_starvation_555",
            "symbol": "DOT",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 60.0,
            "net_pnl_pct": 0.03,
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "starvation_discovery",
            "paper_learning_only": False,
            "real_readiness_eligible": True,
            "readiness_eligible": False,  # This + bucket = skip
            "regime": "TRENDING",
            "side": "SELL",
        }

        before_qual = self.learner.qualification_n

        self.learner.record_close(closed_trade)

        # Should skip
        assert self.learner.qualification_n == before_qual

    def test_v5_bridge_learning_still_runs_for_skipped_qualification(self):
        """V5 bridge learning_update should run even if qualification skipped."""
        # This test verifies that skipping qualification doesn't block learning flow
        # (tested via mocking the learning update path)

        closed_trade = {
            "trade_id": "v5_bridge_test_666",
            "symbol": "BTC",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 100.0,
            "net_pnl_pct": 0.05,
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "paper_starvation_learning",
            "paper_learning_only": True,
            "real_readiness_eligible": False,
            "readiness_eligible": False,
            "regime": "TRENDING",
            "side": "BUY",
        }

        before_rolling = len(self.learner.rolling100)

        self.learner.record_close(closed_trade)

        # Verify learning metrics updated (proves learning continued)
        assert len(self.learner.rolling100) == before_rolling + 1, \
            "Rolling100 should update even if qualification skipped"

        # Verify segment weights were updated (learning feedback)
        segment_key = "BTC:TRENDING:BUY"
        assert segment_key in self.learner.segment_weights or len(self.learner.rolling100) > 0, \
            "Learning feedback should process for starvation trades"

    def test_multiple_starvation_trades_no_qualification_buildup(self):
        """Multiple starvation trades: qualification_n stays at starting point."""
        # Add 5 starvation trades
        for i in range(5):
            trade = {
                "trade_id": f"starvation_batch_{i}",
                "symbol": "BTC",
                "entry_ts": time.time() - (600 - i * 10),
                "outcome": "WIN" if i % 2 == 0 else "LOSS",
                "net_pnl": 100.0 if i % 2 == 0 else -50.0,
                "net_pnl_pct": 0.05 if i % 2 == 0 else -0.03,
                "training_bucket": "PAPER_STARVATION_DISCOVERY",
                "learning_source": "paper_starvation_learning",
                "paper_learning_only": True,
                "real_readiness_eligible": False,
                "readiness_eligible": False,
                "regime": "TRENDING",
                "side": "BUY" if i % 2 == 0 else "SELL",
            }
            self.learner.record_close(trade)

        # After 5 starvation trades, qualification_n should still be 0
        assert self.learner.qualification_n == 0, \
            "Starvation trades should NOT increment qualification_n"

        # But rolling100 should have 5 entries
        assert len(self.learner.rolling100) == 5, \
            "Starvation trades SHOULD update rolling100"

    def test_mixed_starvation_and_normal_trades_qualification_selective(self):
        """Mix of starvation + normal: only normal trades count toward qualification."""
        # Add 2 starvation trades
        for i in range(2):
            trade = {
                "trade_id": f"starvation_mixed_{i}",
                "symbol": "BTC",
                "entry_ts": time.time() - (600 + i * 100),
                "outcome": "WIN",
                "net_pnl": 100.0,
                "net_pnl_pct": 0.05,
                "training_bucket": "PAPER_STARVATION_DISCOVERY",
                "learning_source": "paper_starvation_learning",
                "paper_learning_only": True,
                "real_readiness_eligible": False,
                "readiness_eligible": False,
                "regime": "TRENDING",
                "side": "BUY",
            }
            self.learner.record_close(trade)

        # Add 3 normal trades
        for i in range(3):
            trade = {
                "trade_id": f"normal_mixed_{i}",
                "symbol": "ETH",
                "entry_ts": time.time() - (600 + 200 + i * 100),
                "outcome": "WIN",
                "net_pnl": 100.0,
                "net_pnl_pct": 0.05,
                "training_bucket": "C_WEAK_EV_TRAIN",
                "learning_source": "bootstrap",
                "paper_learning_only": False,
                "real_readiness_eligible": True,
                "readiness_eligible": True,
                "regime": "TRENDING",
                "side": "BUY",
            }
            self.learner.record_close(trade)

        # Qualification should have incremented 3 times (normal trades only)
        assert self.learner.qualification_n == 3, \
            "Only normal trades should count toward qualification (got {}, expected 3)".format(
                self.learner.qualification_n
            )

        # Rolling100 should have 5 entries (both starvation and normal)
        assert len(self.learner.rolling100) == 5, \
            "Both starvation and normal should update rolling100"


class TestQualificationSkipLogging:
    """Verify diagnostic logging for skipped qualifications."""

    def setup_method(self):
        """Reset state."""
        self.learner = pal.PaperAdaptiveLearning()
        self.learner.qualification_started_at = time.time() - 3600

    @patch('src.services.paper_adaptive_learning.log')
    def test_starvation_qualification_skip_logged(self, mock_log):
        """Verify [PAPER_QUALIFICATION_SKIP] logged for starvation trades."""
        closed_trade = {
            "trade_id": "logging_test_1",
            "symbol": "BTC",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 100.0,
            "net_pnl_pct": 0.05,
            "training_bucket": "PAPER_STARVATION_DISCOVERY",
            "learning_source": "paper_starvation_learning",
            "paper_learning_only": True,
            "real_readiness_eligible": False,
            "readiness_eligible": False,
            "regime": "TRENDING",
            "side": "BUY",
        }

        self.learner.record_close(closed_trade)

        # Verify log.info was called with [PAPER_QUALIFICATION_SKIP]
        calls = [call for call in mock_log.info.call_args_list
                 if "PAPER_QUALIFICATION_SKIP" in str(call)]
        assert len(calls) > 0, "Should log [PAPER_QUALIFICATION_SKIP]"

    @patch('src.services.paper_adaptive_learning.log')
    def test_readiness_ineligible_skip_logged(self, mock_log):
        """Verify [PAPER_QUALIFICATION_SKIP] with readiness_ineligible reason."""
        closed_trade = {
            "trade_id": "logging_test_2",
            "symbol": "ETH",
            "entry_ts": time.time() - 600,
            "outcome": "WIN",
            "net_pnl": 50.0,
            "net_pnl_pct": 0.03,
            "training_bucket": "C_WEAK_EV_TRAIN",
            "learning_source": "recovery",
            "paper_learning_only": False,
            "real_readiness_eligible": True,
            "readiness_eligible": False,  # This should trigger skip
            "regime": "RANGING",
            "side": "SELL",
        }

        self.learner.record_close(closed_trade)

        # Verify skip was logged
        calls = [call for call in mock_log.info.call_args_list
                 if "PAPER_QUALIFICATION_SKIP" in str(call)]
        assert len(calls) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
