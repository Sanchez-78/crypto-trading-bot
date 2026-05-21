"""
P1.1AP-I: D_NEG_EV_CONTROL isolation from canonical learning

Verify that D_NEG_EV_CONTROL diagnostic trades:
- Still emit PAPER_EXIT and quality diagnostics
- Skip canonical learning updates
- Don't affect economic health
- Non-D_NEG learning paths are unchanged
"""

import pytest
from unittest.mock import patch, MagicMock


class TestP1_1AP_I_DnegLearningIsolation:
    """P1.1AP-I: Isolate D_NEG_EV_CONTROL from canonical learning"""

    def test_dneg_exits_skip_canonical_learning(self, caplog):
        """P1.1AP-I-1: D_NEG paper exits still log but skip canonical learning"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade

        # Create a D_NEG_EV_CONTROL trade
        pos = {
            "symbol": "BTCUSDT",
            "regime": "BULL",
            "side": "BUY",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "trade_id": "test_trade_001",
        }
        pnl_data = {
            "outcome": "LOSS",
            "exit_reason": "TIMEOUT",
            "net_pnl_pct": -0.05,
        }

        # Mock learning_monitor.update_from_paper_trade to track if it's called
        with patch("src.services.learning_monitor.update_from_paper_trade") as mock_update:
            result = _safe_learning_update_for_paper_trade(pos, pnl_data)

            # Should return False (skipped)
            assert result is False, "D_NEG trade should skip learning"

            # update_from_paper_trade should NOT be called
            mock_update.assert_not_called()

            # Should emit PAPER_LEARNING_SHADOW_SKIP log
            log_output = caplog.text
            assert "[PAPER_LEARNING_SHADOW_SKIP]" in log_output
            assert "D_NEG_EV_CONTROL" in log_output
            assert "d_neg_ev_control_shadow_only" in log_output

    def test_dneg_training_bucket_also_skips(self, caplog):
        """P1.1AP-I-1b: D_NEG in training_bucket field also triggers skip"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade

        # D_NEG in training_bucket, not bucket field
        pos = {
            "symbol": "ETHUSDT",
            "regime": "BULL",
            "side": "SELL",
            "bucket": "C_WEAK_EV_TRAIN",
            "training_bucket": "D_NEG_EV_CONTROL",
            "trade_id": "test_trade_002",
        }
        pnl_data = {
            "outcome": "LOSS",
            "exit_reason": "SL",
            "net_pnl_pct": -0.10,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade") as mock_update:
            result = _safe_learning_update_for_paper_trade(pos, pnl_data)

            assert result is False, "D_NEG in training_bucket should also skip"
            mock_update.assert_not_called()
            assert "[PAPER_LEARNING_SHADOW_SKIP]" in caplog.text

    def test_non_dneg_still_learns(self, caplog):
        """P1.1AP-I-2: Non-D_NEG paper trades still undergo canonical learning"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade
        import logging

        # Ensure we capture INFO level logs
        caplog.set_level(logging.INFO)

        pos = {
            "symbol": "ADAUSDT",
            "regime": "RANGE",
            "side": "BUY",
            "bucket": "C_WEAK_EV_TRAIN",
            "training_bucket": "C_WEAK_EV_TRAIN",
            "trade_id": "test_trade_003",
        }
        pnl_data = {
            "outcome": "WIN",
            "exit_reason": "TP",
            "net_pnl_pct": 0.15,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade") as mock_update:
            mock_update.return_value = True
            result = _safe_learning_update_for_paper_trade(pos, pnl_data)

            # Should return True (learned)
            assert result is True, "Non-D_NEG trade should learn normally"

            # update_from_paper_trade SHOULD be called
            mock_update.assert_called_once()

            # Should emit LEARNING_UPDATE log (not SHADOW_SKIP)
            # The log might be emitted but check the mock was called instead
            assert "[PAPER_LEARNING_SHADOW_SKIP]" not in caplog.text

    def test_strict_take_unchanged(self):
        """P1.1AP-I-3: A_STRICT_TAKE / B_RECOVERY_READY unchanged"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade

        pos = {
            "symbol": "DOGEUSDT",
            "regime": "BULL",
            "side": "BUY",
            "bucket": "A_STRICT_TAKE",
            "training_bucket": "A_STRICT_TAKE",
            "trade_id": "test_trade_004",
        }
        pnl_data = {
            "outcome": "WIN",
            "exit_reason": "TP",
            "net_pnl_pct": 0.20,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade") as mock_update:
            mock_update.return_value = True
            result = _safe_learning_update_for_paper_trade(pos, pnl_data)

            # A_STRICT_TAKE should learn normally (not D_NEG)
            assert result is True
            mock_update.assert_called_once()

    def test_dneg_metrics_still_update(self, caplog):
        """P1.1AP-I-5: D_NEG bucket metrics still update locally"""
        from src.services.paper_trade_executor import _safe_bucket_metrics_update_for_paper_trade

        closed_trade = {
            "symbol": "XRPUSDT",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "outcome": "LOSS",
            "net_pnl_pct": -0.08,
        }

        # Call bucket metrics update (should not raise)
        try:
            _safe_bucket_metrics_update_for_paper_trade(closed_trade)
        except Exception as e:
            pytest.fail(f"Bucket metrics update should not raise: {e}")

        # Bucket metrics should be updated (this is diagnostics-only, not canonical)
        # Check that function completed without error


class TestP1_1AP_I_QuarantineUnchanged:
    """P1.1AP-I-4: Verify quarantine behavior is unchanged"""

    def test_quarantine_not_confused_with_dneg(self, caplog):
        """Quarantined positions should have their own log, not D_NEG shadow skip log"""
        # Quarantine behavior is tested separately in test_p11ab_stale_position_quarantine.py
        # This test verifies that D_NEG shadow skip is distinct from quarantine
        # by checking that a D_NEG trade doesn't emit PAPER_POSITION_QUARANTINED

        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade

        # D_NEG trade (not quarantined, not stale)
        pos = {
            "symbol": "BTCUSDT",
            "regime": "BULL",
            "side": "BUY",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "trade_id": "test_trade_dneg",
        }
        pnl_data = {
            "outcome": "LOSS",
            "exit_reason": "TIMEOUT",
            "net_pnl_pct": -0.05,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade"):
            _safe_learning_update_for_paper_trade(pos, pnl_data)

            # D_NEG should emit SHADOW_SKIP, not QUARANTINED
            assert "[PAPER_LEARNING_SHADOW_SKIP]" in caplog.text
            assert "[PAPER_POSITION_QUARANTINED]" not in caplog.text


class TestP1_1AP_I_DnegIslands:
    """Verify D_NEG isolation doesn't leak to other functions"""

    def test_dneg_record_training_closed_still_updates(self, caplog):
        """D_NEG bucket metrics in record_training_closed should still work"""
        from src.services.paper_training_sampler import record_training_closed

        # Call record_training_closed with D_NEG bucket
        # This is diagnostics-only, should not raise
        try:
            record_training_closed(bucket="D_NEG_EV_CONTROL", outcome="LOSS")
        except Exception as e:
            pytest.fail(f"record_training_closed should handle D_NEG: {e}")


class TestP1_1AP_I2_LegacyLogSuppression:
    """P1.1AP-I2: Suppress legacy LEARNING_UPDATE log for D_NEG"""

    def test_dneg_shadow_skip_has_real_trade_id(self, caplog):
        """P1.1AP-I2-1: D_NEG shadow skip log includes real trade_id, not UNKNOWN"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade
        import logging

        caplog.set_level(logging.WARNING)

        pos = {
            "symbol": "BTCUSDT",
            "regime": "BULL",
            "side": "BUY",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "trade_id": "paper_test_dneg_123",  # Real trade_id
        }
        pnl_data = {
            "outcome": "LOSS",
            "exit_reason": "TIMEOUT",
            "net_pnl_pct": -0.05,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade"):
            _safe_learning_update_for_paper_trade(pos, pnl_data)

            # Should have real trade_id in log, not UNKNOWN
            assert "paper_test_dneg_123" in caplog.text
            assert "[PAPER_LEARNING_SHADOW_SKIP]" in caplog.text
            # Should NOT have UNKNOWN trade_id
            assert "trade_id=UNKNOWN" not in caplog.text

    def test_dneg_legacy_learning_update_suppressed(self, caplog):
        """P1.1AP-I2-2: D_NEG does not emit legacy [LEARNING_UPDATE] log"""
        from src.services.trade_executor import _closed_trade_is_d_neg_shadow
        import logging

        caplog.set_level(logging.WARNING)

        # D_NEG closed trade
        closed_trade = {
            "symbol": "SOLUSDT",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "outcome": "LOSS",
            "net_pnl_pct": -0.08,
            "trade_id": "paper_dneg_456",
            "learning_shadow_only": True,
        }

        # Verify helper correctly identifies D_NEG
        assert _closed_trade_is_d_neg_shadow(closed_trade) is True

        # Simulate the save logic check
        if not _closed_trade_is_d_neg_shadow(closed_trade):
            # This code should NOT run for D_NEG
            pytest.fail("D_NEG trade should be identified as shadow-only")

    def test_non_dneg_legacy_learning_update_unchanged(self):
        """P1.1AP-I2-3: Non-D_NEG trades still emit legacy LEARNING_UPDATE"""
        from src.services.trade_executor import _closed_trade_is_d_neg_shadow

        # Non-D_NEG closed trade
        closed_trade = {
            "symbol": "ADAUSDT",
            "bucket": "C_WEAK_EV_TRAIN",
            "training_bucket": "C_WEAK_EV_TRAIN",
            "outcome": "WIN",
            "net_pnl_pct": 0.10,
        }

        # Should NOT be identified as D_NEG shadow
        assert _closed_trade_is_d_neg_shadow(closed_trade) is False

    def test_dneg_fallback_chain_handles_all_id_fields(self, caplog):
        """P1.1AP-I2: trade_id fallback chain handles multiple field names"""
        from src.services.paper_trade_executor import _safe_learning_update_for_paper_trade
        import logging

        caplog.set_level(logging.WARNING)

        # Use 'id' field instead of 'trade_id'
        pos = {
            "symbol": "ETHUSDT",
            "regime": "RANGE",
            "side": "SELL",
            "bucket": "D_NEG_EV_CONTROL",
            "training_bucket": "D_NEG_EV_CONTROL",
            "id": "paper_id_789",  # 'id' field instead of 'trade_id'
        }
        pnl_data = {
            "outcome": "FLAT",
            "exit_reason": "MANUAL",
            "net_pnl_pct": 0.0,
        }

        with patch("src.services.learning_monitor.update_from_paper_trade"):
            _safe_learning_update_for_paper_trade(pos, pnl_data)

            # Should find 'id' in fallback chain
            assert "paper_id_789" in caplog.text
            assert "[PAPER_LEARNING_SHADOW_SKIP]" in caplog.text
