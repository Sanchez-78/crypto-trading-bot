"""Fail-closed startup configuration validation for the P0.8+ pipeline
(Evidence-First Strategy Expansion v2, §20: "Validate at startup. Reject
invalid combinations.").

Gate G0's own gap table (`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` §9)
flagged "no central typed config-validation-at-startup module" as an
open item at P0.7 time. This module closes it for the P0.8+-specific
configuration surface (not a general-purpose config validator for the
whole repository, which is a much larger, separate undertaking -- see
`_workspace/37_document_compliance_gap_analysis.md`'s Tier list).

Mirrors `src/core/runtime_mode.py`'s `assert_real_orders_prohibited()`
pattern exactly: a single function, called once during boot, deliberately
OUTSIDE any exception handler that would reduce a real misconfiguration
to a warning, raising RuntimeError (halting startup) rather than logging
and continuing.

The document's own §20 examples (`OFI_MODE=filter while OFI disabled`,
`dynamic exit enabled without required ATR feature`, `real orders
enabled`, `negative fee value`, `maximum spread <= 0`) are suggestions
for a config surface this repository does not have identically -- OFI
has no live mode flag at all yet (zero live callers, see
docs/P0_9_ACCEPTANCE.md), dynamic exit has no separate enable flag (it is
scoped by strategy_id, not a toggle), and there is no configured
"maximum spread" ceiling anywhere in cost_model.py (spread is computed
dynamically from best_bid/best_ask, not compared against a config
value). This module validates the configuration surface that actually
exists, adapted per §29's "adapt to the repository rather than forcing
exact paths" -- it does not invent flags or checks for behavior this
repository does not have, per §26's "do not silently widen risk limits"
spirit (inventing a fake check would be worse than an honest gap).
"""
from __future__ import annotations

import os


class P0_8_PlusConfigError(RuntimeError):
    """Raised by assert_p0_8_plus_config_valid() -- a distinct type (not
    a bare RuntimeError) so callers/tests can distinguish this specific
    failure class from an unrelated startup error."""


def _float_env(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise P0_8_PlusConfigError(
            f"{name}={raw!r} is not a valid number"
        ) from exc


def assert_p0_8_plus_config_valid() -> None:
    """Fail-closed startup assertion for the P0.8+ pipeline's own
    environment variables. Raises P0_8_PlusConfigError (a RuntimeError
    subclass) on the first invalid value found; does nothing (returns
    None) if the effective configuration is internally consistent.

    Deliberately does NOT re-check ENABLE_REAL_ORDERS/TRADING_MODE/
    LIVE_TRADING_CONFIRMED -- src.core.runtime_mode.
    assert_real_orders_prohibited() (P0.7, called immediately before this
    in bot2/main.py's boot sequence) already owns that check exactly
    once; duplicating it here would be two competing sources of truth
    for the same real-order prohibition.
    """
    # PAPER_FEE_PCT / PAPER_SLIPPAGE_PCT: document's own explicit example
    # ("negative fee value -> startup error"). A negative fee/slippage
    # would mean the cost model REWARDS a strategy for trading, silently
    # inverting the whole "cost-aware" premise of this program.
    fee_pct = _float_env("PAPER_FEE_PCT", "0.0015")
    if fee_pct < 0:
        raise P0_8_PlusConfigError(
            f"PAPER_FEE_PCT={fee_pct} is negative -- a negative fee would "
            "silently reward trading instead of costing it, inverting the "
            "cost-aware premise this program requires (§20)"
        )
    slippage_pct = _float_env("PAPER_SLIPPAGE_PCT", "0.0003")
    if slippage_pct < 0:
        raise P0_8_PlusConfigError(
            f"PAPER_SLIPPAGE_PCT={slippage_pct} is negative -- same reasoning "
            "as PAPER_FEE_PCT above"
        )

    # PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS: a negative synthetic spread
    # would compute a negative-width bid/ask around the candle close
    # (ask < bid), the exact "crossed book" condition cost_model.py
    # itself fails closed on when given real quotes.
    synthetic_spread_bps = _float_env("PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS", "3.0")
    if synthetic_spread_bps < 0:
        raise P0_8_PlusConfigError(
            f"PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS={synthetic_spread_bps} is "
            "negative -- would synthesize a crossed book (ask < bid)"
        )

    # PAPER_P0_8_PLUS_MAX_DATA_AGE_MS / PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S:
    # a non-positive freshness window would make every single candidate
    # reject as REJECT_STALE_MARKET_DATA (or every live quote as aged
    # out) -- not a semantic risk like the ones above, but a silent,
    # hard-to-diagnose full stall exactly like the historical incidents
    # this whole session's forensics have repeatedly had to unwind.
    max_data_age_ms = _float_env("PAPER_P0_8_PLUS_MAX_DATA_AGE_MS", "90000")
    if max_data_age_ms <= 0:
        raise P0_8_PlusConfigError(
            f"PAPER_P0_8_PLUS_MAX_DATA_AGE_MS={max_data_age_ms} must be "
            "positive -- a non-positive value would reject every candidate "
            "as stale unconditionally"
        )
    quote_max_age_s = _float_env("PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S", "30.0")
    if quote_max_age_s <= 0:
        raise P0_8_PlusConfigError(
            f"PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S={quote_max_age_s} must be "
            "positive -- a non-positive value would treat every live quote "
            "as aged-out unconditionally, silently forcing the live "
            "pipeline to never open a position (quote_source would never "
            "be 'live')"
        )
