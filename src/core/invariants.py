"""
src/core/invariants.py — Hard Trading Invariants (V10.14.b)

validate_position() is the canonical pre-execution integrity check.
Any failure raises CriticalInvariantError, caught by
failure_manager.handle_hard_fail() which halts the system.

Design: fail-closed. When in doubt, raise — never silently pass.
"""

from __future__ import annotations

import math


class CriticalInvariantError(Exception):
    """Raised when a hard trading invariant is violated."""


def validate_position(pos: dict) -> None:
    """
    Raise CriticalInvariantError if pos contains structurally invalid values.

    Checks (in order — fail on first):
      1. Not None
      2. size  — finite, > 0
      3. entry — finite, > 0  (accepts both 'entry' and 'entry_price' keys)
      4. action — one of BUY / SELL / long / short
      5. TP/SL monotonicity — when present:
           BUY : tp > entry > sl
           SELL: sl > entry > tp

    Called by execution_engine._handle_signal and trade_executor.handle_signal
    before any order is placed.
    """
    if pos is None:
        raise CriticalInvariantError("Position is None")

    # ── size ───────────────────────────────────────────────────────────────────
    size = pos.get("size", 0)
    if not math.isfinite(size) or size <= 0:
        raise CriticalInvariantError(f"Invalid size: {size!r}")

    # ── entry price ────────────────────────────────────────────────────────────
    entry = pos.get("entry_price") or pos.get("entry") or pos.get("price") or 0
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        entry = 0.0
    if entry <= 0 or not math.isfinite(entry):
        raise CriticalInvariantError(f"Invalid entry_price: {entry!r}")

    # ── action ─────────────────────────────────────────────────────────────────
    action = pos.get("action", "")
    if action not in ("BUY", "SELL", "long", "short"):
        raise CriticalInvariantError(f"Invalid action: {action!r}")

    # ── TP / SL monotonicity (only when both are present) ─────────────────────
    tp_raw = pos.get("tp") or pos.get("take_profit")
    sl_raw = pos.get("sl") or pos.get("stop_loss")
    if tp_raw is not None and sl_raw is not None:
        try:
            tp = float(tp_raw)
            sl = float(sl_raw)
        except (TypeError, ValueError):
            raise CriticalInvariantError(
                f"Non-numeric TP/SL: tp={tp_raw!r} sl={sl_raw!r}")

        if not (math.isfinite(tp) and math.isfinite(sl)):
            raise CriticalInvariantError(f"Non-finite TP/SL: tp={tp} sl={sl}")

        if action in ("BUY", "long"):
            if not (tp > entry > sl):
                raise CriticalInvariantError(
                    f"Monotone violation BUY: entry={entry} tp={tp} sl={sl}")
        else:  # SELL / short
            if not (sl > entry > tp):
                raise CriticalInvariantError(
                    f"Monotone violation SELL: entry={entry} tp={tp} sl={sl}")
