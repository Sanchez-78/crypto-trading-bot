"""
Ultra-adaptive capital allocation — Bayesian EV, bandit routing,
depth-aware execution, stable regimes.

EV (Bayesian + time-decayed):
  risk_ev = 0.6×prev + 0.2×raw_sharpe + 0.2×bayes_ev, then ×0.995^dt.
  bayes_ev = Beta posterior WR (alpha/beta updated per trade, prior 5/5).

Capital allocation (six-factor):
  score  = risk_ev × risk_parity × cluster_penalty × (1+kelly) × bandit_UCB
  weight = softmax(scores)
  alloc  = base × clamp(0.5 + weight + 0.1×entropy, 0.5, 1.5)

Regime stability:
  detect_regime resists switching — 70% hysteresis via reg_cache.

Execution alpha (depth-weighted):
  0.02 × (imb−1) × min(depth/100000, 1).

Leverage: module-level equity tracking; boost capped +10%.
"""

import random
import numpy as np
import time as _time

# ── Per-symbol session state ───────────────────────────────────────────────────

slippage_hist: dict = {}   # sym -> [frac_slip, ...]         (last 100)
fill_stats:    dict = {}   # sym -> {"f": int, "t": int}
trade_log:     list = []   # [{"sym","reg","ws","slip"}]      (last 500)
returns_hist:  dict = {}   # sym -> [pnl, ...]                (last 200)
ev_cache:      dict = {}   # (sym, reg) -> (smooth, timestamp)
bayes_stats:   dict = {}   # (sym, reg) -> [alpha, beta]  (Beta prior 5/5)
bandit_stats:  dict = {}   # (sym, reg) -> [wins, plays]
reg_cache:     dict = {}   # sym -> last confirmed regime (hysteresis)
_equity:       list = [1.0]       # [current equity]   — mutable scalar
_equity_peak:  list = [1.0]       # [peak equity]


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


def detect_regime(sym):
    """
    Infer regime from last 20 returns with 70% hysteresis (reg_cache).
    Resists noisy flips: a raw change is accepted only 30% of the time,
    preventing overreaction to single-bar moves.
    BULL: positive trend + vol < 2%.  BEAR: negative + vol < 2%.  RANGE: else.
    """
    r = returns_hist.get(sym, [0.0])
    if len(r) < 20:
        return "RANGE"
    recent = r[-20:]
    trend  = float(np.mean(recent))
    v      = float(np.std(recent))
    if trend > 0 and v < 0.02:
        raw = "BULL"
    elif trend < 0 and v < 0.02:
        raw = "BEAR"
    else:
        raw = "RANGE"
    prev = reg_cache.get(sym, raw)
    if raw != prev and random.random() < 0.7:
        return prev   # resist switching 70% of the time
    reg_cache[sym] = raw
    return raw


def cluster_id(sym):
    """
    Symbol cluster classification (substring match for full pair names).
    majors: BTC, ETH  |  L1: SOL, AVAX  |  alts: everything else
    """
    if "BTC" in sym or "ETH" in sym:
        return "majors"
    if "SOL" in sym or "AVAX" in sym:
        return "L1"
    return "alts"


def cluster_penalty(sym, positions):
    """
    Penalise same-cluster concentration: 1 / (1 + 0.5 × count_in_cluster).
    count=0 → 1.0, count=1 → 0.67, count=2 → 0.5.
    Replaces correlation-based approach — works without returns history.
    """
    cid   = cluster_id(sym)
    count = sum(1 for p in positions.values()
                if cluster_id(p["signal"]["symbol"]) == cid)
    return 1.0 / (1.0 + 0.5 * count)


# ── Volatility & risk parity ──────────────────────────────────────────────────

def vol(sym):
    """Std of last 50 returns. Floor 0.005 caps risk_parity_weight at 200×."""
    r = returns_hist.get(sym, [0.0])
    return max(float(np.std(r[-50:])), 0.005)


def risk_parity_weight(sym):
    """1/vol — low-vol symbols receive proportionally larger allocation."""
    return 1.0 / vol(sym)


def entropy_reg(weights):
    """Shannon entropy of allocation weights. Higher = more diversified."""
    w = np.array(weights)
    return float(-np.sum(w * np.log(w + 1e-9)))


def bandit_update(sym, reg, outcome):
    """UCB1 bandit: outcome=1 win, 0 loss. Called on every trade close."""
    wins, plays = bandit_stats.get((sym, reg), (1, 2))
    bandit_stats[(sym, reg)] = (wins + outcome, plays + 1)


def bandit_score(sym, reg):
    """
    UCB1 exploration bonus: WR + sqrt(2×ln(N+1)/plays).
    Naturally routes toward under-explored (sym, reg) pairs.
    """
    wins, plays = bandit_stats.get((sym, reg), (1, 2))
    total = sum(p for _, p in bandit_stats.values()) + 1
    ucb   = wins / plays + float(np.sqrt(2.0 * np.log(total) / plays))
    return ucb


def kelly_fraction(sym, reg):
    """
    Half-Kelly: k = (p×(b+1)−1)/b, clamped [0, 0.25].
    Requires ≥20 trades per (sym, reg); else conservative 0.1.
    Uses median (robust to outliers) + clips pnl to ±0.05.
    """
    trades = [t for t in trade_log if t["sym"] == sym and t["reg"] == reg][-50:]
    if len(trades) < 20:
        return 0.1
    pnl  = np.clip([t["ws"] - t["slip"] for t in trades], -0.05, 0.05)
    wins = [p for p in pnl if p > 0]
    loss = [p for p in pnl if p < 0]
    if not wins or not loss:
        return 0.1
    p = len(wins) / len(pnl)
    b = float(np.median(wins)) / (abs(float(np.median(loss))) + 1e-6)
    k = (p * (b + 1) - 1) / (b + 1e-6)
    return max(0.0, min(k, 0.25))


# ── Risk EV (Sharpe-like) ─────────────────────────────────────────────────────

def raw_risk_ev(sym, reg):
    """Raw Sharpe-like EV from trade_log. PnL clipped ±0.05; std floor 0.01."""
    trades = [t for t in trade_log
              if t["sym"] == sym and t["reg"] == reg][-50:]
    if len(trades) < 10:
        return 0.0
    pnl = np.clip([t["ws"] - t["slip"] for t in trades], -0.05, 0.05)
    return float(np.mean(pnl)) / (float(np.std(pnl)) + 0.01)


def bayes_update(sym, reg, pnl):
    """Update Beta posterior: win → alpha+1, loss → beta+1."""
    a, b = bayes_stats.get((sym, reg), (5, 5))
    if pnl > 0:
        a += 1
    else:
        b += 1
    bayes_stats[(sym, reg)] = (a, b)


def bayes_ev(sym, reg):
    """Beta posterior WR: alpha/(alpha+beta). Prior 5/5 → 0.5 cold start."""
    a, b = bayes_stats.get((sym, reg), (5, 5))
    return a / (a + b)


def risk_ev(sym, reg):
    """
    Three-source blend + time decay:
      smooth = (0.6×prev + 0.2×raw_sharpe + 0.2×bayes_ev) × 0.995^dt_s.
    Bayes anchors cold-start; raw_sharpe corrects when data arrives.
    ev_cache stores (smooth, timestamp) for time-aware updates.
    """
    now      = _time.time()
    raw      = raw_risk_ev(sym, reg)
    b_ev     = bayes_ev(sym, reg)
    prev, ts = ev_cache.get((sym, reg), (raw, now))
    dt       = max(1, now - ts)
    smooth   = (0.6 * prev + 0.2 * raw + 0.2 * b_ev) * (0.995 ** dt)
    ev_cache[(sym, reg)] = (smooth, now)
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
    Six-factor softmax allocation:
      score  = risk_ev × risk_parity × cluster_penalty × (1+kelly) × bandit_UCB
      weight = softmax(scores)
      alloc  = base × clamp(0.5 + weight + 0.1×entropy, 0.5, 1.5)
    Bandit UCB drives exploration of under-traded (sym, reg) pairs.
    """
    def _score(s, r, pos_dict):
        return (max(risk_ev(s, r), 0.0)
                * risk_parity_weight(s)
                * cluster_penalty(s, pos_dict)
                * (1.0 + kelly_fraction(s, r))
                * bandit_score(s, r))

    new_score  = _score(sym, reg, positions)
    all_scores = [
        _score(p["signal"]["symbol"],
               p["signal"].get("regime", "RANGING"),
               positions)
        for p in positions.values()
    ]
    all_scores.append(new_score)
    exps    = np.exp(np.clip(all_scores, -10, 10))
    weights = exps / (np.sum(exps) + 1e-9)
    w_new   = float(weights[-1])
    entropy = entropy_reg(weights)
    return base * max(0.5, min(1.5, 0.5 + w_new + 0.1 * entropy))


# ── Exposure scale + leverage + final size ────────────────────────────────────

def exposure_scale(positions):
    """
    Smooth exposure throttle — replaces hard 70% cap.
    exp < 0.50 → 1.0  (full capital available)
    exp > 0.90 → 0.0  (fully deployed, no new positions)
    0.50–0.90  → linear taper 1 → 0
    """
    exp = sum(p["size"] for p in positions.values())
    if exp < 0.50:
        return 1.0
    if exp > 0.90:
        return 0.0
    return 1.0 - (exp - 0.50) / 0.40


def update_equity(pnl):
    """Update module-level equity and peak. Call on every trade close."""
    _equity[0]      += float(pnl)
    _equity_peak[0]  = max(_equity_peak[0], _equity[0])


def leverage(sym, reg):
    """
    Drawdown-adaptive base × EV boost (module-level equity, no import needed).
    base  = 1.2 - 0.7×min(dd/0.1, 1)  → [0.5, 1.2]
    boost = min(0.2×max(risk_ev,0), 0.1)  → capped at +10%.
    """
    peak = _equity_peak[0]
    eq   = _equity[0]
    if peak > 0:
        dd    = (peak - eq) / peak
        base  = 1.2 - 0.7 * min(dd / 0.1, 1.0)
        boost = min(0.2 * max(risk_ev(sym, reg), 0.0), 0.1)
        return base * (1.0 + boost)
    return 1.2


def execution_alpha(sym, ob):
    """
    Depth-weighted OB imbalance nudge: 0.02 × (imb−1) × min(depth/100000, 1).
    Thin books → strength→0 (unreliable signal).
    Deep books → full ±2% nudge at extreme imbalance.
    """
    imb      = ob.bid_vol / (ob.ask_vol + 1e-6)
    depth    = ob.bid_vol + ob.ask_vol
    strength = min(depth / 100_000.0, 1.0)
    return 0.02 * (imb - 1.0) * strength


def final_size(sym, reg, base, positions, ob=None):
    """
    capital_alloc × exposure_scale × leverage(sym,reg) × execution_alpha.
    detect_regime(sym) infers regime from returns_hist; overrides signal regime
    when not RANGE (i.e. when there is sufficient history to trust it).
    Returns 0 if exposure_scale == 0 (fully deployed).
    """
    scale = exposure_scale(positions)
    if scale == 0.0:
        return 0.0
    det_reg = detect_regime(sym)
    eff_reg = det_reg if det_reg != "RANGE" else reg
    alloc   = min(capital_alloc(sym, eff_reg, base, positions), 0.25)
    size    = alloc * scale * leverage(sym, eff_reg)
    if ob is not None:
        size *= (1.0 + execution_alpha(sym, ob))
    return size


def entry_filter(sym, reg):
    """Hard gate: only enter when risk_ev > 0.05. Blocks low-quality setups."""
    return risk_ev(sym, reg) > 0.05


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
