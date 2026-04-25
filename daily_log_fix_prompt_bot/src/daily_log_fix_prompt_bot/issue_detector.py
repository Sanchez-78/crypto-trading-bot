"""Detect issues from parsed log data."""

import logging
from typing import List, Dict, Any
from .models import Issue, Severity

log = logging.getLogger(__name__)


class IssueDetector:
    """Detect trading/system issues from parsed logs."""

    def __init__(self):
        """Initialize detector."""
        self.issues: List[Issue] = []

    def detect(self, events: List[Dict[str, Any]], metrics: Dict[str, Any],
               raw_logs: str) -> List[Issue]:
        """Detect issues from parsed log data."""
        self.issues = []

        # Run all detectors
        self._detect_signal_stall(events, metrics, raw_logs)
        self._detect_high_rejection_rate(events, metrics, raw_logs)
        self._detect_timeout_overload(metrics, raw_logs)
        self._detect_pnl_anomaly(events, metrics, raw_logs)
        self._detect_version_mismatch(raw_logs)
        self._detect_firebase_issues(metrics, raw_logs)
        self._detect_redis_issues(metrics, raw_logs)
        self._detect_exceptions(events, metrics, raw_logs)

        return self.issues

    def _detect_signal_stall(self, events: List[Dict[str, Any]], metrics: Dict[str, Any],
                             raw_logs: str) -> None:
        """Detect when no signals are being generated."""
        if metrics.get("signals", 0) == 0:
            self.issues.append(Issue(
                id="NO_SIGNALS",
                severity=Severity.CRITICAL,
                confidence=1.0,
                title="No signals generated in analysis period",
                evidence=["No signal_created events found in logs"],
                probable_root_cause="Signal generator stalled, WebSocket dead, or data feed frozen",
                recommended_fix="Check market_stream WebSocket, verify Binance connectivity, restart if hung",
                likely_files=["src/services/market_stream.py", "src/services/signal_generator.py"],
                validation_steps=["Check WebSocket connection status", "Verify Binance API is accessible"],
            ))

    def _detect_high_rejection_rate(self, events: List[Dict[str, Any]], metrics: Dict[str, Any],
                                    raw_logs: str) -> None:
        """Detect high decision rejection rate."""
        decisions = metrics.get("decisions", 1)
        rejections = metrics.get("rejections", 0)
        rate = rejections / decisions if decisions > 0 else 0

        if rate > 0.8:
            self.issues.append(Issue(
                id="HIGH_REJECTION_RATE",
                severity=Severity.HIGH,
                confidence=0.9,
                title=f"High rejection rate: {rate:.0%} of decisions rejected",
                evidence=[f"Rejections: {rejections}/{decisions}"],
                probable_root_cause="EV threshold too high, regime filter too strict, or scoring gate too aggressive",
                recommended_fix="Review EV threshold in config, check calibration, verify regime classification",
                likely_files=["src/services/realtime_decision_engine.py", "src/services/calibration_guard.py"],
                validation_steps=["Check adaptive threshold value", "Verify gate thresholds"],
            ))

    def _detect_timeout_overload(self, metrics: Dict[str, Any], raw_logs: str) -> None:
        """Detect excessive timeout exits."""
        timeouts = metrics.get("timeouts", 0)
        closed = metrics.get("trades_closed", 1)
        rate = timeouts / closed if closed > 0 else 0

        if timeouts > 10 and rate > 0.3:
            self.issues.append(Issue(
                id="TIMEOUT_OVERLOAD",
                severity=Severity.MEDIUM,
                confidence=0.85,
                title=f"High timeout exit rate: {rate:.0%} exits via timeout",
                evidence=[f"Timeout exits: {timeouts}/{closed}"],
                probable_root_cause="Position hold windows too long, exit triggers not firing, stagnation exit tuning",
                recommended_fix="Reduce TP/SL hold windows, check exit evaluation logic, verify timeout is detected",
                likely_files=["src/services/trade_executor.py", "src/services/smart_exit_engine.py"],
                validation_steps=["Check timeout threshold", "Verify exit evaluation is running"],
            ))

    def _detect_pnl_anomaly(self, events: List[Dict[str, Any]], metrics: Dict[str, Any],
                            raw_logs: str) -> None:
        """Detect anomalous PnL (all negative, zeros, or misformatting)."""
        closed_trades = [e for e in events if e.get("type") == "trade_close"]
        if not closed_trades:
            return

        pnls = [float(e.get("pnl", 0)) for e in closed_trades if e.get("pnl") is not None]
        if not pnls:
            return

        negative_count = sum(1 for p in pnls if p < 0)
        zero_count = sum(1 for p in pnls if p == 0)

        if negative_count == len(pnls):
            self.issues.append(Issue(
                id="ALL_LOSSES",
                severity=Severity.HIGH,
                confidence=0.9,
                title="All trades are losing",
                evidence=[f"All {len(pnls)} closed trades show negative PnL"],
                probable_root_cause="Strategy parameters broken, entry/exit logic reversed, or fees/slippage too high",
                recommended_fix="Audit entry/exit logic, check sign of PnL calculation, review fee structure",
                likely_files=["src/services/trade_executor.py", "src/services/learning_event.py"],
                validation_steps=["Verify PnL sign conventions", "Check fee calculation"],
            ))

        if zero_count > len(pnls) * 0.5:
            self.issues.append(Issue(
                id="ZERO_PNL_ANOMALY",
                severity=Severity.MEDIUM,
                confidence=0.7,
                title="Excessive zero PnL trades",
                evidence=[f"{zero_count}/{len(pnls)} trades have zero PnL"],
                probable_root_cause="Rounding errors, flat timeout exits not classified, or PnL not computed",
                recommended_fix="Check PnL rounding logic, verify timeout classification, ensure computation",
                likely_files=["src/services/learning_event.py", "src/services/metrics_engine.py"],
                validation_steps=["Inspect PnL calculation code", "Check rounding thresholds"],
            ))

    def _detect_version_mismatch(self, raw_logs: str) -> None:
        """Detect old version running in production."""
        import re
        matches = re.findall(r"V(\d+)\.(\d+)([a-z]?)", raw_logs)
        if matches:
            versions = set(f"{m[0]}.{m[1]}{m[2]}" for m in matches)
            if "10.13" in str(versions) and len(versions) > 1:
                self.issues.append(Issue(
                    id="VERSION_MISMATCH",
                    severity=Severity.MEDIUM,
                    confidence=0.7,
                    title=f"Multiple versions observed: {', '.join(sorted(versions))}",
                    evidence=list(versions),
                    probable_root_cause="Bot restarted with different code, or mixed deployment",
                    recommended_fix="Verify deployment is consistent, check git HEAD, restart bot cleanly",
                    likely_files=["start.py", "bot2/main.py"],
                    validation_steps=["Check git status", "Verify single instance running"],
                ))

    def _detect_firebase_issues(self, metrics: Dict[str, Any], raw_logs: str) -> None:
        """Detect Firebase read/write quota issues."""
        firebase_warnings = metrics.get("firebase_warnings", 0)

        if firebase_warnings > 10:
            self.issues.append(Issue(
                id="FIREBASE_QUOTA_RISK",
                severity=Severity.HIGH,
                confidence=0.8,
                title=f"High Firebase warnings count: {firebase_warnings}",
                evidence=[f"Firebase warnings in logs: {firebase_warnings}"],
                probable_root_cause="Quota exhaustion, slow writes, or connection timeouts",
                recommended_fix="Check Firebase quota status, optimize batch writes, add backoff retry",
                likely_files=["src/services/firebase_client.py"],
                validation_steps=["Run quota monitor", "Check daily usage stats"],
            ))

    def _detect_redis_issues(self, metrics: Dict[str, Any], raw_logs: str) -> None:
        """Detect Redis connection issues."""
        redis_warnings = metrics.get("redis_warnings", 0)

        if redis_warnings > 5:
            self.issues.append(Issue(
                id="REDIS_FAILURES",
                severity=Severity.MEDIUM,
                confidence=0.75,
                title=f"Repeated Redis connection failures: {redis_warnings}",
                evidence=[f"Redis warnings in logs: {redis_warnings}"],
                probable_root_cause="Redis server down, network timeout, or connection pool exhaustion",
                recommended_fix="Check Redis server status, verify network connectivity, increase pool size",
                likely_files=["src/services/learning_event.py", "src/services/execution_engine.py"],
                validation_steps=["ping Redis server", "Check connection pool stats"],
            ))

    def _detect_exceptions(self, events: List[Dict[str, Any]], metrics: Dict[str, Any],
                           raw_logs: str) -> None:
        """Detect uncaught exceptions."""
        exceptions = metrics.get("exceptions", 0)

        if exceptions > 0:
            exc_events = [e for e in events if e.get("type") == "exception"]
            self.issues.append(Issue(
                id="UNCAUGHT_EXCEPTIONS",
                severity=Severity.CRITICAL,
                confidence=0.95,
                title=f"Uncaught exceptions detected: {exceptions}",
                evidence=[e.get("raw", "")[:100] for e in exc_events[:3]],
                probable_root_cause="Code bug, missing error handling, or edge case not covered",
                recommended_fix="Inspect traceback, add error handling, write test for edge case",
                likely_files=["src/services/realtime_decision_engine.py", "src/services/trade_executor.py"],
                validation_steps=["Read full traceback", "Reproduce locally", "Add unit test"],
            ))
