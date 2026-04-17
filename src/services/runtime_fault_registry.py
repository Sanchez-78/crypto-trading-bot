"""
V10.13L: Runtime Fault Registry — Centralized safety state for critical components.

Purpose:
  When a critical module (smart_exit_engine, trade_executor, realtime_decision_engine)
  experiences a syntax/runtime/import error, the system must:
  - Explicitly mark it as FAULTED
  - Disable new trading (fail-closed)
  - Prevent watchdog from masking the problem via threshold relaxation
  - Preserve existing position management

State Machine:
  OK       → all components healthy, trading allowed
  DEGRADED → non-critical fault, positions managed via fallback
  FAULTED  → critical fault, new trades blocked, minimal operations only

API:
  mark_fault(component, error, severity='hard')
  clear_fault(component)
  has_hard_fault() -> bool
  is_trading_allowed() -> bool
  get_fault_snapshot() -> dict
  get_state() -> str
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Critical components — faults here disable trading
_CRITICAL_COMPONENTS = {
    "smart_exit_engine",
    "trade_executor",
    "realtime_decision_engine",
    "signal_generator",
    "market_stream",
    "boot_guardian",
    "event_dispatch",
}

# Internal state
_registry: Dict[str, Dict] = {}
_fault_clear_times: Dict[str, datetime] = {}  # Track when faults can be cleared
_FAULT_PERSIST_SECS = 30  # Fault must be clear for 30s before marking OK

def _get_state() -> str:
    """Compute current state based on faults."""
    if not _registry:
        return "OK"

    hard_faults = [f for f in _registry.values() if f["severity"] == "hard"]
    if hard_faults:
        return "FAULTED"

    return "DEGRADED"


def mark_fault(component: str, error: str, severity: str = "hard") -> None:
    """
    Mark a component as faulted.

    Args:
        component: Component name (should be in _CRITICAL_COMPONENTS)
        error: Error message/description
        severity: "hard" (blocks trading) or "soft" (degrades only)
    """
    global _registry

    is_critical = component in _CRITICAL_COMPONENTS
    severity = severity if severity in ("hard", "soft") else "hard"

    if is_critical and severity == "hard":
        actual_severity = "hard"
    else:
        actual_severity = severity

    _registry[component] = {
        "error": error,
        "severity": actual_severity,
        "timestamp": datetime.utcnow().isoformat(),
        "is_critical": is_critical,
    }

    _fault_clear_times[component] = None  # Reset clear timer

    log.warning(
        f"[FAULT_MARK] {component} ({actual_severity}): {error} | state={_get_state()}"
    )

    # Immediately log critical faults to stderr for visibility
    if is_critical and actual_severity == "hard":
        import sys
        print(f"⚠️  RUNTIME_FAULT [CRITICAL]: {component}: {error}", file=sys.stderr, flush=True)


def clear_fault(component: str) -> None:
    """
    Clear a fault after recovery window.
    Fault is only truly cleared after 30s without recurrence.
    """
    global _registry, _fault_clear_times

    if component not in _registry:
        return

    now = datetime.utcnow()

    # Start clear window if not already started
    if _fault_clear_times.get(component) is None:
        _fault_clear_times[component] = now
        log.info(f"[FAULT_CLEAR_WINDOW_START] {component}")
        return

    # Check if 30s have passed
    elapsed = (now - _fault_clear_times[component]).total_seconds()
    if elapsed >= _FAULT_PERSIST_SECS:
        del _registry[component]
        del _fault_clear_times[component]
        log.info(f"[FAULT_CLEARED] {component} after {elapsed:.0f}s recovery window")
    else:
        log.debug(
            f"[FAULT_CLEAR_WAITING] {component}: {elapsed:.0f}s/{_FAULT_PERSIST_SECS}s"
        )


def has_hard_fault() -> bool:
    """Check if any hard fault exists."""
    return any(f["severity"] == "hard" for f in _registry.values())


def is_trading_allowed() -> bool:
    """
    Check if new trading is allowed.
    Returns False if any hard fault exists.
    """
    return not has_hard_fault()


def get_state() -> str:
    """Return current state: OK, DEGRADED, or FAULTED."""
    return _get_state()


def get_fault_snapshot() -> dict:
    """Return detailed fault state snapshot."""
    return {
        "state": _get_state(),
        "trading_allowed": is_trading_allowed(),
        "fault_count": len(_registry),
        "hard_fault_count": sum(1 for f in _registry.values() if f["severity"] == "hard"),
        "faults": _registry,
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_faults() -> Dict[str, str]:
    """Return dict of {component: error_string} for all active faults."""
    return {comp: fault["error"] for comp, fault in _registry.items()}


# Utility: call this periodically in main loop to advance clear timers
def _tick_clear_timers() -> None:
    """Advance fault clear timers. Call once per main loop iteration."""
    components_to_check = list(_fault_clear_times.keys())
    for component in components_to_check:
        if _fault_clear_times[component] is not None:
            clear_fault(component)
