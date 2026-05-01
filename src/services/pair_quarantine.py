"""
V10.13j: Pair-Level Dynamic Quarantine for Toxic Symbol-Regime Buckets

Suppress trading in clearly toxic symbols that destroy portfolio expectancy.
Uses reversible quarantine (not permanent ban) with timeout-based recovery.

Detection criteria:
  - n >= 6 trades accumulated
  - WR <= 20%
  - EV negative (structurally losing)

Effect when quarantined:
  - Position size multiplier: 0.25x (quarter-sized trades only)
  - Duration: 30-60 minutes (reversible if regime/symbol conditions change)
  - Can be manually lifted via recover() or automatically after timeout

Example:
  DOT/BEAR_TREND showing 0% WR after 8 trades is toxic → 0.25x until recovery
"""

import logging
import time
from typing import Dict, Tuple, Optional, List

log = logging.getLogger(__name__)

# Global state
_quarantine: Dict[Tuple[str, str], float] = {}  # (sym, regime) -> quarantine_until_ts
_quarantine_cooldown = 3600  # 60 minutes: duration of quarantine
_recovery_check_interval = 60  # Check recovery status every 60s


class PairQuarantine:
    """Manage reversible quarantine for toxic pairs."""

    def __init__(self):
        self.quarantined_pairs = {}  # (sym, regime) -> {until_ts, reason, wr, n}
        self._lock = threading.Lock()  # BUG-023 fix: thread-safe access
    
    def check_and_quarantine(
        self,
        sym: str,
        regime: str,
        wr: float,
        n: int,
        ev: float,
    ) -> Tuple[bool, Optional[str]]:
        """Check if pair-regime should be quarantined. Thread-safe (BUG-023 fix)."""
        key = (sym, regime)
        now = time.time()
        with self._lock:
            if key in self.quarantined_pairs:
                if now >= self.quarantined_pairs[key]["until_ts"]:
                    log.info(
                        f"[QUARANTINE] {sym}/{regime} recovered "
                        f"(was WR {self.quarantined_pairs[key]['wr']:.0%}, n={self.quarantined_pairs[key]['n']})"
                    )
                    del self.quarantined_pairs[key]
                else:
                    remaining = self.quarantined_pairs[key]["until_ts"] - now
                    return True, f"Quarantined ({remaining:.0f}s remain): {self.quarantined_pairs[key]['reason']}"

            if n >= 5 and wr <= 0.20 and ev <= -0.001:
                reason = f"Toxic: WR={wr:.0%}, n={n}, EV={ev:.3f}"
                self.quarantined_pairs[key] = {
                    "until_ts": now + _quarantine_cooldown,
                    "reason": reason,
                    "wr": wr,
                    "n": n,
                    "ev": ev,
                }
                log.warning(f"[QUARANTINE] {sym}/{regime} quarantined: {reason}")
                return True, reason

            return False, None

    def get_size_multiplier(self, sym: str, regime: str) -> float:
        """Get size multiplier for symbol-regime pair. Thread-safe."""
        key = (sym, regime)
        now = time.time()
        with self._lock:
            if key in self.quarantined_pairs:
                if now >= self.quarantined_pairs[key]["until_ts"]:
                    del self.quarantined_pairs[key]
                    return 1.0
                return 0.25
        return 1.0

    def recover(self, sym: str, regime: str) -> bool:
        """Manually recover a pair (for testing or admin override)."""
        key = (sym, regime)
        with self._lock:
            if key in self.quarantined_pairs:
                del self.quarantined_pairs[key]
                log.info(f"[QUARANTINE] {sym}/{regime} manually recovered")
            return True
        return False
    
    def status(self) -> Dict[str, List[str]]:
        """Get status of all quarantined pairs."""
        now = time.time()
        active = []
        for (sym, regime), data in list(self.quarantined_pairs.items()):
            if now < data["until_ts"]:
                active.append(f"{sym}/{regime}: {data['reason']} ({data['until_ts']-now:.0f}s remain)")
        return {"quarantined": active}


# Global instance
_quarantine_manager = PairQuarantine()


def should_quarantine(
    sym: str,
    regime: str,
    wr: float,
    n: int,
    ev: float,
) -> Tuple[bool, Optional[str]]:
    """Check if pair-regime should be quarantined."""
    return _quarantine_manager.check_and_quarantine(sym, regime, wr, n, ev)


def get_size_mult(sym: str, regime: str) -> float:
    """Get size multiplier for quarantine state."""
    return _quarantine_manager.get_size_multiplier(sym, regime)


def recover_pair(sym: str, regime: str) -> bool:
    """Manually recover a pair."""
    return _quarantine_manager.recover(sym, regime)


def quarantine_status() -> Dict[str, List[str]]:
    """Get quarantine status."""
    return _quarantine_manager.status()
