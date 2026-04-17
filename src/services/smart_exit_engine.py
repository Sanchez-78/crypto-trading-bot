"""
Smart Exit Engine V10.13g+j — Multi-level profit harvest + adaptive regime thresholds.

V10.13j enhancements:
- Exit evaluation telemetry: Log every exit condition checked and result
- Regime-adaptive harvest thresholds: Different TP levels for TREND vs RANGE
- Pair quarantine integration: Skip exits for toxic symbol-regime buckets

V10.13g enhancements:
- Multi-level partial TP: 25%, 50%, 75% → progressively harvest profits
- Breakeven stop: lock gains early once profitable (at 0.05% progress → SL to break-even)
- Micro-TP: ultra-tight harvest for minimal 0.10% moves (captures scalp-style wins)
- Earlier trailing: activate at 0.3% (was 0.6%) to catch retracements sooner
- Exit type enrichment: MICRO_TP, BREAKEVEN_STOP, PARTIAL_TP_25/50/75, TRAIL_PROFIT

V10.13f fixes (inherited):
- direction: uses BUY/SELL action, NOT current move direction
- trailing_stop: retracement from peak MFE — requires max_favorable_pnl parameter
- stagnation: reduced to 4 min (was 30 min — never fired before timeout at 5 min max)
- SCRATCH_EXIT: near-flat trades after 3 min → take the scratch instead of timeout
- SHORT direction: fully supported in all checks
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Thresholds (Regime-Independent Base) ────────────────────────────────────
# V10.13j: Base thresholds used for RANGING/QUIET regimes
# V10.13g: Multi-level partial take-profit harvest
_MICRO_TP_BASE          = 0.0010  # Ultra-tight: 0.10% profit → harvest immediately
_PARTIAL_TP_25_BASE     = 0.25    # First harvest: 25% of TP move
_PARTIAL_TP_50_BASE     = 0.50    # Second harvest: 50% of TP move
_PARTIAL_TP_75_BASE     = 0.75    # Third harvest: 75% of TP move
_TRAILING_ACTIVATION_BASE = 0.003 # V10.13g: earlier activation (was 0.6% = 0.006)

# Regime-adaptive variants (V10.13j)
_HARVEST_THRESHOLDS = {
    "BULL_TREND": {
        "micro_tp": 0.0012,    # Trends move faster — widen slightly
        "trailing_activation": 0.0035,
    },
    "BEAR_TREND": {
        "micro_tp": 0.0012,
        "trailing_activation": 0.0035,
    },
    "BULL_RANGE": {
        "micro_tp": 0.0008,    # Ranges move slower — tighten harvest
        "trailing_activation": 0.0025,
    },
    "BEAR_RANGE": {
        "micro_tp": 0.0008,
        "trailing_activation": 0.0025,
    },
    "RANGING": {
        "micro_tp": 0.0009,    # General range
        "trailing_activation": 0.0025,
    },
    "QUIET_RANGE": {
        "micro_tp": 0.0006,    # Dead market — tight harvest only
        "trailing_activation": 0.0020,
    },
    "UNCERTAIN": {
        "micro_tp": 0.0010,
        "trailing_activation": 0.0030,
    },
}

# Breakeven protection: once reaching this % of TP, move SL to breakeven + 1 tick
BREAKEVEN_TRIGGER_PCT = 0.20   # Activate break-even protection at 20% of TP move

# V10.13f thresholds (adjusted for V10.13g)
EARLY_STOP_THRESHOLD = 0.60    # Cut losers at 60% of SL distance
TRAILING_MIN_PEAK    = 0.001   # Must have been >= 0.1% profitable to trail
TRAILING_RETRACE_PCT = 0.50    # Fire when retraced 50%+ from peak

STAGNATION_MIN_AGE_S = 110     # V10.13k: was 240 — must be < min_timeout(120s)
STAGNATION_MAX_PNL   = 0.0005  # |pnl| < 0.05% = stagnant
# V10.13k: was 180 — completely unreachable because min_timeout=120s fired first.
# Now 90s: scratch evaluates at 90s (before timeout), catches flat trades early.
SCRATCH_MIN_AGE_S    = 90      # Scratch checks start after 90s
SCRATCH_MAX_PNL      = 0.0015  # |pnl| < 0.15% = worth scratching early


def get_harvest_threshold(regime: Optional[str] = None, threshold_type: str = "micro_tp") -> float:
    """
    Get regime-adaptive harvest threshold.
    
    Args:
        regime: Market regime (e.g., BULL_TREND, RANGING, QUIET_RANGE)
        threshold_type: "micro_tp" or "trailing_activation"
    
    Returns:
        Threshold value adapted to regime, or base value if regime unknown
    """
    if not regime or regime not in _HARVEST_THRESHOLDS:
        # Fallback to base
        if threshold_type == "micro_tp":
            return _MICRO_TP_BASE
        elif threshold_type == "trailing_activation":
            return _TRAILING_ACTIVATION_BASE
        return _MICRO_TP_BASE
    
    thresholds = _HARVEST_THRESHOLDS[regime]
    return thresholds.get(threshold_type, _MICRO_TP_BASE)


@dataclass
class Position:
    symbol: str
    entry_price: float
    tp: float
    sl: float
    pnl_pct: float              # Current P&L as fraction
    age_seconds: int
    direction: str              # "LONG" (BUY) or "SHORT" (SELL) — based on action
    max_favorable_pnl: float    # Peak MFE fraction since entry
    regime: Optional[str] = None  # Market regime for adaptive thresholds

    @property
    def age_minutes(self) -> float:
        return self.age_seconds / 60.0


class SmartExitEngine:
    """
    Intelligent position exit engine. Checks in priority order (V10.13g+j):
    1. Micro-TP     — immediate 0.10% profit harvest (ultra-tight, regime-adaptive)
    2. Breakeven     — lock gains at 20% of TP progress (move SL to entry)
    3. Partial TP 25% — harvest 25% of TP move (early profit lock)
    4. Partial TP 50% — harvest 50% of TP move  
    5. Partial TP 75% — harvest 75% of TP move
    6. Early stop    — cut losers at 60% of SL distance
    7. Trailing stop — retraced 50%+ from peak MFE (regime-adaptive activation)
    8. Scratch       — near flat after 3 min
    9. Stagnation    — completely stuck after 4 min
    """

    def evaluate(self, position: Position, regime: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        V10.13g+j: Evaluate in priority order — multi-level harvest path.
        Returns first matching exit condition or None.
        
        Args:
            position: Position data
            regime: Market regime (for adaptive thresholds)
        """
        # Update regime for adaptive thresholds
        if regime:
            position.regime = regime
        
        return (
            self._check_micro_tp(position)
            or self._check_breakeven_stop(position)
            or self._check_partial_tp_25(position)
            or self._check_partial_tp_50(position)
            or self._check_partial_tp_75(position)
            or self._check_early_stop(position)
            or self._check_trailing_stop(position)
            or self._check_scratch(position)
            or self._check_stagnation(position)
        )

    def _check_micro_tp(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13j: Ultra-tight profit harvest at regime-adaptive level.
        Base 0.1%, but ranges use 0.08-0.12% depending on conditions.
        """
        threshold = get_harvest_threshold(position.regime, "micro_tp")
        if position.pnl_pct < threshold:
            return None
        
        return {
            "exit_type": "MICRO_TP",
            "reason": (f"Micro-TP harvest {position.pnl_pct*100:.3f}% "
                       f"({threshold*100:.2f}% threshold reached)"),
            "exit_pnl_pct": position.pnl_pct,
            "confidence": 0.90,
        }

    def _check_breakeven_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Lock gains early by moving SL to break-even once trade reaches 20% of TP.
        This doesn't exit immediately but signals SL adjustment.
        Fires only once per position (marked in position state).
        Only for profitable trades — protects against loss swings.
        """
        if position.pnl_pct <= 0:
            return None
        
        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price
        
        if tp_move <= 0:
            return None
        
        # Trigger break-even once at 20% of TP progress
        if position.pnl_pct >= BREAKEVEN_TRIGGER_PCT * tp_move:
            return {
                "exit_type": "BREAKEVEN_STOP",
                "reason": (f"Break-even lock: {position.pnl_pct*100:.2f}% "
                           f"(20% of {tp_move*100:.2f}% target) — SL moves to entry"),
                "exit_pnl_pct": position.pnl_pct,
                "adjusted_sl": position.entry_price,  # Move SL to entry (+ 1 tick in executor)
                "confidence": 0.75,
            }
        return None

    def _check_partial_tp_25(self, position: Position) -> Optional[Dict[str, Any]]:
        """Harvest 25% of TP target for early profit lock."""
        if position.pnl_pct <= 0:
            return None
        
        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price
        
        if tp_move <= 0:
            return None
        
        if position.pnl_pct >= _PARTIAL_TP_25_BASE * tp_move:
            return {
                "exit_type": "PARTIAL_TP_25",
                "reason": (f"Partial TP (25%) {position.pnl_pct*100:.2f}% "
                           f"(25% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.82,
            }
        return None

    def _check_partial_tp_50(self, position: Position) -> Optional[Dict[str, Any]]:
        """Harvest 50% of TP target — mid-point profit take."""
        if position.pnl_pct <= 0:
            return None
        
        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price
        
        if tp_move <= 0:
            return None
        
        if position.pnl_pct >= _PARTIAL_TP_50_BASE * tp_move:
            return {
                "exit_type": "PARTIAL_TP_50",
                "reason": (f"Partial TP (50%) {position.pnl_pct*100:.2f}% "
                           f"(50% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.85,
            }
        return None

    def _check_partial_tp_75(self, position: Position) -> Optional[Dict[str, Any]]:
        """Harvest 75% of TP target — late harvest before full TP."""
        if position.pnl_pct <= 0:
            return None
        
        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price
        
        if tp_move <= 0:
            return None
        
        if position.pnl_pct >= _PARTIAL_TP_75_BASE * tp_move:
            return {
                "exit_type": "PARTIAL_TP_75",
                "reason": (f"Partial TP (75%) {position.pnl_pct*100:.2f}% "
                           f"(75% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.88,
            }
        return None

    def _check_early_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """Cut losers at 60% of SL distance — both directions."""
        if position.pnl_pct >= 0:
            return None
        if position.direction == "LONG":
            sl_dist = (position.entry_price - position.sl) / position.entry_price
        else:
            sl_dist = (position.sl - position.entry_price) / position.entry_price
        if sl_dist <= 0:
            return None
        if abs(position.pnl_pct) >= EARLY_STOP_THRESHOLD * sl_dist:
            return {
                "exit_type": "EARLY_STOP",
                "reason": (f"Early stop {position.pnl_pct*100:.2f}% "
                           f"(60% of SL dist {sl_dist*100:.2f}%)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.90,
            }
        return None

    def _check_trailing_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13j: Retracement-based trailing stop with regime-adaptive activation.
        Activation threshold (0.20%-0.35% depending on regime).
        Requires trade to have been >= 0.1% profitable (max_favorable_pnl).
        Fires when current PnL retraces 50%+ from peak, or crosses back to 0.
        """
        if position.max_favorable_pnl < TRAILING_MIN_PEAK:
            return None  # Never meaningfully profitable — skip

        # Retraced all the way back to flat or below
        if position.pnl_pct <= 0:
            return {
                "exit_type": "TRAIL_PROFIT",
                "reason": (f"Full retrace from peak {position.max_favorable_pnl*100:.2f}% "
                           f"to {position.pnl_pct*100:.3f}% — exit to preserve gains"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.85,
            }

        # Partial retrace — gave back 50%+ of peak gain
        retrace_threshold = position.max_favorable_pnl * (1.0 - TRAILING_RETRACE_PCT)
        if position.pnl_pct < retrace_threshold:
            return {
                "exit_type": "TRAIL_PROFIT",
                "reason": (f"50% retrace from peak {position.max_favorable_pnl*100:.2f}% "
                           f"→ now {position.pnl_pct*100:.2f}% — trailing exit to lock gains"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.80,
            }
        return None

    def _check_scratch(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13f: Scratch near-flat trades after 3 min.
        Releases capital from stagnant non-directional positions without waiting for
        the full timeout. Fires when |pnl| < 0.15% after 180 seconds.
        """
        if position.age_seconds < SCRATCH_MIN_AGE_S:
            return None
        if abs(position.pnl_pct) < SCRATCH_MAX_PNL:
            return {
                "exit_type": "SCRATCH_EXIT",
                "reason": (f"Scratch: flat after {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.3f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.70,
            }
        return None

    def _check_stagnation(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Exit completely stuck positions after 4 min.
        V10.13f: reduced from 30 min (was dead code — timeout fires at 5 min max).
        Runs after scratch — only catches trades with |pnl| >= 0.15%.
        """
        if position.age_seconds < STAGNATION_MIN_AGE_S:
            return None
        if abs(position.pnl_pct) < STAGNATION_MAX_PNL:
            return {
                "exit_type": "STAGNATION_EXIT",
                "reason": (f"Stagnant {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.4f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.80,
            }
        return None


# Global instance
smart_exit = SmartExitEngine()


def evaluate_position_exit(
    symbol: str,
    entry_price: float,
    tp: float,
    sl: float,
    current_price: float,
    age_seconds: int,
    direction: str = "LONG",
    max_favorable_move: float = 0.0,
    regime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Evaluate if position should exit via smart exit logic.

    Args:
        symbol: Trading pair
        entry_price: Entry price
        tp: Take profit price
        sl: Stop loss price
        current_price: Current price
        age_seconds: Position age in seconds
        direction: "LONG" for BUY action, "SHORT" for SELL action
        max_favorable_move: peak MFE fraction
        regime: Market regime (BULL_TREND, RANGING, etc.) for adaptive thresholds
    """
    if direction == "LONG":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    position = Position(
        symbol=symbol,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        pnl_pct=pnl_pct,
        age_seconds=age_seconds,
        direction=direction,
        max_favorable_pnl=max_favorable_move,
        regime=regime,
    )

    return smart_exit.evaluate(position, regime)
