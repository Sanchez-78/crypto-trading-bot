"""Parse trading bot logs and extract events."""

import re
import logging
from typing import List, Dict, Any
from datetime import datetime

log = logging.getLogger(__name__)


class LogParser:
    """Parse CryptoMaster logs and extract structured events."""

    # Regex patterns for key events
    SIGNAL_PATTERN = r"signal.*created|signal_created"
    DECISION_PATTERN = r"APPROVE|REJECT|BLOCK|decision"
    REJECTION_PATTERN = r"reject.*reason|EV_TOO_LOW|SPREAD_WIDE|OVERTRADING|LOSS_STREAK|DRAWDOWN"
    TRADE_OPEN_PATTERN = r"open.*position|position.*open|order.*sent"
    TRADE_CLOSE_PATTERN = r"trade.*closed|position.*closed|exit"
    TIMEOUT_PATTERN = r"TIMEOUT|timeout"
    PNL_PATTERN = r"pnl|profit|loss|net_pnl"
    EXCEPTION_PATTERN = r"Traceback|Exception|Error|error"
    VERSION_PATTERN = r"V\d+\.\d+[a-z]?|commit=([a-f0-9]+)"
    FIREBASE_PATTERN = r"Firebase|firebase|Firestore|quota"
    REDIS_PATTERN = r"Redis|redis|connection.*refused"

    def __init__(self):
        """Initialize parser."""
        self.events: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Any] = {
            "signals": 0,
            "decisions": 0,
            "rejections": 0,
            "approvals": 0,
            "trades_opened": 0,
            "trades_closed": 0,
            "timeouts": 0,
            "exceptions": 0,
            "firebase_warnings": 0,
            "redis_warnings": 0,
        }

    def parse(self, logs: str) -> Dict[str, Any]:
        """Parse logs and extract events."""
        lines = logs.split("\n")
        for line in lines:
            self._parse_line(line)

        return {
            "events": self.events,
            "metrics": self.metrics,
        }

    def _parse_line(self, line: str) -> None:
        """Parse a single log line."""
        if not line.strip():
            return

        # Extract timestamp
        timestamp = self._extract_timestamp(line)

        # Check for signal
        if re.search(self.SIGNAL_PATTERN, line, re.IGNORECASE):
            self.metrics["signals"] += 1
            symbol = self._extract_symbol(line)
            self.events.append({
                "type": "signal",
                "timestamp": timestamp,
                "symbol": symbol,
                "raw": line[:200],
            })

        # Check for decision
        if re.search(self.DECISION_PATTERN, line, re.IGNORECASE):
            self.metrics["decisions"] += 1
            decision = self._extract_decision(line)
            symbol = self._extract_symbol(line)
            if decision == "APPROVE":
                self.metrics["approvals"] += 1
            elif decision == "REJECT":
                self.metrics["rejections"] += 1
            self.events.append({
                "type": "decision",
                "timestamp": timestamp,
                "symbol": symbol,
                "decision": decision,
                "raw": line[:200],
            })

        # Check for trade open
        if re.search(self.TRADE_OPEN_PATTERN, line, re.IGNORECASE):
            self.metrics["trades_opened"] += 1
            symbol = self._extract_symbol(line)
            self.events.append({
                "type": "trade_open",
                "timestamp": timestamp,
                "symbol": symbol,
                "raw": line[:200],
            })

        # Check for trade close
        if re.search(self.TRADE_CLOSE_PATTERN, line, re.IGNORECASE):
            self.metrics["trades_closed"] += 1
            symbol = self._extract_symbol(line)
            pnl = self._extract_pnl(line)
            self.events.append({
                "type": "trade_close",
                "timestamp": timestamp,
                "symbol": symbol,
                "pnl": pnl,
                "raw": line[:200],
            })

        # Check for timeout
        if re.search(self.TIMEOUT_PATTERN, line, re.IGNORECASE):
            self.metrics["timeouts"] += 1

        # Check for exceptions
        if re.search(self.EXCEPTION_PATTERN, line):
            self.metrics["exceptions"] += 1
            self.events.append({
                "type": "exception",
                "timestamp": timestamp,
                "raw": line[:300],
            })

        # Check for Firebase warnings
        if re.search(self.FIREBASE_PATTERN, line, re.IGNORECASE):
            self.metrics["firebase_warnings"] += 1

        # Check for Redis warnings
        if re.search(self.REDIS_PATTERN, line, re.IGNORECASE):
            self.metrics["redis_warnings"] += 1

    def _extract_timestamp(self, line: str) -> str:
        """Extract ISO timestamp from log line."""
        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
        return match.group(0) if match else "?"

    def _extract_symbol(self, line: str) -> str:
        """Extract symbol (BTC, ETH, etc.) from log line."""
        match = re.search(r"([A-Z]{2,6}USDT)", line)
        return match.group(1) if match else "?"

    def _extract_decision(self, line: str) -> str:
        """Extract decision (APPROVE, REJECT, BLOCK) from log line."""
        if "APPROVE" in line.upper():
            return "APPROVE"
        elif "REJECT" in line.upper():
            return "REJECT"
        elif "BLOCK" in line.upper():
            return "BLOCK"
        return "?"

    def _extract_pnl(self, line: str) -> float:
        """Extract PnL value from log line."""
        match = re.search(r"pnl['\"]?\s*[:=]\s*([+-]?\d+\.?\d*)", line, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.0
