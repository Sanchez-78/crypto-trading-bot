"""Shared admission metadata between signal evaluation and execution.

The signal generator publishes every evaluated signal so monitoring consumers can
observe rejects as well as takes. Execution consumers therefore need an explicit,
machine-readable RDE outcome instead of inferring acceptance from EV or buckets.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping


RDE_ACCEPTED_KEY = "rde_accepted"
RDE_DECISION_KEY = "rde_decision"


def stamp_rde_outcome(
    signal: MutableMapping[str, Any], result: Any
) -> MutableMapping[str, Any]:
    """Attach the authoritative RDE outcome to a published signal."""

    accepted = result is not None
    signal[RDE_ACCEPTED_KEY] = accepted
    signal[RDE_DECISION_KEY] = "TAKE" if accepted else "REJECT"
    return signal


def is_explicit_rde_reject(signal: MutableMapping[str, Any]) -> bool:
    """Return True only for signals carrying an authoritative RDE rejection."""

    return signal.get(RDE_ACCEPTED_KEY) is False


def has_authoritative_rde_take(signal: MutableMapping[str, Any]) -> bool:
    """Return True only when the RDE explicitly accepted the signal."""

    return signal.get(RDE_ACCEPTED_KEY) is True


def is_regime_aligned(side: str, regime: str) -> bool:
    """Check direction alignment for directional market regimes."""

    side_norm = str(side or "").strip().upper()
    regime_norm = str(regime or "").strip().upper()
    if regime_norm == "BULL_TREND":
        return side_norm == "BUY"
    if regime_norm == "BEAR_TREND":
        return side_norm == "SELL"
    return True


def select_regime_aligned_candidate(
    *,
    regime: str,
    buy_score: float,
    buy_features: Mapping[str, Any],
    sell_score: float,
    sell_features: Mapping[str, Any],
    minimum_score: float,
) -> tuple[str | None, float, Mapping[str, Any]]:
    """Select a scored side without permitting directional counter-trend entries."""

    buy_ok = buy_score >= minimum_score
    sell_ok = sell_score >= minimum_score
    regime_norm = str(regime or "").strip().upper()

    if regime_norm == "BULL_TREND":
        return ("BUY", buy_score, buy_features) if buy_ok else (None, 0.0, {})
    if regime_norm == "BEAR_TREND":
        return ("SELL", sell_score, sell_features) if sell_ok else (None, 0.0, {})
    if buy_ok and (not sell_ok or buy_score >= sell_score):
        return "BUY", buy_score, buy_features
    if sell_ok:
        return "SELL", sell_score, sell_features
    return None, 0.0, {}
