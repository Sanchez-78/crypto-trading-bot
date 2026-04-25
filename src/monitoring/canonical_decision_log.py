"""
Canonical decision and lifecycle logging formatters.
Produces single-line, stable-format logs for auditing decision flow.
"""

from typing import Dict, Any, Optional
import logging


def format_decision_log(decision: Dict[str, Any]) -> str:
    """
    Format a decision dict as a single-line canonical log.

    Example output:
    CANON_DECISION sym=BTCUSDT reg=BULL_TREND side=BUY decision=APPROVE ev=+0.123 gates=OK status=OK
    """
    sym = decision.get("symbol", "?")
    regime = decision.get("regime", "?")
    side = decision.get("side", "?")
    dec = decision.get("decision", "?")
    ev = decision.get("ev_final") or decision.get("ev") or 0.0
    score = decision.get("score", 0.0)
    gates = decision.get("gates", {})

    # Handle both dict (from plain dict) and list (from DecisionFrame.to_dict)
    if isinstance(gates, list):
        gate_status = "OK" if all(g.get("passed", False) for g in gates) else "FAIL"
        gate_names = ",".join([g.get("gate_type", "?") for g in gates if g.get("passed")])
    elif isinstance(gates, dict):
        gate_status = "OK" if all(gates.values()) else "FAIL"
        gate_names = ",".join([k for k, v in gates.items() if v])
    else:
        gate_status = "?"
        gate_names = "?"

    return (
        f"CANON_DECISION sym={sym} reg={regime} side={side} "
        f"decision={dec} ev={ev:+.6f} score={score:.3f} "
        f"gates=[{gate_names}] status={gate_status}"
    )


def format_lifecycle_log(lifecycle: Dict[str, Any]) -> str:
    """
    Format an order lifecycle dict as a single-line canonical log.

    Example output:
    CANON_LIFECYCLE sym=BTCUSDT state=ORDER_SENT pnl=+100.50 mfe=+0.5% mae=-0.2%
    """
    sym = lifecycle.get("symbol", "?")
    state = lifecycle.get("current_state", "?")
    pnl = lifecycle.get("pnl")
    mfe = lifecycle.get("mfe")
    mae = lifecycle.get("mae")

    pnl_str = f"{pnl:+.6f}" if pnl is not None else "?"
    mfe_str = f"{mfe:+.1%}" if mfe is not None else "?"
    mae_str = f"{mae:+.1%}" if mae is not None else "?"

    return (
        f"CANON_LIFECYCLE sym={sym} state={state} "
        f"pnl={pnl_str} mfe={mfe_str} mae={mae_str}"
    )


class CanonicalLogger:
    """Wrapper for safe canonical logging (catches exceptions)."""

    def __init__(self, logger_name: str = "canonical"):
        self._logger = logging.getLogger(logger_name)

    def decision(self, decision: Dict[str, Any]) -> Optional[str]:
        """Log a decision, return formatted string, catch exceptions."""
        try:
            log_line = format_decision_log(decision)
            self._logger.info(log_line)
            return log_line
        except Exception as e:
            logging.debug(f"canonical decision log failed: {e}", exc_info=True)
            return None

    def lifecycle(self, lifecycle: Dict[str, Any]) -> Optional[str]:
        """Log a lifecycle event, return formatted string, catch exceptions."""
        try:
            log_line = format_lifecycle_log(lifecycle)
            self._logger.info(log_line)
            return log_line
        except Exception as e:
            logging.debug(f"canonical lifecycle log failed: {e}", exc_info=True)
            return None
