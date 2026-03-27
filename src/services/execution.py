"""
Exchange-level execution engine — order book aware, slippage-minimising.

Order type selection:
  MARKET — high momentum + order book imbalance confirms direction
  LIMIT  — tight spread, passive fill at inside quote + 10% of spread
  POST   — default; maker-only, zero taker fee, no fill guarantee

Partial fill loop (exec_order):
  3 attempts × 40% of size each; market fallback for remainder.
  Simulates realistic fill in paper-trading context.

Slippage model:
  size / depth — fraction of available liquidity consumed.
  Used in net_edge gate and stored per trade for analysis.

Signal staleness:
  Reject signals older than 500 ms — stale price = wrong edge.
"""

import time as _time


# ── Order book snapshot ────────────────────────────────────────────────────────

class OrderBook:
    """Minimal OB snapshot passed from price feed or constructed from ticker."""

    __slots__ = ("bid", "ask", "bid_vol", "ask_vol", "ts")

    def __init__(self, bid, ask, bid_vol=1.0, ask_vol=1.0, ts=None):
        self.bid     = float(bid)
        self.ask     = float(ask)
        self.bid_vol = float(bid_vol)
        self.ask_vol = float(ask_vol)
        self.ts      = ts or _time.time()

    @classmethod
    def from_price(cls, price, spread_pct=0.001):
        """Construct a minimal OB from a single price + spread estimate."""
        half = price * spread_pct / 2
        return cls(bid=price - half, ask=price + half,
                   bid_vol=10.0, ask_vol=10.0)


# ── Order type selection ───────────────────────────────────────────────────────

def choose_type(sig, ob):
    """
    MARKET  — strong momentum (mom>0.7) AND OB imbalance confirms (imb>1.2 for BUY)
    LIMIT   — spread tight enough for passive fill (<0.05% of mid)
    POST    — default; maker-only
    """
    spread = ob.ask - ob.bid
    mid    = (ob.ask + ob.bid) / 2
    imb    = ob.bid_vol / (ob.ask_vol + 1e-6)
    mom    = sig.get("features", {}).get("mom5", 0.0)

    # Momentum + confirming imbalance → take liquidity immediately
    if abs(mom) > 0.007 and imb > 1.2:
        return "MARKET"
    # Tight spread → passive limit is cheap and likely to fill
    if spread / max(mid, 1e-9) < 0.0005:
        return "LIMIT"
    return "POST"


# ── Limit price ────────────────────────────────────────────────────────────────

def limit_price(ob, side):
    """
    Place limit 10% into the spread from our side.
    BUY: bid + 10% of spread (slightly better than best bid, avoids queue tail)
    SELL: ask - 10% of spread
    """
    spread = ob.ask - ob.bid
    if side == "BUY":
        return ob.bid + 0.10 * spread
    return ob.ask - 0.10 * spread


# ── Slippage estimate ──────────────────────────────────────────────────────────

def slippage(size, ob, side="BUY"):
    """
    Fraction of available depth consumed by this order.
    Higher size relative to depth = more adverse fill.
    """
    depth = ob.ask_vol if side == "BUY" else ob.bid_vol
    return size / (depth + 1e-6)


# ── Net edge after costs ───────────────────────────────────────────────────────

def net_edge(ws, size, ob, fee, side="BUY"):
    """ws after slippage + round-trip fees. Negative = destroy edge."""
    return ws - slippage(size, ob, side) - fee


# ── Order book directional signal ─────────────────────────────────────────────

def ob_signal(ob):
    """
    +1 = buy pressure (imb > 1.5)
    -1 = sell pressure (imb < 0.67)
     0 = neutral
    """
    imb = ob.bid_vol / (ob.ask_vol + 1e-6)
    if imb > 1.5:
        return 1
    if imb < 0.67:
        return -1
    return 0


# ── Signal staleness guard ─────────────────────────────────────────────────────

def valid(sig_time, max_age_ms=500):
    """Return True if signal is fresh enough to act on."""
    age_ms = (_time.time() - sig_time) * 1000
    return age_ms < max_age_ms


# ── Core execution ─────────────────────────────────────────────────────────────

def _send_limit(size, price, side, ob):
    """
    Paper-trading limit fill simulation.
    Fills if price is within current spread; partial fill probability ~80%.
    Returns amount filled and average fill price.
    """
    if side == "BUY" and price >= ob.ask:
        return size, ob.ask                   # marketable limit → immediate fill
    if side == "SELL" and price <= ob.bid:
        return size, ob.bid
    # Passive limit: 80% fill probability per attempt
    import random
    if random.random() < 0.80:
        return size, price
    return 0.0, price


def _send_market(size, side, ob):
    """Market order: fills at ask (BUY) or bid (SELL) plus slippage."""
    slip  = slippage(size, ob, side)
    price = ob.ask * (1 + slip) if side == "BUY" else ob.bid * (1 - slip)
    return size, price


def exec_order(sig, size, ob):
    """
    Partial fill loop: 3 attempts × 40% each via limit.
    Market order for unfilled remainder.
    Returns {"filled": float, "avg_price": float, "order_type": str, "slippage": float}
    """
    side       = sig.get("action", "BUY")
    order_type = choose_type(sig, ob)
    lp         = limit_price(ob, side)

    filled      = 0.0
    price_sum   = 0.0
    entry_price = ob.ask if side == "BUY" else ob.bid   # reference for slippage calc

    if order_type in ("LIMIT", "POST"):
        for _ in range(3):
            chunk = size * 0.40
            if filled >= size * 0.80:
                break
            f, p = _send_limit(chunk, lp, side, ob)
            filled    += f
            price_sum += f * p

    # MARKET order or remainder
    if order_type == "MARKET" or filled < size:
        remainder = size - filled
        f, p = _send_market(remainder, side, ob)
        filled    += f
        price_sum += f * p

    avg_price  = price_sum / max(filled, 1e-9)
    slip_frac  = abs(avg_price - entry_price) / max(entry_price, 1e-9)

    return {
        "filled":     round(filled, 8),
        "avg_price":  avg_price,
        "order_type": order_type,
        "slippage":   round(slip_frac, 6),
    }
