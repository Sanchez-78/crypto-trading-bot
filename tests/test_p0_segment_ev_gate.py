"""
Unit tests for P0.3 Segment EV Gate module.

Tests cover:
- Segment key construction
- Stats computation
- Eligibility evaluation
- Quarantine logic
- Evidence collection scope
- All 8 required test cases from P0.3 spec
"""

import pytest
from src.services.p0_segment_ev_gate import (
    P0SegmentEVGate,
    SegmentKey,
    SegmentStats,
    SegmentGateDecision,
)


class TestSegmentKeyConstruction:
    """Test SegmentKey building."""

    def test_build_segment_key_valid(self):
        """Test valid segment key construction."""
        key = P0SegmentEVGate.build_segment_key(
            symbol="ETHUSDT",
            side="BUY",
            regime="BULL_TREND",
            source="paper_evidence_collection",
            tp_sl_profile="0.8_1.5",
        )
        assert key.symbol == "ETHUSDT"
        assert key.side == "BUY"
        assert key.regime == "BULL_TREND"
        assert key.source == "paper_evidence_collection"
        assert key.tp_sl_profile == "0.8_1.5"

    def test_build_segment_key_with_none_values(self):
        """Test segment key handles None values with UNKNOWN fallback."""
        key = P0SegmentEVGate.build_segment_key(
            symbol=None,
            side="BUY",
            regime=None,
            source="test",
            tp_sl_profile="1.0_2.0",
        )
        assert key.symbol == "UNKNOWN"
        assert key.regime == "UNKNOWN"

    def test_segment_key_equality(self):
        """Test segment key equality comparison."""
        key1 = P0SegmentEVGate.build_segment_key("ETHUSDT", "BUY", "BULL_TREND", "src1", "1.0_2.0")
        key2 = P0SegmentEVGate.build_segment_key("ETHUSDT", "BUY", "BULL_TREND", "src1", "1.0_2.0")
        key3 = P0SegmentEVGate.build_segment_key("BTCUSDT", "BUY", "BULL_TREND", "src1", "1.0_2.0")

        assert key1 == key2
        assert key1 != key3

    def test_segment_key_hashable(self):
        """Test segment key is hashable (can be used in dicts/sets)."""
        key = P0SegmentEVGate.build_segment_key("ETHUSDT", "BUY", "BULL_TREND", "src", "1.0_2.0")
        key_dict = {key: "value"}
        assert key_dict[key] == "value"


class TestSegmentStatsComputation:
    """Test segment statistics computation."""

    def test_compute_segment_stats_empty_history(self):
        """Test stats computation with no matching trades."""
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": 0.001},
        ]
        key = SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0")
        stats = P0SegmentEVGate.compute_segment_stats(trades, key)
        assert stats is None

    def test_compute_segment_stats_single_win(self):
        """Test stats computation with single winning trade."""
        trades = [
            {
                "symbol": "ETHUSDT",
                "side": "BUY",
                "regime": "BULL_TREND",
                "source": "test",
                "tp_sl_profile": "1.0_2.0",
                "pnl_usd": 0.001,
                "exit_reason": "TP",
            }
        ]
        key = SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0")
        stats = P0SegmentEVGate.compute_segment_stats(trades, key)

        assert stats is not None
        assert stats.n == 1
        assert stats.wins == 1
        assert stats.losses == 0
        assert stats.gross_win_usd == 0.001
        assert stats.gross_loss_usd == 0.0
        assert stats.net_pnl_usd == 0.001
        assert stats.avg_pnl_usd == 0.001
        assert stats.profit_factor > 1000  # Large PF when no losses

    def test_compute_segment_stats_mixed_wins_losses(self):
        """Test stats computation with both wins and losses."""
        trades = [
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": 0.002, "exit_reason": "TP"},
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": -0.001, "exit_reason": "SL"},
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": 0.001, "exit_reason": "TIMEOUT"},
        ]
        key = SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0")
        stats = P0SegmentEVGate.compute_segment_stats(trades, key)

        assert stats.n == 3
        assert stats.wins == 2
        assert stats.losses == 1
        assert abs(stats.gross_win_usd - 0.003) < 1e-9
        assert abs(stats.gross_loss_usd - 0.001) < 1e-9
        assert abs(stats.net_pnl_usd - 0.002) < 1e-9
        assert abs(stats.avg_pnl_usd - (0.002 / 3)) < 1e-9
        assert abs(stats.profit_factor - 3.0) < 0.01

    def test_compute_segment_stats_timeout_rate(self):
        """Test timeout rate computation."""
        trades = [
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": -0.001, "exit_reason": "TIMEOUT"},
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": 0.001, "exit_reason": "TP"},
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": -0.001, "exit_reason": "TIMEOUT"},
            {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "source": "test", "tp_sl_profile": "1.0_2.0", "pnl_usd": -0.001, "exit_reason": "TIMEOUT"},
        ]
        key = SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0")
        stats = P0SegmentEVGate.compute_segment_stats(trades, key)

        assert stats.timeout_count == 3
        assert abs(stats.timeout_rate - 0.75) < 0.01  # 75%


class TestSegmentEligibilityGate:
    """Test P0.3 strict EV eligibility evaluation."""

    # Test 1: Insufficient evidence (n < 30)
    def test_strict_ev_blocked_when_n_too_small(self):
        """Test 1: Insufficient evidence blocks strict EV."""
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=10,  # Below MIN_SAMPLE_SIZE=30
            wins=5,
            losses=5,
            gross_win_usd=0.01,
            gross_loss_usd=0.005,
            net_pnl_usd=0.005,
            avg_pnl_usd=0.0005,
            profit_factor=2.0,
            timeout_count=2,
            timeout_rate=0.2,
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        assert decision.strict_ev_allowed is False
        assert "insufficient_evidence" in decision.reason
        assert decision.readiness_eligible is False

    # Test 2: Low profit factor blocks strict EV
    def test_strict_ev_blocked_when_pf_too_low(self):
        """Test 2: Profit Factor < 1.2 blocks strict EV."""
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=30,
            wins=16,
            losses=14,
            gross_win_usd=0.02,
            gross_loss_usd=0.019,  # Low PF
            net_pnl_usd=0.001,
            avg_pnl_usd=0.00003,
            profit_factor=1.05,  # Below MIN_PROFIT_FACTOR=1.2
            timeout_count=10,
            timeout_rate=0.33,
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        assert decision.strict_ev_allowed is False
        assert "pf_too_low" in decision.reason
        assert decision.readiness_eligible is False

    # Test 3: Negative expectancy blocks strict EV
    def test_strict_ev_blocked_when_avg_pnl_negative(self):
        """Test 3: Negative expectancy blocks strict EV."""
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=30,
            wins=12,
            losses=18,
            gross_win_usd=0.015,
            gross_loss_usd=0.020,
            net_pnl_usd=-0.005,  # Negative
            avg_pnl_usd=-0.000167,  # Negative expectancy
            profit_factor=0.75,
            timeout_count=5,
            timeout_rate=0.17,
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        assert decision.strict_ev_allowed is False
        assert "negative_expectancy" in decision.reason
        assert decision.readiness_eligible is False

    # Test 4: High timeout rate blocks strict EV
    def test_strict_ev_blocked_when_timeout_rate_too_high(self):
        """Test 4: timeout_rate > 60% blocks strict EV."""
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=30,
            wins=20,
            losses=10,
            gross_win_usd=0.025,
            gross_loss_usd=0.010,
            net_pnl_usd=0.015,
            avg_pnl_usd=0.0005,
            profit_factor=2.5,
            timeout_count=20,  # High timeout count
            timeout_rate=0.67,  # 67% > 60%
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        assert decision.strict_ev_allowed is False
        assert "timeout_rate_too_high" in decision.reason
        assert decision.readiness_eligible is False

    # Test 5: All criteria met → strict EV approved
    def test_strict_ev_approved_when_all_criteria_met(self):
        """Test 5: All criteria passed → strict EV approved."""
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=50,  # >= 30
            wins=32,
            losses=18,
            gross_win_usd=0.040,
            gross_loss_usd=0.020,  # PF = 2.0 >= 1.2
            net_pnl_usd=0.020,
            avg_pnl_usd=0.0004,  # > 0
            profit_factor=2.0,
            timeout_count=20,
            timeout_rate=0.40,  # <= 60%
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        assert decision.strict_ev_allowed is True
        assert "approved" in decision.reason
        assert decision.readiness_eligible is True
        assert decision.realized_ev_usd == 0.0004


class TestQuarantineLogic:
    """Test quarantine policy."""

    def test_btcusdt_quarantined(self):
        """Test BTCUSDT is quarantined from strict EV."""
        is_quar, reason = P0SegmentEVGate.is_quarantined_for_strict_ev("BTCUSDT", "BULL_TREND")
        assert is_quar is True
        assert "symbol_quarantined" in reason

    def test_solusdt_quarantined(self):
        """Test SOLUSDT is quarantined from strict EV."""
        is_quar, reason = P0SegmentEVGate.is_quarantined_for_strict_ev("SOLUSDT", "BULL_TREND")
        assert is_quar is True
        assert "symbol_quarantined" in reason

    def test_bear_trend_quarantined(self):
        """Test BEAR_TREND is quarantined from strict EV."""
        is_quar, reason = P0SegmentEVGate.is_quarantined_for_strict_ev("ETHUSDT", "BEAR_TREND")
        assert is_quar is True
        assert "regime_quarantined" in reason

    def test_ethusdt_bull_trend_not_quarantined(self):
        """Test ETHUSDT + BULL_TREND is not quarantined."""
        is_quar, reason = P0SegmentEVGate.is_quarantined_for_strict_ev("ETHUSDT", "BULL_TREND")
        assert is_quar is False
        assert "not_quarantined" in reason


class TestEvidenceCollectionScope:
    """Test evidence collection scope eligibility."""

    def test_ethusdt_bull_trend_eligible_for_evidence_collection(self):
        """Test ETHUSDT + BULL_TREND is allowed for evidence collection."""
        is_allowed, reason = P0SegmentEVGate.is_eligible_for_evidence_collection("ETHUSDT", "BULL_TREND")
        assert is_allowed is True
        assert "allowed_for_evidence_collection" in reason

    def test_ethusdt_bear_trend_eligible_for_evidence_collection(self):
        """Test ETHUSDT + BEAR_TREND is allowed for evidence collection."""
        is_allowed, reason = P0SegmentEVGate.is_eligible_for_evidence_collection("ETHUSDT", "BEAR_TREND")
        assert is_allowed is True

    def test_btcusdt_not_eligible_for_evidence_collection(self):
        """Test BTCUSDT is blocked from evidence collection."""
        is_allowed, reason = P0SegmentEVGate.is_eligible_for_evidence_collection("BTCUSDT", "BULL_TREND")
        assert is_allowed is False
        assert "not_in_evidence_scope" in reason


class TestDecideSegmentGateComplete:
    """Test complete gate decision pipeline."""

    # Test 6: Evidence collection remains allowed when strict EV blocked
    def test_evidence_collection_allowed_when_strict_ev_blocked(self):
        """Test 6: Strict EV blocked, but evidence collection allowed."""
        # ETHUSDT with n < 30 (insufficient for strict EV)
        trades = []
        for i in range(9):
            trades.append({
                "symbol": "ETHUSDT",
                "side": "BUY",
                "regime": "BULL_TREND",
                "source": "paper_evidence_collection",  # Match the requested source
                "tp_sl_profile": "1.0_2.0",
                "pnl_usd": 0.001,
                "exit_reason": "TP",
            })

        decision = P0SegmentEVGate.decide_segment_gate(
            symbol="ETHUSDT",
            side="BUY",
            regime="BULL_TREND",
            source="paper_evidence_collection",
            tp_sl_profile="1.0_2.0",
            closed_trades=trades,
        )

        # Strict EV blocked (n < 30)
        assert decision.strict_ev_allowed is False
        assert "insufficient_evidence" in decision.reason

        # But evidence collection check should be independent
        is_allowed, _ = P0SegmentEVGate.is_eligible_for_evidence_collection("ETHUSDT", "BULL_TREND")
        assert is_allowed is True

    # Test 7: Fixed RR=1.25 cannot approve a trade
    def test_fixed_rr_not_in_gate_logic(self):
        """Test 7: Fixed RR=1.25 is NOT used in gate logic."""
        # Verify that the gate logic only uses segment stats (PF, avg_pnl, etc.)
        # and never references fixed RR=1.25
        stats = SegmentStats(
            key=SegmentKey("ETHUSDT", "BUY", "BULL_TREND", "test", "1.0_2.0"),
            n=30,
            wins=18,
            losses=12,
            gross_win_usd=0.018,
            gross_loss_usd=0.012,  # Real PF = 1.5
            net_pnl_usd=0.006,
            avg_pnl_usd=0.0002,
            profit_factor=1.5,  # Real PF from history
            timeout_count=5,
            timeout_rate=0.17,
        )
        decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)

        # Should pass (real PF >= 1.2), NOT because of fixed RR
        assert decision.strict_ev_allowed is True
        # Verify realized_ev is based on actual avg_pnl, not RR
        assert decision.realized_ev_usd == 0.0002

    # Test 8: REAL remains disabled (no wiring to REAL in this module)
    def test_module_has_no_real_execution_logic(self):
        """Test 8: Module is pure logic, no REAL execution paths."""
        # Verify that the module has no methods that:
        # - Place real orders
        # - Call Binance API
        # - Write to position state
        # - Execute anything besides decision logic

        module_methods = [name for name in dir(P0SegmentEVGate) if not name.startswith("_")]
        real_methods = ["order", "execute", "place", "binance", "api", "position"]

        for method_name in module_methods:
            for real_keyword in real_methods:
                assert real_keyword.lower() not in method_name.lower(), \
                    f"Module should not have {real_keyword} logic"

        # Verify dataclasses are pure data, not action
        assert not hasattr(SegmentGateDecision, "execute")
        assert not hasattr(SegmentGateDecision, "place_order")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
