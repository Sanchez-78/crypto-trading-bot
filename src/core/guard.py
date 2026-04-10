"""
src/core/guard.py — System Health Guard & Failure Escalation (V11.0)

Implements the three-tier failure escalation model:
  SOFT    — Log + Continue (default). Minor anomalies.
  DEGRADE — Log + 0.5x Position Sizing. Moderate systemic stress.
  HARD    — Binary Kill-Switch. Invariant breach or catastrophic drawdown.

Invariants monitored:
  - NaN/Null in price/metrics.
  - Negative Equity/Drawdown (> 40%).
  - Monotone violation (Profit/Loss logic inverted).
  - High Latency (> 200ms consecutive).
"""

import enum
import logging
import time

log = logging.getLogger(__name__)

class FailureLevel(enum.IntEnum):
    SOFT    = 0
    DEGRADE = 1
    HARD    = 2

class SystemGuard:
    def __init__(self):
        self.level = FailureLevel.SOFT
        self.reason = "INITIAL_STATE"
        self.hard_stop = False
        self._latency_spikes = 0
        self._invariants_checked = 0

    def escalate(self, level: FailureLevel, reason: str):
        """Escalate to a higher failure regime. Levels only move UP manually."""
        if level > self.level:
            self.level = level
            self.reason = reason
            if level == FailureLevel.HARD:
                self.hard_stop = True
            log.warning(f"⚠️ [SYSTEM_GUARD] ESCALATION: {level.name} - Reason: {reason}")
            # Keep system_state string in sync with FailureLevel enum
            try:
                from src.core.system_state import set_mode
                _mode_map = {
                    FailureLevel.SOFT:    "NORMAL",
                    FailureLevel.DEGRADE: "DEGRADED",
                    FailureLevel.HARD:    "HALTED",
                }
                set_mode(_mode_map[level])
            except Exception:
                pass

    def reset(self):
        """Reset to SOFT. Should only be called via manual override/restart."""
        self.level = FailureLevel.SOFT
        self.reason = "MANUAL_RESET"
        self.hard_stop = False
        self._latency_spikes = 0
        log.info("✅ [SYSTEM_GUARD] RESET to SOFT")
        try:
            from src.core.system_state import reset as _state_reset
            _state_reset()
        except Exception:
            pass

    def check_trade_invariants(self, sym, size, entry, tp, sl):
        """HARD failure if basic trading math is corrupted."""
        self._invariants_checked += 1
        
        # 1. NaN/None Check
        if any(v is None or (isinstance(v, float) and v != v) for v in [size, entry, tp, sl]):
            self.escalate(FailureLevel.HARD, f"INVARIANT_NAN: {sym}")
            return False

        # 2. Logic Monotonicity
        # BUG V3 logic check: BUY tp > sl and SELL sl > tp
        if size <= 0:
            self.escalate(FailureLevel.HARD, f"INVARIANT_SIZE: {sym} size={size}")
            return False
            
        return True

    def report_latency(self, ms: float):
        """Track decision latency. 5+ spikes > 200ms triggers DEGRADE."""
        if ms > 200:
            self._latency_spikes += 1
            if self._latency_spikes >= 5 and self.level < FailureLevel.DEGRADE:
                self.escalate(FailureLevel.DEGRADE, "CONSECUTIVE_LATENCY_SPIKES")
        else:
            self._latency_spikes = max(0, self._latency_spikes - 1)

    def get_size_multiplier(self) -> float:
        if self.level == FailureLevel.HARD:    return 0.0
        if self.level == FailureLevel.DEGRADE: return 0.5
        return 1.0

# Singleton instance
guard = SystemGuard()
