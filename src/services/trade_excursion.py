"""Trade excursion (MFE/MAE) contract — audit F8, observability only.

Persisting MFE/MAE with EXPLICIT units + the ORDER in which the favorable and
adverse extremes occurred is the prerequisite for an honest offline TP/SL
counterfactual (a trade that hit its adverse extreme first vs its favorable
extreme first has the opposite counterfactual outcome even for identical
magnitudes). This module computes that from the tracked per-position extremes
and their timestamps. It is PURE and changes NO close math, TP/SL, cost, or
strategy — it only describes what the price already did.

Sign policy (side-aware): mfe_gross_* >= 0 (favorable), mae_gross_* <= 0
(adverse). Values are GROSS (before fees/slippage) — the excursion of the raw
price path; cost is applied elsewhere in the counterfactual.

NOTE: global-extreme timestamps give first-order ordering. A full per-level
crossing sequence (for sweeping many candidate TP/SL values) needs the 1s
directional price-path table (F8b, follow-up) — out of scope here.
"""
from __future__ import annotations

from typing import Any, Optional

EXCURSION_POLICY_VERSION = 1

_SELL_SIDES = {"SELL", "SHORT"}

EXCURSION_FIELDS = (
    "excursion_policy_version",
    "mfe_gross_fraction", "mfe_gross_pct", "mfe_gross_bps",
    "mae_gross_fraction", "mae_gross_pct", "mae_gross_bps",
    "max_favorable_price", "max_adverse_price",
    "time_to_mfe_ms", "time_to_mae_ms",
)


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _ms_between(later, earlier) -> Optional[int]:
    if later is None or earlier is None:
        return None
    try:
        return int(round((float(later) - float(earlier)) * 1000.0))
    except (TypeError, ValueError):
        return None


def empty_excursion() -> dict[str, Any]:
    return {
        "excursion_policy_version": EXCURSION_POLICY_VERSION,
        "mfe_gross_fraction": 0.0, "mfe_gross_pct": 0.0, "mfe_gross_bps": 0.0,
        "mae_gross_fraction": 0.0, "mae_gross_pct": 0.0, "mae_gross_bps": 0.0,
        "max_favorable_price": None, "max_adverse_price": None,
        "time_to_mfe_ms": None, "time_to_mae_ms": None,
    }


def compute_excursion(side: str, entry_price, max_seen, min_seen,
                      entry_ts=None, max_seen_ts=None, min_seen_ts=None) -> dict[str, Any]:
    """Compute the side-aware gross MFE/MAE excursion contract.

    max_seen/min_seen are the highest/lowest prices observed during the hold;
    max_seen_ts/min_seen_ts are when those extremes were FIRST reached.
    """
    e = _f(entry_price)
    if e <= 0:
        return empty_excursion()
    s = str(side or "BUY").upper()
    mx = _f(max_seen, e)
    mn = _f(min_seen, e)

    if s in _SELL_SIDES:
        # short: favorable = price falls (toward min), adverse = price rises (max)
        mfe_frac = (e - mn) / e
        mae_frac = (e - mx) / e
        fav_price, adv_price = mn, mx
        t_fav, t_adv = min_seen_ts, max_seen_ts
    else:
        mfe_frac = (mx - e) / e
        mae_frac = (mn - e) / e
        fav_price, adv_price = mx, mn
        t_fav, t_adv = max_seen_ts, min_seen_ts

    # Enforce the sign policy defensively (should already hold).
    mfe_frac = max(mfe_frac, 0.0)
    mae_frac = min(mae_frac, 0.0)

    return {
        "excursion_policy_version": EXCURSION_POLICY_VERSION,
        "mfe_gross_fraction": round(mfe_frac, 10),
        "mfe_gross_pct": round(mfe_frac * 100.0, 6),
        "mfe_gross_bps": round(mfe_frac * 10000.0, 4),
        "mae_gross_fraction": round(mae_frac, 10),
        "mae_gross_pct": round(mae_frac * 100.0, 6),
        "mae_gross_bps": round(mae_frac * 10000.0, 4),
        "max_favorable_price": fav_price,
        "max_adverse_price": adv_price,
        "time_to_mfe_ms": _ms_between(t_fav, entry_ts),
        "time_to_mae_ms": _ms_between(t_adv, entry_ts),
    }


def favorable_first(excursion: dict[str, Any]) -> Optional[bool]:
    """True if the favorable extreme occurred before the adverse one (the
    first-order TP-before-SL proxy). None if timing is unknown."""
    t_fav = excursion.get("time_to_mfe_ms")
    t_adv = excursion.get("time_to_mae_ms")
    if t_fav is None or t_adv is None:
        return None
    return t_fav <= t_adv
