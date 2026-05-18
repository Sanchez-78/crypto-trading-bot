"""
V10.13k: Dual Logging System — CORE FLOW (trades/learning) vs DIAGNOSTICS (technical)

CORE FLOW: What the bot actually does (bright, colored, simple)
  - Signal entry/exit
  - Learning updates
  - Errors/mismatches (red)
  - Attribution (yellow)

DIAGNOSTICS: Why/how it works (dim, collapsed, technical)
  - Throttle logs
  - Cap checks
  - State validation
  - Internal state
"""

import logging
import sys
from typing import Optional

# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Bright colors for CORE FLOW
    GREEN = "\033[92m"      # Entry/success
    BLUE = "\033[94m"       # Trade info
    YELLOW = "\033[93m"     # Attribution/warning
    RED = "\033[91m"        # Error/mismatch
    CYAN = "\033[96m"       # Learning update
    MAGENTA = "\033[95m"    # Exit/close

    # Dim colors for DIAGNOSTICS
    GRAY_GREEN = "\033[32m"
    GRAY_BLUE = "\033[34m"
    GRAY_YELLOW = "\033[33m"


class CoreFlowFormatter(logging.Formatter):
    """Format CORE FLOW logs with color and emphasis."""

    def format(self, record):
        if record.name.startswith("CORE_FLOW"):
            # Extract signal type
            msg = record.getMessage()

            if "ENTRY" in msg or "ACCEPTED" in msg:
                color = Colors.GREEN + Colors.BOLD
                prefix = "→ ENTRY"
            elif "EXIT" in msg or "CLOSED" in msg:
                color = Colors.MAGENTA + Colors.BOLD
                prefix = "← EXIT"
            elif "LM_STATE" in msg or "LEARNING_UPDATE" in msg:
                color = Colors.CYAN + Colors.BOLD
                prefix = "📚 LEARN"
            elif "MISMATCH" in msg or "ERROR" in msg or "FAIL" in msg:
                color = Colors.RED + Colors.BOLD
                prefix = "⚠️  ERROR"
            elif "ATTRIBUTION" in msg or "attribution=" in msg:
                color = Colors.YELLOW
                prefix = "📊 ATTR"
            else:
                color = Colors.BLUE
                prefix = "ℹ️  INFO"

            return f"{color}{prefix:12}{Colors.RESET} {msg}"

        return record.getMessage()


class DiagnosticsFormatter(logging.Formatter):
    """Format DIAGNOSTICS logs as dim/collapsed."""

    def format(self, record):
        msg = record.getMessage()
        # Suppress unless explicitly enabled
        return f"{Colors.DIM}[DIAG] {msg}{Colors.RESET}"


# Create separate loggers
_core_flow_logger = None
_diagnostics_logger = None


def _init_loggers():
    """Initialize dual logging system."""
    global _core_flow_logger, _diagnostics_logger

    if _core_flow_logger is not None:
        return

    # CORE FLOW logger (stdout, bright, important)
    _core_flow_logger = logging.getLogger("CORE_FLOW")
    _core_flow_logger.setLevel(logging.INFO)
    _core_flow_logger.propagate = False

    core_handler = logging.StreamHandler(sys.stdout)
    core_handler.setFormatter(CoreFlowFormatter())
    _core_flow_logger.addHandler(core_handler)

    # DIAGNOSTICS logger (stdout, dim, technical)
    _diagnostics_logger = logging.getLogger("CORE_FLOW.DIAG")
    _diagnostics_logger.setLevel(logging.DEBUG)
    _diagnostics_logger.propagate = False

    diag_handler = logging.StreamHandler(sys.stdout)
    diag_handler.setFormatter(DiagnosticsFormatter())
    _diagnostics_logger.addHandler(diag_handler)


def log_trade_entry(
    symbol: str,
    side: str,
    price: float,
    bucket: str,
    source: str,
    ev: float,
    **kwargs
):
    """Log a paper/live trade entry (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"{symbol:8} {side:4} @ {price:10.2f} bucket={bucket:20} source={source:20} ev={ev:+.4f}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"PAPER_TRAIN_ENTRY {msg}")


def log_trade_exit(
    symbol: str,
    trade_id: str,
    outcome: str,
    pnl_pct: float,
    bucket: str,
    reason: str,
    **kwargs
):
    """Log a paper/live trade exit (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"trade_id={trade_id} {symbol:8} outcome={outcome:8} pnl={pnl_pct:+6.2f}% bucket={bucket:20} reason={reason:15}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"PAPER_EXIT {msg}")


def log_learning_update(
    trades_in_lm: int,
    calibration_confidence: Optional[float] = None,
    attribution_dominant: Optional[str] = None,
    **kwargs
):
    """Log LM state update (CORE FLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"trades_in_lm={trades_in_lm}"
    if calibration_confidence is not None:
        msg += f" confidence={calibration_confidence:.2f}"
    if attribution_dominant:
        msg += f" dominant_attr={attribution_dominant}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"LM_STATE_AFTER_UPDATE {msg}")


def log_error(error_type: str, message: str, **kwargs):
    """Log error/mismatch (CORE FLOW, RED)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"{error_type}: {message}"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.warning(f"ERROR {msg}")


def log_attribution(
    trade_id: str,
    symbol: str,
    attribution: str,
    loss_pct: float,
    **kwargs
):
    """Log economic attribution (CORE FLOW, YELLOW)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = f"trade_id={trade_id} {symbol:8} attribution={attribution:25} loss={loss_pct:+6.2f}%"
    if extra:
        msg += f" {extra}"
    _core_flow_logger.info(f"ATTRIBUTION {msg}")


def log_diag(message: str, **kwargs):
    """Log diagnostic detail (DIAGNOSTICS, DIM)."""
    _init_loggers()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    msg = message
    if extra:
        msg += f" {extra}"
    _diagnostics_logger.debug(msg)


# Export for use in other modules
__all__ = [
    "log_trade_entry",
    "log_trade_exit",
    "log_learning_update",
    "log_error",
    "log_attribution",
    "log_diag",
]
