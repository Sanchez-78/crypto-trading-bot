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
import time

BATCH       = []
_positions  = {}
_last_flush = [0.0]

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


def get_open_positions():
    return dict(_positions)


def _flush():
    if BATCH:
        save_batch(BATCH)
        BATCH.clear()
    _last_flush[0] = time.time()


def handle_signal(signal):
    sym = signal["symbol"]
    if sym in _positions:
        return

    entry = signal["price"]
    atr   = signal.get("atr", entry * 0.003)

    # Position sizing: EV-scaled, auditor floor 0.7, strong-EV boost
    import math
    from src.services.learning_event           import get_metrics as _gm
    from src.services.realtime_decision_engine import (
        get_ev_threshold, get_ws_threshold, equity_guard)
    _t      = _gm().get("trades", 0)
    ev      = signal.get("ev", 0.05)
    ws      = signal.get("ws", 0.5)
    explore = signal.get("explore", False)
    af      = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))
    base    = 0.05 if _t >= 20 else 0.025
    thr     = get_ev_threshold()
    ws_thr  = get_ws_threshold()
    # sqrt sizing: less aggressive than linear; caps overbetting at high ws
    ws_ratio = (ws / ws_thr) if ws_thr > 0 else 1.0
    size     = base * math.sqrt(min(ws_ratio, 2.25)) * af  # sqrt(2.25)=1.5 max
    if ev > thr * 1.5:
        size *= 1.5                          # strong EV boost
    if explore:
        size *= 0.3                          # exploration trades: small position
    size *= equity_guard()                   # halve size if drawdown > 10%
    size  = max(0.005, size)

    # TP/SL: edge-specific ATR multipliers
    edge    = signal.get("edge", "")
    regime  = signal.get("regime", "RANGING")
    tp_mult = _EDGE_TP.get(edge, _TP_MULT.get(regime, 1.0))
    sl_mult = _EDGE_SL.get(edge, _SL_MULT.get(regime, 0.8))
    trail   = _EDGE_TRAIL.get(edge, _TRAIL)
    tp_move = max(atr * tp_mult / entry, MIN_TP_PCT)
    sl_move = max(atr * sl_mult / entry, MIN_SL_PCT)

    _positions[sym] = {
        "action":       signal["action"],
        "entry":        entry,
        "size":         size,
        "tp_move":      tp_move,
        "sl_move":      sl_move,
        "trail_sl":     -sl_move,
        "trail_offset": trail * sl_move,
        "signal":       signal,
        "ticks":        0,
    }


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
    if   move >= pos["tp_move"]:   reason = "TP"
    elif move <= pos["trail_sl"]:  reason = "SL" if move < 0 else "trail"
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
        "profit":       profit,
        "result":       result,
        "exit_price":   curr,
        "close_reason": reason,
        "timestamp":    time.time(),
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

    del _positions[sym]


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
