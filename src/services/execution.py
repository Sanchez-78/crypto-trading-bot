"""
Regime-aware portfolio EV engine — stable feedback, capital routing.

Slippage:
  blended_slip: 70% book-walk + 30% per-symbol history (>=5 samples).

EV feedback (bounded):
  true_ev(sym, reg): mean(ws - actual_slip) over last 50 trades for (sym, regime).
  ev_conf(sym, reg): sample confidence = min(n/50, 1.0).
  ev_adjust: ws + 0.3 * clamp(ev, -0.05, +0.05) * conf.
  Clamp prevents runaway feedback; conf prevents cold-start noise.

Capital allocation:
  capital_alloc: base * (0.5 + ev_weight), where weight = sym_ev / total_ev.
  Floor at 0.5× base prevents starvation; EV drives up to 1.5× base.

Portfolio rotation:
  rotate_capital: replaces worst (sym, reg) position if new signal EV is 20%
  better. Returns (True, worst_sym) — caller handles the actual close.

Staleness:
  dynamic_staleness: vol capped at 0.02 (2×) to prevent extreme widening.
"""

import numpy as np
import time as _time

# ── Per-symbol session state ───────────────────────────────────────────────────

slippage_hist: dict = {}   # sym -> [frac_slip, ...]  (last 100)
fill_stats:    dict = {}   # sym -> {"f": int, "t": int}
trade_log:     list = []   # [{"sym","reg","ws","slip"}, ...]  (last 500)


# ── Order book snapshot ────────────────────────────────────────────────────────

class OrderBook:
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
    """Fractional: (avg_fill - mid) / mid."""
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


def blended_slip(sym, size, ob):
    """70% book estimate + 30% per-symbol history (when >=5 samples)."""
    est  = slippage(size, ob)
    hist = slippage_hist.get(sym, [])
    if len(hist) >= 5:
        return 0.7 * est + 0.3 * float(np.mean(hist[-20:]))
    return est


# ── Net edge after costs ───────────────────────────────────────────────────────

def net_edge(ws, size, ob, fee, sym):
    return ws - blended_slip(sym, size, ob) - fee


# ── OB imbalance: proportional ws adjustment ──────────────────────────────────

def ob_adjust(ws, ob):
    """delta = 0.03 × |imb-1| × sign(imb-1). Neutral OB → 0 delta."""
    imb      = ob.bid_vol / (ob.ask_vol + 1e-6)
    strength = abs(imb - 1.0)
    return ws + 0.03 * strength * float(np.sign(imb - 1.0))


# ── Per-symbol fill rate ───────────────────────────────────────────────────────

def fill_rate(sym=None):
    if sym is not None:
        s = fill_stats.get(sym, {"f": 0, "t": 0})
        return s["f"] / s["t"] if s["t"] > 0 else 1.0
    total_f = sum(s["f"] for s in fill_stats.values())
    total_t = sum(s["t"] for s in fill_stats.values())
    return total_f / total_t if total_t > 0 else 1.0


# ── Order type selection ───────────────────────────────────────────────────────

def choose_type(sig, ob, sym):
    fr     = fill_rate(sym)
    spread = ob.ask - ob.bid
    mid    = ob.mid
    imb    = ob.bid_vol / (ob.ask_vol + 1e-6)
    mom    = sig.get("features", {}).get("mom5", 0.0)

    if fr < 0.30:                                    return "MARKET"
    if abs(mom) > 0.007 and imb > 1.2:              return "MARKET"
    if spread / max(mid, 1e-9) < 0.0005:            return "LIMIT"
    return "POST"


# ── Limit price ────────────────────────────────────────────────────────────────

def limit_price(ob, side):
    spread = ob.ask - ob.bid
    return ob.bid + 0.10 * spread if side == "BUY" else ob.ask - 0.10 * spread


# ── Dynamic staleness ─────────────────────────────────────────────────────────

def dynamic_staleness(tick_ms, vol=0.0):
    """Vol capped at 0.02 — prevents extreme window widening in flash events."""
    base = max(200, min(800, 2 * tick_ms))
    return base * (1.0 + min(vol, 0.02) * 2.0)


def valid(sig_time, tick_ms=250, vol=0.0):
    age_ms = (_time.time() - sig_time) * 1000
    return age_ms < dynamic_staleness(tick_ms, vol)


# ── Cost gates ─────────────────────────────────────────────────────────────────

def pre_cost(ws, fee):
    """Cheap early-exit before slippage calculation."""
    return ws > fee


def cost_guard(ws, size, ob, fee, sym):
    return net_edge(ws, size, ob, fee, sym) > 0


# ── Regime-aware true EV ──────────────────────────────────────────────────────

def true_ev(sym, reg):
    """
    Mean(ws - slip) for (sym, regime) over last 50 trades.
    Returns 0 when fewer than 10 samples — not enough to trust.
    """
    trades = [t for t in trade_log
              if t["sym"] == sym and t["reg"] == reg][-50:]
    if len(trades) < 10:
        return 0.0
    return float(np.mean([t["ws"] - t["slip"] for t in trades]))


def ev_conf(sym, reg):
    """Confidence weight: min(n/50, 1.0). Zero → no adjustment; 50+ → full."""
    n = sum(1 for t in trade_log if t["sym"] == sym and t["reg"] == reg)
    return min(1.0, n / 50.0)


def ev_adjust(ws, sym, reg):
    """
    Bounded regime-aware EV blend: ws + 0.3 × clamp(ev, -0.05, +0.05) × conf.
    Clamp prevents runaway positive/negative feedback loops.
    """
    ev   = max(-0.05, min(0.05, true_ev(sym, reg)))
    conf = ev_conf(sym, reg)
    return ws + 0.3 * ev * conf


# ── Portfolio EV snapshot ──────────────────────────────────────────────────────

def portfolio_ev(positions):
    """
    Returns {sym: true_ev(sym, reg)} for all open positions.
    positions: dict of sym -> position dict (from trade_executor._positions).
    """
    return {
        sym: true_ev(sym, pos["signal"].get("regime", "RANGING"))
        for sym, pos in positions.items()
    }


# ── EV-weighted capital allocation ────────────────────────────────────────────

def capital_alloc(sym, reg, base, positions):
    """
    EV-proportional base size: base × (0.5 + weight).
    weight = sym_ev / total_positive_ev across open positions + new signal.
    Floor 0.5× prevents capital starvation; max 1.5× caps over-allocation.
    """
    sym_ev   = max(true_ev(sym, reg), 0.0)
    total_ev = sym_ev + sum(
        max(true_ev(p["signal"]["symbol"],
                    p["signal"].get("regime", "RANGING")), 0.0)
        for p in positions.values()
    ) + 1e-6
    weight = sym_ev / total_ev
    return base * max(0.5, min(1.5, 0.5 + weight))


# ── Capital rotation ───────────────────────────────────────────────────────────

def rotate_capital(new_sig, positions, max_pos=2):
    """
    When portfolio is full, replace worst position if new signal's regime EV
    is at least 20% better. Returns (should_rotate: bool, worst_sym: str|None).
    Caller is responsible for the actual close/open.
    """
    if len(positions) < max_pos:
        return False, None
    new_ev = true_ev(new_sig["symbol"], new_sig.get("regime", "RANGING"))
    worst_sym = min(
        positions,
        key=lambda s: true_ev(s, positions[s]["signal"].get("regime", "RANGING"))
    )
    worst_ev = true_ev(worst_sym,
                       positions[worst_sym]["signal"].get("regime", "RANGING"))
    if new_ev > worst_ev * 1.2:
        return True, worst_sym
    return False, None


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
    2 × 50% limit attempts + market fallback.
    Records regime in trade_log for regime-split EV tracking.
    Returns (avg_fill_price, fractional_slip).
    """
    side       = sig.get("action", "BUY")
    order_type = choose_type(sig, ob, sym)
    lp         = limit_price(ob, side)
    ref_price  = sig.get("price", ob.mid)
    reg        = sig.get("regime", "RANGING")

    filled    = 0.0
    price_sum = 0.0
    fs        = fill_stats.setdefault(sym, {"f": 0, "t": 0})

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

    trade_log.append({"sym": sym, "reg": reg, "ws": sig.get("ws", 0.5), "slip": slip})
    if len(trade_log) > 500:
        trade_log.pop(0)

    return avg, slip
