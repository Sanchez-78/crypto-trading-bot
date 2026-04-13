from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class CloseReason(str, Enum):
    TP = "TP"
    SL = "SL"
    TIMEOUT = "TIMEOUT"
    MANUAL = "MANUAL"
    VALIDATION = "VALIDATION"

class TradeResult(str, Enum):
    WIN = "VÝHRA"
    LOSS = "PROHRA"
    BREAKEVEN = "BREAKEVEN"
    PENDING = "NEVYHODNOCEN"

@dataclass
class BotConfig:
    taker_fee_pct: float = 0.001
    min_sl_dist_pct: float = 0.002
    max_sl_dist_pct: float = 0.03
    min_rr: float = 1.5
    max_rr: float = 10.0
    min_duration_sec: int = 60
    max_duration_sec: int = 3600
    min_obi_long: float = 10.0
    max_obi_short: float = -10.0
    pnl_decimals: int = 4

@dataclass
class TradeSignal:
    symbol: str
    direction: Direction
    entry_price: float
    sl_price: float
    tp_price: float
    probability: float
    expected_value: float
    obi: float
    atr: float = 0.0
    atr_ratio: float = 1.0
    regime: str = "RANGING"
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class Trade:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    direction: Direction = Direction.LONG
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    probability: float = 0.0
    expected_value: float = 0.0
    obi: float = 0.0
    atr: float = 0.0
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    max_profit_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    close_reason: Optional[CloseReason] = None
    result: TradeResult = TradeResult.PENDING
    net_pnl_pct: float = 0.0
    raw_pnl_pct: float = 0.0
    rejection_reason: str = ""
    entry_size: float = 1.0

    @property
    def duration_seconds(self) -> Optional[int]:
        return (
            int((self.closed_at - self.opened_at).total_seconds())
            if self.opened_at and self.closed_at
            else None
        )

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None and self.closed_at is None
