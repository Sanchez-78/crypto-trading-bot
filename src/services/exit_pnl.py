"""V10.13u+8: Canonical close-PnL helper for unified exit accounting."""
from __future__ import annotations


def canonical_close_pnl(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    size: float,
    fee_rate: float,
    slippage_rate: float = 0.0,
    realized_fee: float | None = None,
    realized_slippage: float | None = None,
    prior_realized_pnl: float = 0.0,
) -> dict:
    """
    Compute canonical close PnL with algebraic identity guarantee.

    Args:
        symbol: Trading pair (e.g., "XRPUSDT")
        side: "BUY" or "SELL"
        entry_price: Entry price
        exit_price: Exit price
        size: Current position size (after any partial TPs)
        fee_rate: Fee rate as decimal (0.002 = 0.2%)
        slippage_rate: Slippage rate as decimal (default 0.0)
        realized_fee: Real fee amount (if known). If None, computed from fee_rate and size.
        realized_slippage: Real slippage amount (if known). If None, computed from slippage_rate and size.
        prior_realized_pnl: PnL booked from prior partial TP closes (default 0.0)

    Returns:
        dict with keys:
            - gross_pnl: move PnL before costs (includes prior_realized_pnl)
            - fee_pnl: negative cost
            - slippage_pnl: negative cost
            - net_pnl: gross_pnl + fee_pnl + slippage_pnl
            - fee_rate: fee rate used
            - slippage_rate: slippage rate used
            - source: "canonical_close_pnl"

    Hard invariants:
        - fee_pnl <= 0
        - slippage_pnl <= 0
        - abs(net_pnl - (gross_pnl + fee_pnl + slippage_pnl)) < 1e-12
    """
    # Compute raw move PnL
    if side == "BUY":
        raw_move_pnl = (exit_price - entry_price) / entry_price * size
    elif side == "SELL":
        raw_move_pnl = (entry_price - exit_price) / entry_price * size
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'.")

    # Gross PnL includes prior partial TP proceeds
    gross_pnl = raw_move_pnl + prior_realized_pnl

    # Fee PnL: always non-positive
    if realized_fee is not None:
        fee_pnl = -abs(realized_fee)
    else:
        fee_pnl = -(fee_rate * size)

    # Slippage PnL: always non-positive
    if realized_slippage is not None:
        slippage_pnl = -abs(realized_slippage)
    else:
        slippage_pnl = -(slippage_rate * size)

    # Net PnL: algebraic identity
    net_pnl = gross_pnl + fee_pnl + slippage_pnl

    # Hard invariants
    assert fee_pnl <= 0, f"fee_pnl must be non-positive, got {fee_pnl}"
    assert slippage_pnl <= 0, f"slippage_pnl must be non-positive, got {slippage_pnl}"
    assert (
        abs(net_pnl - (gross_pnl + fee_pnl + slippage_pnl)) < 1e-12
    ), f"Algebraic identity violated: net_pnl={net_pnl} but gross+fee+slip={gross_pnl + fee_pnl + slippage_pnl}"

    return {
        "gross_pnl": gross_pnl,
        "fee_pnl": fee_pnl,
        "slippage_pnl": slippage_pnl,
        "net_pnl": net_pnl,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "source": "canonical_close_pnl",
    }
