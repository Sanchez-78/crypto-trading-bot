"""PAPER position lifecycle for Clean Core MVP."""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import time


class PositionState(Enum):
    """State of a PAPER position."""

    CREATED = "created"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class PaperPosition:
    """Complete record of a PAPER position lifecycle."""

    position_id: str
    symbol: str
    entry_price: float
    qty: float
    side: str  # "long" or "short"
    entry_time_utc: str
    tp_price: float
    sl_price: float
    timeout_minutes: int
    state: PositionState = PositionState.CREATED
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_time_utc: Optional[str] = None
    exit_slippage_bps: float = 0.0
    entry_metadata: dict = field(default_factory=dict)  # signal_id, hypothesis, etc.

    def open(self) -> None:
        """Mark position as opened."""
        self.state = PositionState.OPEN

    def close(
        self,
        exit_price: float,
        exit_reason: str,
        exit_time_utc: str,
        exit_slippage_bps: float = 0.0,
    ) -> None:
        """Mark position as closed with exit details."""
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.exit_time_utc = exit_time_utc
        self.exit_slippage_bps = exit_slippage_bps
        self.state = PositionState.CLOSED

    def gross_pnl_pct(self) -> float:
        """Calculate gross PnL before fees/funding."""
        if self.exit_price is None:
            return 0.0
        return ((self.exit_price - self.entry_price) / self.entry_price) * 100.0

    def is_open(self) -> bool:
        """Check if position is currently open."""
        return self.state == PositionState.OPEN

    def holding_minutes(self) -> Optional[float]:
        """Calculate minutes held (if closed)."""
        if not self.exit_time_utc:
            return None
        # Simple calculation: parse ISO format and diff
        from datetime import datetime
        entry_dt = datetime.fromisoformat(self.entry_time_utc.replace("Z", "+00:00"))
        exit_dt = datetime.fromisoformat(self.exit_time_utc.replace("Z", "+00:00"))
        return (exit_dt - entry_dt).total_seconds() / 60.0
