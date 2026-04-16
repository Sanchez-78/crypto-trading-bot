"""
Anomaly Detector v1 — Real-time failure detection.

Monitors:
- EQUITY_DROP: >3% drop from last peak (hard signal: bug/crash)
- STALL: No trades for 15+ minutes (pipeline dead)
- NO_SIGNALS: Zero signals generated (filter pipeline failed)
- HIGH_DRAWDOWN: >35% daily loss (system in crisis)

Each anomaly triggers appropriate auto-response.
"""

import logging

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Monitor system health and detect anomalies."""

    # Thresholds
    EQUITY_DROP_PCT = 0.03  # 3% drop = anomaly
    STALL_SECONDS = 900  # 15 min idle = stall
    HIGH_DD = 0.35  # 35% drawdown = crisis
    
    def __init__(self):
        self.last_equity = 1.0
        self.consecutive_no_signals = 0
        self.anomaly_count = 0

    def check(self, state) -> list:
        """
        Check for anomalies in current state.
        
        Returns: list of anomaly codes
        """
        anomalies = []

        # ────────────────────────────────────────────────────────────────────
        # 1. EQUITY DROP (hard signal: algo crashed or bad trade)
        # ────────────────────────────────────────────────────────────────────
        if state.equity < self.last_equity * (1 - self.EQUITY_DROP_PCT):
            anomalies.append("EQUITY_DROP")
            logger.warning(
                f"🚨 ANOMALY: EQUITY_DROP {state.equity:.6f} < "
                f"{self.last_equity * (1-self.EQUITY_DROP_PCT):.6f}"
            )

        # ────────────────────────────────────────────────────────────────────
        # 2. STALL (no trades → pipeline might be dead)
        # ────────────────────────────────────────────────────────────────────
        if hasattr(state, "no_trade_duration") and state.no_trade_duration > self.STALL_SECONDS:
            anomalies.append("STALL")
            logger.warning(f"🚨 ANOMALY: STALL {state.no_trade_duration}s > {self.STALL_SECONDS}s")

        # ────────────────────────────────────────────────────────────────────
        # 3. NO SIGNALS (signal generation pipeline dead)
        # ────────────────────────────────────────────────────────────────────
        signal_count = getattr(state, "signal_count", 0)
        if signal_count == 0:
            self.consecutive_no_signals += 1
            if self.consecutive_no_signals >= 3:
                anomalies.append("NO_SIGNALS")
                logger.debug(f"anomaly: NO_SIGNALS {self.consecutive_no_signals} cycles")
        else:
            self.consecutive_no_signals = 0

        # ────────────────────────────────────────────────────────────────────
        # 4. EXTREME DRAWDOWN (system in crisis mode)
        # ────────────────────────────────────────────────────────────────────
        if state.drawdown > self.HIGH_DD:
            anomalies.append("HIGH_DRAWDOWN")
            logger.warning(f"🚨 ANOMALY: HIGH_DRAWDOWN {state.drawdown:.2%} > {self.HIGH_DD:.2%}")

        # Update tracking
        self.last_equity = state.equity
        if anomalies:
            self.anomaly_count += 1

        return anomalies

    def status(self) -> dict:
        """Current detector status."""
        return {
            "last_equity": round(self.last_equity, 6),
            "consecutive_no_signals": self.consecutive_no_signals,
            "total_anomalies_detected": self.anomaly_count,
        }
