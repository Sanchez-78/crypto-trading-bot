"""One exit taxonomy for every dashboard/API view (read-only presentation, no trading logic).

The dashboard used to count only the legacy reasons tp/sl/scratch/stagnation/timeout, so every
exit of the dynamic exit engine (HARD_STOP_*, DYNAMIC_TARGET_EXIT, TREND_INVALIDATED, ...) was
silently missing from `exit_distribution` (2026-11-24: 232 of 334 epoch trades).

Groups keep the five legacy keys (the Android app reads exactly those) with their meaning:
  tp  = profit target reached (TP, DYNAMIC_TARGET_EXIT)
  sl  = the ORIGINAL stop loss was hit (SL, HARD_STOP_VOLATILITY)
and add the groups that had no key, plus `other` and `total`, so the counts always add up.
"""
from __future__ import annotations

import math

LEGACY_GROUPS = ("tp", "sl", "scratch", "stagnation", "timeout")
EXTRA_GROUPS = ("trailing_stop", "signal_exit", "risk_exit", "other")
GROUPS = LEGACY_GROUPS + EXTRA_GROUPS

_EXACT = {
    "TP": "tp", "TP_HIT": "tp", "DYNAMIC_TARGET_EXIT": "tp",
    "SL": "sl", "SL_HIT": "sl", "HARD_STOP_VOLATILITY": "sl",
    "HARD_STOP_STRUCTURAL": "trailing_stop", "TRAILING_STOP_EXIT": "trailing_stop",
    "TREND_INVALIDATED": "signal_exit", "REGIME_INVALIDATED": "signal_exit",
    "FLOW_REVERSAL_EXIT": "signal_exit", "EDGE_DECAY_EXIT": "signal_exit",
    "RISK_LIMIT_EXIT": "risk_exit", "DATA_INTEGRITY_EXIT": "risk_exit",
    "MAX_HOLD_SAFETY_EXIT": "timeout",
}

# Czech labels: what happened, in words a non-programmer understands.
_LABELS = {
    "TP": "Cíl zisku (TP)",
    "TP_HIT": "Cíl zisku (TP)",
    "DYNAMIC_TARGET_EXIT": "Cíl zisku (dynamický)",
    "SL": "Stop loss",
    "SL_HIT": "Stop loss",
    "HARD_STOP_VOLATILITY": "Stop loss (původní stop)",
    "HARD_STOP_STRUCTURAL": "Posunutý stop (trailing)",
    "TRAILING_STOP_EXIT": "Posunutý stop (trailing)",
    "TREND_INVALIDATED": "Trend skončil (výstup podle signálu)",
    "REGIME_INVALIDATED": "Změna režimu trhu",
    "FLOW_REVERSAL_EXIT": "Obrat toku objednávek",
    "EDGE_DECAY_EXIT": "Výhoda vyprchala",
    "RISK_LIMIT_EXIT": "Rizikový limit",
    "DATA_INTEGRITY_EXIT": "Chyba dat (ochranný výstup)",
    "MAX_HOLD_SAFETY_EXIT": "Časový limit",
}
_GROUP_LABELS = {
    "tp": "Cíl zisku", "sl": "Stop loss", "timeout": "Časový limit", "scratch": "Scratch (u nuly)",
    "stagnation": "Stagnace", "trailing_stop": "Posunutý stop", "signal_exit": "Výstup podle signálu",
    "risk_exit": "Ochranný výstup", "other": "Ostatní",
}


def exit_group(reason) -> str:
    code = str(reason or "").strip().upper()
    if code in _EXACT:
        return _EXACT[code]
    lowered = code.lower()
    if "timeout" in lowered:
        return "timeout"
    if "scratch" in lowered:
        return "scratch"
    if "stag" in lowered:
        return "stagnation"
    return "other"


def exit_label(reason) -> str:
    code = str(reason or "").strip().upper()
    if code in _LABELS:
        return _LABELS[code]
    return _GROUP_LABELS[exit_group(code)] if exit_group(code) != "other" else (code or "Neznámý")


def group_labels() -> dict:
    return dict(_GROUP_LABELS)


def empty_distribution() -> dict:
    return {**{group: 0 for group in GROUPS}, "total": 0}


def add_exit(distribution: dict, by_reason: dict, reason, count: int = 1) -> None:
    distribution[exit_group(reason)] += count
    distribution["total"] += count
    code = str(reason or "").strip().upper() or "UNKNOWN"
    by_reason[code] = by_reason.get(code, 0) + count


_DIRECTIONS = {
    "BUY": ("LONG", "Long – vydělává při růstu ceny"), "LONG": ("LONG", "Long – vydělává při růstu ceny"),
    "SELL": ("SHORT", "Short – vydělává při poklesu ceny"), "SHORT": ("SHORT", "Short – vydělává při poklesu ceny"),
}


def direction(side) -> dict:
    """BUY = long (profits when the price rises), SELL = short (profits when it falls).

    Only an explicit side is translated; a missing/unknown side (legacy rows) is UNKNOWN, never
    silently LONG, so the label cannot explain a short's move backwards (review 2026-11-25 #1).
    """
    found = _DIRECTIONS.get(str(side or "").strip().upper())
    if found is None:
        return {"direction": "UNKNOWN", "direction_label": "Směr nezjištěn"}
    return {"direction": found[0], "direction_label": found[1]}


def price_move_pct(entry_price, exit_price):
    """Raw market move exit vs entry in percent (NOT the trade's P/L, which depends on side).

    None unless both prices and the result are finite and positive prices; never Infinity/NaN,
    which would make the API JSON unparsable for JavaScript (review 2026-11-25 #4).
    """
    try:
        entry, exit_ = float(entry_price), float(exit_price)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(entry) and math.isfinite(exit_) and entry > 0 and exit_ > 0):
        return None
    move = (exit_ / entry - 1.0) * 100.0
    return round(move, 4) if math.isfinite(move) else None


def describe_trade(side, entry_price, exit_price, reason) -> dict:
    """Presentation fields added to every closed-trade row of the API."""
    return {**direction(side), "exit_group": exit_group(reason), "exit_label": exit_label(reason),
            "price_move_pct": price_move_pct(entry_price, exit_price)}
