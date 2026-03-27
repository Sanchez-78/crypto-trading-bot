"""
Execution-aware learning engine — per-symbol state, unbiased slippage, true EV.

Slippage:
  Book-walk gives point estimate. blended_slip() mixes 70% book + 30% per-symbol
  history (when ≥5 samples) — unbiased vs global max() which over-penalised.

Order type:
  Per-symbol fill_rate() replaces global counter — avoids one illiquid symbol
  forcing MARKET across all pairs.

OB adjustment:
  Proportional: strength = |imb-1|, delta = 0.03 × strength × sign(imb-1).
  Larger imbalance → larger ws shift; neutral book → zero delta.

Staleness:
  dynamic_staleness(tick_ms, vol): base × (1 + vol×5).
  High volatility → wider tolerance (signal still relevant in fast market).

True EV:
  Per-symbol trade_log tracks ws - fractional_slip.
  true_ev(sym) returns mean of last 50. ev_adjust() blends into ws pre-sizing.

All slippage values stored and used as fractions of mid price.
"""

import numpy as np
import time as _time

# ── Per-symbol session state ───────────────────────────────────────────────────

slippage_hist: dict = {}   # sym -> [fractional slip, ...]   (last 100)
fill_stats:    dict = {}   # sym -> {"f": filled_count, "t": total_attempts}
trade_log:     list = []   # [{"sym", "ws", "slip"}, ...]    (last 500)


# ── Order book snapshot ────────────────────────────────────────────────────────

class OrderBook:
    """
    OB snapshot with 5 synthetic ask levels.
    levels: [(price, volume), ...] ascending (ask side).
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
        half   = price * spread_pct / 2
        ask    = price + half
        levels = [
            (ask,          5.0),
            (ask * 1.0002, 3.0),
            (ask * 1.0005, 2.0),
            (ask * 1.001,  1.0),
            (ask * 1.002,  0.5),
        ]
        return cls(bid=price - half, ask=ask,
                   bid_vol=10.0, ask_vol=10.0, levels=levels)


# ── Slippage: walk the book ────────────────────────────────────────────────────

def slippage(size, ob):
    """
    Walk ob.levels for true avg fill price.
    Returns fractional slippage: (avg_fill - mid) / mid.
    """
    if not ob.levels:
        return (ob.ask - ob.mid) / max(ob.mid, 1e-9)
    rem  = size
    cost = 0.0
    for p, v in ob.levels:
        take  = min(rem, v)
        cost += take * p
        rem  -= take
        if rem <= 0:
            break
    if rem > 0:
        cost += rem * ob.levels[-1][0]
    avg = cost / max(size, 1e-6)
    return (avg - ob.mid) / max(ob.mid, 1e-9)


# ── Per-symbol blended slippage ────────────────────────────────────────────────

def blended_slip(sym, size, ob):
    """
    70% book estimate + 30% per-symbol historical mean (when ≥5 samples).
    Falls back to pure book estimate during cold start.
    Removes global max() bias that over-penalised liquid symbols.
    """
    est  = slippage(size, ob)
    hist = slippage_hist.get(sym, [])
    if len(hist) >= 5:
        hist_mean = float(np.mean(hist[-20:]))
        return 0.7 * est + 0.3 * hist_mean
    return est


# ── Net edge after costs ───────────────────────────────────────────────────────

def net_edge(ws, size, ob, fee, sym):
    """Per-symbol blended slippage + fees. Positive = executable edge."""
    return ws - blended_slip(sym, size, ob) - fee


# ── OB imbalance: proportional ws adjustment ──────────────────────────────────

def ob_adjust(ws, ob):
    """
    Proportional: delta = 0.03 × |imb-1| × sign(imb-1).
    Neutral book (imb≈1) → near-zero delta; strong imbalance → up to ±0.03.
    """
    imb      = ob.bid_vol / (ob.ask_vol + 1e-6)
    strength = abs(imb - 1.0)
    return ws + 0.03 * strength * float(np.sign(imb - 1.0))


# ── Per-symbol fill rate ───────────────────────────────────────────────────────

def fill_rate(sym=None):
    """
    Per-symbol limit fill fraction.
    sym=None → aggregate across all symbols (fallback).
    Returns 1.0 when no data (optimistic cold start).
    """
    if sym is not None:
        s = fill_stats.get(sym, {"f": 0, "t": 0})
        return s["f"] / s["t"] if s["t"] > 0 else 1.0
    # aggregate
    total_f = sum(s["f"] for s in fill_stats.values())
    total_t = sum(s["t"] for s in fill_stats.values())
    return total_f / total_t if total_t > 0 else 1.0


# ── Order type selection ───────────────────────────────────────────────────────

def choose_type(sig, ob, sym):
    """Per-symbol fill_rate drives MARKET fallback — one slow symbol won't pollute others."""
    fr     = fill_rate(sym)
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
    spread = ob.ask - ob.bid
    if side == "BUY":
        return ob.bid + 0.10 * spread
    return ob.ask - 0.10 * spread


# ── Dynamic staleness ─────────────────────────────────────────────────────────

def dynamic_staleness(tick_ms, vol=0.0):
    """
    base = clamp(2×tick_ms, 200, 800).
    High vol extends window: fast moves keep signal relevant longer.
    """
    base = max(200, min(800, 2 * tick_ms))
    return base * (1.0 + vol * 5.0)


# ── Signal staleness guard ─────────────────────────────────────────────────────

def valid(sig_time, tick_ms=250, vol=0.0):
    age_ms = (_time.time() - sig_time) * 1000
    return age_ms < dynamic_staleness(tick_ms, vol)


# ── Pre-cost fast gate ─────────────────────────────────────────────────────────

def pre_cost(ws, fee):
    """Cheap early-exit: skip full slippage calc if ws can't cover fees alone."""
    return ws > fee


# ── Full cost gate ─────────────────────────────────────────────────────────────

def cost_guard(ws, size, ob, fee, sym):
    """net_edge > 0 using per-symbol blended slippage."""
    return net_edge(ws, size, ob, fee, sym) > 0


# ── True per-symbol EV from trade history ─────────────────────────────────────

def true_ev(sym):
    """
    Mean (ws - actual_slip) over last 50 trades for this symbol.
    Returns 0 if fewer than 10 samples — not enough data to trust.
    """
    trades = [t for t in trade_log if t["sym"] == sym][-50:]
    if len(trades) < 10:
        return 0.0
    pnl = [t["ws"] - t["slip"] for t in trades]
    return float(np.mean(pnl))


# ── EV-adjusted ws ────────────────────────────────────────────────────────────

def ev_adjust(ws, sym):
    """
    Blend current ws with per-symbol realised EV (weight 0.5).
    Positive history → cautiously higher ws; negative → lower.
    """
    ev = true_ev(sym)
    return ws + 0.5 * ev


# ── Internal paper-trading fill simulation ─────────────────────────────────────

def _send_limit(size, price, side, ob):
    import random
    if side == "BUY"  and price >= ob.ask: return size, ob.ask
    if side == "SELL" and price <= ob.bid: return size, ob.bid
    if random.random() < 0.80:            return size, price
    return 0.0, price


def _send_market(size, side, ob):
    slip  = slippage(size, ob)
    mid   = ob.mid
    price = mid * (1.0 + slip) if side == "BUY" else mid * (1.0 - slip)
    return size, price


# ── Core execution ─────────────────────────────────────────────────────────────

def exec_order(sig, size, ob, sym):
    """
    2 × 50% limit attempts; market fallback for remainder.
    Updates per-symbol fill_stats and slippage_hist.
    Appends to trade_log for true_ev().
    Returns (avg_fill_price, fractional_slip).
    """
    side       = sig.get("action", "BUY")
    order_type = choose_type(sig, ob, sym)
    lp         = limit_price(ob, side)
    ref_price  = sig.get("price", ob.mid)

    filled    = 0.0
    price_sum = 0.0

    fs = fill_stats.setdefault(sym, {"f": 0, "t": 0})

    if order_type in ("LIMIT", "POST"):
        for _ in range(2):
            chunk = size * 0.50
            if filled >= size * 0.70:
                break
            fs["t"] += 1
            f, p = _send_limit(chunk, lp, side, ob)
            if f > 0:
                fs["f"]   += 1
                filled    += f
                price_sum += f * p

    if order_type == "MARKET" or filled < size:
        f, p = _send_market(size - filled, side, ob)
        filled    += f
        price_sum += f * p

    avg  = price_sum / max(filled, 1e-9)
    slip = (avg - ref_price) / max(ref_price, 1e-9)
    if side == "SELL":
        slip = -slip

    hist = slippage_hist.setdefault(sym, [])
    hist.append(slip)
    if len(hist) > 100:
        hist.pop(0)

    trade_log.append({"sym": sym, "ws": sig.get("ws", 0.5), "slip": slip})
    if len(trade_log) > 500:
        trade_log.pop(0)

    return avg, slip
