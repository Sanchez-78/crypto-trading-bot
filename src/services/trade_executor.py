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
    ev_adjust, fill_rate, capital_alloc, rotate_capital, OrderBook)
import time

BATCH             = []
_positions        = {}
_last_flush       = [0.0]
_regime_exposure  = {}   # regime -> count of open positions
_pending_open     = []   # signals queued after replace_if_better triggers

MAX_POSITIONS     = 2    # max concurrent open positions
MAX_SAME_DIR      = 1    # max positions in same direction (BUY or SELL)
MAX_REGIME_PCT    = 0.70 # block if one regime holds > 70% of open positions
_TOTAL_CAPITAL    = 1.0  # normalised capital (position sizes are fractions)
_MAX_CAP_USED     = 0.70 # don't deploy more than 70% of capital
_TARGET_VOL       = 0.02 # 2% target realised volatility for vol-adjusted sizing
_REPLACE_MARGIN   = 1.10 # new signal must be 10% better to replace weakest
_REPLACE_COOLDOWN = 300  # seconds between replacements of the same symbol
_MAX_TOTAL_RISK   = 0.05 # total portfolio risk cap (sum of size*sl_pct)
_SPREAD_PCT       = 0.001 # estimated bid-ask spread (0.10%)
_last_replaced    = {}   # symbol -> timestamp of last replacement

FEE_RT      = 0.0020    # 0.20% round-trip Binance taker fees
MIN_TP_PCT  = 0.0025    # 0.25% min TP
MIN_SL_PCT  = 0.0020    # 0.20% min SL
MAX_TICKS   = 60
FLUSH_EVERY = 60

# Edge-specific TP/SL multipliers (× ATR)
# trend_pullback: moderate TP — riding the bounce back to mean
# vol_breakout:   wide TP — volatility expansion has further to run
# fake_breakout:  tight TP — quick reversal, grab fast
_EDGE_TP    = {"trend_pullback": 1.5, "vol_breakout": 2.0, "fake_breakout": 1.2}
_EDGE_SL    = {"trend_pullback": 1.0, "vol_breakout": 1.0, "fake_breakout": 0.8}
_EDGE_TRAIL = {"trend_pullback": 0.4, "vol_breakout": 0.5, "fake_breakout": 0.3}

# Fallback (unknown edge)
_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8,
            "RANGING":    0.8, "QUIET_RANGE": 0.8}
_TRAIL   = 0.4   # fallback trail


def net_ws(ws, spread_pct, fee_rt):
    """WS after spread and round-trip fees. Negative = edge eaten by costs."""
    return ws - (spread_pct + fee_rt)


def _replace_allowed(symbol):
    """True if no replacement happened for this symbol in the last 300 s."""
    last = _last_replaced.get(symbol, 0.0)
    return (time.time() - last) > _REPLACE_COOLDOWN


def _total_risk():
    """Sum of (size × sl_move) across all open positions."""
    return sum(p["size"] * p["sl_move"] for p in _positions.values())


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
    if capital_usage() >= _MAX_CAP_USED:
        return False, "capital_limit"
    if len(_positions) >= MAX_POSITIONS:
        return False, "max_positions"
    # Direction concentration: max 1 same-direction position
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
            _replace_if_better(signal)   # may queue replacement
        else:
            print(f"    portfolio gate: {reason}  sym={sym}")
        return

    entry = signal["price"]
    atr   = signal.get("atr", entry * 0.003)

    # Build OB snapshot for cost calculations
    ob = OrderBook.from_price(entry, spread_pct=_SPREAD_PCT)

    # Signal staleness — tick_ms from ATR velocity; vol from features
    sig_ts  = signal.get("timestamp", time.time())
    vol_f   = signal.get("features", {}).get("vol", 0.0)
    tick_ms = max(100, min(500, int(atr / max(entry, 1e-9) * 100_000)))
    if not valid(sig_ts, tick_ms, vol_f):
        print(f"    portfolio gate: stale_signal  sym={sym}")
        return

    ws_raw = signal.get("ws", 0.5)

    # Pre-cost fast gate (cheap, before OB/slippage calculation)
    if not pre_cost(ws_raw, FEE_RT):
        print(f"    portfolio gate: pre_cost  sym={sym}  ws={ws_raw:.3f}")
        return

    # OB proportional adjustment + regime-aware EV blend
    reg    = signal.get("regime", "RANGING")
    ws_adj = ob_adjust(ws_raw, ob)
    ws_adj = ev_adjust(ws_adj, sym, reg)

    # Position sizing: EV-scaled, auditor floor 0.7, strong-EV boost
    import math
    from src.services.learning_event           import get_metrics as _gm
    from src.services.realtime_decision_engine import (
        get_ev_threshold, get_ws_threshold, equity_guard)
    _t      = _gm().get("trades", 0)
    ev      = signal.get("ev", 0.05)
    explore = signal.get("explore", False)
    af      = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))
    base    = capital_alloc(sym, reg, 0.05 if _t >= 20 else 0.025, _positions)
    thr     = get_ev_threshold()
    ws_thr  = get_ws_threshold()
    ws_ratio = (ws_adj / ws_thr) if ws_thr > 0 else 1.0
    size     = base * math.sqrt(min(ws_ratio, 2.25)) * af
    if ev > thr * 1.5:
        size *= 1.5
    if explore:
        size *= 0.3
    size *= equity_guard()
    size  = _vol_adjust(size, signal)
    size  = max(0.005, size)

    # Full cost guard with per-symbol blended slippage
    if not cost_guard(ws_adj, size, ob, FEE_RT, sym):
        print(f"    portfolio gate: cost_guard  sym={sym}  "
              f"ws_adj={ws_adj:.3f}  fr={fill_rate(sym):.2f}")
        return

    # TP/SL: edge-specific ATR multipliers
    edge    = signal.get("edge", "")
    regime  = signal.get("regime", "RANGING")
    tp_mult = _EDGE_TP.get(edge, _TP_MULT.get(regime, 1.0))
    sl_mult = _EDGE_SL.get(edge, _SL_MULT.get(regime, 0.8))
    trail   = _EDGE_TRAIL.get(edge, _TRAIL)
    tp_move = max(atr * tp_mult / entry, MIN_TP_PCT)
    sl_move = max(atr * sl_mult / entry, MIN_SL_PCT)

    # ── Per-symbol execution ──────────────────────────────────────────────────
    actual_entry, fill_slip = exec_order(signal, size, ob, sym)
    actual_entry = actual_entry or entry

    _positions[sym] = {
        "action":        signal["action"],
        "entry":         actual_entry,
        "size":          size,
        "tp_move":       tp_move,
        "sl_move":       sl_move,
        "trail_sl":      -sl_move,
        "trail_offset":  trail * sl_move,
        "signal":        signal,
        "ticks":         0,
        "fill_slippage": fill_slip,
    }
    print(f"    exec: slip={fill_slip:.5f}  fr={fill_rate(sym):.2f}  "
          f"ws_adj={ws_adj:.3f}  {size:.4f}@{actual_entry:.4f}")
    _regime_exposure[regime] = _regime_exposure.get(regime, 0) + 1
    _risk_guard()


def on_price(data):
    if time.time() - _last_flush[0] >= FLUSH_EVERY and BATCH:
        _flush()

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

    # ── Trailing stop ─────────────────────────────────────────────────────────
    if move > 0:
        pos["trail_sl"] = max(pos["trail_sl"], move - pos["trail_offset"])

    # ── Exit conditions ───────────────────────────────────────────────────────
    if   pos.get("force_close"):    reason = "replaced"
    elif move >= pos["tp_move"]:    reason = "TP"
    elif move <= pos["trail_sl"]:   reason = "SL" if move < 0 else "trail"
    elif pos["ticks"] >= MAX_TICKS: reason = "timeout"
    else:
        return

    profit = (move - FEE_RT) * pos["size"]
    result = "WIN" if profit > 0 else "LOSS"
    short  = sym.replace("USDT", "")
    icon   = "✅" if result == "WIN" else "❌"

    print(f"    {icon} {short} {pos['action']} "
          f"${entry:,.4f}→${curr:,.4f}  {profit:+.6f}  [{reason}]")

    trade = {
        **pos["signal"],
        "profit":        profit,
        "result":        result,
        "exit_price":    curr,
        "close_reason":  reason,
        "timestamp":     time.time(),
        "fill_slippage": pos.get("fill_slippage", 0.0),
    }

    update_metrics(pos["signal"], trade)

    # ── Calibration + edge learning feedback ──────────────────────────────────
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
    if len(BATCH) >= 20:
        _flush()

    closed_regime = pos["signal"].get("regime", "RANGING")
    _regime_exposure[closed_regime] = max(
        0, _regime_exposure.get(closed_regime, 1) - 1)
    del _positions[sym]

    # Open any pending replacement signal now that a slot freed
    if _pending_open:
        pending = _pending_open.pop(0)
        handle_signal(pending)


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
