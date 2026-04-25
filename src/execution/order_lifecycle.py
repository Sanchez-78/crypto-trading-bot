"""
Order lifecycle state machine and transition tracking.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum


class OrderState(Enum):
    """Complete order lifecycle states."""
    SIGNAL_CREATED = "signal_created"
    DECISION_STARTED = "decision_started"
    FEATURES_LOCKED = "features_locked"
    REGIME_LOCKED = "regime_locked"
    EV_COMPUTED = "ev_computed"
    GATES_EVALUATED = "gates_evaluated"
    DECISION_APPROVED = "decision_approved"
    DECISION_REJECTED = "decision_rejected"
    ORDER_ARMED = "order_armed"
    PREFIRE_VALIDATED = "prefire_validated"
    ORDER_SENT = "order_sent"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    EXIT_TRIGGERED = "exit_triggered"
    POSITION_CLOSED = "position_closed"
    PNL_ATTRIBUTED = "pnl_attributed"
    LEARNING_UPDATED = "learning_updated"
    FIREBASE_STATE_UPDATED = "firebase_state_updated"


@dataclass
class StateTransition:
    """Record of a single state transition."""
    from_state: Optional[OrderState]
    to_state: OrderState
    timestamp: float
    detail: Optional[Dict[str, Any]] = None


@dataclass
class OrderLifecycle:
    """Tracks an order through its complete lifecycle."""
    symbol: str
    side: str  # "BUY" | "SELL"
    entry_price: float
    current_state: OrderState = OrderState.SIGNAL_CREATED
    transitions: List[StateTransition] = field(default_factory=list)
    pnl: Optional[float] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    close_reason: Optional[str] = None

    @classmethod
    def from_signal(cls, symbol: str, side: str, entry_price: float) -> 'OrderLifecycle':
        """Construct from signal creation."""
        return cls(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
        )

    @classmethod
    def from_order(cls, order: Dict[str, Any], position: Dict[str, Any]) -> 'OrderLifecycle':
        """Construct from executor order dict."""
        return cls(
            symbol=order.get("symbol", "?"),
            side=order.get("side", "BUY"),
            entry_price=position.get("entry_price", 0.0),
        )

    @classmethod
    def from_closed_trade(cls, trade: Dict[str, Any]) -> 'OrderLifecycle':
        """Construct from closed trade dict."""
        return cls(
            symbol=trade.get("symbol", "?"),
            side=trade.get("side", "BUY"),
            entry_price=trade.get("entry_price", 0.0),
            pnl=trade.get("net_pnl"),
            mfe=trade.get("mfe"),
            mae=trade.get("mae"),
            close_reason=trade.get("close_reason"),
        )

    def mark_state(self, state: OrderState, detail: Optional[Dict[str, Any]] = None,
                   timestamp: Optional[float] = None) -> 'OrderLifecycle':
        """Mark state transition."""
        if timestamp is None:
            timestamp = time.time()

        transition = StateTransition(
            from_state=self.current_state,
            to_state=state,
            timestamp=timestamp,
            detail=detail,
        )
        self.transitions.append(transition)
        self.current_state = state
        return self

    def set_pnl(self, pnl: float, mfe: Optional[float] = None,
                mae: Optional[float] = None) -> 'OrderLifecycle':
        """Set PnL metrics."""
        self.pnl = pnl
        if mfe is not None:
            self.mfe = mfe
        if mae is not None:
            self.mae = mae
        return self

    def format_log(self) -> str:
        """Format as single-line log."""
        pnl_str = f"{self.pnl:+.6f}" if self.pnl is not None else "?"
        mfe_str = f"{self.mfe:+.1%}" if self.mfe is not None else "?"
        mae_str = f"{self.mae:+.1%}" if self.mae is not None else "?"

        return (
            f"CANON_LIFECYCLE sym={self.symbol} side={self.side} "
            f"state={self.current_state.value} pnl={pnl_str} "
            f"mfe={mfe_str} mae={mae_str}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "current_state": self.current_state.value,
            "transitions": [
                {
                    "from": t.from_state.value if t.from_state else None,
                    "to": t.to_state.value,
                    "timestamp": t.timestamp,
                }
                for t in self.transitions
            ],
            "pnl": self.pnl,
            "mfe": self.mfe,
            "mae": self.mae,
            "close_reason": self.close_reason,
        }
