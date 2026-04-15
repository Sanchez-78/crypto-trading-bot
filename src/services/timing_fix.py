"""
Rejection Fix 2: Timing Filter Auto-Calibration

TIMING=514(+55% worse) → aggressive windows 50-95% + diagnostic.

Current: timing window too tight, blocks good trades
Better: aggressive windows by default, tighten after proven success

Windows:
  "low" (slow markets):     50%
  "normal":                 70%
  "high" (volatile):        88%
  "extreme" (very volatile): 95%

Auto-tightening: after 100 trades with WR>50%, narrow to 30-70-85%
"""

from datetime import datetime
from collections import deque, Counter
import numpy as np
import logging

logger = logging.getLogger(__name__)


class TimingDiagnostic:
    """Track rejection patterns to identify root causes."""

    def __init__(self):
        self._log: deque = deque(maxlen=2000)

    def record(self, sym: str, tf: str, frac: float, hour: int, action: str, regime: str):
        """Record a timing decision."""
        self._log.append({"s": sym, "tf": tf, "frac": frac, "h": hour, "a": action, "r": regime})

    def analyze(self) -> dict:
        """Analyze rejection patterns."""
        if not self._log:
            return {}

        rej = [e for e in self._log if e["a"] == "REJECT"]
        if not rej:
            return {"rej": 0}

        fracs = np.array([e["frac"] for e in rej])
        return {
            "n_rej": len(rej),
            "avg_frac": round(float(fracs.mean()), 3),
            "pct_over80": f"{(fracs > 0.8).mean():.0%}",
            "worst_hours": dict(Counter(e["h"] for e in rej).most_common(5)),
            "worst_regime": dict(Counter(e["r"] for e in rej).most_common()),
            "ROOT_CAUSE": (
                "SIGNAL_LAG:signals arrive 80%+ into candle"
                if (fracs > 0.8).mean() > 0.5
                else "THRESHOLD_TIGHT:signals early but window rejects"
                if fracs.mean() < 0.4
                else "PROCESSING_DELAY:mid-candle but lag adds overhead"
            ),
        }


class AggressiveTimingOverride:
    """Aggressive timing with auto-calibration."""

    WINDOWS = {
        "low": 0.50,
        "normal": 0.70,
        "high": 0.88,
        "extreme": 0.95,
    }
    TIGHT = {
        "low": 0.30,
        "normal": 0.50,
        "high": 0.70,
        "extreme": 0.85,
    }
    TIGHTEN_AFTER = 100
    TIGHTEN_WR = 0.50

    def __init__(self, candle_s: int = 3600, diag: TimingDiagnostic = None):
        self.cs = candle_s
        self.diag = diag or TimingDiagnostic()
        self._n = 0
        self._wins = 0
        self._tight = False

    def evaluate(
        self,
        sig_t: datetime,
        open_t: datetime,
        price: float,
        open_: float,
        high: float,
        low: float,
        atr: float,
        history: list,
        sym: str = "",
        tf: str = "1h",
    ) -> dict:
        """
        Evaluate if signal timing is acceptable.
        
        Returns: {action, size, regime, frac, max_t, mode}
        """
        # Where in candle did signal arrive? (0-1)
        frac = (sig_t - open_t).total_seconds() / self.cs
        
        # Volatility regime
        atr_pct = (atr / price) * 100 if price > 0 else 0
        regime = self._regime(atr_pct, history)
        
        # Pick window based on volatility regime
        w = (self.TIGHT if self._tight else self.WINDOWS)[regime]
        
        # Price action since candle open
        disp = abs(price - open_) / atr if atr > 0 else 999
        rr = (high - low) / atr if atr > 0 else 0
        
        # Decision
        if frac <= w and rr < 0.92:
            action = "ENTER"
            size = 1.0
        elif disp < 0.40:
            action = "ENTER_REDUCED"
            size = 0.5
        else:
            action = "REJECT"
            size = 0.0
        
        self.diag.record(sym, tf, round(frac, 3), sig_t.hour, action, regime)
        
        return {
            "action": action,
            "size": size,
            "regime": regime,
            "frac": round(frac, 3),
            "max_t": w,
            "mode": "TIGHT" if self._tight else "AGGRESSIVE",
        }

    def record_result(self, won: bool):
        """Record trade outcome for auto-calibration."""
        self._n += 1
        if won:
            self._wins += 1
        
        if (
            self._n >= self.TIGHTEN_AFTER
            and self._wins / self._n >= self.TIGHTEN_WR
            and not self._tight
        ):
            self._tight = True
            logger.info(f"TIMING auto-tightened: n={self._n} wr={self._wins/self._n:.0%}")

    def _regime(self, atr_pct: float, h: list) -> str:
        """Detect volatility regime."""
        if len(h) < 20:
            return "normal"
        s = sorted(h)
        n = len(s)
        if atr_pct > s[int(n * 0.95)]:
            return "extreme"
        elif atr_pct > s[int(n * 0.75)]:
            return "high"
        elif atr_pct < s[int(n * 0.25)]:
            return "low"
        else:
            return "normal"
