"""
Smart Exit Engine V10.13p — Harvest conversion patch (near-miss to real harvest).

V10.13p enhancements (convert near-miss exits into real harvests):
- PARTIAL_TP_25_BASE: 0.15→0.13 (convert 27,804 near-miss events into real exits)
- TRAILING_ACTIVATION_BASE: 0.0020→0.0018 (lower activation for more trailing opportunities)
- Leaves SCRATCH unchanged (V10.13o's 105s/0.0016 band working well)
- Rationale: V10.13o fixed timeout problem and improved partial mix, but 27,804 partial25_near_miss
  events show massive untapped harvest opportunity. Positions getting very close to 25% TP but not
  quite converting. V10.13p tightens thresholds slightly to convert near-misses into real exits,
  improving exit diversification without risking PF regression.

V10.13o enhancements (rebalance patch based on live data):
- SCRATCH_MIN_AGE: 85s→105s (delay activation to let trades develop into higher-value exits)
- SCRATCH_MAX_PNL: 0.0020→0.0016 (narrow band to prevent premature flat-release)
- Rationale: V10.13n achieved timeout elimination but scratch became dominant (79% of exits),
  preventing PARTIAL_TP_50/75 and higher trailing from developing. V10.13o rebalances without
  reintroducing timeout risk.

V10.13n enhancements (evidence-based from V10.13m audit data):
- MICRO_TP: 0.0010→0.0012 (widen to reduce near-miss threshold gap)
- PARTIAL_TP: 0.25/0.50/0.75→0.15/0.35/0.60 (closer to real move distribution)
- TRAILING_ACTIVATION: 0.003→0.0020 (activate sooner for retrace capture)
- SCRATCH: 90s→85s (earlier), 0.0015→0.0020 pnl band (wider)
- Regime-adaptive: All harvest thresholds tuned for optimal move capture
- Result: Improved partial harvest, trailing activation, scratch exit frequency

V10.13m enhancements:
- Exit attribution telemetry: Why each branch PASS/FAIL for every position
- Branch rejection counters: Track most common blockers (age, pnl, etc.)
- Timeout pre-emption tracker: Detect near-miss exits that timeout beat
- MFE/MAE/trailing state diagnostics: Verify state integrity
- Debug toggle: EXIT_AUDIT_DEBUG env var to enable detailed logging

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
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)

# V10.13m: Debug toggles
EXIT_AUDIT_DEBUG = os.getenv("EXIT_AUDIT_DEBUG", "0") == "1"
EXIT_AUDIT_VERBOSE = os.getenv("EXIT_AUDIT_VERBOSE", "0") == "1"

# ── Thresholds (Regime-Independent Base) ────────────────────────────────────
# V10.13p: Harvest conversion patch — convert near-miss exits into real harvests
#   - PARTIAL_TP_25: 0.15 → 0.13 (27,804 near-miss events in logs → activate more conversions)
#   - TRAILING_ACTIVATION: 0.0020 → 0.0018 (give trailing more chance to arm and manage exits)
# V10.13n: Evidence-based tuning from 2-hour audit data (V10.13m)
#   - MICRO_TP: 0.0010 → 0.0012 (widen to reduce near-miss gap)
#   - PARTIAL_TP: 0.25/0.50/0.75 → 0.15/0.35/0.60 (closer to real move distribution)
#   - TRAILING_ACTIVATION: 0.003 → 0.0020 (activate sooner, catch more retracements)
# V10.13j: Base thresholds used for RANGING/QUIET regimes
# V10.13g: Multi-level partial take-profit harvest
_MICRO_TP_BASE          = 0.0010  # V10.13s.3: 0.0012→0.0010 (5589 near-miss events) reduce gap
_PARTIAL_TP_25_BASE     = 0.10    # V10.13s.3: 0.13→0.10 (convert near-miss to real harvests)
_PARTIAL_TP_50_BASE     = 0.30    # V10.13s.3: 0.35→0.30 (match market move distribution)
_PARTIAL_TP_75_BASE     = 0.50    # V10.13s.3: 0.60→0.50 (more reachable, better harvest rate)
_TRAILING_ACTIVATION_BASE = 0.0015 # V10.13s.3: 0.0018→0.0015 (activate trailing sooner)

# Regime-adaptive variants (V10.13s.3: adjusted for harvest conversion patch)
_HARVEST_THRESHOLDS = {
    "BULL_TREND": {
        "micro_tp": 0.0012,    # V10.13s.3: 0.0014→0.0012 (reduce near-miss gap)
        "trailing_activation": 0.0018,  # V10.13s.3: 0.0022→0.0018 (activate sooner)
    },
    "BEAR_TREND": {
        "micro_tp": 0.0012,    # V10.13s.3: 0.0014→0.0012 (reduce threshold gap)
        "trailing_activation": 0.0018,  # V10.13s.3: 0.0022→0.0018 (lower for more trails)
    },
    "BULL_RANGE": {
        "micro_tp": 0.0008,    # V10.13s.3: 0.0010→0.0008 (tighter for range trades)
        "trailing_activation": 0.0011,  # V10.13s.3: 0.0013→0.0011 (activate earlier)
    },
    "BEAR_RANGE": {
        "micro_tp": 0.0008,    # V10.13s.3: 0.0010→0.0008 (tighter for range trades)
        "trailing_activation": 0.0011,  # V10.13s.3: 0.0013→0.0011 (activate earlier)
    },
    "RANGING": {
        "micro_tp": 0.0009,    # V10.13s.3: 0.0011→0.0009 (general range tuned)
        "trailing_activation": 0.0013,  # V10.13s.3: 0.0015→0.0013 (catch swings sooner)
    },
    "QUIET_RANGE": {
        "micro_tp": 0.0007,    # V10.13s.3: 0.0008→0.0007 (tight for dead markets)
        "trailing_activation": 0.0008,  # V10.13s.3: 0.0010→0.0008 (sensitive activation)
    },
    "UNCERTAIN": {
        "micro_tp": 0.0010,    # V10.13s.3: 0.0012→0.0010 (match new base)
        "trailing_activation": 0.0015,  # V10.13s.3: 0.0018→0.0015 (match new base)
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
# V10.13s.3: Harvest optimization patch
# Previous: V10.13o scratch (105s, 0.0016) still caused 82% scratch dominance
# Problem: 5589 partial25_near_miss events show trades come close but don't trigger
# Solution: Extend scratch time to 120s (give partial triggers more time)
#           Tighten band to 0.0012 (more selective scratch classification)
SCRATCH_MIN_AGE_S    = 120     # V10.13s.3: 105→120 (5s more for partial triggers to fire)
SCRATCH_MAX_PNL      = 0.0012  # V10.13s.3: 0.0016→0.0012 (tighter band, fewer false scratches)


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

    V10.13m: Each branch is audited — we track why it passed/failed.
    """

    # V10.13m: Exit attribution audit counters
    _exit_audit_rejections = {}    # {branch:reason: count}
    _timeout_preemptions = {}      # {scratch/micro/trail/partial near_miss: count}
    _exit_winners = {}             # {exit_type: count}

    def __init__(self):
        """Initialize audit counters."""
        # Branch rejection counters: why positions didn't exit
        self._exit_audit_rejections = {
            "MICRO_TP:below_threshold": 0,
            "MICRO_TP:negative_pnl": 0,
            "BREAKEVEN_STOP:non_positive_pnl": 0,
            "BREAKEVEN_STOP:below_trigger": 0,
            "PARTIAL_TP_25:below_threshold": 0,
            "PARTIAL_TP_50:below_threshold": 0,
            "PARTIAL_TP_75:below_threshold": 0,
            "EARLY_STOP:no_loss": 0,
            "EARLY_STOP:below_threshold": 0,
            "TRAILING_STOP:insufficient_peak": 0,
            "TRAILING_STOP:insufficient_retrace": 0,
            "SCRATCH_EXIT:too_young": 0,
            "SCRATCH_EXIT:pnl_outside_band": 0,
            "STAGNATION_EXIT:too_young": 0,
            "STAGNATION_EXIT:below_stagnation_pnl": 0,
        }

        # Near-miss tracking: timeout won while branch was close
        self._timeout_preemptions = {
            "scratch_near_miss": 0,
            "micro_near_miss": 0,
            "trail_near_miss": 0,
            "partial25_near_miss": 0,
            "partial50_near_miss": 0,
            "partial75_near_miss": 0,
        }

        # Exit winners: which branches actually fired
        self._exit_winners = {
            "MICRO_TP": 0,
            "BREAKEVEN_STOP": 0,
            "PARTIAL_TP_25": 0,
            "PARTIAL_TP_50": 0,
            "PARTIAL_TP_75": 0,
            "EARLY_STOP": 0,
            "TRAIL_PROFIT": 0,
            "SCRATCH_EXIT": 0,
            "STAGNATION_EXIT": 0,
        }

    def _log_exit_eval(self, symbol: str, direction: str, branch: str, decision: str,
                      age_s: int, pnl_pct: float, mfe_pct: float,
                      threshold: Optional[float] = None, observed: Optional[float] = None,
                      reason: str = ""):
        """
        V10.13m: Log why a branch PASS/FAIL. Only logs if EXIT_AUDIT_DEBUG enabled.
        Keeps output compact but informative.
        """
        if not EXIT_AUDIT_DEBUG:
            return

        threshold_str = f" threshold={threshold*100:.3f}%" if threshold is not None else ""
        observed_str = f" observed={observed*100:.3f}%" if observed is not None else ""
        reason_str = f" reason={reason}" if reason else ""

        log.debug(f"[EXIT_AUDIT] {symbol} {direction} age={age_s}s pnl={pnl_pct*100:.4f}% "
                 f"mfe={mfe_pct*100:.4f}% branch={branch} {decision}{threshold_str}"
                 f"{observed_str}{reason_str}")

    def evaluate(self, position: Position, regime: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        V10.13m+g+j: Evaluate in priority order — multi-level harvest path.
        V10.13m: Track why branches PASS/FAIL for observability.
        Returns first matching exit condition or None.

        Args:
            position: Position data
            regime: Market regime (for adaptive thresholds)
        """
        # Update regime for adaptive thresholds
        if regime:
            position.regime = regime

        # V10.13m: Evaluate each branch and track results
        exit_result = (
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

        # V10.13m: Emit winner summary if exit found
        if exit_result:
            exit_type = exit_result.get("exit_type", "UNKNOWN")
            self._exit_winners[exit_type] = self._exit_winners.get(exit_type, 0) + 1

            tp_progress = 0.0
            if position.direction == "LONG":
                tp_move = (position.tp - position.entry_price) / position.entry_price
            else:
                tp_move = (position.entry_price - position.tp) / position.entry_price

            if tp_move > 0:
                tp_progress = position.pnl_pct / tp_move

            log.debug(f"[EXIT_WINNER] {position.symbol} {position.direction} "
                     f"reason={exit_type} age={position.age_seconds} "
                     f"pnl={position.pnl_pct*100:.5f}% mfe={position.max_favorable_pnl*100:.5f}% "
                     f"tp_prog={tp_progress*100:.1f}% regime={position.regime}")

        return exit_result

    def _check_micro_tp(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13m+j: Ultra-tight profit harvest at regime-adaptive level.
        Base 0.1%, but ranges use 0.08-0.12% depending on conditions.
        V10.13m: Log why branch PASS/FAIL.
        """
        threshold = get_harvest_threshold(position.regime, "micro_tp")

        # V10.13m: Log if below threshold
        if position.pnl_pct < threshold:
            if position.pnl_pct >= 0:
                self._exit_audit_rejections["MICRO_TP:below_threshold"] += 1
                # Near-miss: if threshold is close (within 50% distance)
                if position.pnl_pct >= threshold * 0.5:
                    self._timeout_preemptions["micro_near_miss"] += 1
                self._log_exit_eval(position.symbol, position.direction, "MICRO_TP", "FAIL",
                                   position.age_seconds, position.pnl_pct, position.max_favorable_pnl,
                                   threshold=threshold, observed=position.pnl_pct,
                                   reason="below_threshold")
            else:
                self._exit_audit_rejections["MICRO_TP:negative_pnl"] += 1
                self._log_exit_eval(position.symbol, position.direction, "MICRO_TP", "FAIL",
                                   position.age_seconds, position.pnl_pct, position.max_favorable_pnl,
                                   reason="negative_pnl")
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
        V10.13m+: Lock gains early by moving SL to break-even once trade reaches 20% of TP.
        This doesn't exit immediately but signals SL adjustment.
        Fires only once per position (marked in position state).
        Only for profitable trades — protects against loss swings.
        """
        if position.pnl_pct <= 0:
            self._exit_audit_rejections["BREAKEVEN_STOP:non_positive_pnl"] += 1
            return None

        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price

        if tp_move <= 0:
            return None

        trigger_level = BREAKEVEN_TRIGGER_PCT * tp_move

        # Trigger break-even once at 20% of TP progress
        if position.pnl_pct >= trigger_level:
            return {
                "exit_type": "BREAKEVEN_STOP",
                "reason": (f"Break-even lock: {position.pnl_pct*100:.2f}% "
                           f"(20% of {tp_move*100:.2f}% target) — SL moves to entry"),
                "exit_pnl_pct": position.pnl_pct,
                "adjusted_sl": position.entry_price,  # Move SL to entry (+ 1 tick in executor)
                "confidence": 0.75,
            }

        self._exit_audit_rejections["BREAKEVEN_STOP:below_trigger"] += 1
        return None

    def _check_partial_tp_25(self, position: Position) -> Optional[Dict[str, Any]]:
        """V10.13m+: Harvest 25% of TP target for early profit lock."""
        if position.pnl_pct <= 0:
            return None

        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price

        if tp_move <= 0:
            return None

        threshold = _PARTIAL_TP_25_BASE * tp_move
        if position.pnl_pct >= threshold:
            return {
                "exit_type": "PARTIAL_TP_25",
                "reason": (f"Partial TP (25%) {position.pnl_pct*100:.2f}% "
                           f"(25% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.82,
            }

        self._exit_audit_rejections["PARTIAL_TP_25:below_threshold"] += 1
        # Near-miss if within 50% of threshold
        if position.pnl_pct >= threshold * 0.5:
            self._timeout_preemptions["partial25_near_miss"] += 1
        return None

    def _check_partial_tp_50(self, position: Position) -> Optional[Dict[str, Any]]:
        """V10.13m+: Harvest 50% of TP target — mid-point profit take."""
        if position.pnl_pct <= 0:
            return None

        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price

        if tp_move <= 0:
            return None

        threshold = _PARTIAL_TP_50_BASE * tp_move
        if position.pnl_pct >= threshold:
            return {
                "exit_type": "PARTIAL_TP_50",
                "reason": (f"Partial TP (50%) {position.pnl_pct*100:.2f}% "
                           f"(50% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.85,
            }

        self._exit_audit_rejections["PARTIAL_TP_50:below_threshold"] += 1
        if position.pnl_pct >= threshold * 0.5:
            self._timeout_preemptions["partial50_near_miss"] += 1
        return None

    def _check_partial_tp_75(self, position: Position) -> Optional[Dict[str, Any]]:
        """V10.13m+: Harvest 75% of TP target — late harvest before full TP."""
        if position.pnl_pct <= 0:
            return None

        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price

        if tp_move <= 0:
            return None

        threshold = _PARTIAL_TP_75_BASE * tp_move
        if position.pnl_pct >= threshold:
            return {
                "exit_type": "PARTIAL_TP_75",
                "reason": (f"Partial TP (75%) {position.pnl_pct*100:.2f}% "
                           f"(75% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.88,
            }

        self._exit_audit_rejections["PARTIAL_TP_75:below_threshold"] += 1
        if position.pnl_pct >= threshold * 0.5:
            self._timeout_preemptions["partial75_near_miss"] += 1
        return None

    def _check_early_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """V10.13m+: Cut losers at 60% of SL distance — both directions."""
        if position.pnl_pct >= 0:
            self._exit_audit_rejections["EARLY_STOP:no_loss"] += 1
            return None

        if position.direction == "LONG":
            sl_dist = (position.entry_price - position.sl) / position.entry_price
        else:
            sl_dist = (position.sl - position.entry_price) / position.entry_price

        if sl_dist <= 0:
            return None

        threshold = EARLY_STOP_THRESHOLD * sl_dist
        if abs(position.pnl_pct) >= threshold:
            return {
                "exit_type": "EARLY_STOP",
                "reason": (f"Early stop {position.pnl_pct*100:.2f}% "
                           f"(60% of SL dist {sl_dist*100:.2f}%)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.90,
            }

        self._exit_audit_rejections["EARLY_STOP:below_threshold"] += 1
        return None

    def _check_trailing_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13m+j: Retracement-based trailing stop with regime-adaptive activation.
        Activation threshold (0.20%-0.35% depending on regime).
        Requires trade to have been >= 0.1% profitable (max_favorable_pnl).
        Fires when current PnL retraces 50%+ from peak, or crosses back to 0.
        V10.13m: Log why trailing PASS/FAIL.
        """
        if position.max_favorable_pnl < TRAILING_MIN_PEAK:
            self._exit_audit_rejections["TRAILING_STOP:insufficient_peak"] += 1
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

        self._exit_audit_rejections["TRAILING_STOP:insufficient_retrace"] += 1
        # Near-miss if within 10% of retrace threshold
        if position.pnl_pct < retrace_threshold * 1.1:
            self._timeout_preemptions["trail_near_miss"] += 1
        return None

    def _check_scratch(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13m+f: Scratch near-flat trades after 3 min.
        Releases capital from stagnant non-directional positions without waiting for
        the full timeout. Fires when |pnl| < 0.15% after 90 seconds.
        V10.13m: Log why scratch PASS/FAIL.
        """
        if position.age_seconds < SCRATCH_MIN_AGE_S:
            self._exit_audit_rejections["SCRATCH_EXIT:too_young"] += 1
            return None

        if abs(position.pnl_pct) < SCRATCH_MAX_PNL:
            return {
                "exit_type": "SCRATCH_EXIT",
                "reason": (f"Scratch: flat after {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.3f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.70,
            }

        self._exit_audit_rejections["SCRATCH_EXIT:pnl_outside_band"] += 1
        # Near-miss if within 10% of pnl band threshold
        if abs(position.pnl_pct) < SCRATCH_MAX_PNL * 1.1:
            self._timeout_preemptions["scratch_near_miss"] += 1
        return None

    def _check_stagnation(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13m+f: Exit completely stuck positions after 4 min.
        V10.13f: reduced from 30 min (was dead code — timeout fires at 5 min max).
        Runs after scratch — only catches trades with |pnl| >= 0.15%.
        V10.13m: Log why stagnation PASS/FAIL.
        """
        if position.age_seconds < STAGNATION_MIN_AGE_S:
            self._exit_audit_rejections["STAGNATION_EXIT:too_young"] += 1
            return None

        if abs(position.pnl_pct) < STAGNATION_MAX_PNL:
            return {
                "exit_type": "STAGNATION_EXIT",
                "reason": (f"Stagnant {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.4f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.80,
            }

        self._exit_audit_rejections["STAGNATION_EXIT:below_stagnation_pnl"] += 1
        return None

    def get_audit_summary(self) -> Dict[str, Any]:
        """
        V10.13m: Return exit audit telemetry for dashboard display.
        Shows winners, near-misses, and top rejection reasons.
        """
        # Top rejections
        top_rejects = sorted(
            [(k, v) for k, v in self._exit_audit_rejections.items() if v > 0],
            key=lambda x: x[1],
            reverse=True
        )[:5]

        return {
            "winners": {k: v for k, v in self._exit_winners.items() if v > 0},
            "near_miss": {k: v for k, v in self._timeout_preemptions.items() if v > 0},
            "top_rejects": dict(top_rejects),
        }

    def reset_audit_counters(self):
        """V10.13m: Reset audit counters (useful for periodic snapshots)."""
        self._exit_audit_rejections = {k: 0 for k in self._exit_audit_rejections.keys()}
        self._timeout_preemptions = {k: 0 for k in self._timeout_preemptions.keys()}
        self._exit_winners = {k: 0 for k in self._exit_winners.keys()}


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
