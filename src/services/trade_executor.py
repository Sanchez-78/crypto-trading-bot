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
    is_bootstrap, net_edge)
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


def compute_tp_sl(entry, direction, atr=0.003, sym=None, reg=None):
    """Absolute TP/SL prices.
    V6 L8: dynamic tp_k based on pair EV — proven strong edges get wider TP
    to let winners run; sl_k=0.8 unchanged (keeps RR ≥ 1.5).
      ev > 0.5 → tp_k=1.8  (strong edge, wide target)
      ev > 0.2 → tp_k=1.4  (moderate edge)
      default  → tp_k=1.2  (baseline / exploration)
    """
    tp_k = 1.2
    if sym and reg:
        try:
            from src.services.learning_monitor import lm_pnl_hist as _lph
            import numpy as _np
            _p = _lph.get((sym, reg), [])
            if len(_p) >= 10:
                _m = float(_np.mean(_p[-20:]))
                _s = max(float(_np.std(_p[-20:])), 0.002)
                _ev = _m / _s
                if _ev > 0.5:
                    tp_k = 1.8
                elif _ev > 0.2:
                    tp_k = 1.4
        except Exception:
            pass
    sl_k = 0.8

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


def _reject_bad_rr(entry, tp, sl):
    """True (= reject) when reward/risk < 1.2 — poor asymmetry."""
    risk = abs(sl - entry)
    if risk == 0:
        return True
    return abs(tp - entry) / risk < 1.2


def _dynamic_hold(atr_abs, entry):
    """Timeout ticks scaled to volatility.
    High ATR → shorter hold (5 ticks); low ATR → longer (40 ticks).
    Cap raised 20→40: with tp_k=1.5 and ATR floor 0.3%, TP distance=0.45%;
    crypto needs ~60-90s to move 0.45% → 20-tick cap (≈40s) was cutting TP
    exits prematurely, forcing 86% timeouts. 40 ticks ≈ 80s gives TP time to fire.
    ATR floor 0.3% → adj=33, comfortably below the new cap.
    """
    atr_pct = atr_abs / max(entry, 1e-9)
    adj = int(10 * (0.01 / max(atr_pct, 0.002)))
    return max(5, min(40, adj))


def _force_trade_guard():
    """True when fewer than MIN_TRADES_PER_100_TICKS opened in the last 100 ticks.
    Bypasses sigmoid gate to guarantee minimum learning data flow.
    """
    n = _tick_counter[0]
    recent = sum(1 for t in _trades_at_tick if n - t <= 100)
    return recent < MIN_TRADES_PER_100_TICKS


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
    if _reject_bad_rr(entry, tp_est, sl_est):
        rr = abs(tp_est - entry) / max(abs(sl_est - entry), 1e-9)
        print(f"    portfolio gate: bad_rr  sym={sym}  rr={rr:.2f}<1.2")
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
    force = _force_trade_guard()

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

    if ev > thr * 1.5:
        size *= 1.5
    if explore:
        size *= 0.3
    size = _vol_adjust(size, signal)
    size = size_floor(size)
    size = final_size_meta(size)

    # Regime WR penalty: if a regime has <40% WR after 10+ trades, halve size.
    # Hard block if WR < 35% after 15+ trades — statistically reliable signal.
    # Self-adaptive — no hardcoded regime names.
    # Penalty/block lifts automatically if WR improves above threshold.
    try:
        _reg_stats = _gm().get("regime_stats", {}).get(reg, {})
        _reg_n  = _reg_stats.get("trades", 0)
        _reg_wr = _reg_stats.get("winrate", 1.0)
        if _reg_n >= 15 and _reg_wr < 0.35:
            print(f"    regime BLOCK  regime={reg}  wr={_reg_wr:.1%}  n={_reg_n}")
            return None
        elif _reg_n >= 10 and _reg_wr < 0.40:
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

    # ── Exit conditions ────────────────────────────────────────────────────────
    reason = None
    atr          = pos["signal"].get("atr", entry * 0.003)
    trail_offset = 1.5 * atr

    if pos.get("force_close"):
        reason = "replaced"
    elif pos["is_trailing"]:
        if pos["action"] == "BUY"  and curr <= (pos["trail_price"] - trail_offset):
            reason = "TRAIL_SL"
        elif pos["action"] == "SELL" and curr >= (pos["trail_price"] + trail_offset):
            reason = "TRAIL_SL"
    else:
        # V3 BUG FIX: pos["tp"] was stored but never checked — TP exits never fired.
        # Added explicit TP check before SL and removed the TP_FALLBACK (>10%) crutch.
        if   pos["action"] == "BUY"  and curr >= pos["tp"]: reason = "TP"
        elif pos["action"] == "SELL" and curr <= pos["tp"]: reason = "TP"
        elif pos["action"] == "BUY"  and curr <= pos["sl"]: reason = "SL"
        elif pos["action"] == "SELL" and curr >= pos["sl"]: reason = "SL"

    # V3: dynamic hold — volatility-adaptive timeout (5–20 ticks) replaces
    # hardcoded 15 from V2. High ATR → shorter hold; low ATR → longer.
    timeout = _dynamic_hold(atr, entry)
    if reason is None and pos["ticks"] >= timeout:
        reason = "timeout"

    if reason is None:
        return

    fee_used = pos.get("fee_rt", FEE_RT)
    profit   = (move - fee_used) * pos["size"]
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
        # V3: suppress micro-PnL from lm_update — near-zero trades carry no edge
        # signal and pollute convergence stats; set to 0.0 so they count as neutral.
        learning_pnl = 0.0 if abs(profit) < 0.001 else profit
        # V6 L12: timeout penalty — timeouts produce no learning signal (neutral PnL)
        # but represent a regime/pair that can't reach TP or SL → penalise so EV
        # diverges negative over time → pair_block eventually self-triggers.
        if reason == "timeout":
            learning_pnl -= 0.001
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
