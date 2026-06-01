"""
V5 Legacy Bridge — Event Models

Maps legacy trading lifecycle events to V5-compatible data structures
for persistence, learning, and metrics publication.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class LegacyPaperOpenEvent:
    """Legacy bot PAPER entry captured as V5-compatible event."""
    trade_id: str
    symbol: str
    side: str  # BUY or SELL
    strategy_id: Optional[str] = None
    regime: Optional[str] = None
    entry_ts: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    entry_price: float = 0.0
    size: float = 0.1
    bucket: Optional[str] = None
    expected_move_bps: float = 0.0
    required_move_bps: float = 0.0
    cost_edge_ok: bool = True
    real_orders_allowed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firebase-compatible dict."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "strategy_id": self.strategy_id,
            "regime": self.regime,
            "entry_ts": self.entry_ts,
            "entry_price": self.entry_price,
            "size": self.size,
            "bucket": self.bucket,
            "expected_move_bps": self.expected_move_bps,
            "required_move_bps": self.required_move_bps,
            "cost_edge_ok": self.cost_edge_ok,
            "real_orders_allowed": self.real_orders_allowed,
            "metadata": self.metadata,
            "event_type": "paper_open",
            "created_at": datetime.utcnow().isoformat(),
        }


@dataclass
class LegacyPaperCloseEvent:
    """Legacy bot PAPER exit captured as V5-compatible event."""
    trade_id: str
    symbol: str
    side: str  # BUY or SELL
    exit_ts: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    exit_price: float = 0.0
    exit_reason: str = "manual_close"
    gross_pnl: float = 0.0
    fees: float = 0.0
    spread: float = 0.0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    duration_seconds: float = 0.0
    learning_eligible: bool = True
    readiness_eligible: bool = False
    real_orders_allowed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firebase-compatible dict."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "exit_ts": self.exit_ts,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "gross_pnl": self.gross_pnl,
            "fees": self.fees,
            "spread": self.spread,
            "net_pnl": self.net_pnl,
            "net_pnl_pct": self.net_pnl_pct,
            "duration_seconds": self.duration_seconds,
            "learning_eligible": self.learning_eligible,
            "readiness_eligible": self.readiness_eligible,
            "real_orders_allowed": self.real_orders_allowed,
            "metadata": self.metadata,
            "event_type": "paper_close",
            "created_at": datetime.utcnow().isoformat(),
        }


@dataclass
class V5QuotaSnapshot:
    """Current quota state."""
    reads_used: int = 0
    reads_cap: int = 20000
    writes_used: int = 0
    writes_cap: int = 10000
    outbox_pending: int = 0
    state: str = "normal"  # normal, warning, exhausted
    timestamp: float = field(default_factory=lambda: datetime.utcnow().timestamp())

    def reads_remaining(self) -> int:
        return max(0, self.reads_cap - self.reads_used)

    def writes_remaining(self) -> int:
        return max(0, self.writes_cap - self.writes_used)

    def is_healthy(self) -> bool:
        """Check if quota is healthy enough for new operations."""
        return self.state == "normal" and self.writes_remaining() > 500


@dataclass
class V5DashboardSnapshot:
    """Metrics for dashboard and readiness publishing."""
    timestamp: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    bot_version: str = "v5_legacy_hybrid"
    service_name: str = "cryptomaster.service"
    active_epoch: str = ""
    mode: str = "paper_train"
    real_orders_allowed: bool = False
    legacy_runtime: bool = True
    v5_bridge_enabled: bool = True

    # Trading metrics
    open_positions: int = 0
    closed_today: int = 0
    entries_attempted: int = 0
    entries_accepted: int = 0
    entries_rejected: int = 0
    cost_edge_pass: int = 0
    cost_edge_fail: int = 0

    # Learning metrics
    eligible_closes: int = 0
    learning_updates: int = 0
    readiness_status: str = "calibrating"  # calibrating, ready, blocked
    readiness_reason: str = ""

    # Quota
    quota_state: str = "normal"
    quota_reads_remaining: int = 20000
    quota_writes_remaining: int = 10000
    outbox_pending: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Firebase-compatible dict."""
        return {
            k: v for k, v in self.__dict__.items()
        }
