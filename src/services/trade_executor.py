"""
Trade executor with ATR-based TP/SL and trailing stop.

Risk management:
  TP    = 1.2× ATR   minimum 0.30% of entry price
  SL    = 1.0× ATR   minimum 0.25% of entry price
  Trail = 0.5× SL    trailing offset once in profit
  Timeout = 60 ticks (~6 min at 2s/tick × 3 symbols)

Position sizing:
  size = base × clamp(ev×6, 0.5, 3.0) × auditor_factor (floor 0.7)
  Strong edge: ev > threshold×1.5 → size ×1.5
  ≥ 20 trades: base 5%;  < 20 trades: base 2.5%

Calibration feedback:
  After every close → calibrator.update(confidence, WIN/LOSS)
  Enables empirical WR mapping per confidence bucket.

Firebase batch flush: every 20 trades OR every 5 minutes.
"""

from src.core.event_bus           import subscribe_once
from src.services.learning_event  import update_metrics
from src.services.firebase_client import save_batch
from src.services.execution       import (
    exec_order, valid, ob_adjust, cost_guard, pre_cost,
    ev_adjust, fill_rate, final_size, entry_filter,
    rotate_capital, update_returns, update_equity, record_trade_close,
    bayes_update, bandit_update, OrderBook,
    bootstrap_mode, ws_threshold, cost_guard_bootstrap, size_floor,
    failure_control, epsilon, final_size_meta,
    is_bootstrap, net_edge, returns_hist)
import math
import random
import time

BATCH             = []
_positions        = {}
_last_flush       = [0.0]
_regime_exposure  = {}   # regime -> count of open positions
_pending_open     = []   # signals queued after replace_if_better triggers

MAX_POSITIONS     = 3    # max concurrent open positions (raised for bootstrap learning speed)
MAX_SAME_DIR      = 2    # max positions in same direction — 1→2: in BULL_TREND all symbols
                          # generate BUY, old limit=1 blocked 2/3 signals every tick, cutting
                          # learning rate by 67%; raise to 2 for faster data accumulation
MAX_REGIME_PCT    = 0.70 # block if one regime holds > 70% of open positions
_TOTAL_CAPITAL    = 1.0  # normalised capital (position sizes are fractions)
_MAX_CAP_USED     = 0.70 # don't deploy more than 70% of capital
_TARGET_VOL       = 0.02 # 2% target realised volatility for vol-adjusted sizing
_REPLACE_MARGIN   = 1.10 # new signal must be 10% better to replace weakest
_REPLACE_COOLDOWN = 300  # seconds between replacements of the same symbol
_MAX_TOTAL_RISK   = 0.05 # total portfolio risk cap (sum of size*sl_pct)
_SPREAD_PCT       = 0.001 # estimated bid-ask spread (0.10%)
_last_replaced    = {}   # symbol -> timestamp of last replacement
_last_replace_ts  = 0.0  # V10.4b: global cooldown — no replacement within 15 s of the last one
_pf_tick_counter  = [0]  # V10.13: global tick counter for portfolio_pnl sampling rate
_meta_ema   = {"lm_health": None, "sharpe": None, "drawdown": None}  # V10.6b: smoothed inputs
_meta_state = {                                                        # V10.6b: adaptive control
    "mode":              "neutral",
    "last_update":       0.0,
    "replace_threshold": 0.05,   # default; updated by update_meta_mode()
    "pyramid_trigger":   0.004,  # default; updated by update_meta_mode()
    "reduce_threshold":  -0.003, # default; updated by update_meta_mode()
}

FEE_RT      = 0.0015    # 0.15% round-trip (Binance taker 0.075%×2)
MIN_TP_PCT  = 0.008     # 0.80% — giving trades room to hit higher RRs
MIN_SL_PCT  = 0.004     # 0.40% min SL — double the old size to survive spread + fee + noise
FLUSH_EVERY              = 15   # lowered 60→15s: with 60s window up to 14 trades
                                 # were lost on Railway restart (BATCH not flushed
                                 # before process kill). 15s → max ~3-4 trades lost.
MIN_TRADES_PER_100_TICKS = 5     # force-trade threshold: if fewer → bypass sigmoid gate
MIN_EDGE_PCT             = 0.0003 # 0.03% min TP/SL distance (log: avg ATR-based TP=0.038%,
                                  # old 0.20% blocked 336/346 signals — 97% kill rate)
_tick_counter   = [0]            # global price-tick counter (incremented in on_price)
_trades_at_tick = []             # tick values when positions were opened (rate tracking)


def _adaptive_tp_sl(ev, wr):
    """V8: Continuous TP/SL multipliers from EV and win rate.

    Replaces discrete 3-tier EV lookup with smooth scaling.
    At ev=0, wr=0.5: tp_k=1.1, sl_k=0.9  (near-current baseline).
    At ev=0.5, wr=0.6: tp_k=1.55, sl_k=0.75  (proven winner).
    At ev=-0.5, wr=0.4: tp_k=0.75, sl_k=1.05  (clipped to 1.0/0.6).
    Clamps: tp_k ∈ [1.0, 2.0], sl_k ∈ [0.6, 1.0].
    """
    tp_k = 1.1 + (ev * 0.8) + ((wr - 0.5) * 0.5)
    sl_k = 0.9 - (ev * 0.3)
    return min(max(tp_k, 1.0), 2.0), min(max(sl_k, 0.6), 1.0)


def regime_tp_sl_adjust(tp_k, sl_k, regime):
    """V10.2: Regime-specific TP/SL multipliers applied after EV/WR scaling.

    Trend regimes (BULL/BEAR): wider TP (let winners run), tighter SL
      (confirmed direction — stop doesn't need to be as wide).
    HIGH_VOL: narrower TP (take profit sooner before reversal), wider SL
      (noise is larger, SL needs room to breathe).
    QUIET_RANGE: narrower TP (low ATR, don't wait for large moves), tight SL.
    RANGING: unchanged (EV/WR scaling is sufficient for mean-reversion).

    Applied after both QUIET_RANGE override and _adaptive_tp_sl so regime
    context adds a final layer on top of the EV-based baseline.
    """
    if regime in ("BULL_TREND", "BEAR_TREND"):
        tp_k *= 1.2   # let trend run further
        sl_k *= 0.9   # confirmed direction → tighter SL
    elif regime == "HIGH_VOL":
        tp_k *= 0.9   # take profit before volatile reversal
        sl_k *= 1.1   # wider SL to survive noise spikes
    elif regime == "QUIET_RANGE":
        tp_k *= 0.8   # low ATR — target small move, exit fast
        sl_k *= 0.9
    # RANGING: EV/WR scaling is the sole driver — no regime override
    return tp_k, sl_k


def adaptive_sl_tightening(entry, current_price, sl, direction, atr):
    """V10.2: Gradually tighten SL as trade moves into profit.

    Activates only after 0.3% move (well above fee + spread noise floor).
    tighten factor scales with move depth: 0.3%→0.15, 1%→0.5 (cap).
    For BUY: new_sl = max(old_sl, entry + move × tighten × entry)
    For SELL: new_sl = min(old_sl, entry - move × tighten × entry)
    The max/min ensures SL only ever moves in the favorable direction.

    Operates in the 0.3%–0.6% pre-trail window (trailing activates at 0.6%
    and Chandelier takes over — pos["sl"] is not read after that point).
    After partial TP (SL→breakeven), pushes SL slightly above entry to
    capture additional profit if price reverses before trail activates.

    atr parameter reserved for future ATR-normalized version.
    """
    move = ((current_price - entry) / entry if direction == "BUY"
            else (entry - current_price) / entry)
    if move < 0.003:   # below activation threshold — don't touch SL
        return sl
    tighten = min(0.5, move * 50)   # 0.3%→0.15, 0.6%→0.30, 1%→0.50 (cap)
    if direction == "BUY":
        return max(sl, entry + move * tighten * entry)
    else:
        return min(sl, entry - move * tighten * entry)


# ── V10.3 helpers ───────────────────────────────────────────────────────────────

def _winsorize(x, p=0.1):
    """V10.3c: Clamp extreme values before std computation.

    Removes the top and bottom p-fraction of values so that a single outlier
    trade (e.g. a flash-crash tick or an abnormally large fill) cannot spike
    the realized-vol estimate and cause a sudden size reduction.
    Falls back to identity when k==0 (fewer than 10 samples at p=0.1).
    """
    if not x:
        return x
    xs = sorted(x)
    n  = len(xs)
    k  = int(n * p)
    if k == 0:
        return x
    low  = xs[k]
    high = xs[-k - 1]
    return [min(max(v, low), high) for v in x]


def volatility_adjustment(sym):
    """V10.3c: Winsorized + smoothed realized-vol sizing refinement.

    Applies _winsorize(p=0.1) inside _std before computing variance, so
    extreme outlier returns don't distort the vol estimate.  Otherwise
    identical to V10.3b: 70/30 blend of recent/older windows, normalised
    around 1% typical crypto vol, clamped [0.7, 1.3], bootstrap-safe (<30→1.0).
    """
    ret = returns_hist.get(sym, [])
    if len(ret) < 30:
        return 1.0

    def _std(x):
        xw = _winsorize(x, p=0.1)
        m  = sum(xw) / len(xw)
        return (sum((i - m) ** 2 for i in xw) / len(xw)) ** 0.5

    recent     = ret[-20:]
    older      = ret[-40:-20] if len(ret) >= 40 else recent
    std        = 0.7 * _std(recent) + 0.3 * _std(older)
    vol_factor = 0.01 / (std + 1e-6)
    return max(0.7, min(1.3, vol_factor))


def dynamic_hold_extension(base_hold, ev, atr, entry):
    """V10.3c: EV + ATR-volatility aware hold-time scaling.

    Two independent scale factors multiplied together:

    EV component (unchanged from V10.3b):
      scale_ev = 1.0 + clamp(ev × 1.5, -0.3, +0.3)
      ev=-0.2 → 0.70×   ev=0 → 1.0×   ev=+0.2 → 1.30×

    ATR/volatility component (new):
      atr_pct  = atr / entry
      vol_scale = clamp(0.01 / atr_pct, 0.85, 1.15)
      Low-vol (tight ATR) → up to 1.15× (trade has room to develop quietly)
      High-vol (wide ATR) → down to 0.85× (don't overstay in choppy markets)
      Normalised around 1% move; tighter band than EV component to stay subtle.

    Combined: scale = scale_ev × vol_scale
    Bounded result: [5, 22] ticks — identical to V10.3b.
    """
    scale_ev  = 1.0 + max(-0.3, min(0.3, ev * 1.5))
    atr_pct   = atr / max(entry, 1e-9)
    vol_scale = max(0.85, min(1.15, 0.01 / (atr_pct + 1e-6)))
    timeout   = int(base_hold * scale_ev * vol_scale)
    return max(5, min(22, timeout))


# ── V10.4 helpers — portfolio intelligence ────────────────────────────────────

def signal_score(signal, ev):
    """V10.4: Composite quality score for incoming signals.

    Weights EV (proven statistical edge) at 70% and signal confidence
    (indicator agreement) at 30%.  Used to rank candidates against open
    positions before committing capital.

    Returns a float; higher = better opportunity.
    """
    conf = signal.get("confidence", 0.5) or 0.5
    return 0.7 * ev + 0.3 * conf


def position_score(pos, now_ts=None):
    """V10.4b: Time-decayed composite quality score for an open position.

    Base score mirrors signal_score (0.7×risk_ev + 0.3×conf) so they are
    directly comparable.  A linear decay kicks in after the first 30 ticks
    of age (≈60 s at 2 s/tick), bottoming at 0.70× at age≥150 s.

    Effect: stale positions that have not hit TP/SL/trail lose priority
    naturally, making them rotation candidates without any forced-exit logic.
    Bootstrap-safe: positions without open_ts are treated as brand-new (no decay).
    """
    if now_ts is None:
        now_ts = time.time()
    ev   = pos.get("risk_ev", 0.0)
    conf = pos.get("signal", {}).get("confidence", 0.5) or 0.5
    base = 0.7 * ev + 0.3 * conf

    open_ts = pos.get("open_ts")
    if open_ts is None:
        return base   # legacy position — no decay

    age   = now_ts - open_ts
    if age <= 30:
        return base
    decay = max(0.70, 1.0 - (age - 30) / 120)
    return base * decay


def can_replace(now_ts=None):
    """V10.4b: Global 15-second cooldown between any two replacements.

    Prevents back-to-back churn loops where the same (or another) signal
    triggers a second replacement immediately after the first one fires.
    Updates _last_replace_ts on success.
    """
    global _last_replace_ts
    if now_ts is None:
        now_ts = time.time()
    if now_ts - _last_replace_ts < 15:
        return False
    _last_replace_ts = now_ts
    return True


def should_replace(new_score, positions, now_ts=None):
    """V10.4b: Find the weakest open position that the incoming signal beats.

    Profit protection: positions with live_pnl > 0.3% or trailing stop active
    are never replaced — they are working and should be allowed to reach TP.

    Churn guard: requires new_score > worst_score + 0.05 (≈7pp EV gap).

    Returns the symbol of the replacement candidate, or None.
    """
    if not positions:
        return None
    if now_ts is None:
        now_ts = time.time()

    worst_sym   = min(positions, key=lambda s: position_score(positions[s], now_ts))
    worst_pos   = positions[worst_sym]

    # Profit protection — do not kill winning trades
    if worst_pos.get("is_trailing", False):
        return None
    if worst_pos.get("live_pnl", 0.0) > 0.003:
        return None

    worst_score = position_score(worst_pos, now_ts)
    if new_score > worst_score + _meta_state["replace_threshold"]:
        return worst_sym
    return None


def rotate_position(sym):
    """V10.4: Flag an open position for immediate close so capital is freed."""
    if sym in _positions:
        _positions[sym]["force_close"] = True


# ── V10.5 helpers — position scaling & pyramiding ─────────────────────────────

def should_add_to_position(pos, curr, prev):
    """V10.5b: True when a winning position qualifies for a momentum-confirmed pyramid add.

    All V10.5 conditions plus two new guards:
      momentum  — price must still be moving in trade direction (curr tick vs prev tick)
                  prevents late adds at the top/bottom of a move
      near-trail — block adds when move > 0.55% (trailing activates at 0.60%)
                  adding just before trail would increase size right at peak exposure
    """
    if pos.get("is_trailing", False):
        return False
    if pos.get("partial_taken", False):
        return False
    if pos.get("adds", 0) >= 2:
        return False
    reg = pos.get("signal", {}).get("regime", "")
    if reg == "HIGH_VOL":
        return False

    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry
    if move < _meta_state["pyramid_trigger"]:
        return False
    if pos.get("risk_ev", 0.0) < 0.1:
        return False

    # V10.5b: momentum confirmation — price must continue moving in trade direction
    if pos["action"] == "BUY"  and curr <= prev:
        return False
    if pos["action"] == "SELL" and curr >= prev:
        return False

    # V10.5b: near-trail guard — avoid adding within 0.05% of trailing activation
    if move > 0.0055:
        return False

    # Cap: size + add must not exceed 2× original
    orig     = pos.get("original_size", pos["size"])
    max_add  = orig * 2.0 - pos["size"]
    if max_add <= 0:
        return False

    # Capital headroom: adding half current size must not breach _MAX_CAP_USED
    size_add = min(pos["size"] * 0.5, max_add)
    if (capital_usage() + size_add / _TOTAL_CAPITAL) >= _MAX_CAP_USED:
        return False

    return True


def add_to_position(pos, curr):
    """V10.5: Scale into a winning position (VWAP entry, capped at 2×original).

    size_add = min(current_size × 0.5, remaining room to 2× cap)
    New entry = VWAP of old position and add — accurate blended cost basis.
    _risk_guard() is called after to ensure _MAX_TOTAL_RISK is respected.
    """
    orig     = pos.get("original_size", pos["size"])
    max_add  = orig * 2.0 - pos["size"]
    size_add = min(pos["size"] * 0.5, max_add)

    old_size  = pos["size"]
    old_entry = pos["entry"]
    new_size  = old_size + size_add

    # VWAP blended entry — correct for unequal lot sizes
    pos["entry"] = (old_entry * old_size + curr * size_add) / new_size
    pos["size"]  = new_size
    pos["adds"]  = pos.get("adds", 0) + 1
    _risk_guard()


def should_reduce_position(pos, curr):
    """V10.5: True when a losing position with negative edge should be halved.

    Conditions (all must pass):
      move < -0.3%     — position is losing (below noise floor)
      risk_ev < 0.0    — edge is confirmed negative (not just unlucky)
      not reduced      — only one reduction allowed per position
      not partial_taken — partial TP already handled sizing; don't double-cut
    """
    if pos.get("reduced", False):
        return False
    if pos.get("partial_taken", False):
        return False

    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry
    if move > -0.003:
        return False
    if pos.get("risk_ev", 0.0) >= 0.0:
        return False

    return True


def reduce_position(pos, curr):
    """V10.5b: Adaptively cut a losing position — severity scales with loss depth.

    move < -0.6%  → keep 30% (heavy loss, cut hard)
    move < -0.4%  → keep 50% (moderate loss, standard halve)
    move < -0.3%  → keep 70% (mild loss, light trim)

    Smoother than the fixed 50% cut: shallow losses get a light trim that
    preserves more upside if price reverses; deep losses get cut hard to
    protect remaining capital.
    """
    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry

    if   move < -0.006:  factor = 0.3
    elif move < -0.004:  factor = 0.5
    else:                factor = 0.7

    pos["size"]    *= factor
    pos["reduced"]  = True
    _risk_guard()


# ── V10.6b helpers — robust meta-adaptive control ─────────────────────────────

def _ema_update(prev, x, alpha=0.2):
    """Single-step EMA.  Returns x on first call (prev is None)."""
    return x if prev is None else (alpha * x + (1.0 - alpha) * prev)


def _update_meta_inputs(lm_h, sr, dd):
    """Smooth raw metrics with alpha=0.2 EMA before mode decisions.

    Prevents single noisy readings from triggering mode switches.
    Stored in module-level _meta_ema dict.
    """
    _meta_ema["lm_health"] = _ema_update(_meta_ema["lm_health"], lm_h)
    _meta_ema["sharpe"]    = _ema_update(_meta_ema["sharpe"],    sr)
    _meta_ema["drawdown"]  = _ema_update(_meta_ema["drawdown"],  dd)
    return _meta_ema["lm_health"], _meta_ema["sharpe"], _meta_ema["drawdown"]


def _replacement_threshold(mode, lm_h):
    """Continuous replacement gap: base 0.05 adjusted by lm_health and mode.

    Higher lm_h → easier replacement (better signals justify lower bar).
    Defensive mode adds +0.02 (harder to replace — protect stability).
    Aggressive mode subtracts -0.01 (slightly easier rotation).
    Clamped [0.03, 0.08].
    """
    adj = (lm_h - 0.3) * 0.05
    if   mode == "defensive":  adj += 0.02
    elif mode == "aggressive": adj -= 0.01
    return max(0.03, min(0.08, 0.05 + adj))


def _pyramiding_trigger(mode, sr):
    """Continuous pyramid entry move threshold.

    Higher Sharpe → can add earlier (edge is confirmed).
    Defensive adds +0.001 (wait for more move before scaling).
    Aggressive subtracts -0.001 (scale sooner).
    Clamped [0.003, 0.006].
    """
    adj = (sr - 1.0) * 0.001
    if   mode == "defensive":  adj += 0.001
    elif mode == "aggressive": adj -= 0.001
    return max(0.003, min(0.006, 0.004 + adj))


def _reduce_threshold(mode, dd):
    """Continuous loss-reduction trigger (negative move %).

    Larger drawdown → tighter threshold (reduce earlier).
    Aggressive mode gives +0.001 of slack (tolerates slightly more loss).
    Clamped [-0.005, -0.002].
    """
    adj = dd * 0.02
    if mode == "aggressive": adj -= 0.001
    return max(-0.005, min(-0.002, -0.003 + adj))


def update_meta_mode(now_ts=None):
    """V10.6b: Hysteresis mode switcher with EMA-smoothed inputs and 10s cooldown.

    Reads lm_health / sharpe / max_drawdown from their canonical sources,
    smooths them, then applies hysteresis band logic to avoid oscillation:

      neutral  → defensive  when dd_smooth > 0.12
      neutral  → aggressive when lm_h_smooth > 0.45 AND sharpe_smooth > 1.3
      aggressive → neutral  when lm_h_smooth < 0.35 OR sharpe_smooth < 1.0
      defensive  → neutral  when dd_smooth < 0.08

    Safety: aggressive is blocked when raw dd > 0.10 (hard override).
    Updates _meta_state thresholds on every non-cooldown call.
    Returns current mode string.
    """
    if now_ts is None:
        now_ts = time.time()
    if now_ts - _meta_state["last_update"] < 10:
        return _meta_state["mode"]

    # Fetch raw metrics (safe fallbacks)
    lm_h = 0.0
    sr   = 0.0
    dd   = 0.0
    try:
        from src.services.learning_monitor import lm_health as _lmh
        lm_h = float(_lmh() or 0.0)
    except Exception:
        pass
    try:
        from src.services.diagnostics import sharpe as _sr, max_drawdown as _dd
        sr = float(_sr() or 0.0)
        dd = float(_dd() or 0.0)
    except Exception:
        pass

    # EMA-smooth before any decision
    lm_h_s, sr_s, dd_s = _update_meta_inputs(lm_h, sr, dd)

    mode = _meta_state["mode"]

    if mode == "neutral":
        if dd_s > 0.12:
            mode = "defensive"
        elif lm_h_s > 0.45 and sr_s > 1.3 and dd < 0.10:   # raw dd safety
            mode = "aggressive"
    elif mode == "aggressive":
        if dd >= 0.10 or lm_h_s < 0.35 or sr_s < 1.0:      # raw dd hard override
            mode = "neutral"
    elif mode == "defensive":
        if dd_s < 0.08:
            mode = "neutral"

    _meta_state["mode"]              = mode
    _meta_state["last_update"]       = now_ts
    _meta_state["replace_threshold"] = _replacement_threshold(mode, lm_h_s)
    _meta_state["pyramid_trigger"]   = _pyramiding_trigger(mode, sr_s)
    _meta_state["reduce_threshold"]  = _reduce_threshold(mode, dd_s)

    return mode


def compute_tp_sl(entry, direction, atr=0.003, sym=None, reg=None):
    """Absolute TP/SL prices.

    QUIET_RANGE: quick-exit targets (tp_k=0.7, sl_k=0.5, RR=1.4).

    Other regimes — V8 adaptive_tp_sl: continuous EV+WR scaling.
    risk_ev = tanh(mean/std) × min(n/50, 1) → near 0 during bootstrap,
    so tp_k ≈ 1.1 until statistically confirmed (EV must earn scaling).
    WR from global metrics (converges toward pair-specific as trades accumulate).

    V10.2: regime_tp_sl_adjust applied after EV/WR scaling — trend gets
    wider TP, high-vol gets wider SL, quiet gets tighter TP.
    """
    if reg == "QUIET_RANGE":
        tp_k, sl_k = 0.7, 0.5
    else:
        _ev = 0.0
        if sym and reg:
            try:
                from src.services.execution import risk_ev as _rev
                _ev = _rev(sym, reg)
            except Exception:
                pass
        try:
            from src.services.learning_event import get_metrics as _lgm
            _wr = _lgm().get("winrate", 0.5) or 0.5
        except Exception:
            _wr = 0.5
        tp_k, sl_k = _adaptive_tp_sl(_ev, _wr)

    tp_k, sl_k = regime_tp_sl_adjust(tp_k, sl_k, reg or "RANGING")

    if direction == "BUY":
        return entry * (1 + tp_k * atr), entry * (1 - sl_k * atr)
    else:
        return entry * (1 - tp_k * atr), entry * (1 + sl_k * atr)

_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8,
            "RANGING":    0.8, "QUIET_RANGE": 0.8}


def net_ws(ws, spread_pct, fee_rt):
    """WS after spread and round-trip fees. Negative = edge eaten by costs."""
    return ws - (spread_pct + fee_rt)


# ── V3 helpers ─────────────────────────────────────────────────────────────────

def _decision_score(ev, ws):
    """EV-dominant blend: 75% EV + 25% WS."""
    return 0.75 * ev + 0.25 * ws


def _allow_trade_sigmoid(ev, ws):
    """Sigmoid probability gate — replaces hard should_trade() threshold.
    Center at 0.1: score=0.1→50% pass, score=0.4→87% pass, score=-0.2→13% pass.
    Weak-positive EV still gets through probabilistically instead of being blocked.
    """
    import math
    s = _decision_score(ev, ws)
    p = 1.0 / (1.0 + math.exp(-6.0 * (s - 0.1)))
    return random.random() < p


def _has_min_edge(entry, tp, sl):
    """Reject if TP or SL distance < MIN_EDGE_PCT — prevents micro-PnL noise trades."""
    tp_dist = abs(tp - entry) / max(entry, 1e-9)
    sl_dist = abs(sl - entry) / max(entry, 1e-9)
    return tp_dist >= MIN_EDGE_PCT and sl_dist >= MIN_EDGE_PCT


def _dynamic_rr_threshold(ev, atr_pct, wr):
    """V8: WR+EV+volatility-aware RR threshold.

    Base from EV tier:  ev>0.2→0.95,  ev>0→1.05,  ev≤0→1.2.
    WR adjustment: high WR (0.7) lowers required RR by 10% (can afford lower RR).
    Vol adjustment: high-ATR markets clamp at 1.2 (wider TP needed); low-ATR at 0.85.
    Hard floor 0.95 — never accept RR below this regardless of WR.
    """
    base    = 0.95 if ev > 0.2 else 1.05 if ev > 0 else 1.2
    wr_adj  = 1.0 - (wr - 0.5) * 0.5          # wr=0.7→0.9×, wr=0.3→1.1×
    vol_adj = min(max(atr_pct / 0.01, 0.85), 1.2)
    return max(0.95, base * wr_adj * vol_adj)


def _reject_bad_rr(entry, tp, sl, ev=None, atr_pct=None):
    """True (= reject) when reward/risk < V8 dynamic threshold.

    V8: threshold driven by EV, WR, and current ATR volatility — no static 1.0/1.2 split.
    WR from global metrics (most reliable proxy available in bootstrap phase).
    """
    risk = abs(sl - entry)
    if risk == 0:
        return True
    rr = abs(tp - entry) / risk
    _ev  = ev if ev is not None else 0.0
    _atr = atr_pct if atr_pct is not None else 0.01
    try:
        from src.services.learning_event import get_metrics as _lgm
        _wr = _lgm().get("winrate", 0.5) or 0.5
    except Exception:
        _wr = 0.5
    threshold = _dynamic_rr_threshold(_ev, _atr, _wr)
    return rr < threshold


def _dynamic_hold(atr_abs, entry, sym=None, reg=None, adx=0.0):
    """Timeout ticks scaled continuously by EV, then fine-tuned by ATR + trend.

    V8: EV-continuous base (replaces V7 discrete tiers 7/10/12):
      ev_factor = clamp((ev + 1) / 2, 0, 1)   — maps [-1..1] EV to [0..1]
      base = 6 + int(ev_factor × 6)             — continuous 6–12 ticks
      ev=-1 → 6,  ev=0 → 9,  ev=0.5 → 10,  ev=1 → 12

    Preserves V7 base-as-floor guarantee: EV base is never reduced by ATR.
    ATR tunes up to base+4 (was +3 in V7 — slight expansion for patience).
    ADX trend bonus (+2): confirmed trend needs more room to develop.
    Hard ceiling 17 prevents runaway holds.
    """
    atr_pct     = atr_abs / max(entry, 1e-9)
    atr_adj     = int(5 * max(0.002, 0.01 / max(atr_pct, 1e-9)))
    trend_bonus = 2 if adx > 25 else 0

    _ev = 0.0
    if sym and reg:
        try:
            from src.services.execution import risk_ev as _rev
            _ev = _rev(sym, reg)
        except Exception:
            pass

    # V8: continuous EV → base mapping
    ev_factor = min(max((_ev + 1) / 2, 0.0), 1.0)
    base      = 6 + int(ev_factor * 6)   # range [6, 12]

    # Base is a FLOOR (V7 guarantee retained). ATR tunes up to base+4.
    hold = max(base, min(base + 4, atr_adj + trend_bonus))
    return max(5, min(hold, 17))   # absolute ceiling 17


def _force_trade_guard():
    """True when fewer than MIN_TRADES_PER_100_TICKS opened in the last 100 ticks.
    Bypasses sigmoid gate to guarantee minimum learning data flow.
    """
    n = _tick_counter[0]
    recent = sum(1 for t in _trades_at_tick if n - t <= 100)
    return recent < MIN_TRADES_PER_100_TICKS


# ── V9 helpers ─────────────────────────────────────────────────────────────────

def policy_score(ev, wr, momentum, vol, regime_score):
    """V9: Policy-based continuous entry score (replaces binary ev>thr*1.5→*1.5).

    Weights (sum = 1.0):
      0.40 × ev           — dominant: proven edge drives sizing most
      0.20 × (wr - 0.5)  — WR contribution; 0 at 50%, +0.1 at 60%
      0.15 × momentum     — directional confirmation (ws proxy, normalized)
      0.15 × regime_score — trending (1.0) vs ranging (0.5)
      0.10 × (1 - vol)    — penalise high-vol entries (wider spread risk)

    Typical ranges at neutral state (ev=0, wr=0.5, momentum=0, regime=0.5, vol=0.01):
      score ≈ 0.17  → size *= 1.17  (slight boost — system is exploring)
    At strong state (ev=0.5, wr=0.65, momentum=0.4, regime=1.0, vol=0.008):
      score ≈ 0.46  → size *= 1.46  (near-cap boost — confident edge)
    At weak state  (ev=-0.3, wr=0.35, momentum=-0.3, regime=0.5, vol=0.025):
      score ≈ -0.14 → size *= 0.86  (trimmed — poor conditions)
    """
    score = (
        0.40 * ev +
        0.20 * (wr - 0.5) +
        0.15 * momentum +
        0.15 * regime_score +
        0.10 * (1.0 - vol)
    )
    return score


def meta_controller(sharpe, drawdown, winrate, trade_freq, volatility=0.0):
    """V9→V10: System-health aggression multiplier with hard kill-switch.

    Conditions evaluated top-to-bottom (first match wins):
      DD > 20%            → 0.0×  V10: hard stop — approaching catastrophic loss,
                                   halt all new positions (defense-in-depth before
                                   failure_control fires at its own threshold)
      DD > 12%            → 0.5×  V9: strong risk-off
      volatility > 3%     → 0.7×  V10: HIGH_VOL regime — wider spreads, execution
                                   risk; signal_generator also penalises but this
                                   adds a position-sizing layer
      Sharpe < 0.5        → 0.7×  underperforming system — reduce size
      trade_freq < 0.1    → 1.1×  activity pressure (< 10 trades/100 ticks)
      default             → 1.0×  healthy system

    Risk-on 1.2× (sharpe>1.5 AND wr>0.6) intentionally omitted:
    win-streak anti-martingale in auditor.py already covers this path (1.2-1.4×),
    stacking would compound to 1.68× which approaches unsafe concentration.
    """
    if drawdown > 0.20:
        return 0.0   # hard stop: catastrophic drawdown — no new positions
    if drawdown > 0.12:
        return 0.5
    if volatility > 0.03:
        return 0.7   # HIGH_VOL: wider spreads amplify execution risk
    if sharpe < 0.5:
        return 0.7
    if trade_freq < 0.1:
        return 1.1
    return 1.0


def _replace_allowed(symbol):
    """True if no replacement happened for this symbol in the last 300 s."""
    last = _last_replaced.get(symbol, 0.0)
    return (time.time() - last) > _REPLACE_COOLDOWN


def _total_risk():
    """Sum of (size × sl_fraction) across all open positions.
    sl_fraction = |sl - entry| / entry — derived from absolute sl price."""
    return sum(
        p["size"] * abs(p["sl"] - p["entry"]) / max(p["entry"], 1e-9)
        for p in _positions.values()
    )


def _risk_guard():
    """If total portfolio risk exceeds cap, scale all position sizes down."""
    if _total_risk() > _MAX_TOTAL_RISK:
        for p in _positions.values():
            p["size"] *= 0.7


def get_open_positions():
    return dict(_positions)


def capital_usage():
    """Fraction of normalised capital currently deployed."""
    return sum(p["size"] for p in _positions.values()) / _TOTAL_CAPITAL


def _effective_ws(signal):
    """
    Risk-adjusted + regime-penalised WS for portfolio ranking.
    risk_adjust: normalise by avg WS of open positions.
    regime_penalty: reduce score proportionally to regime concentration.
    """
    ws     = signal.get("ws", 0.5)
    regime = signal.get("regime", "RANGING")
    # Risk-adjust: ws / avg_ws_of_open_positions
    if _positions:
        avg_ws = sum(p["signal"].get("ws", 0.5)
                     for p in _positions.values()) / len(_positions)
        ws = ws / max(avg_ws, 0.01)
    # Regime penalty: ws * (1 - exposure_fraction)
    n = len(_positions)
    if n > 0:
        exposure = _regime_exposure.get(regime, 0) / n
        ws *= (1.0 - exposure)
    return ws


def _vol_adjust(size, signal):
    """
    Scale size to target 2% realised volatility.
    Clamps ratio 0.5× – 2.0× to prevent extreme adjustments.
    """
    realised_vol = signal.get("features", {}).get("volatility", _TARGET_VOL)
    ratio = _TARGET_VOL / max(realised_vol, 1e-6)
    return size * max(0.5, min(2.0, ratio))


def _replace_if_better(signal):
    """
    V10.13: Global portfolio_score comparison replaces local effective_ws logic.

    Instead of comparing new signal vs weakest position in isolation, we
    SIMULATE the portfolio after each candidate replacement and score the
    resulting portfolio globally. Replace only when the simulated portfolio
    improves on the current global score.

    Global score = sum(efficiency_live) + momentum_bonus − risk_penalty
    (see risk_engine.portfolio_score for full definition).

    Process:
    1. Score the current portfolio baseline.
    2. For each candidate replacement (worst efficiency_live, worst ws):
       a. Build a simulated positions dict: remove candidate, add proxy for
          incoming signal using its policy_ev / estimated_hold.
       b. Score the simulated portfolio.
       c. If simulated_score > current_score + GLOBAL_REPLACE_MARGIN: replace.
    3. Fall back to V10.12 ws/ev rotation if global score doesn't improve.

    GLOBAL_REPLACE_MARGIN = 0.05: requires the portfolio to genuinely improve
    by at least 5% of a typical single-position efficiency contribution, not
    just a marginal improvement that could be noise.

    Returns True if replacement was queued, False otherwise.
    """
    if len(_positions) < MAX_POSITIONS:
        return False

    GLOBAL_REPLACE_MARGIN = 0.05

    try:
        from src.services.risk_engine import portfolio_score as _pf_score

        current_score = _pf_score(_positions)

        # Build a proxy position for the incoming signal (used in simulation)
        _ev_sig = signal.get("ev", 0.0) or 0.0
        _atr_s  = max(signal.get("atr", 0) or 0, signal["price"] * 0.003)
        _adx_s  = signal.get("features", {}).get("adx", 0.0)
        _hold_s = _dynamic_hold(_atr_s, signal["price"],
                                signal["symbol"], signal.get("regime","RANGING"),
                                adx=_adx_s)
        _hold_s = dynamic_hold_extension(_hold_s, _ev_sig, _atr_s, signal["price"])
        _eff_s  = _ev_sig / max(_hold_s, 1e-6)

        # Proxy position has same structure as a real position but simplified
        _now_sim = time.time()
        _proxy   = {
            "action":          signal.get("action", "BUY"),
            "size":            0.025,   # conservative estimate — real size unknown
            "entry":           signal["price"],
            "sl":              signal["price"] * 0.996,   # 0.4% proxy SL
            "sl_move":         0.004,                     # 0.4% proxy SL distance
            "signal":          signal,
            "efficiency":      _eff_s,
            "efficiency_live": _eff_s,
            "expected_hold":   _hold_s,
            "live_pnl":        0.0,
            "open_ts":         _now_sim,
        }

        best_candidate = None
        best_sim_score = current_score + GLOBAL_REPLACE_MARGIN   # must beat this

        for candidate_sym in _positions:
            if not _replace_allowed(candidate_sym):
                continue
            wp = _positions[candidate_sym]
            # Safety guards: never replace trailing/partial-taken/strong winners
            if wp.get("is_trailing", False):
                continue
            if wp.get("partial_taken", False):
                continue
            if wp.get("live_pnl", 0.0) >= 0.003:
                continue

            # Simulate: remove candidate, add proxy
            simulated = {s: p for s, p in _positions.items() if s != candidate_sym}
            simulated[signal["symbol"]] = _proxy
            sim_score = _pf_score(simulated)

            if sim_score > best_sim_score:
                best_sim_score = sim_score
                best_candidate = candidate_sym

        if best_candidate is not None:
            _positions[best_candidate]["force_close"] = True
            _pending_open.append(signal)
            _last_replaced[best_candidate] = _now_sim
            _gain = best_sim_score - current_score
            print(f"    replace[v10.13/global]: {best_candidate} "
                  f"← {signal['symbol']}  "
                  f"score {current_score:.4f}→{best_sim_score:.4f} "
                  f"(+{_gain:.4f})")
            return True

    except Exception:
        pass

    # ── Fallback: ws-margin and EV rotation (V10.12 logic preserved) ──────────
    weakest_sym = min(_positions,
                      key=lambda s: _effective_ws(_positions[s]["signal"]))
    new_eff  = _effective_ws(signal)
    weak_eff = _effective_ws(_positions[weakest_sym]["signal"])
    if new_eff > weak_eff * _REPLACE_MARGIN and _replace_allowed(weakest_sym):
        _positions[weakest_sym]["force_close"] = True
        _pending_open.append(signal)
        _last_replaced[weakest_sym] = time.time()
        print(f"    replace[ws]: {weakest_sym} (eff_ws={weak_eff:.3f}) "
              f"← {signal['symbol']} (eff_ws={new_eff:.3f})")
        return True

    should_rotate, worst_sym = rotate_capital(signal, _positions, MAX_POSITIONS)
    if should_rotate and worst_sym and _replace_allowed(worst_sym):
        _positions[worst_sym]["force_close"] = True
        _pending_open.append(signal)
        _last_replaced[worst_sym] = time.time()
        print(f"    replace[ev]: {worst_sym} "
              f"← {signal['symbol']} (regime={signal.get('regime','?')})")
        return True
    return False


def _allow_trade(symbol, direction, regime):
    """
    Portfolio-level gates before accepting a new position.
    Returns (allowed: bool, reason: str).
    """
    if symbol in _positions:
        return False, "already_open"
    # Bootstrap: bypass portfolio gates until 50 closed trades — fills lm_pnl_hist fast
    try:
        from src.services.learning_event import get_metrics as _lgm
        if _lgm().get("trades", 0) < 50:
            return True, "bootstrap_open"
    except Exception:
        pass
    if capital_usage() >= _MAX_CAP_USED:
        return False, "capital_limit"
    if len(_positions) >= MAX_POSITIONS:
        return False, "max_positions"
    from src.services.macro_guard import is_safe
    if not is_safe():
        return False, "macro_guard_halt"
        
    from src.services.squeeze_guard import is_safe_long, is_safe_short
    if direction == "BUY" and not is_safe_long(symbol):
        return False, "squeeze_guard_long"
    if direction == "SELL" and not is_safe_short(symbol):
        return False, "squeeze_guard_short"
        
    from src.services.correlation_shield import is_safe_correlation
    if not is_safe_correlation(symbol, direction, _positions, 0.85):
        return False, "correlation_shield"
        
    same_dir = sum(1 for p in _positions.values() if p["action"] == direction)
    if same_dir >= MAX_SAME_DIR:
        return False, "same_dir"
    # Regime concentration: block if one regime dominates (>70%)
    n = len(_positions)
    if n > 0:
        regime_count = _regime_exposure.get(regime, 0)
        if regime_count / n >= MAX_REGIME_PCT:
            return False, "regime_concentration"
    return True, "ok"


def _flush():
    if BATCH:
        save_batch(BATCH)
        BATCH.clear()
    _last_flush[0] = time.time()


def handle_signal(signal):
    global _last_replace_ts   # V10.10: written directly in efficiency replacement path
    sym     = signal["symbol"]
    regime  = signal.get("regime", "RANGING")
    allowed, reason = _allow_trade(sym, signal["action"], regime)
    if not allowed:
        if reason == "max_positions":
            # Global 15 s cooldown — covers both V10.10 and V10.4b paths
            _now = time.time()
            if not can_replace(_now):
                return

            # ── Shared: risk_ev for incoming signal ───────────────────────────
            _ev_r = 0.0
            try:
                from src.services.execution import risk_ev as _rev_r
                _ev_r = _rev_r(sym, regime)
            except Exception:
                pass

            # ── V10.10: Efficiency-based replacement (primary path) ────────────
            # Compute expected hold time for the incoming signal using same
            # logic as the open path — dynamic_hold then hold_extension.
            _sig_atr_r = max(signal.get("atr", 0) or 0, signal["price"] * 0.003)
            _sig_adx_r = signal.get("features", {}).get("adx", 0.0)
            _hold_r    = _dynamic_hold(_sig_atr_r, signal["price"], sym, regime,
                                       adx=_sig_adx_r)
            _hold_r    = dynamic_hold_extension(_hold_r, _ev_r, _sig_atr_r,
                                                signal["price"])
            _new_eff   = _ev_r / max(_hold_r, 1e-6)

            # Gate D: fw_score ≥ MIN and policy_ev > 0
            _fw_bools_r = {k: v for k, v in signal.get("features", {}).items()
                           if isinstance(v, bool)}
            _fw_r = 0.0
            try:
                from src.services.feature_weights import compute_weighted_score as _cws_r
                _fw_r = _cws_r(_fw_bools_r, sym, regime)
            except Exception:
                pass
            from src.services.feature_weights import MIN_SCORE as _FW_MIN_R

            _use_v1010 = (_fw_r >= _FW_MIN_R and _ev_r > 0 and _positions)

            if _use_v1010:
                # Find weakest by efficiency_live (falls back to efficiency at open)
                _worst10 = min(
                    _positions,
                    key=lambda s: _positions[s].get(
                        "efficiency_live", _positions[s].get("efficiency", 0.0)))
                _wp10     = _positions[_worst10]
                _worst_eff = _wp10.get("efficiency_live",
                                       _wp10.get("efficiency", 0.0))

                # Threshold: meta-adaptive (spec §4B) + V10.12 correlation adj
                # Replacing worst_sym with a diversifying position → lower bar
                # Replacing with a concentrating position → higher bar
                _mode10  = _meta_state["mode"]
                _eff_thr = 0.01 if _mode10 == "aggressive" else \
                           0.04 if _mode10 == "defensive"  else 0.02
                try:
                    from src.services.risk_engine import (
                        replacement_correlation_adj as _rca)
                    _corr_adj = _rca(signal.get("action", ""), regime,
                                     _positions, _worst10)
                    _eff_thr *= _corr_adj
                except Exception:
                    _corr_adj = 1.0

                # All replacement conditions
                _cond_A = _new_eff > _worst_eff + _eff_thr
                _cond_C = (_wp10.get("live_pnl", 0.0) < 0.003
                           and not _wp10.get("is_trailing", False)
                           and not _wp10.get("partial_taken", False))

                if _cond_A and _cond_C and _replace_allowed(_worst10):
                    # Tag the signal so handle_signal records it + applies recycling
                    signal["_is_replacement"] = True
                    rotate_position(_worst10)
                    _pending_open.append(signal)
                    _last_replaced[_worst10] = _now
                    print(f"    replace[v10.10/v10.12]: {_worst10} "
                          f"(eff={_worst_eff:.4f}) ← {sym} "
                          f"(eff={_new_eff:.4f})  "
                          f"thr={_eff_thr:.4f}  corr_adj×{_corr_adj:.2f}  "
                          f"mode={_mode10}")
                    return

            # ── V10.4b fallback: score-based replacement ───────────────────────
            _new_score = signal_score(signal, _ev_r)
            _worst_sym = should_replace(_new_score, _positions, _now)
            if _worst_sym and _replace_allowed(_worst_sym):
                rotate_position(_worst_sym)
                _pending_open.append(signal)
                _last_replaced[_worst_sym] = _now
                _ws = position_score(_positions[_worst_sym], _now)
                print(f"    replace[v10.4b]: {_worst_sym} (score={_ws:.3f}) "
                      f"← {sym} (score={_new_score:.3f})")
            else:
                _replace_if_better(signal)   # fall back to ws/EV rotation
        else:
            print(f"    portfolio gate: {reason}  sym={sym}")
        return

    entry = signal["price"]
    # ATR floor: micro-price coins (NOM $0.0027, KAT $0.012) can have ATR≈0
    # in absolute terms → TP=SL=entry → trade can only close on timeout.
    # Floor at 0.3% of entry ensures minimum meaningful TP/SL distance.
    atr   = max(signal.get("atr", 0) or 0, entry * 0.003)

    # ── V3: quality pre-filter on estimated TP/SL ─────────────────────────────
    atr_pct = atr / max(entry, 1e-9)
    tp_est, sl_est = compute_tp_sl(entry, signal["action"], atr_pct, sym, signal.get("regime", "RANGING"))
    if not _has_min_edge(entry, tp_est, sl_est):
        print(f"    portfolio gate: min_edge  sym={sym}  "
              f"tp={abs(tp_est-entry)/entry:.4f}  sl={abs(sl_est-entry)/entry:.4f}")
        return
    _sig_ev = signal.get("ev", 0.0)   # set by RDE evaluate_signal; 0.0 = conservative
    if _reject_bad_rr(entry, tp_est, sl_est, ev=_sig_ev, atr_pct=atr_pct):
        rr  = abs(tp_est - entry) / max(abs(sl_est - entry), 1e-9)
        print(f"    portfolio gate: bad_rr  sym={sym}  rr={rr:.2f}")
        return

    # QUIET_RANGE: skip when ATR < 2.5× round-trip fee.
    # With FEE_RT=0.15%, ATR must exceed 0.375% or the fee alone eats the edge.
    # Not bootstrapped — this is a structural market condition, not a learning gate.
    if regime == "QUIET_RANGE":
        _atr_pct = atr / max(entry, 1e-9)
        if _atr_pct < 2.5 * FEE_RT:
            print(f"    portfolio gate: quiet_atr_fee  sym={sym}  "
                  f"atr={_atr_pct:.4f}<{2.5*FEE_RT:.4f}")
            return

    # Bootstrap open: bypass staleness/cost gates until 30 closed trades
    try:
        from src.services.learning_event import get_metrics as _lgm
        bootstrap_open = _lgm().get("trades", 0) < 30
    except Exception:
        bootstrap_open = False

    ob = OrderBook.from_price(entry, spread_pct=_SPREAD_PCT)

    sig_ts  = signal.get("timestamp", time.time())
    vol_f   = signal.get("features", {}).get("vol", 0.0)
    tick_ms = max(100, min(500, int(atr / max(entry, 1e-9) * 100_000)))
    if not bootstrap_open and not valid(sig_ts, tick_ms, vol_f):
        print(f"    portfolio gate: stale_signal  sym={sym}")
        return

    ws_raw = signal.get("ws", 0.5)
    if not bootstrap_open and not pre_cost(ws_raw, FEE_RT):
        print(f"    portfolio gate: pre_cost  sym={sym}  ws={ws_raw:.3f}")
        return

    reg    = signal.get("regime", "RANGING")

    # ── V10.9: Feature-weighted quality gate ──────────────────────────────────
    # Blocks trades with insufficient feature confirmation after bootstrap.
    # Score = Σ feature_value × adaptive_weight over 7 boolean features.
    # Gate fires only post-bootstrap (≥30 trades) to avoid deadlock during cold start.
    # MIN_SCORE=3.0: requires at least 3 confirmed features at baseline weight.
    _fw_bools = {k: v for k, v in signal.get("features", {}).items()
                 if isinstance(v, bool)}
    _fw_score = 0.0
    try:
        from src.services.feature_weights import compute_weighted_score as _cws
        _fw_score = _cws(_fw_bools, sym, reg)
    except Exception:
        pass
    from src.services.feature_weights import MIN_SCORE as _FW_MIN
    if not bootstrap_open and _fw_score < _FW_MIN:
        print(f"    portfolio gate: fw_score  sym={sym}  "
              f"score={_fw_score:.2f}<{_FW_MIN}  regime={reg}")
        return
    ws_adj = ob_adjust(ws_raw, ob)
    ws_adj = ev_adjust(ws_adj, sym, reg)
    ev     = signal.get("ev", 0.05)

    # RDE already applied sigmoid gate — track force flag for logging only.
    # Force trades suppressed in QUIET_RANGE: market is dead (low ATR, no momentum)
    # so force-trading just produces timeout losses with no edge. The force guard
    # exists to maintain learning data flow — but QUIET_RANGE trades produce only
    # noise (53% timeout rate observed). Better to wait for real conditions.
    force = _force_trade_guard()
    if force and reg == "QUIET_RANGE":
        print(f"    portfolio gate: force_quiet  sym={sym}  regime=QUIET_RANGE")
        return

    import math
    from src.services.learning_event           import get_metrics as _gm
    from src.services.realtime_decision_engine import get_ev_threshold, get_ws_threshold
    _t       = _gm().get("trades", 0)
    explore  = signal.get("explore", False) or (random.random() < epsilon())
    af       = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))

    # ── V10.13: Pre-sizing inputs (coherence, portfolio_pressure) ─────────────
    _coh_v1013 = signal.get("coherence", 1.0)   # set by evaluate_signal V10.12
    _pp_v1013  = 0.0
    _mom_v1013 = 0.0
    try:
        from src.services.risk_engine import (
            portfolio_pressure as _ppfn,
            portfolio_momentum as _pmfn,
        )
        _pp_v1013  = _ppfn(_positions)
        _mom_v1013 = _pmfn(_positions)
    except Exception:
        pass

    base     = final_size(sym, reg, 0.05 if _t >= 20 else 0.025, _positions, ob,
                          coherence=_coh_v1013,
                          portfolio_pressure=_pp_v1013)
    if base == 0.0:
        print(f"    portfolio gate: exposure_full  sym={sym}")
        return
    thr      = get_ev_threshold()
    ws_thr   = ws_threshold()
    ws_ratio = (ws_adj / ws_thr) if ws_thr > 0 else 1.0
    size     = base * math.sqrt(min(ws_ratio, 2.25)) * af

    # Half-Kelly sizing after 30 trades
    if _t >= 30:
        pf = _gm().get("profit_factor", 1.0)
        wr = _gm().get("winrate", 0.0)
        if 0 < wr < 1.0 and pf > 0:
            rrr = pf * (1.0 - wr) / wr
            if rrr > 0:
                kelly_pct = wr - ((1.0 - wr) / rrr)
                if kelly_pct > 0:
                    half_kelly = max(0.01, min(0.20, kelly_pct / 2.0))
                    size = half_kelly * af

    # ── V10.13: Portfolio momentum sizing multiplier ───────────────────────────
    # Portfolio-level trajectory (not per-signal momentum) modulates size.
    # Positive portfolio momentum → allow slight expansion; negative → trim.
    # Range: momentum=+1 → ×1.20; momentum=-1 → ×0.70 (floor).
    # Applied AFTER Kelly so the trajectory multiplier scales the Kelly fraction,
    # not base — keeps Kelly math intact.
    _pf_mom_mult = max(0.70, 1.0 + 0.20 * _mom_v1013)
    size *= _pf_mom_mult

    # V9: policy_score — continuous size modulation replacing binary ev>thr*1.5→*1.5.
    # momentum proxy: ws_raw normalized to [-1, 1] via (ws-0.5)*2 — ws already
    # aggregates MACD/RSI/EMA signals from signal_generator, so it's the best
    # available momentum estimate without recomputing indicators.
    _wr_ps     = _gm().get("winrate", 0.5) or 0.5
    _momentum  = (ws_raw - 0.5) * 2.0
    _feat_adx  = signal.get("features", {}).get("adx", 0.0)
    _reg_score = 1.0 if _feat_adx > 25 else 0.5

    # ── V10.7: Policy Layer — meta-adaptive EV multiplier ─────────────────────
    # policy_ev = risk_ev × policy_multiplier(meta_mode, alignment, confidence, wr)
    # Replaces raw ev in policy_score so sizing reflects system health context.
    _meta_mode_pol = _meta_state["mode"]
    _conf_pol      = signal.get("confidence", 0.5) or 0.5
    _act_pol       = signal.get("action", "")
    _reg_align     = 0.5   # neutral (RANGING / HIGH_VOL / QUIET_RANGE)
    if (_act_pol == "BUY"  and reg == "BULL_TREND") or \
       (_act_pol == "SELL" and reg == "BEAR_TREND"):
        _reg_align = 1.0   # signal aligned with regime
    elif (_act_pol == "BUY"  and reg == "BEAR_TREND") or \
         (_act_pol == "SELL" and reg == "BULL_TREND"):
        _reg_align = 0.0   # counter-regime signal
    _raw_ev_pol = 0.0
    try:
        from src.services.execution import risk_ev as _rev_pol
        _raw_ev_pol = _rev_pol(sym, reg)
    except Exception:
        pass
    _policy_ev, _pm = _raw_ev_pol, 1.0
    try:
        from src.services.policy_layer import compute_policy_ev as _cev
        _policy_ev, _pm = _cev(_raw_ev_pol, _meta_mode_pol, _reg_align, _conf_pol, _wr_ps)
    except Exception:
        pass

    _pol  = policy_score(_policy_ev, _wr_ps, _momentum, atr_pct, _reg_score)
    size *= max(0.5, min(1.5, 1.0 + _pol))   # clamp: never below 50% or above 150%

    # V10: meta_controller — system-health aggression multiplier.
    # V10 adds volatility param (atr_pct already computed above) and hard 0.0 stop.
    # Applied after Kelly/base sizing; trade_freq from tick-rate window.
    _dd_mc    = _gm().get("max_drawdown", 0.0)
    _sharpe   = _gm().get("sharpe", 0.0)
    _recent_n = sum(1 for t in _trades_at_tick if _tick_counter[0] - t <= 100)
    _meta     = meta_controller(_sharpe, _dd_mc, _wr_ps, _recent_n / 100.0,
                                volatility=atr_pct)
    if _meta == 0.0:
        print(f"    portfolio gate: meta_hard_stop  DD={_dd_mc:.1%}  sym={sym}")
        return
    size *= _meta

    # ── V10.8: Regime Transition Prediction ───────────────────────────────────
    # Scale new position down if a regime switch is predicted; exit open weak
    # positions already in the transitioning regime (risk_ev < 0.05).
    _pred_reg = reg
    try:
        from src.services.regime_predictor import predicted_regime as _pred_fn
        _pred_reg = _pred_fn(signal, reg, _meta_mode_pol)
    except Exception:
        pass
    if _pred_reg != reg:
        size *= 0.85
        print(f"    regime_pred[v10.8]: {reg}→{_pred_reg}  size×0.85")
        for _psym, _ppos in list(_positions.items()):
            if (_ppos.get("signal", {}).get("regime", "") == reg
                    and _ppos.get("risk_ev", 0.0) < 0.05):
                rotate_position(_psym)
                print(f"    regime_pred[v10.8]: weak exit  sym={_psym}  ev<0.05")

    # ── V10.5: Correlation size penalty ──────────────────────────────────────
    # Spec chain: cluster_penalty → max_pos cap → …
    # Applied BEFORE max_pos so the cap sees already-penalised size.
    # Soft multiplier [0.70, 1.0] — complements correlation_shield hard block.
    _corr_penalty = 1.0
    try:
        from src.services.execution import correlation_size_penalty as _csp
        _corr_penalty = _csp(sym, signal.get("action", ""), _positions)
    except Exception:
        pass
    if _corr_penalty < 1.0:
        size *= _corr_penalty
        print(f"    corr_penalty[v10.5]: ×{_corr_penalty:.2f}  sym={sym}")

    # ── V10.8: Adaptive max position cap ──────────────────────────────────────
    # Spec chain: cluster_penalty → max_pos cap (this block).
    # defensive / HIGH_VOL → 0.70×base; aggressive + trend → 1.30×base.
    _max_pos = base
    try:
        from src.services.policy_layer import adaptive_max_pos as _amp
        _max_pos = _amp(base, _meta_mode_pol, _pred_reg)
    except Exception:
        pass
    if size > _max_pos:
        print(f"    max_pos[v10.8]: {size:.4f}→{_max_pos:.4f}  "
              f"mode={_meta_mode_pol}  pred={_pred_reg}")
        size = _max_pos

    # ── V10.12: Portfolio risk budget constraint ───────────────────────────────
    # Correlation-aware marginal VaR ensures the new position fits within the
    # remaining risk budget without breaching the per-regime allocation.
    # Uses estimated SL (tp_est/sl_est computed earlier from atr_pct) so no
    # additional computation is needed — sl_pct is already available here.
    # corr_size_factor() replaces the count-based correlation_size_penalty()
    # with a regime-aware version that includes a hedge bonus (opposite dir →
    # 1.10×) and a heavier same-regime penalty (same dir + same reg → 0.60×).
    _sl_pct_rb = abs(sl_est - entry) / max(entry, 1e-9)
    try:
        from src.services.risk_engine import (
            apply_risk_budget as _arb,
            corr_size_factor  as _csf,
            risk_report       as _rrpt,
        )
        # Regime-aware correlation factor (supplement to existing corr_penalty)
        _csf_mult  = _csf(signal.get("action", ""), reg, _positions)
        _size_pre  = size
        size      *= _csf_mult
        # Budget constraint — quadratic solve for max size within var cap
        size       = _arb(size, _sl_pct_rb, signal.get("action", ""), reg, _positions)
        if size < _size_pre * 0.95:   # log only when meaningfully constrained
            _rb  = _rrpt(_positions)
            print(f"    risk_engine[v10.12]: {_size_pre:.4f}→{size:.4f}  "
                  f"csf×{_csf_mult:.2f}  "
                  f"budget_used={_rb.get('budget_used_pct', 0):.1%}  "
                  f"regime={reg}")
    except Exception:
        pass

    # ── V10.8: Policy-scaled partial TP multiplier ────────────────────────────
    # healthy system (pm>1) → fires later (let winners run);
    # defensive (pm<1) → fires earlier (lock gains sooner). Stored in position.
    _partial_tp_mult = 1.5
    try:
        from src.services.policy_layer import scaled_partial_tp as _stp
        _partial_tp_mult = _stp(1.5, _pm)
    except Exception:
        pass

    _repl_flag  = signal.get("_is_replacement", False)
    _coh_log    = signal.get("coherence", 1.0)
    _efficiency = 0.0   # computed post-exec at line ~1507; pre-log placeholder
    print(f"    policy[v10.7/10.8/v10.9/v10.10/v10.12/v10.13]: "
          f"mode={_meta_mode_pol}  pm={_pm:.3f}  "
          f"policy_ev={_policy_ev:.4f}  risk_ev={_raw_ev_pol:.4f}\n"
          f"     fw={_fw_score:.2f}  pred={_pred_reg}  max_pos={_max_pos:.4f}  "
          f"ptp×={_partial_tp_mult:.2f}  corr×={_corr_penalty:.2f}  sxd=False\n"
          f"     eff={_efficiency:.4f}  eff_live={_efficiency:.4f}  "
          f"repl={_repl_flag}  coh={_coh_log:.3f}\n"
          f"     pp={_pp_v1013:.3f}  mom={_mom_v1013:.3f}  "
          f"mom_mult×{_pf_mom_mult:.2f}")

    # V10.1: confidence → size coupling.
    # signal.confidence is from signal_generator (penalised by HIGH_VOL×0.5,
    # counter-trend×0.6, weak-EMA×0.7, session-quality×0.85-1.0).
    # Normalize to 0.5 baseline so average-quality signal = 1.0× (no change):
    #   confidence=0.5 → 1.0×   neutral
    #   confidence=0.3 → 0.6×   weak signal: trim exposure
    #   confidence=0.7 → 1.2×   strong signal: slight boost (capped)
    #   confidence=0.25 → 0.5×  floor
    # Bootstrap-safe: most early signals have confidence≈0.5 → multiplier≈1.0×.
    # Spec formula (confidence×size) NOT used — it halves every typical signal
    # since confidence<1 for all practical inputs. Normalized version preserves
    # expected sizing behaviour while enabling differentiation.
    _conf = signal.get("confidence", 0.5) or 0.5
    size *= max(0.5, min(1.2, _conf / 0.5))

    if explore:
        size *= 0.3
    size = _vol_adjust(size, signal)
    size = size_floor(size)
    size = final_size_meta(size)
    # V10.3: realized-vol refinement — stable symbols get slightly more capital,
    # high-vol symbols get slightly less; bounded [0.7×, 1.3×], bootstrap-safe
    size *= volatility_adjustment(sym)

    # Regime WR penalty: if a regime has <40% WR after 20+ trades, halve size.
    # Hard block if WR < 35% after 25+ trades — bootstrap safety: fresh DB
    # needs enough data before regime blocks fire.
    # Self-adaptive — no hardcoded regime names.
    # Penalty/block lifts automatically if WR improves above threshold.
    try:
        _reg_stats = _gm().get("regime_stats", {}).get(reg, {})
        _reg_n  = _reg_stats.get("trades", 0)
        _reg_wr = _reg_stats.get("winrate", 1.0)
        if _reg_n >= 25 and _reg_wr < 0.35:
            print(f"    regime BLOCK  regime={reg}  wr={_reg_wr:.1%}  n={_reg_n}")
            return None
        elif _reg_n >= 20 and _reg_wr < 0.40:
            size *= 0.5
            print(f"    regime penalty x0.5  regime={reg}  wr={_reg_wr:.1%}  n={_reg_n}")
    except Exception:
        pass

    # Micro-cap penalty: coins priced below $0.01 (NOM $0.0027, etc.) have
    # near-zero absolute ATR → exits dominated by timeouts → all PnL is noise.
    # Cap position size at 25% of normal to limit per-trade damage while the
    # system still collects learning data from these pairs.
    _price = signal.get("price", 1.0) or 1.0
    if _price < 0.01:
        size *= 0.25
        print(f"    micro-cap penalty x0.25  price={_price:.6f}  sym={sym}")

    ctrl = failure_control(_positions)
    if ctrl == 0.0:
        print(f"    portfolio gate: failure_halt  sym={sym}  mode={bootstrap_mode()}")
        return
    size *= ctrl

    # ── V10.11: Execution Quality Layer ──────────────────────────────────────
    # Applied last in sizing chain — after all EV/policy/risk multipliers.
    # Only hard block: extreme spread (> 0.15%). Everything else is a penalty.
    try:
        from src.services.execution_quality import exec_quality_score as _eqs
        _eq = _eqs(sym, signal.get("action", "BUY"), entry, atr_pct, ob)
        if _eq["skip"]:
            print(f"    exec_quality[v10.11]: SKIP_SPREAD  "
                  f"spread={_eq['spread']:.4f}>{0.0015:.4f}  sym={sym}")
            return
        _eq_mult = _eq["exec_quality"]
        if _eq_mult < 1.0:
            size *= _eq_mult
        print(f"    exec_quality[v10.11]: "
              f"exec_q={_eq_mult:.2f} spread={_eq['spread']:.4f} "
              f"slip={_eq['slip']:.4f} fill={_eq['fill']:.2f} "
              f"lat={_eq['lat']:.2f}")
    except Exception as _eq_exc:
        print(f"    exec_quality[v10.11]: skipped ({_eq_exc})")

    edge = net_edge(ws_adj, size, ob, FEE_RT, sym)
    if not cost_guard_bootstrap(edge):
        print(f"    portfolio gate: cost_guard  sym={sym}  "
              f"edge={edge:.4f}  mode={bootstrap_mode()}")
        return

    # ── V10.12b: Portfolio Risk Budget ────────────────────────────────────────
    # Applied after all sizing multipliers and quality/cost checks.
    # Only block: portfolio heat limit (total notional exposure cap).
    try:
        from src.services.risk_engine import (
            portfolio_risk_budget as _prb,
            heat_limit_ok         as _hlo,
        )
        _rb_res = _prb(_positions)
        _rb     = _rb_res["risk_budget"]

        if not _hlo(_positions, _rb):
            print(f"    risk_budget[v10.12c]: HEAT_LIMIT  sym={sym}  "
                  f"risk={_rb:.2f}")
            return

        if _rb < 1.0:
            size *= _rb
            # _max_pos intentionally NOT scaled: recycling gate has its own dd<12% guard

        print(f"    risk_budget[v10.12c]: "
              f"risk={_rb:.2f} dd={_rb_res['dd']:.3f} "
              f"sharpe={_rb_res['sharpe']:.2f} ruin={_rb_res['ruin']:.3f} "
              f"heat={_rb_res['heat']:.4f} max_heat={_rb_res['max_heat']:.4f}")
    except Exception as _rb_exc:
        print(f"    risk_budget[v10.12b]: skipped ({_rb_exc})")

    # ── Execution ─────────────────────────────────────────────────────────────
    actual_entry, fill_slip, actual_fee_rt = exec_order(signal, size, ob, sym)
    actual_entry = actual_entry or entry

    actual_atr = max(signal.get("atr", 0) or 0, actual_entry * 0.003) / actual_entry if actual_entry else 0.003
    tp, sl = compute_tp_sl(actual_entry, signal["action"], actual_atr, sym, signal.get("regime", "RANGING"))

    # Record tick for force-trade rate tracking
    _trades_at_tick.append(_tick_counter[0])
    if len(_trades_at_tick) > 200:
        del _trades_at_tick[:-200]

    # V10.4: capture risk_ev at open time for position_score() comparisons
    _ev_open = 0.0
    try:
        from src.services.execution import risk_ev as _rev_open
        _ev_open = _rev_open(sym, signal.get("regime", "RANGING"))
    except Exception:
        pass

    # V10.10: expected hold time + efficiency at open
    # Re-uses dynamic_hold + dynamic_hold_extension (same as on_price timeout logic)
    # so efficiency = policy_ev per expected tick of capital lock-up.
    _adx_open10   = signal.get("features", {}).get("adx", 0.0)
    _hold_base10  = _dynamic_hold(atr, actual_entry, sym, reg, adx=_adx_open10)
    _expected_hold = dynamic_hold_extension(_hold_base10, _ev_open, atr, actual_entry)
    _efficiency    = _policy_ev / max(_expected_hold, 1e-6)

    # V10.10/V10.13: capital recycling bonus — disabled under portfolio stress.
    # Recycling ×1.1 only fires when:
    #   - replaced position closed profitably (move ≥ 0)
    #   - portfolio_pressure < 0.50  (not in stress regime)
    #   - portfolio_momentum ≥ -0.30 (trajectory not actively worsening)
    #   - drawdown < 12%            (not in defensive mode)
    _recycling_pnl = signal.get("_recycling_pnl", None)
    _dd_recycle    = _gm().get("max_drawdown", 0.0)
    _recycle_ok    = (
        _recycling_pnl is not None
        and _recycling_pnl >= 0
        and _pp_v1013 < 0.50
        and _mom_v1013 >= -0.30
        and _dd_recycle < 0.12
    )
    if _recycle_ok:
        size = min(size * 1.1, _max_pos)
        print(f"    recycle[v10.10/v10.13]: ×1.1  prev_move={_recycling_pnl*100:.2f}%"
              f"  pp={_pp_v1013:.2f}  mom={_mom_v1013:.2f}  size→{size:.4f}")
    elif _recycling_pnl is not None and _recycling_pnl >= 0:
        print(f"    recycle[v10.13/BLOCKED]: pp={_pp_v1013:.2f}  "
              f"mom={_mom_v1013:.2f}  dd={_dd_recycle:.1%}  → no bonus")

    _positions[sym] = {
        "action":        signal["action"],
        "entry":         actual_entry,
        "size":          size,
        "tp":            tp,
        "sl":            sl,
        "tp_move":       abs(tp - actual_entry) / actual_entry,
        "sl_move":       abs(sl - actual_entry) / actual_entry,
        "signal":        signal,
        "ticks":         0,
        "fill_slippage": fill_slip,
        "fee_rt":        actual_fee_rt,
        "trail_price":   actual_entry,
        "max_price":     actual_entry,
        "min_price":     actual_entry,
        "is_trailing":   False,
        "partial_taken": False,   # True after partial TP exit fires
        "realized_pnl":  0.0,    # accumulated profit from partial exits
        "risk_ev":       _ev_open,  # V10.4: stored for position_score comparisons
        "open_ts":       time.time(),  # V10.4b: for time-decay in position_score
        "live_pnl":      0.0,    # V10.4b: updated each tick for profit protection
        "original_size": size,   # V10.5: pyramid cap — total size ≤ 2× this
        "adds":          0,      # V10.5: number of scale-ins so far (max 2)
        "reduced":       False,  # V10.5: True once de-risk cut has fired
        "policy_mult":      _pm,               # V10.7: policy multiplier at open
        "partial_tp_mult":  _partial_tp_mult,  # V10.8: scaled TP ATR multiplier
        "pred_regime":      _pred_reg,         # V10.8: predicted regime at open
        "soft_exit_done":   False,             # V10.8: one-shot soft preemptive exit
        "fw_score":         _fw_score,         # V10.9: feature-weighted score at open
        "efficiency":       _efficiency,       # V10.10: EV / expected_hold at open
        "efficiency_live":  _efficiency,       # V10.10: decays each tick (exp decay)
        "expected_hold":    _expected_hold,    # V10.10: hold ticks used as decay tau
    }
    tag = "[force]" if force else ""
    print(f"    exec{tag}: slip={fill_slip:.5f}  fee={actual_fee_rt:.5f}  fr={fill_rate(sym):.2f}  "
          f"ws_adj={ws_adj:.3f}  {size:.4f}@{actual_entry:.4f}  "
          f"tp={tp:.4f}  sl={sl:.4f}")
    _regime_exposure[regime] = _regime_exposure.get(regime, 0) + 1
    _risk_guard()

    # V10.10: portfolio efficiency snapshot (diagnostic — not persisted)
    if _positions:
        _pf_ev_sum  = sum(p.get("efficiency", 0.0) * max(p.get("expected_hold", 1.0), 1e-6)
                          for p in _positions.values())
        _pf_sz_sum  = sum(p["size"] * max(p.get("expected_hold", 1.0), 1e-6)
                          for p in _positions.values())
        _pf_eff     = _pf_ev_sum / max(_pf_sz_sum, 1e-9)
        print(f"    portfolio[v10.10]: positions={len(_positions)}  "
              f"portfolio_efficiency={_pf_eff:.4f}")


def on_price(data):
    if time.time() - _last_flush[0] >= FLUSH_EVERY and BATCH:
        _flush()

    _tick_counter[0] += 1   # global tick — drives force_trade_guard rate

    sym = data["symbol"]
    if sym not in _positions:
        return

    pos = _positions[sym]
    pos["ticks"] += 1
    curr  = data["price"]
    entry = pos["entry"]

    move = (curr - entry) / entry
    if pos["action"] == "SELL":
        move *= -1

    # V10.4b: keep live_pnl fresh so should_replace profit protection is accurate
    pos["live_pnl"] = move

    # V10.10: live efficiency decay — exp(-t/tau) where tau = expected_hold ticks.
    # As the trade ages past its expected duration its efficiency value drops,
    # making it a natural candidate for replacement by fresher opportunities.
    _t_alive = time.time() - pos.get("open_ts", time.time())
    _tau10   = max(pos.get("expected_hold", 10.0), 1e-6)
    pos["efficiency_live"] = pos.get("efficiency", 0.0) * math.exp(-_t_alive / _tau10)

    # V10.13: record portfolio PnL snapshot every 5 ticks (sampled, not every tick)
    # to keep _pf_pnl_hist dense enough for OLS slope without excessive overhead.
    _pf_tick_counter[0] += 1
    if _pf_tick_counter[0] % 5 == 0 and _positions:
        try:
            from src.services.risk_engine import record_portfolio_pnl as _rpf
            _rpf(_positions)
        except Exception:
            pass

    # MAE / MFE tracking
    if curr > pos["max_price"]: pos["max_price"] = curr
    if curr < pos["min_price"]: pos["min_price"] = curr

    # Trail price tracking
    if pos["action"] == "BUY" and curr > pos["trail_price"]:
        pos["trail_price"] = curr
    elif pos["action"] == "SELL" and curr < pos["trail_price"]:
        pos["trail_price"] = curr

    # Activate trailing stop at +0.60% profit
    if not pos["is_trailing"] and move >= 0.006:
        pos["is_trailing"] = True
        print(f"    🚀 {sym} TRAILING STOP ACTIVOVÁN! Zisk: {move*100:.2f}%")

    # ── V10.8: Soft preemptive exit — de-risk on predicted regime transition ──
    # Fires once when the regime is predicted to change AND position gain is
    # small (< 0.15×ATR) — not worth waiting in a transitioning market.
    # Reduces size 50% to lock partial value; guarded by soft_exit_done flag.
    # Skipped when already partial-taken, reduced, or trailing (those handlers
    # manage sizing independently and must not be double-cut).
    if not pos.get("soft_exit_done") and not pos.get("partial_taken") \
            and not pos.get("reduced") and not pos.get("is_trailing"):
        _reg_op   = pos.get("signal", {}).get("regime", "RANGING")
        _pred_soft = _reg_op
        try:
            from src.services.regime_predictor import predicted_regime as _pf
            _pred_soft = _pf(pos["signal"], _reg_op, _meta_state["mode"])
        except Exception:
            pass
        if _pred_soft != _reg_op:
            _atr_soft     = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
            _atr_pct_soft = _atr_soft / max(entry, 1e-9)
            if move < 0.15 * _atr_pct_soft:   # small gain — not worth holding
                pos["size"]          *= 0.5
                pos["soft_exit_done"] = True
                _risk_guard()
                print(f"    🔀 {sym.replace('USDT','')} SOFT_EXIT 50%  "
                      f"{_reg_op}→{_pred_soft}  move={move*100:.2f}%")

    # ── Partial TP: exit 50% at scaled×ATR profit, move SL to breakeven ──────
    # V10.8: threshold = partial_tp_mult × ATR (stored at open, driven by pm).
    # Higher pm (healthy/aggressive) → fires later; lower pm (defensive) → sooner.
    # Research (Mind Math Money / Semantic Scholar): partial scale-out at an
    # intermediate target is "the most practical approach" — locks in real gains
    # while preserving upside on the remaining half. Directly reduces timeouts:
    # positions that reach the threshold then reverse now book 50% of that gain
    # instead of timing out at zero. After partial exit, SL moves to entry
    # (breakeven) — remaining half is risk-free. Chandelier trail continues.
    # Apply the same ATR floor as compute_tp_sl (entry×0.003 minimum).
    # Without the floor, raw tick-level ATR (e.g. 0.00006 for ADA at $0.25) makes
    # the threshold ~0.036% — partial TP fires on noise before fees are covered.
    _atr_partial  = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
    _fee_p        = pos.get("fee_rt", FEE_RT)
    _ptp_mult     = pos.get("partial_tp_mult", 1.5)
    if not pos.get("partial_taken") and move >= _ptp_mult * (_atr_partial / max(entry, 1e-9)) and move > _fee_p:
        partial = (move - _fee_p) * pos["size"] * 0.5
        pos["partial_taken"] = True
        pos["realized_pnl"]  = pos.get("realized_pnl", 0.0) + partial
        pos["size"]         *= 0.5
        pos["sl"]            = entry   # breakeven: remaining half is now risk-free
        _short_p = sym.replace("USDT", "")
        print(f"    📦 {_short_p} PARTIAL TP 50%  "
              f"pnl={partial:+.6f}  move={move*100:.2f}%  SL→breakeven")

    # V10.5b: position scaling — pyramid winners / de-risk losers
    # Runs after partial TP (which can change size/sl) but before exit checks.
    _prev = pos.get("prev_price", curr)   # price from previous tick (neutral on tick 1)
    if should_add_to_position(pos, curr, _prev):
        add_to_position(pos, curr)
        entry = pos["entry"]   # refresh local var — exit math must use blended entry
        short_p = sym.replace("USDT", "")
        print(f"    📈 {short_p} PYRAMID add#{pos['adds']}  "
              f"size={pos['size']:.4f}  avg_entry={entry:.4f}  move={move*100:.2f}%")
    if should_reduce_position(pos, curr):
        reduce_position(pos, curr)
        short_p = sym.replace("USDT", "")
        print(f"    ✂️  {short_p} REDUCE  "
              f"size={pos['size']:.4f}  move={move*100:.2f}%  ev={pos.get('risk_ev',0):.3f}")

    # V10.2: adaptive SL tightening — protect profits in pre-trail window (0.3%-0.6%)
    # Not applied during trailing (Chandelier owns the stop; pos["sl"] not read)
    if not pos["is_trailing"]:
        _atr_tighten = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
        pos["sl"] = adaptive_sl_tightening(
            entry, curr, pos["sl"], pos["action"], _atr_tighten)

    # ── Exit conditions ────────────────────────────────────────────────────────
    reason = None
    atr = pos["signal"].get("atr", entry * 0.003)

    # Chandelier exit: highest_high - 2×ATR (BUY) / lowest_low + 2×ATR (SELL)
    # Research: ATR-based Chandelier exit outperforms fixed TP in volatile regimes
    # (Semantic Scholar peer-reviewed study). It expands in high-vol allowing trades
    # to breathe, and contracts in low-vol locking in gains — superior to a fixed
    # trail_price offset that doesn't adapt to volatility changes during the trade.
    # Uses max_price/min_price already tracked in the position dict.
    # Multiplier 2.0×ATR: tighter than 3× (standard) to suit short 1m timeframes.
    chandelier_atr_mult = 2.0
    if pos["action"] == "BUY":
        chandelier_stop = pos["max_price"] - chandelier_atr_mult * atr
    else:
        chandelier_stop = pos["min_price"] + chandelier_atr_mult * atr

    if pos.get("force_close"):
        reason = "replaced"
    elif pos["is_trailing"]:
        # Chandelier exit: uses highest_high/lowest_low since entry rather than
        # last tick trail_price — gives more room in trending moves, still cuts
        # quickly if price reverses sharply from the peak/trough
        if pos["action"] == "BUY"  and curr <= chandelier_stop:
            reason = "TRAIL_SL"
        elif pos["action"] == "SELL" and curr >= chandelier_stop:
            reason = "TRAIL_SL"
    else:
        # V3 BUG FIX: pos["tp"] was stored but never checked — TP exits never fired.
        # Added explicit TP check before SL and removed the TP_FALLBACK (>10%) crutch.
        if   pos["action"] == "BUY"  and curr >= pos["tp"]: reason = "TP"
        elif pos["action"] == "SELL" and curr <= pos["tp"]: reason = "TP"
        elif pos["action"] == "BUY"  and curr <= pos["sl"]: reason = "SL"
        elif pos["action"] == "SELL" and curr >= pos["sl"]: reason = "SL"

    # ── L2 sell/buy wall exit — proactive exit before order book barrier ─────
    # Fires only when position is already profitable (move ≥ 0.10%) to avoid
    # noise-triggered exits in flat/losing trades.  Detects when a massive
    # opposite-side wall sits within WALL_BAND_PCT (0.3%) of current price:
    #   BUY  position + sell wall above  → exit before wall caps upside
    #   SELL position + buy wall below   → exit before wall caps downside
    # Skipped when trailing stop is already active (Chandelier owns the exit).
    # Skipped post-partial-taken: SL already at breakeven, risk is minimal.
    if reason is None and not pos["is_trailing"] and not pos.get("partial_taken"):
        try:
            from src.services.order_book_depth import (
                is_sell_wall, is_buy_wall, MIN_PROFIT_TO_EXIT)
            if pos["action"] == "BUY" and move >= MIN_PROFIT_TO_EXIT:
                if is_sell_wall(sym, curr):
                    reason = "wall_exit"
                    print(f"    🧱 {sym.replace('USDT','')} SELL_WALL detected  "
                          f"move={move*100:.2f}%  → proactive exit")
            elif pos["action"] == "SELL" and move >= MIN_PROFIT_TO_EXIT:
                if is_buy_wall(sym, curr):
                    reason = "wall_exit"
                    print(f"    🧱 {sym.replace('USDT','')} BUY_WALL detected  "
                          f"move={move*100:.2f}%  → proactive exit")
        except Exception:
            pass

    # V9 early exit: negative-EV pair that is losing → don't hold to full timeout.
    # Rationale: if risk_ev(sym, reg) < -0.1 (statistically confirmed negative edge)
    # AND trade is currently down 0.2%+ after at least 5 ticks, there's no reason
    # to wait. Timeout would only worsen the loss while consuming position capacity.
    # Threshold -0.1 (not 0) prevents triggering during bootstrap when ev ≈ 0.
    # Threshold move < -0.002: below typical noise floor (~0.1%) and spread (0.1%).
    # Partial-taken positions skipped — breakeven SL already protects remaining half.
    if reason is None and move < -0.002 and pos["ticks"] >= 5 and not pos.get("partial_taken"):
        try:
            from src.services.execution import risk_ev as _rev
            if _rev(sym, pos["signal"].get("regime", "RANGING")) < -0.1:
                reason = "early_exit"
        except Exception:
            pass

    _adx_sig = pos["signal"].get("features", {}).get("adx", 0.0)
    _reg_hold = pos["signal"].get("regime", "RANGING")
    timeout   = _dynamic_hold(atr, entry, sym, _reg_hold, adx=_adx_sig)
    # V10.3: extend/shorten hold based on live edge quality
    _ev_hold  = 0.0
    try:
        from src.services.execution import risk_ev as _rev_h
        _ev_hold = _rev_h(sym, _reg_hold)
    except Exception:
        pass
    timeout = dynamic_hold_extension(timeout, _ev_hold, atr, entry)
    if reason is None and pos["ticks"] >= timeout:
        reason = "timeout"

    # V10.5b: store current price as prev for next tick's momentum check
    pos["prev_price"] = curr

    if reason is None:
        return

    fee_used = pos.get("fee_rt", FEE_RT)
    profit   = (move - fee_used) * pos["size"] + pos.get("realized_pnl", 0.0)
    result   = "WIN" if profit > 0 else "LOSS"
    short    = sym.replace("USDT", "")
    icon     = "✅" if result == "WIN" else "❌"

    print(f"    {icon} {short} {pos['action']} "
          f"${entry:,.4f}→${curr:,.4f}  {profit:+.6f}  [{reason}] (fee: {fee_used:.5f})")

    mfe = ((pos["max_price"] - entry) / entry if pos["action"] == "BUY"
           else (entry - pos["min_price"]) / entry)
    mae = ((entry - pos["min_price"]) / entry if pos["action"] == "BUY"
           else (pos["max_price"] - entry) / entry)

    try:
        from src.services.notifier import send_trade_notification
        send_trade_notification(sym, pos["action"], move - fee_used, reason)
    except Exception as e:
        print(f"    [Warn: Notifikace error] {e}")

    trade = {
        **pos["signal"],
        "profit":        profit,
        "result":        result,
        "exit_price":    curr,
        "close_reason":  reason,
        "timestamp":     time.time(),
        "fill_slippage": pos.get("fill_slippage", 0.0),
        "mae":           mae,
        "mfe":           mfe,
    }

    update_metrics(pos["signal"], trade)
    update_returns(sym, profit)
    update_equity(profit)
    reg_sig = pos["signal"].get("regime", "RANGING")
    bayes_update(sym, reg_sig, profit)
    bandit_update(sym, reg_sig, max(-0.05, min(0.05, profit)))
    record_trade_close(sym, reg_sig, profit)

    try:
        from src.services.learning_monitor import lm_update
        raw_f  = pos["signal"].get("features", {})
        bool_f = {k: v for k, v in raw_f.items() if isinstance(v, bool)}
        # V7: micro-PnL mapping — preserve directional signal for mid-range trades.
        # < 0.0005: pure noise / timeout → 0.0 (no signal either way)
        # [0.0005, 0.001): real but tiny → ±0.0003 (preserve direction, reduce magnitude)
        # ≥ 0.001: real trade → use as-is
        # Timeout trades typically have |profit| < 0.0005 (fee×tiny_size) → still zeroed.
        _ap = abs(profit)
        if   _ap < 0.0005: learning_pnl = 0.0
        elif _ap < 0.001:  learning_pnl = 0.0003 if profit > 0 else -0.0003
        else:              learning_pnl = profit
        # Timeout = neutral: no TP/SL reached → no directional signal.
        # Penalty removed — in QUIET market 57% timeout rate drove pair EVs
        # negative rapidly → pair_block deadlock after bootstrap wipe.
        lm_update(sym, reg_sig, learning_pnl,
                  ws=pos["signal"].get("ws", 0.5),
                  features=bool_f)
    except Exception:
        pass

    # ── V10.9: Adapt feature weights from closed position ─────────────────────
    # EV contribution per active feature = learning_pnl / n_active.
    # Inactive features are omitted — no penalty for absence, only reward/penalty
    # for features that were present and contributed to this outcome.
    try:
        from src.services.feature_weights import update_feature_weights as _ufw
        _active_fw = [k for k, v in bool_f.items() if v]
        if _active_fw and learning_pnl != 0.0:
            _per_f = learning_pnl / len(_active_fw)
            _fevs  = {k: _per_f for k in _active_fw}
            _lmh_fw, _dd_fw = 0.0, 0.0
            try:
                from src.services.learning_monitor import lm_health as _lmhfn
                _lmh_fw = float(_lmhfn() or 0.0)
            except Exception:
                pass
            try:
                from src.services.diagnostics import max_drawdown as _ddfn
                _dd_fw = float(_ddfn() or 0.0)
            except Exception:
                pass
            _new_w = _ufw(sym, reg_sig, _fevs, _lmh_fw, _dd_fw)
            print(f"    fw[v10.9]: {sym} {reg_sig}  "
                  f"score_pnl={learning_pnl:+.5f}  "
                  f"w={{{', '.join(f'{k}:{v:.2f}' for k, v in _new_w.items() if k in _active_fw)}}}")
    except Exception:
        pass

    try:
        from src.services.realtime_decision_engine import update_calibrator, update_edge_stats
        outcome  = 1 if result == "WIN" else 0
        p        = float(pos["signal"].get("confidence", 0.5))
        features = pos["signal"].get("features", {})
        regime   = pos["signal"].get("regime", "RANGING")
        update_calibrator(p, outcome)
        update_edge_stats(features, outcome, regime)
    except Exception:
        pass

    from src.services.firebase_client import save_last_trade
    save_last_trade(trade)

    BATCH.append(trade)
    if len(BATCH) >= 5:   # lowered 20→5: flush sooner to minimise data loss on restart
        _flush()

    # V10.13: update dynamic correlation memory before removing the position.
    # Pairs the closing trade's realized move with each peer's current live_pnl
    # so the realized correlation can be learned for future variance estimates.
    try:
        from src.services.risk_engine import update_correlation_memory as _ucm
        _ucm(sym, move, _positions)
    except Exception:
        pass

    closed_regime = pos["signal"].get("regime", "RANGING")
    _regime_exposure[closed_regime] = max(
        0, _regime_exposure.get(closed_regime, 1) - 1)
    del _positions[sym]

    if _pending_open:
        pending = _pending_open.pop(0)
        # V10.10: pass closed position's move so handle_signal can apply
        # the capital recycling bonus (×1.1) when the exited trade was profitable.
        pending["_recycling_pnl"] = move
        handle_signal(pending)


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
