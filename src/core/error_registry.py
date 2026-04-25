"""
Error code registry and descriptions.
"""

from enum import Enum


class ErrorCode(Enum):
    """Canonical error/event codes for decision and learning lifecycle."""
    # Decision stage
    DECISION_APPROVED = "decision_approved"
    DECISION_REJECTED = "decision_rejected"
    DECISION_BLOCKED = "decision_blocked"

    # Gate rejections
    EV_TOO_LOW = "ev_too_low"
    SPREAD_TOO_WIDE = "spread_too_wide"
    OVERTRADING = "overtrading"
    LOSS_STREAK = "loss_streak"
    DRAWDOWN_HALT = "drawdown_halt"
    COHERENCE_FAILED = "coherence_failed"

    # Execution stage
    ORDER_ARMED = "order_armed"
    ORDER_SENT = "order_sent"
    ORDER_FILLED = "order_filled"
    ORDER_FAILED = "order_failed"

    # Position stage
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

    # Learning stage
    OUTCOME_WIN = "outcome_win"
    OUTCOME_LOSS = "outcome_loss"
    OUTCOME_FLAT = "outcome_flat"
    LEARN_METRICS_UPDATED = "learn_metrics_updated"
    LEARN_FIREBASE_SAVED = "learn_firebase_saved"


class ErrorRegistry:
    """Registry mapping error codes to human-readable descriptions."""

    _DESCRIPTIONS = {
        ErrorCode.DECISION_APPROVED: "Decision approved by all gates",
        ErrorCode.DECISION_REJECTED: "Decision rejected by gate",
        ErrorCode.DECISION_BLOCKED: "Decision blocked (system halt)",
        ErrorCode.EV_TOO_LOW: "EV below threshold",
        ErrorCode.SPREAD_TOO_WIDE: "Bid-ask spread exceeds limit",
        ErrorCode.OVERTRADING: "Trade frequency limit exceeded",
        ErrorCode.LOSS_STREAK: "Loss streak halt active",
        ErrorCode.DRAWDOWN_HALT: "Drawdown exceeds limit",
        ErrorCode.COHERENCE_FAILED: "Regime/EV coherence check failed",
        ErrorCode.ORDER_ARMED: "Order ready to send",
        ErrorCode.ORDER_SENT: "Order sent to exchange",
        ErrorCode.ORDER_FILLED: "Order fully filled",
        ErrorCode.ORDER_FAILED: "Order failed or cancelled",
        ErrorCode.POSITION_OPENED: "Position opened (entry filled)",
        ErrorCode.POSITION_CLOSED: "Position closed (exit filled)",
        ErrorCode.OUTCOME_WIN: "Trade closed as win",
        ErrorCode.OUTCOME_LOSS: "Trade closed as loss",
        ErrorCode.OUTCOME_FLAT: "Trade closed flat (neutral)",
        ErrorCode.LEARN_METRICS_UPDATED: "Metrics updated from trade outcome",
        ErrorCode.LEARN_FIREBASE_SAVED: "Metrics saved to Firebase",
    }

    @classmethod
    def describe(cls, code: ErrorCode) -> str:
        """Get human-readable description for an error code."""
        return cls._DESCRIPTIONS.get(code, "Unknown error code")

    @classmethod
    def all_descriptions(cls) -> dict:
        """Return all code → description mappings."""
        return {code.value: desc for code, desc in cls._DESCRIPTIONS.items()}
