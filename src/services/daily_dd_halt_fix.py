"""
Rejection Fix 1: Graduated Drawdown Controller

DAILY_DD_HALT=383(36%) → graduated tiers, not binary halt.

Current: hits hard halt if daily DD > 1%
Better: graduated impact based on severity
  <1%  → full trading
  1-2% → 60% size
  2-3% → 30% size
  >3%  → halt + recovery mode

Recovery: 3 consecutive wins → step back up one tier
"""

from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)


class GraduatedDrawdownController:
    """Smart daily drawdown control with graduated tiers."""

    # (DD threshold, size multiplier, name)
    TIERS = [
        (0.01, 1.0, "NORMAL"),
        (0.02, 0.60, "CAUTION"),
        (0.03, 0.30, "WARNING"),
        (1.0, 0.0, "HALT"),
    ]
    RECOVERY_TRADES = 3

    def __init__(self, balance: float = 10000):
        self._bal = balance
        self._daily_pnl: dict = {}  # date -> cumulative P&L pct
        self._session_bal: dict = {}  # date -> opening balance
        self._consec_wins = 0
        self._override = None  # Temp tier override for recovery

    def record(self, pnl_pct: float, balance: float):
        """Record a trade result."""
        today = date.today()
        if today not in self._session_bal:
            self._session_bal[today] = balance
            self._daily_pnl[today] = 0.0

        self._daily_pnl[today] += pnl_pct

        # Check recovery
        _, sz, _ = self._tier(today)
        if sz == 0.0:
            # In HALT: count consecutive wins for recovery
            self._consec_wins = (self._consec_wins + 1) if pnl_pct > 0 else 0
            if self._consec_wins >= self.RECOVERY_TRADES:
                self._override = 2  # Jump to WARNING tier
                self._consec_wins = 0
                logger.info(
                    f"DD_RECOVERY: {self.RECOVERY_TRADES} wins → WARNING tier"
                )
        else:
            self._consec_wins = 0
            self._override = None

    def check(self, balance: float) -> tuple:
        """
        Check current DD status.
        
        Returns: (is_trading_allowed, size_multiplier, status_msg)
        """
        today = date.today()
        if today not in self._session_bal:
            self._session_bal[today] = balance
            self._daily_pnl[today] = 0.0

        i, sz, name = self._tier(today)

        # Apply recovery override
        if self._override is not None and self._override < i:
            i = self._override
            _, sz, name = self.TIERS[i]

        dd = abs(self._daily_pnl.get(today, 0.0))
        return (
            sz > 0,
            sz,
            f"DD_{name}:dd={dd:.2f}%_size={sz:.0%}",
        )

    def _tier(self, today: date) -> tuple:
        """Get tier for given date."""
        dd = abs(self._daily_pnl.get(today, 0.0)) / 100
        for i, (t, s, n) in enumerate(self.TIERS):
            if dd <= t:
                return i, s, n
        return len(self.TIERS) - 1, 0.0, "HALT"

    def summary(self) -> dict:
        """Status summary."""
        today = date.today()
        _, sz, name = self._tier(today)
        return {
            "daily_pnl": round(self._daily_pnl.get(today, 0.0), 4),
            "tier": name,
            "size_mult": sz,
            "recovery_wins": self._consec_wins,
        }
