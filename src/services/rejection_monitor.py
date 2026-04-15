"""
Rejection Fix 5: Rejection Monitor (prevents filter dominance)

Prevents any single filter dominating again (>35% = alert).

Current: TIMING was rejecting 514(48%) of all signals
Better: monitor rejection distribution, alert if imbalanced

Thresholds:
  <20% rate:       OK
  20-35% rate:     Caution
  >35% rate:       Alert (likely single filter dominance)
  1 filter >35%:   Critical alert
"""

from collections import Counter, deque
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RejectionMonitor:
    """Track rejection distribution to detect filter dominance."""

    MAX_SINGLE = 0.35  # Single filter shouldn't reject >35%
    TARGET_RATE = 0.20  # Target overall rejection rate

    def __init__(self):
        self._log: deque = deque(maxlen=5000)
        self._alerts: list = []

    def record(self, reason: str, symbol: str = "", hour: int = 0):
        """Record a rejection."""
        self._log.append(
            {"r": reason, "s": symbol, "h": hour, "ts": datetime.now()}
        )
        self._check()

    def record_pass(self):
        """Record a trade that passed."""
        self._log.append({"r": "PASS", "ts": datetime.now()})

    def _check(self):
        """Check for filter dominance."""
        recent = [e for e in self._log if (datetime.now() - e["ts"]) < timedelta(hours=1)]
        rej = [e for e in recent if e["r"] != "PASS"]
        
        if len(rej) < 20:
            return

        for r, n in Counter(e["r"] for e in rej).items():
            pct = n / len(rej)
            if pct > self.MAX_SINGLE:
                msg = f"ALERT:{r}={pct:.0%}>35% of rejections({n}/{len(rej)})"
                if msg not in self._alerts:
                    self._alerts.append(msg)
                    logger.warning(msg)

    def report(self, hours: float = 24) -> dict:
        """Rejection distribution report."""
        cut = datetime.now() - timedelta(hours=hours)
        rec = [e for e in self._log if e["ts"] > cut]
        rej = [e for e in rec if e["r"] != "PASS"]
        total = len(rec)
        rate = len(rej) / total if total > 0 else 0

        counts = Counter(e["r"] for e in rej)

        return {
            "total": total,
            "rejected": len(rej),
            "rate": f"{rate:.0%}",
            "status": "🚨" if rate > 0.60 else "⚠️" if rate > 0.35 else "✅",
            "breakdown": {
                r: {"n": n, "pct": f"{n/len(rej):.0%}"}
                for r, n in counts.most_common()
            }
            if rej
            else {},
            "alerts": self._alerts[-5:],
        }
