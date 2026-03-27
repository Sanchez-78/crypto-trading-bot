"""
Portfolio risk-parity execution engine — correlation clustering + adaptive leverage.

Risk EV (Sharpe-like):
  risk_ev = mean(pnl) / (std(pnl) + ε)  — rewards consistent EV, penalises variance.
  Regime-split: prevents BULL_TREND weights polluting RANGING allocation.

Capital allocation (three-factor):
  score = risk_ev × risk_parity_weight × cluster_penalty
  weight = score / total_score_of_open_positions
  alloc  = base × clamp(0.5 + weight, 0.5, 1.5)
  - risk_parity_weight = 1/vol → low-vol symbols get larger allocation (equal risk)
  - cluster_penalty: ×0.5 for each open position with |corr| > 0.7 (avoids doubling up)

Leverage (drawdown-adaptive):
  dd > 10%  → 0.5×   (capital preservation)
  dd < 2%   → 1.2×   (light tailwind in low-drawdown phase)
  otherwise → 1.0×

final_size = capital_alloc × leverage  (replaces fixed base in executor)

Rotation:
  rotate_capital: true_ev 20% better AND ev_conf > 0.5 required.
  Confidence gate prevents rotating on thin history.
"""

import numpy as np
import time as _time

# ── Per-symbol session state ───────────────────────────────────────────────────

slippage_hist: dict = {}   # sym -> [frac_slip, ...]         (last 100)
fill_stats:    dict = {}   # sym -> {"f": int, "t": int}
trade_log:     list = []   # [{"sym","reg","ws","slip"}]      (last 500)
returns_hist:  dict = {}   # sym -> [pnl, ...]                (last 200)
ev_cache:      dict = {}   # (sym, reg) -> smoothed risk_ev   (EMA 0.8/0.2)


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


# ── Slippage ───────────────────────────────────────────────────────────────────

def slippage(size, ob):
    """Walk ob.levels → fractional (avg_fill − mid) / mid."""
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
    """70% book + 30% per-symbol history (when ≥5 samples)."""
    est  = slippage(size, ob)
    hist = slippage_hist.get(sym, [])
    if len(hist) >= 5:
        return 0.7 * est + 0.3 * float(np.mean(hist[-20:]))
    return est


def net_edge(ws, size, ob, fee, sym):
    return ws - blended_slip(sym, size, ob) - fee


# ── OB imbalance adjustment ────────────────────────────────────────────────────

def ob_adjust(ws, ob):
    """Proportional: delta = 0.03 × |imb−1| × sign(imb−1)."""
    imb      = ob.bid_vol / (ob.ask_vol + 1e-6)
    strength = abs(imb - 1.0)
    return ws + 0.03 * strength * float(np.sign(imb - 1.0))


# ── Returns history ───────────────────────────────────────────────────────────

def update_returns(sym, pnl):
    """Record realised PnL per symbol. Called on every trade close."""
    hist = returns_hist.setdefault(sym, [])
    hist.append(float(pnl))
    if len(hist) > 200:
        hist.pop(0)


# ── Correlation & clustering ──────────────────────────────────────────────────

def corr(sym1, sym2):
    """
    Pearson correlation of return histories. Returns 0 when <10 common samples.
    Used only for penalty — false positive (over-penalty) is safer than false negative.
    """
    r1 = returns_hist.get(sym1, [])
    r2 = returns_hist.get(sym2, [])
    n  = min(len(r1), len(r2))
    if n < 10:
        return 0.0
    try:
        return float(np.corrcoef(r1[-n:], r2[-n:])[0, 1])
    except Exception:
        return 0.0


def cluster_penalty(sym, positions):
    """
    Non-multiplicative: collect per-position penalties, return the minimum.
    Avoids stacking (two 0.7-corr positions previously gave 0.5×0.5=0.25).
    At corr=0.7: factor=1.0. At corr=1.0: factor=0.5. Floor 0.3.
    """
    penalties = []
    for pos in positions.values():
        other = pos["signal"]["symbol"]
        if other == sym:
            continue
        c = abs(corr(sym, other))
        if c > 0.7:
            penalties.append(1.0 - 0.5 * (c - 0.7) / 0.3)
    if not penalties:
        return 1.0
    return max(min(penalties), 0.3)


# ── Volatility & risk parity ──────────────────────────────────────────────────

def vol(sym):
    """Std of last 50 returns. Floor 0.005 caps risk_parity_weight at 200×."""
    r = returns_hist.get(sym, [0.0])
    return max(float(np.std(r[-50:])), 0.005)


def risk_parity_weight(sym):
    """1/vol — low-vol symbols receive proportionally larger allocation."""
    return 1.0 / vol(sym)


# ── Risk EV (Sharpe-like) ─────────────────────────────────────────────────────

def raw_risk_ev(sym, reg):
    """Raw Sharpe-like EV from trade_log. std floor 0.01."""
    trades = [t for t in trade_log
              if t["sym"] == sym and t["reg"] == reg][-50:]
    if len(trades) < 10:
        return 0.0
    pnl = [t["ws"] - t["slip"] for t in trades]
    return float(np.mean(pnl)) / (float(np.std(pnl)) + 0.01)


def risk_ev(sym, reg):
    """
    EMA-smoothed Sharpe EV: 0.8×prev + 0.2×raw.
    Dampens tick-to-tick noise without forgetting regime shifts.
    Cold start: first call initialises cache from raw value.
    """
    raw  = raw_risk_ev(sym, reg)
    prev = ev_cache.get((sym, reg), raw)
    smooth = 0.8 * prev + 0.2 * raw
    ev_cache[(sym, reg)] = smooth
    return smooth


def ev_conf(sym, reg):
    """min(n/50, 1.0) — confidence weight based on sample count."""
    n = sum(1 for t in trade_log if t["sym"] == sym and t["reg"] == reg)
    return min(1.0, n / 50.0)


def ev_adjust(ws, sym, reg):
    """
    ws + 0.3 × clamp(risk_ev, −0.05, +0.05) × conf.
    Clamp prevents runaway; conf prevents cold-start noise.
    """
    ev   = max(-0.05, min(0.05, risk_ev(sym, reg)))
    conf = ev_conf(sym, reg)
    return ws + 0.3 * ev * conf


# ── Fill rate & order type ─────────────────────────────────────────────────────

def fill_rate(sym=None):
    if sym is not None:
        s = fill_stats.get(sym, {"f": 0, "t": 0})
        return s["f"] / s["t"] if s["t"] > 0 else 1.0
    total_f = sum(s["f"] for s in fill_stats.values())
    total_t = sum(s["t"] for s in fill_stats.values())
    return total_f / total_t if total_t > 0 else 1.0


def choose_type(sig, ob, sym):
    fr     = fill_rate(sym)
    spread = ob.ask - ob.bid
    mid    = ob.mid
    imb    = ob.bid_vol / (ob.ask_vol + 1e-6)
    mom    = sig.get("features", {}).get("mom5", 0.0)
    if fr < 0.30:                           return "MARKET"
    if abs(mom) > 0.007 and imb > 1.2:     return "MARKET"
    if spread / max(mid, 1e-9) < 0.0005:   return "LIMIT"
    return "POST"


def limit_price(ob, side):
    spread = ob.ask - ob.bid
    return ob.bid + 0.10 * spread if side == "BUY" else ob.ask - 0.10 * spread


# ── Staleness ─────────────────────────────────────────────────────────────────

def dynamic_staleness(tick_ms, vol_f=0.0):
    """Vol capped at 0.02 to prevent extreme window widening."""
    base = max(200, min(800, 2 * tick_ms))
    return base * (1.0 + min(vol_f, 0.02) * 2.0)


def valid(sig_time, tick_ms=250, vol_f=0.0):
    return (_time.time() - sig_time) * 1000 < dynamic_staleness(tick_ms, vol_f)


# ── Cost gates ─────────────────────────────────────────────────────────────────

def pre_cost(ws, fee):
    return ws > fee


def cost_guard(ws, size, ob, fee, sym):
    return net_edge(ws, size, ob, fee, sym) > 0


# ── Capital allocation (risk-parity + EV + correlation) ───────────────────────

def capital_alloc(sym, reg, base, positions):
    """
    Softmax weighting over [new_signal] + open positions.
    exp(score) / sum(exp(scores)) — smooth, bounded, sums to 1.
    Clamp output [0.5×, 1.5×] base as before.
    """
    def _score(s, r, pos_dict):
        return (max(risk_ev(s, r), 0.0)
                * risk_parity_weight(s)
                * cluster_penalty(s, pos_dict))

    new_score = _score(sym, reg, positions)
    all_scores = [
        _score(p["signal"]["symbol"],
               p["signal"].get("regime", "RANGING"),
               positions)
        for p in positions.values()
    ]
    all_scores.append(new_score)
    exps = np.exp(np.clip(all_scores, -10, 10))   # clip prevents overflow
    w    = exps[-1] / (np.sum(exps) + 1e-9)
    return base * max(0.5, min(1.5, 0.5 + w))


# ── Adaptive leverage ──────────────────────────────────────────────────────────

def leverage():
    """
    Smooth linear leverage: 1.2 - 0.7 × min(dd/0.1, 1).
    dd=0%   → 1.2×  (maximum; low-drawdown phase)
    dd=10%  → 0.5×  (capital preservation floor)
    dd>10%  → clamped at 0.5× (no further reduction)
    Eliminates the step discontinuity that caused size jumps.
    """
    try:
        from src.services.learning_event import METRICS
        peak   = METRICS.get("equity_peak", 0.0) or 0.0
        profit = METRICS.get("profit", 0.0) or 0.0
        if peak > 0:
            dd = (peak - (1.0 + profit)) / peak
            return 1.2 - 0.7 * min(dd / 0.1, 1.0)
    except Exception:
        pass
    return 1.2


# ── Final position size (allocation × leverage) ────────────────────────────────

def total_exposure(positions):
    """Sum of all open position sizes — portfolio gross exposure."""
    return sum(p["size"] for p in positions.values())


def final_size(sym, reg, base, positions):
    """
    Hard portfolio cap: if total deployed > 70%, reject new position.
    Then: min(capital_alloc, 0.25) × leverage.
    """
    if total_exposure(positions) > 0.70:
        return 0.0
    alloc = min(capital_alloc(sym, reg, base, positions), 0.25)
    return alloc * leverage()


# ── Portfolio EV snapshot ──────────────────────────────────────────────────────

def portfolio_ev(positions):
    return {
        sym: risk_ev(sym, pos["signal"].get("regime", "RANGING"))
        for sym, pos in positions.items()
    }


# ── Capital rotation ───────────────────────────────────────────────────────────

def rotate_capital(new_sig, positions, max_pos=2):
    """
    Replace worst position only when:
      1. new signal risk_ev > worst × 1.2
      2. ev_conf > 0.5 — sufficient history to trust the comparison
    Returns (should_rotate: bool, worst_sym: str|None).
    """
    if len(positions) < max_pos:
        return False, None
    new_sym = new_sig["symbol"]
    new_reg = new_sig.get("regime", "RANGING")
    if ev_conf(new_sym, new_reg) <= 0.5:
        return False, None
    new_rev = risk_ev(new_sym, new_reg)
    worst_sym = min(
        positions,
        key=lambda s: risk_ev(s, positions[s]["signal"].get("regime", "RANGING"))
    )
    worst_rev = risk_ev(worst_sym,
                        positions[worst_sym]["signal"].get("regime", "RANGING"))
    if new_rev > worst_rev * 1.2:
        return True, worst_sym
    return False, None


# ── Internal fill simulation ───────────────────────────────────────────────────

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
    2 × 50% limit + market fallback. Updates fill_stats, slippage_hist, trade_log.
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
            if filled >= size * 0.70:
                break
            chunk = size * 0.50
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
