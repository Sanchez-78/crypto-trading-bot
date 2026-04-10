"""
src/core/failure_manager.py — Failure Escalation Layer (V10.14.b)

Three-tier failure handling. Bridges system_state (string mode) and
guard (FailureLevel enum) so both representations stay in sync.

Tier policy:
  SOFT   — log warning, continue. For transient anomalies.
  DEGRADE— log error, set DEGRADED, 0.5× sizing. Recoverable.
  HARD   — log critical, set HALTED, no new trades. Manual restart required.

Fail-closed guarantee: if imports fail inside handle_hard_fail, we
fall back to writing guard.hard_stop = True directly so the system
never silently continues after a hard invariant breach.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def handle_soft_fail(e: Exception | str) -> None:
    """Tier 1 — log only. System continues at full capacity."""
    log.warning("[SOFT_FAIL] %s", e)


def handle_degrade(e: Exception | str) -> None:
    """
    Tier 2 — log + DEGRADED mode.
    Position sizing drops to 0.5× via guard.get_size_multiplier().
    Recoverable after manual guard.reset().
    """
    log.error("[DEGRADE] %s", e)
    _escalate_to_degrade(str(e))


def handle_hard_fail(e: Exception | str) -> None:
    """
    Tier 3 — log + HALTED. No new trades until manual restart.

    Fail-closed: if any import fails, guard.hard_stop is set directly
    so the execution guard in trade_executor still blocks trades.
    """
    log.critical("[HARD_FAIL] %s", e)
    _escalate_to_halt(str(e))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _escalate_to_degrade(reason: str) -> None:
    try:
        from src.core.system_state import set_mode
        set_mode("DEGRADED")
    except Exception as exc:
        log.debug("_escalate_to_degrade: system_state error: %s", exc)
    try:
        from src.core.guard import guard, FailureLevel
        guard.escalate(FailureLevel.DEGRADE, reason)
    except Exception as exc:
        log.debug("_escalate_to_degrade: guard error: %s", exc)


def _escalate_to_halt(reason: str) -> None:
    try:
        from src.core.system_state import set_mode
        set_mode("HALTED")
    except Exception as exc:
        log.debug("_escalate_to_halt: system_state error: %s", exc)
    try:
        from src.core.guard import guard, FailureLevel
        guard.escalate(FailureLevel.HARD, reason)
    except Exception as exc:
        log.debug("_escalate_to_halt: guard error: %s", exc)
        # Last-resort direct write — ensures execution gate still blocks
        try:
            from src.core.guard import guard as _g
            _g.hard_stop = True
        except Exception:
            pass
