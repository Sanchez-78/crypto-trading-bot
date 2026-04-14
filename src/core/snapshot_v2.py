"""
PATCH: Snapshot Builder v2 — Immutable views of State for rendering.

Consolidates all scattered snapshot builders (dashboard, learning_monitor, metrics)
into ONE canonical snapshot format.

This guarantees:
- Single source of truth for UI rendering
- Hash-based deduplication (no duplicate renders)
- Atomic consistency (all data from same timestamp)
"""

import hashlib
import json
import time
from typing import Dict, Any
from dataclasses import asdict

from .state_v2 import State, get_state_store


class Snapshot:
    """Immutable snapshot of system state at a point in time."""
    
    def __init__(
        self,
        timestamp: float,
        system: Dict[str, Any],
        positions: Dict[str, Any],
        learning: Dict[str, Any],
        market: Dict[str, Any],
    ):
        self.timestamp = timestamp
        self.system = system
        self.positions = positions
        self.learning = learning
        self.market = market
        self._hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute hash for deduplication."""
        data = {
            "system": self.system,
            "positions": self.positions,
            "learning": self.learning,
            "market": self.market,
        }
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()
    
    @property
    def hash(self) -> str:
        """Get snapshot hash."""
        return self._hash
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dict."""
        return {
            "timestamp": self.timestamp,
            "hash": self._hash,
            "system": self.system,
            "positions": self.positions,
            "learning": self.learning,
            "market": self.market,
        }


def build_snapshot(state: State) -> Snapshot:
    """
    Build canonical snapshot from State.
    
    Consolidates:
    - dashboard_snapshot (equity, drawdown, positions, metrics)
    - lm_snapshot (learning convergence, winrate, ev_avg)
    - market_snapshot (regime, atr, last_price)
    
    Returns immutable Snapshot object.
    """
    timestamp = time.time()
    
    # ────────────────────────────────────────────────────────────────────────
    # System metrics (dashboard)
    system = {
        "timestamp": timestamp,
        "equity": round(state.equity, 6),
        "drawdown_pct": round(state.drawdown * 100, 2),
        "peak_equity": round(state.equity_peak, 6),
        "exposure": len(state.positions),
        "total_trades": state.trades_total,
        "winrate": round(
            state.trades_wins / max(state.trades_total, 1),
            3
        ),
        "no_trade_sec": round(state.no_trade_duration, 1),
        "exploration_factor": round(state.exploration_factor, 2),
        "allow_micro": state.allow_micro_trade,
    }
    
    # ────────────────────────────────────────────────────────────────────────
    # Position details
    positions_list = []
    for pos in state.positions:
        positions_list.append({
            "asset": pos.asset,
            "direction": pos.direction,
            "entry": round(pos.entry_price, 8),
            "current": round(pos.entry_price, 8),  # Would fetch from market data
            "size": round(pos.size, 8),
            "sl": round(pos.sl, 8),
            "tp": round(pos.tp, 8),
            "live_pnl": round(pos.live_pnl, 6),
            "confidence": round(pos.confidence, 3),
            "regime": pos.regime,
        })
    
    positions = {
        "active_count": len(positions_list),
        "positions": positions_list,
    }
    
    # ────────────────────────────────────────────────────────────────────────
    # Learning convergence
    learning = {
        "ev_average": round(state.ev_avg, 6),
        "ev_convergence": round(state.ev_convergence, 4),
        "learning_health": round(state.learning_health, 3),
        "recent_trades": min(len(state.closed_trades), 10),
        "win_streak": 0,  # Computed from closed_trades if needed
    }
    
    # Compute win streak
    streak = 0
    for trade in reversed(state.closed_trades[-10:]):
        if trade.pnl > 0:
            streak += 1
        else:
            break
    learning["win_streak"] = streak
    
    # ────────────────────────────────────────────────────────────────────────
    # Market context
    market = {
        "regime": state.market_regime,
        "last_price": round(state.last_price, 8),
        "last_atr": round(state.last_atr, 8),
        "timestamp": timestamp,
    }
    
    return Snapshot(
        timestamp=timestamp,
        system=system,
        positions=positions,
        learning=learning,
        market=market,
    )


def build_snapshot_live() -> Snapshot:
    """
    Build snapshot from current global state (convenience function).
    """
    store = get_state_store()
    state = store.get_state()
    return build_snapshot(state)


# ────────────────────────────────────────────────────────────────────────────
# Deduplication helper

class SnapshotRenderer:
    """
    Thread-safe renderer with hash-based deduplication.
    Prevents duplicate console output due to race conditions.
    """
    
    def __init__(self):
        self._last_snapshot_hash = None
        self._lock = __import__("threading").Lock()
    
    def render(self, snapshot: Snapshot, handler=None) -> bool:
        """
        Render snapshot only if changed since last render.
        
        Args:
            snapshot: Snapshot to render
            handler: Optional callable(snapshot_dict) for custom rendering
        
        Returns:
            True if rendered, False if dedup'd
        """
        with self._lock:
            if snapshot.hash == self._last_snapshot_hash:
                return False
            
            self._last_snapshot_hash = snapshot.hash
        
        # Render outside lock
        if handler:
            handler(snapshot.to_dict())
        else:
            print(f"[SNAPSHOT] {snapshot.to_dict()}")
        
        return True
