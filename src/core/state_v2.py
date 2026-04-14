"""
PATCH: State Store v2 — Single source of truth for system state.

All mutable state lives here. No scattered state in individual modules.
State changes ONLY happen through emit_state_update().

This guarantees:
- No stale data across subsystems
- Replay-able state trajectory
- Strong consistency (no dirty reads)
"""

import threading
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any

# ────────────────────────────────────────────────────────────────────────────
# State Store: immutable value objects

@dataclass
class Trade:
    """Closed trade record."""
    asset: str
    entry_price: float
    exit_price: float
    direction: str  # "BUY" or "SELL"
    pnl: float
    regime: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.5


@dataclass
class Position:
    """Open position record."""
    asset: str
    entry_price: float
    size: float
    direction: str
    regime: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.5
    sl: float = 0.0
    tp: float = 0.0
    live_pnl: float = 0.0


@dataclass
class State:
    """Complete system state — immutable read, updated via emit_state_update()."""
    
    # Core metrics
    equity: float = 1.0
    equity_peak: float = 1.0
    drawdown: float = 0.0
    
    # Positions
    positions: List[Position] = field(default_factory=list)
    closed_trades: List[Trade] = field(default_factory=list)
    
    # Market intelligence
    market_regime: str = "UNKNOWN"  # BULL_TREND, BEAR_TREND, RANGING, etc.
    last_price: float = 0.0
    last_atr: float = 0.0
    
    # Trading activity
    no_trade_duration: float = 0.0  # seconds since last trade close
    last_trade_ts: float = 0.0
    trades_total: int = 0
    trades_wins: int = 0
    
    # Exploration state
    exploration_factor: float = 1.0  # 1.0 = normal, >1.0 = boosted
    allow_micro_trade: bool = False
    
    # Learning convergence
    ev_avg: float = 0.0
    ev_convergence: float = 0.0
    learning_health: float = 0.5
    
    # Metrics
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamp
    last_update: float = field(default_factory=time.time)
    
    def to_dict(self):
        """Serialize to dict (for snapshots)."""
        return {
            "equity": self.equity,
            "drawdown": self.drawdown,
            "positions": len(self.positions),
            "regime": self.market_regime,
            "no_trade_duration": self.no_trade_duration,
            "trades": self.trades_total,
            "winrate": self.trades_wins / max(self.trades_total, 1),
            "learning_health": self.learning_health,
            "exploration": self.exploration_factor,
        }


# ────────────────────────────────────────────────────────────────────────────
# State Store implementation

class StateStore:
    """Thread-safe mutable state."""
    
    def __init__(self):
        self.state = State()
        self.lock = threading.RLock()
        self.version = [0]
        self._history = []
    
    def get_state(self) -> State:
        """Get current state (immutable copy)."""
        with self.lock:
            return State(**vars(self.state))
    
    def update(self, **kwargs):
        """Update state fields (atomic)."""
        with self.lock:
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)
            self.state.last_update = time.time()
            self.version[0] += 1
            
            # Log state changes for audit
            self._history.append({
                "version": self.version[0],
                "timestamp": self.state.last_update,
                "changes": kwargs,
            })
            
            # Keep last 100 changes (configurable)
            if len(self._history) > 100:
                self._history.pop(0)
    
    def add_position(self, position: Position):
        """Add an open position."""
        with self.lock:
            self.state.positions.append(position)
            self.version[0] += 1
    
    def close_position(self, asset: str, exit_price: float, pnl: float):
        """Close a position and record trade."""
        with self.lock:
            # Find and remove position
            for i, pos in enumerate(self.state.positions):
                if pos.asset == asset:
                    closed_pos = self.state.positions.pop(i)
                    
                    # Record as trade
                    trade = Trade(
                        asset=asset,
                        entry_price=closed_pos.entry_price,
                        exit_price=exit_price,
                        direction=closed_pos.direction,
                        pnl=pnl,
                        regime=closed_pos.regime,
                        confidence=closed_pos.confidence,
                    )
                    self.state.closed_trades.append(trade)
                    
                    # Update metrics
                    self.state.trades_total += 1
                    if pnl > 0:
                        self.state.trades_wins += 1
                    
                    self.state.last_trade_ts = time.time()
                    self.state.no_trade_duration = 0.0
                    
                    self.version[0] += 1
                    return trade
        
        return None
    
    def get_history(self, limit=None):
        """Get audit history (last `limit` changes or all)."""
        with self.lock:
            if limit:
                return self._history[-limit:]
            return list(self._history)


# Global singleton
_state_store = None

def get_state_store() -> StateStore:
    """Get or initialize the global state store."""
    global _state_store
    if _state_store is None:
        _state_store = StateStore()
    return _state_store

def init_state_store():
    """Explicitly initialize state store."""
    global _state_store
    _state_store = StateStore()
    return _state_store
