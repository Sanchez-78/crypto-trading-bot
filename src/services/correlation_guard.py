"""Correlation Guard — Prevent correlated position pairs opening simultaneously.

Reduces portfolio concentration risk by limiting how many highly-correlated
symbols can be open at the same time.
"""

import logging
import os

log = logging.getLogger(__name__)

# Hardcoded correlation matrix (pairs with high correlation)
# In production, this would be updated from market data
CORRELATION_PAIRS = {
    ("BTCUSDT", "ETHUSDT"): 0.85,
    ("BTCUSDT", "LTCUSDT"): 0.78,
    ("ETHUSDT", "ADAUSDT"): 0.72,
    ("XRPUSDT", "ADAUSDT"): 0.68,
}


def get_open_symbols(positions: dict) -> set:
    """Get set of symbols with open positions."""
    return set(p.get("symbol") for p in positions.values() if p and p.get("symbol"))


def check_correlation_conflict(
    new_symbol: str,
    open_positions: dict,
) -> tuple[bool, str, str]:
    """Check if new_symbol conflicts with open positions due to correlation.

    Returns: (should_action, reason, action) where action in [ALLOW, SIZE_DOWN, BLOCK]
    """
    ENABLED = os.getenv("PAPER_CORRELATION_GUARD_ENABLED", "true").lower() == "true"
    THRESHOLD = float(os.getenv("PAPER_CORRELATION_THRESHOLD", "0.80"))
    HARD_BLOCK = os.getenv("PAPER_CORRELATION_HARD_BLOCK", "false").lower() == "true"

    if not ENABLED:
        return False, "", "ALLOW"

    open_symbols = get_open_symbols(open_positions)

    # Check for correlation conflicts
    for open_symbol in open_symbols:
        pair = tuple(sorted([new_symbol, open_symbol]))
        if pair in CORRELATION_PAIRS:
            corr = CORRELATION_PAIRS[pair]
            if corr >= THRESHOLD:
                action = "BLOCK" if HARD_BLOCK else "SIZE_DOWN"
                reason = f"correlated_with_{open_symbol}_corr={corr:.2f}"
                return not HARD_BLOCK, reason, action

    return False, "", "ALLOW"


def log_correlation_decision(
    symbol: str,
    open_symbols: set,
    should_action: bool,
    reason: str,
    action: str,
):
    """Log correlation guard decision (throttled)."""
    log.info(
        "[CORRELATION_GUARD_DECISION] symbol=%s open_symbols=%s corr=%s action=%s reason=%s",
        symbol,
        ",".join(sorted(open_symbols)) if open_symbols else "none",
        "high" if should_action else "low",
        action,
        reason or "no_conflict",
    )
