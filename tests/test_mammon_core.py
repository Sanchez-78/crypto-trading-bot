"""Tests for Mammon core helpers (Patches 1-3)."""

import pytest
from src.core.decision_frame import DecisionFrame, DecisionState, GateResult, GateType
from src.core.error_registry import ErrorCode, ErrorRegistry
from src.monitoring.canonical_decision_log import format_decision_log, format_lifecycle_log, CanonicalLogger
from src.execution.order_lifecycle import OrderLifecycle, OrderState


# ============================================================================
# PATCH 1: DecisionFrame Tests
# ============================================================================

class TestDecisionFrame:
    """Tests for DecisionFrame and related enums."""

    def test_decision_frame_construction(self):
        df = DecisionFrame(
            symbol="BTCUSDT",
            side="BUY",
            regime="BULL_TREND",
            confidence=0.8,
            ev=0.15,
            ev_final=0.12,
            score=0.9,
            score_threshold=0.10,
            prob=0.6,
            rr=1.5,
        )
        assert df.symbol == "BTCUSDT"
        assert df.decision == DecisionState.PENDING
        assert df.gates == []

    def test_decision_frame_approve(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5
        )
        df.approve("all gates passed")
        assert df.decision == DecisionState.APPROVED
        assert df.reject_reason is None

    def test_decision_frame_reject(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5
        )
        df.reject("EV-TOO-LOW")
        assert df.decision == DecisionState.REJECTED
        assert df.reject_reason == "EV-TOO-LOW"

    def test_decision_frame_block(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5
        )
        df.block("HALT")
        assert df.decision == DecisionState.BLOCKED
        assert df.reject_reason == "HALT"

    def test_decision_frame_add_gate(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5
        )
        gate = GateResult(gate_type=GateType.EV, passed=True, reason="EV above threshold")
        df.add_gate(gate)
        assert len(df.gates) == 1
        assert df.gates[0].gate_type == GateType.EV
        assert df.gates[0].passed is True

    def test_decision_frame_to_dict(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5
        )
        df.add_gate(GateResult(gate_type=GateType.SPREAD, passed=True))
        df.approve()
        d = df.to_dict()
        assert d["symbol"] == "BTC"
        assert d["decision"] == "approved"
        assert isinstance(d["gates"], list)
        assert len(d["gates"]) == 1

    def test_decision_frame_from_signal_dict(self):
        signal = {
            "symbol": "ETHUSDT",
            "side": "SELL",
            "regime": "BEAR_TREND",
            "confidence": 0.7,
            "prob": 0.55,
            "rr": 2.0,
        }
        df = DecisionFrame.from_signal_dict(signal, ev=0.05, score=0.88, threshold=0.10)
        assert df.symbol == "ETHUSDT"
        assert df.side == "SELL"
        assert df.regime == "BEAR_TREND"
        assert df.confidence == 0.7
        assert df.ev == 0.05

    def test_gate_result_serialization(self):
        gate = GateResult(
            gate_type=GateType.FREQUENCY,
            passed=False,
            reason="overtrading",
            value=7,
            threshold=6,
        )
        d = gate.__dict__  # Simple dict conversion
        assert d["gate_type"] == GateType.FREQUENCY
        assert d["passed"] is False
        assert d["reason"] == "overtrading"


# ============================================================================
# PATCH 1: ErrorRegistry Tests
# ============================================================================

class TestErrorRegistry:
    """Tests for ErrorCode enum and ErrorRegistry."""

    def test_error_code_enum_exists(self):
        assert ErrorCode.DECISION_APPROVED
        assert ErrorCode.EV_TOO_LOW
        assert ErrorCode.ORDER_SENT
        assert ErrorCode.OUTCOME_WIN

    def test_error_registry_describe(self):
        desc = ErrorRegistry.describe(ErrorCode.EV_TOO_LOW)
        assert isinstance(desc, str)
        assert len(desc) > 0
        assert "EV" in desc or "threshold" in desc.lower()

    def test_error_registry_describe_all_codes(self):
        for code in ErrorCode:
            desc = ErrorRegistry.describe(code)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_error_registry_all_descriptions(self):
        all_descs = ErrorRegistry.all_descriptions()
        assert isinstance(all_descs, dict)
        assert len(all_descs) >= 20
        assert "decision_approved" in all_descs
        assert "ev_too_low" in all_descs


# ============================================================================
# PATCH 2: Canonical Logging Tests
# ============================================================================

class TestCanonicalDecisionLog:
    """Tests for canonical decision logging."""

    def test_format_decision_log_basic(self):
        decision = {
            "symbol": "BTCUSDT",
            "regime": "BULL_TREND",
            "side": "BUY",
            "decision": "APPROVE",
            "ev_final": 0.123,
            "score": 0.9,
            "gates": {"ev": True, "coherence": True},
        }
        log = format_decision_log(decision)
        assert "CANON_DECISION" in log
        assert "BTCUSDT" in log
        assert "BULL_TREND" in log
        assert "APPROVE" in log
        assert "+0.123" in log

    def test_format_decision_log_missing_fields(self):
        decision = {"symbol": "BTCUSDT"}  # minimal
        log = format_decision_log(decision)
        assert "CANON_DECISION" in log
        assert "BTCUSDT" in log
        assert "?" in log

    def test_format_decision_log_with_failing_gates(self):
        decision = {
            "symbol": "ETHUSDT",
            "regime": "RANGING",
            "side": "SELL",
            "decision": "REJECT",
            "ev_final": -0.05,
            "score": 0.5,
            "gates": {"ev": False, "spread": True},
        }
        log = format_decision_log(decision)
        assert "CANON_DECISION" in log
        assert "ETHUSDT" in log
        assert "REJECT" in log
        assert "-0.050" in log

    def test_format_lifecycle_log_basic(self):
        lifecycle = {
            "symbol": "BTCUSDT",
            "current_state": "order_sent",
            "pnl": 100.5,
            "mfe": 0.005,
            "mae": -0.002,
        }
        log = format_lifecycle_log(lifecycle)
        assert "CANON_LIFECYCLE" in log
        assert "BTCUSDT" in log
        assert "order_sent" in log
        assert "+100.500000" in log

    def test_format_lifecycle_log_missing_fields(self):
        lifecycle = {"symbol": "ETHUSDT", "current_state": "position_opened"}
        log = format_lifecycle_log(lifecycle)
        assert "CANON_LIFECYCLE" in log
        assert "ETHUSDT" in log
        assert "?" in log

    def test_canonical_logger_decision(self):
        logger = CanonicalLogger("test_decision")
        decision = {
            "symbol": "BTCUSDT",
            "regime": "BULL",
            "side": "BUY",
            "decision": "APPROVE",
            "ev_final": 0.1,
            "score": 0.9,
            "gates": {"ev": True},
        }
        log = logger.decision(decision)
        assert log is not None
        assert "CANON_DECISION" in log

    def test_canonical_logger_lifecycle(self):
        logger = CanonicalLogger("test_lifecycle")
        lifecycle = {
            "symbol": "BTCUSDT",
            "current_state": "order_filled",
            "pnl": 50.0,
            "mfe": 0.01,
            "mae": -0.005,
        }
        log = logger.lifecycle(lifecycle)
        assert log is not None
        assert "CANON_LIFECYCLE" in log

    def test_canonical_logger_exception_handling(self):
        logger = CanonicalLogger("test_exception")
        # Pass invalid data (non-dict) to test exception handling
        bad_decision = "not a dict"
        result = logger.decision(bad_decision)  # type: ignore
        # Should return None (exception caught) rather than crashing
        assert result is None


# ============================================================================
# PATCH 3: OrderLifecycle Tests
# ============================================================================

class TestOrderLifecycle:
    """Tests for OrderLifecycle state machine."""

    def test_order_lifecycle_construction(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        assert lc.symbol == "BTCUSDT"
        assert lc.side == "BUY"
        assert lc.entry_price == 50000.0
        assert lc.current_state == OrderState.SIGNAL_CREATED

    def test_order_lifecycle_mark_state_single(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.mark_state(OrderState.ORDER_SENT)
        assert lc.current_state == OrderState.ORDER_SENT
        assert len(lc.transitions) == 1
        assert lc.transitions[0].to_state == OrderState.ORDER_SENT

    def test_order_lifecycle_state_transitions(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.mark_state(OrderState.ORDER_SENT)
        lc.mark_state(OrderState.ORDER_FILLED)
        lc.mark_state(OrderState.POSITION_CLOSED)
        assert lc.current_state == OrderState.POSITION_CLOSED
        assert len(lc.transitions) == 3

    def test_order_lifecycle_set_pnl(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.set_pnl(100.5, mfe=0.002, mae=-0.001)
        assert lc.pnl == 100.5
        assert lc.mfe == 0.002
        assert lc.mae == -0.001

    def test_order_lifecycle_format_log(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.set_pnl(100.5, mfe=0.002, mae=-0.001)
        log = lc.format_log()
        assert "CANON_LIFECYCLE" in log
        assert "BTCUSDT" in log
        assert "BUY" in log
        assert "+100.500000" in log

    def test_order_lifecycle_to_dict(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.mark_state(OrderState.ORDER_SENT)
        d = lc.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert d["side"] == "BUY"
        assert d["current_state"] == "order_sent"
        assert len(d["transitions"]) == 1

    def test_order_lifecycle_from_order(self):
        order = {"symbol": "ETHUSDT", "side": "SELL"}
        position = {"entry_price": 2000.0}
        lc = OrderLifecycle.from_order(order, position)
        assert lc.symbol == "ETHUSDT"
        assert lc.side == "SELL"
        assert lc.entry_price == 2000.0

    def test_order_lifecycle_from_closed_trade(self):
        trade = {
            "symbol": "ADAUSDT",
            "side": "BUY",
            "entry_price": 0.5,
            "net_pnl": 25.0,
            "mfe": 0.015,
            "mae": -0.008,
            "close_reason": "TP",
        }
        lc = OrderLifecycle.from_closed_trade(trade)
        assert lc.symbol == "ADAUSDT"
        assert lc.pnl == 25.0
        assert lc.close_reason == "TP"

    def test_order_state_enum_completeness(self):
        states = [
            OrderState.SIGNAL_CREATED,
            OrderState.DECISION_STARTED,
            OrderState.ORDER_SENT,
            OrderState.ORDER_FILLED,
            OrderState.POSITION_OPENED,
            OrderState.POSITION_CLOSED,
            OrderState.PNL_ATTRIBUTED,
            OrderState.FIREBASE_STATE_UPDATED,
        ]
        assert len(states) == 8


# ============================================================================
# Integration Tests
# ============================================================================

class TestMammonIntegration:
    """Integration tests for Patches 1-3."""

    def test_decision_frame_and_canonical_log(self):
        df = DecisionFrame(
            symbol="BTCUSDT",
            side="BUY",
            regime="BULL_TREND",
            confidence=0.8,
            ev=0.15,
            ev_final=0.12,
            score=0.9,
            score_threshold=0.10,
            prob=0.6,
            rr=1.5,
        )
        df.add_gate(GateResult(gate_type=GateType.EV, passed=True))
        df.approve()

        decision_dict = df.to_dict()
        log = format_decision_log(decision_dict)
        assert "CANON_DECISION" in log
        assert "BTCUSDT" in log
        assert "approved" in log

    def test_lifecycle_full_flow(self):
        lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
        lc.mark_state(OrderState.DECISION_APPROVED)
        lc.mark_state(OrderState.ORDER_ARMED)
        lc.mark_state(OrderState.ORDER_SENT)
        lc.mark_state(OrderState.ORDER_FILLED)
        lc.mark_state(OrderState.POSITION_OPENED)
        lc.set_pnl(150.0, mfe=0.004, mae=-0.002)
        lc.mark_state(OrderState.EXIT_TRIGGERED)
        lc.mark_state(OrderState.POSITION_CLOSED)
        lc.mark_state(OrderState.PNL_ATTRIBUTED)

        d = lc.to_dict()
        assert d["current_state"] == "pnl_attributed"
        assert len(d["transitions"]) == 8
        assert d["pnl"] == 150.0

    def test_error_code_mapping(self):
        df = DecisionFrame(
            symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
            ev=0.05, ev_final=0.05, score=0.9, score_threshold=0.10, prob=0.6, rr=1.5
        )
        df.approve()
        # Should be able to reference ErrorCode.DECISION_APPROVED
        assert ErrorRegistry.describe(ErrorCode.DECISION_APPROVED)
        assert "approved" in ErrorRegistry.describe(ErrorCode.DECISION_APPROVED).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
