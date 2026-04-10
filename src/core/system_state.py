"""
src/core/system_state.py — Global System Mode (V10.14.b)

Single authoritative source for operating mode.
Both guard.py (FailureLevel) and failure_manager.py write here.
All execution entry-points read is_halted() before placing orders.

Modes:
  NORMAL   — full operation, normal sizing
  DEGRADED — 0.5× sizing, logging elevated, still trading
  HALTED   — no new trades until manual restart / guard.reset()
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SYSTEM_STATE: dict[str, str] = {"mode": "NORMAL"}

_MODE_RANK = {"NORMAL": 0, "DEGRADED": 1, "HALTED": 2}


def set_mode(mode: str) -> None:
    """Transition to mode. Levels only move UP (NORMAL→DEGRADED→HALTED)."""
    if mode not in _MODE_RANK:
        log.warning("[SYSTEM_STATE] Unknown mode %r — ignored", mode)
        return
    prev = SYSTEM_STATE["mode"]
    if _MODE_RANK[mode] > _MODE_RANK.get(prev, 0):
        SYSTEM_STATE["mode"] = mode
        log.warning("[SYSTEM_STATE] %s → %s", prev, mode)


def get_mode() -> str:
    return SYSTEM_STATE["mode"]


def is_halted() -> bool:
    return SYSTEM_STATE["mode"] == "HALTED"


def is_degraded() -> bool:
    """True in DEGRADED *or* HALTED — both suppress full sizing."""
    return SYSTEM_STATE["mode"] in ("DEGRADED", "HALTED")


def reset() -> None:
    """
    Reset to NORMAL. Only valid after manual investigation.
    Called by guard.reset() — do not call directly from trading code.
    """
    prev = SYSTEM_STATE["mode"]
    SYSTEM_STATE["mode"] = "NORMAL"
    log.info("[SYSTEM_STATE] RESET: %s → NORMAL", prev)
