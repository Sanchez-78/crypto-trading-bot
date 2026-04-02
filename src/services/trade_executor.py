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

def volatility_adjustment(sym):
    """V10.3b: Smoothed realized-vol sizing refinement on top of risk_parity_weight.

    Blends recent (last 20) and older (prior 20) volatility windows to avoid
    overreacting to short-term spikes.  Blend: 70% recent + 30% older.
    When fewer than 40 samples exist, older window falls back to recent
    (pure recent std, same as V10.3) — no change in bootstrap behaviour.

    Normalises around 1% typical crypto vol: std=0.01 → 1.0×, stable → up to
    1.3×, high-vol → down to 0.7×.  Returns 1.0 when < 30 samples (bootstrap-safe).
    """
    ret = returns_hist.get(sym, [])
    if len(ret) < 30:
        return 1.0

    def _std(x):
        m = sum(x) / len(x)
        return (sum((i - m) ** 2 for i in x) / len(x)) ** 0.5

    recent     = ret[-20:]
    older      = ret[-40:-20] if len(ret) >= 40 else recent
    std        = 0.7 * _std(recent) + 0.3 * _std(older)
    vol_factor = 0.01 / (std + 1e-6)
    return max(0.7, min(1.3, vol_factor))


def dynamic_hold_extension(base_hold, ev):
    """V10.3b: Continuous EV-based hold-time scaling (replaces discrete tiers).

    scale = 1.0 + clamp(ev × 1.5, -0.3, +0.3)

    ev=-0.2  → scale≈0.70  → base×0.70   (confirmed negative edge, exit faster)
    ev= 0.0  → scale=1.00  → unchanged
    ev=+0.2  → scale=1.30  → base×1.30   (strong edge, more room to develop)

    Continuous response removes step-function jumps between tiers.
    Same clamp range as V10.3 [0.7×, 1.3×].
    Bounded result: [5, 22] ticks — identical ceiling/floor as before.
    """
    scale   = 1.0 + max(-0.3, min(0.3, ev * 1.5))
    timeout = int(base_hold * scale)
    return max(5, min(22, timeout))


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
    If portfolio is full and new signal's effective_ws > weakest position's
    effective_ws by REPLACE_MARGIN, mark weakest for immediate close and
    queue new signal to open after close.
    Returns True if replacement was queued.
    """
    if len(_positions) < MAX_POSITIONS:
        return False  # space available — caller handles normally
    weakest_sym = min(_positions,
                      key=lambda s: _effective_ws(_positions[s]["signal"]))
    new_eff  = _effective_ws(signal)
    weak_eff = _effective_ws(_positions[weakest_sym]["signal"])
    # Primary: effective_ws margin (existing logic)
    if new_eff > weak_eff * _REPLACE_MARGIN and _replace_allowed(weakest_sym):
        _positions[weakest_sym]["force_close"] = True
        _pending_open.append(signal)
        _last_replaced[weakest_sym] = time.time()
        print(f"    replace[ws]: {weakest_sym} (eff_ws={weak_eff:.3f}) "
              f"← {signal['symbol']} (eff_ws={new_eff:.3f})")
        return True
    # Secondary: regime EV rotation (true_ev 20% better)
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
    sym     = signal["symbol"]
    regime  = signal.get("regime", "RANGING")
    allowed, reason = _allow_trade(sym, signal["action"], regime)
    if not allowed:
        if reason == "max_positions":
            _replace_if_better(signal)
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
    base     = final_size(sym, reg, 0.05 if _t >= 20 else 0.025, _positions, ob)
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

    # V9: policy_score — continuous size modulation replacing binary ev>thr*1.5→*1.5.
    # momentum proxy: ws_raw normalized to [-1, 1] via (ws-0.5)*2 — ws already
    # aggregates MACD/RSI/EMA signals from signal_generator, so it's the best
    # available momentum estimate without recomputing indicators.
    _wr_ps     = _gm().get("winrate", 0.5) or 0.5
    _momentum  = (ws_raw - 0.5) * 2.0
    _feat_adx  = signal.get("features", {}).get("adx", 0.0)
    _reg_score = 1.0 if _feat_adx > 25 else 0.5
    _pol       = policy_score(ev, _wr_ps, _momentum, atr_pct, _reg_score)
    size      *= max(0.5, min(1.5, 1.0 + _pol))   # clamp: never below 50% or above 150%

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

    edge = net_edge(ws_adj, size, ob, FEE_RT, sym)
    if not cost_guard_bootstrap(edge):
        print(f"    portfolio gate: cost_guard  sym={sym}  "
              f"edge={edge:.4f}  mode={bootstrap_mode()}")
        return

    # ── Execution ─────────────────────────────────────────────────────────────
    actual_entry, fill_slip, actual_fee_rt = exec_order(signal, size, ob, sym)
    actual_entry = actual_entry or entry

    actual_atr = max(signal.get("atr", 0) or 0, actual_entry * 0.003) / actual_entry if actual_entry else 0.003
    tp, sl = compute_tp_sl(actual_entry, signal["action"], actual_atr, sym, signal.get("regime", "RANGING"))

    # Record tick for force-trade rate tracking
    _trades_at_tick.append(_tick_counter[0])
    if len(_trades_at_tick) > 200:
        del _trades_at_tick[:-200]

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
    }
    tag = "[force]" if force else ""
    print(f"    exec{tag}: slip={fill_slip:.5f}  fee={actual_fee_rt:.5f}  fr={fill_rate(sym):.2f}  "
          f"ws_adj={ws_adj:.3f}  {size:.4f}@{actual_entry:.4f}  "
          f"tp={tp:.4f}  sl={sl:.4f}")
    _regime_exposure[regime] = _regime_exposure.get(regime, 0) + 1
    _risk_guard()


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

    # ── Partial TP: exit 50% at 1.5×ATR profit, move SL to breakeven ─────────
    # Research (Mind Math Money / Semantic Scholar): partial scale-out at an
    # intermediate target is "the most practical approach" — locks in real gains
    # while preserving upside on the remaining half. Directly reduces timeouts:
    # positions that reach 1.5×ATR profit then reverse now book 50% of that gain
    # instead of timing out at zero. After partial exit, SL moves to entry
    # (breakeven) — remaining half is risk-free. Chandelier trail continues.
    # Apply the same ATR floor as compute_tp_sl (entry×0.003 minimum).
    # Without the floor, raw tick-level ATR (e.g. 0.00006 for ADA at $0.25) makes
    # the threshold ~0.036% — partial TP fires on noise before fees are covered.
    # With floor: threshold = 1.5×0.3% = 0.45% — well above the 0.15% round-trip fee.
    _atr_partial = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
    _fee_p       = pos.get("fee_rt", FEE_RT)
    if not pos.get("partial_taken") and move >= 1.5 * (_atr_partial / max(entry, 1e-9)) and move > _fee_p:
        partial = (move - _fee_p) * pos["size"] * 0.5
        pos["partial_taken"] = True
        pos["realized_pnl"]  = pos.get("realized_pnl", 0.0) + partial
        pos["size"]         *= 0.5
        pos["sl"]            = entry   # breakeven: remaining half is now risk-free
        _short_p = sym.replace("USDT", "")
        print(f"    📦 {_short_p} PARTIAL TP 50%  "
              f"pnl={partial:+.6f}  move={move*100:.2f}%  SL→breakeven")

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
    timeout = dynamic_hold_extension(timeout, _ev_hold)
    if reason is None and pos["ticks"] >= timeout:
        reason = "timeout"

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

    closed_regime = pos["signal"].get("regime", "RANGING")
    _regime_exposure[closed_regime] = max(
        0, _regime_exposure.get(closed_regime, 1) - 1)
    del _positions[sym]

    if _pending_open:
        pending = _pending_open.pop(0)
        handle_signal(pending)


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
