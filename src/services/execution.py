"""
Exchange-level execution engine — feedback-aware, cost-accurate.

Slippage model:
  Walk ob.levels (price, volume) pairs to compute true avg fill price.
  Pessimistic: max(book_estimate, mean(last_20_actual)) prevents underestimation.

Order type:
  MARKET  — fill_rate<30% (limits not filling) OR strong momentum+imbalance
  LIMIT   — spread<0.05% of mid
  POST    — default maker

Partial fill loop:
  2 attempts × 50%; market fallback for remainder.
  fill_stats tracks limit attempts vs actual fills → drives choose_type.

OB adjustment:
  ob_adjust() softly shifts ws ±0.02 — not a hard block.

Staleness:
  dynamic_staleness(tick_ms) = clamp(2×tick_ms, 200, 800 ms).
  Fast market → tighter window; slow market → more tolerance.
"""

import time as _time

# ── Session state ──────────────────────────────────────────────────────────────

slippage_hist = []          # actual slippage per fill (fractional, last 100)
fill_stats    = {"limit": 0, "market": 0, "limit_filled": 0}


# ── Order book snapshot ────────────────────────────────────────────────────────

class OrderBook:
    """
    OB snapshot with synthetic depth levels.
    levels: list of (price, volume) tuples in ascending price order (ask side).
    mid: (bid + ask) / 2
    """
    __slots__ = ("bid", "ask", "bid_vol", "ask_vol", "levels", "ts")

    def __init__(self, bid, ask, bid_vol=10.0, ask_vol=10.0, levels=None, ts=None):
        self.bid     = float(bid)
        self.ask     = float(ask)
        self.bid_vol = float(bid_vol)
        self.ask_vol = float(ask_vol)
        self.levels  = levels or []
        self.ts      = ts or _time.time()

    @property
    def mid(self):
        return (self.bid + self.ask) / 2.0

    @classmethod
    def from_price(cls, price, spread_pct=0.001):
        """
        Construct OB from single price.
        Synthesizes 5 ask levels with decreasing volume at widening spread.
        """
        half = price * spread_pct / 2
        ask  = price + half
        # (price, volume) — each level further away, thinner
        levels = [
            (ask,              5.0),
            (ask * 1.0002,     3.0),
            (ask * 1.0005,     2.0),
            (ask * 1.001,      1.0),
            (ask * 1.002,      0.5),
        ]
        return cls(bid=price - half, ask=ask,
                   bid_vol=10.0, ask_vol=10.0, levels=levels)


# ── Slippage: walk the book ────────────────────────────────────────────────────

def slippage(size, ob):
    """
    Walk ob.levels to compute avg fill price. Returns fraction above mid.
    Falls back to spread/2 if levels are empty.
    """
    if not ob.levels:
        return (ob.ask - ob.mid) / max(ob.mid, 1e-9)
    remaining = size
    cost      = 0.0
    for p, v in ob.levels:
        take       = min(remaining, v)
        cost      += take * p
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:                          # exhausted book — use last level
        cost += remaining * ob.levels[-1][0]
    avg = cost / max(size, 1e-6)
    return (avg - ob.mid) / max(ob.mid, 1e-9)  # fractional slippage


# ── Net edge after costs ───────────────────────────────────────────────────────

def net_edge(ws, size, ob, fee):
    """
    Pessimistic net edge: use max(book_estimate, recent_mean).
    Prevents underestimating costs when market is moving.
    """
    est_slip = slippage(size, ob)
    if len(slippage_hist) > 20:
        recent_mean = sum(slippage_hist[-20:]) / 20
        est_slip    = max(est_slip, recent_mean)
    return ws - est_slip - fee


# ── OB imbalance: soft ws adjustment ──────────────────────────────────────────

def ob_adjust(ws, ob):
    """
    Soft adjustment: confirming imbalance +0.02, opposing -0.02.
    Not a hard gate — avoids over-filtering low-liquidity markets.
    """
    imb = ob.bid_vol / (ob.ask_vol + 1e-6)
    if imb > 1.5:
        return ws + 0.02
    if imb < 0.70:
        return ws - 0.02
    return ws


# ── Dynamic staleness ─────────────────────────────────────────────────────────

def dynamic_staleness(tick_ms):
    """Clamp(2×tick_ms, 200, 800). Fast feed = tighter window."""
    return max(200, min(800, 2 * tick_ms))


# ── Fill rate tracker ──────────────────────────────────────────────────────────

def fill_rate():
    """Fraction of limit attempts that actually filled. 1.0 if no data."""
    if fill_stats["limit"] == 0:
        return 1.0
    return fill_stats["limit_filled"] / fill_stats["limit"]


# ── Order type selection ───────────────────────────────────────────────────────

def choose_type(sig, ob, fr=None):
    """
    fr: fill_rate() result — if < 0.30, limits aren't filling → use MARKET.
    MARKET  — low fill rate OR strong momentum + confirming imbalance
    LIMIT   — tight spread (<0.05% of mid)
    POST    — default
    """
    if fr is None:
        fr = fill_rate()
    spread = ob.ask - ob.bid
    mid    = ob.mid
    imb    = ob.bid_vol / (ob.ask_vol + 1e-6)
    mom    = sig.get("features", {}).get("mom5", 0.0)

    if fr < 0.30:
        return "MARKET"
    if abs(mom) > 0.007 and imb > 1.2:
        return "MARKET"
    if spread / max(mid, 1e-9) < 0.0005:
        return "LIMIT"
    return "POST"


# ── Limit price ────────────────────────────────────────────────────────────────

def limit_price(ob, side):
    """10% into spread — competitive but avoids queue tail."""
    spread = ob.ask - ob.bid
    if side == "BUY":
        return ob.bid + 0.10 * spread
    return ob.ask - 0.10 * spread


# ── Signal staleness guard ─────────────────────────────────────────────────────

def valid(sig_time, tick_ms=250):
    """Fresh if age < dynamic_staleness(tick_ms)."""
    age_ms = (_time.time() - sig_time) * 1000
    return age_ms < dynamic_staleness(tick_ms)


# ── Cost guard ─────────────────────────────────────────────────────────────────

def cost_guard(ws, size, ob, fee):
    """True only if net_edge > 0 after pessimistic slippage + fees."""
    return net_edge(ws, size, ob, fee) > 0


# ── Internal paper-trading fill simulation ─────────────────────────────────────

def _send_limit(size, price, side, ob):
    """80% fill probability for passive limit; immediate if marketable."""
    import random
    if side == "BUY" and price >= ob.ask:
        return size, ob.ask
    if side == "SELL" and price <= ob.bid:
        return size, ob.bid
    if random.random() < 0.80:
        return size, price
    return 0.0, price


def _send_market(size, side, ob):
    """Market fill at top-of-book; walks levels for price impact."""
    slip  = slippage(size, ob)
    mid   = ob.mid
    price = mid * (1 + slip) if side == "BUY" else mid * (1 - slip)
    return size, price


# ── Core execution ─────────────────────────────────────────────────────────────

def exec_order(sig, size, ob):
    """
    2 attempts × 50% via limit; market fallback for remainder.
    Updates fill_stats. Records actual slippage in slippage_hist.
    Returns (avg_fill_price, slippage_frac).
    """
    side       = sig.get("action", "BUY")
    fr         = fill_rate()
    order_type = choose_type(sig, ob, fr)
    lp         = limit_price(ob, side)
    ref_price  = sig.get("price", ob.mid)

    filled    = 0.0
    price_sum = 0.0

    if order_type in ("LIMIT", "POST"):
        for _ in range(2):
            chunk = size * 0.50
            if filled >= size * 0.70:
                break
            fill_stats["limit"] += 1
            f, p = _send_limit(chunk, lp, side, ob)
            if f > 0:
                fill_stats["limit_filled"] += 1
                filled    += f
                price_sum += f * p

    if order_type == "MARKET" or filled < size:
        remainder = size - filled
        fill_stats["market"] += 1
        f, p = _send_market(remainder, side, ob)
        filled    += f
        price_sum += f * p

    avg   = price_sum / max(filled, 1e-9)
    slip  = (avg - ref_price) / max(ref_price, 1e-9)
    if side == "SELL":
        slip = -slip          # SELL: lower fill = slippage

    slippage_hist.append(slip)
    if len(slippage_hist) > 100:
        slippage_hist.pop(0)

    return avg, slip
