"""
Trade executor with ATR-based TP/SL and trailing stop.

Risk management:
  TP    = 1.2× ATR   minimum 0.30% of entry price   (closer = fewer timeouts)
  SL    = 1.0× ATR   minimum 0.25% of entry price
  RR    = 1.2:1       breakeven WR ≈ 46%
  Trail = 0.5× ATR   trailing offset once in profit  (captures momentum)
  Timeout = 60 ticks per symbol (~6 min at 2s/tick × 3 symbols)

Position sizing:
  ≥ 20 trades: base 5% × EV-scaled × auditor_factor (floor 0.7)
  < 20 trades: base 2.5% (conservative while learning)
  Strong edge: ev > 0.30 → size × 2

Firebase batch flush: every 20 trades OR every 5 minutes.
"""

from src.core.event_bus          import subscribe_once
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time

BATCH       = []
_positions  = {}
_last_flush = [0.0]

FEE_RT      = 0.0020    # 0.20% round-trip Binance taker fees
MIN_TP_PCT  = 0.0030    # 0.30% min TP (covers fees + net)
MIN_SL_PCT  = 0.0025    # 0.25% min SL
MAX_TICKS   = 60
FLUSH_EVERY = 60

# Flat TP/SL: 1.2×ATR / 1.0×ATR — matches realtime_decision_engine
_TP_MULT = {"BULL_TREND": 1.2, "BEAR_TREND": 1.2,
            "RANGING":    1.2, "QUIET_RANGE": 1.2}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_TRAIL   = 0.5   # trailing offset = 0.5 × sl_move


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

    # Position sizing: EV-based, auditor factor floor 0.7
    from src.services.learning_event import get_metrics as _gm
    _t   = _gm().get("trades", 0)
    ev   = signal.get("ev", 0.05)
    af   = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))
    base = 0.05 if _t >= 20 else 0.025
    size = base * min(3.0, max(0.5, ev * 5)) * af
    if ev > 0.30:
        size *= 2.0                          # strong edge boost (ev>0.30 = real signal)
    size = max(0.005, size)

    # TP/SL: flat ATR-based with fee-adjusted minimums
    regime  = signal.get("regime", "RANGING")
    tp_mult = _TP_MULT.get(regime, 1.2)
    sl_mult = _SL_MULT.get(regime, 1.0)
    tp_move = max(atr * tp_mult / entry, MIN_TP_PCT)
    sl_move = max(atr * sl_mult / entry, MIN_SL_PCT)

    _positions[sym] = {
        "action":       signal["action"],
        "entry":        entry,
        "size":         size,
        "tp_move":      tp_move,
        "sl_move":      sl_move,
        "trail_sl":     -sl_move,            # starts as hard SL
        "trail_offset": _TRAIL * sl_move,    # 0.5×ATR trailing buffer
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

    # ── Trailing stop: tighten once in profit ─────────────────────────────────
    if move > 0:
        pos["trail_sl"] = max(pos["trail_sl"], move - pos["trail_offset"])

    # ── Exit conditions ───────────────────────────────────────────────────────
    if   move >= pos["tp_move"]:           reason = "TP"
    elif move <= pos["trail_sl"]:          reason = "SL" if move < 0 else "trail"
    elif pos["ticks"] >= MAX_TICKS:        reason = "timeout"
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

    from src.services.firebase_client import save_last_trade
    save_last_trade(trade)

    BATCH.append(trade)
    if len(BATCH) >= 20:
        _flush()

    del _positions[sym]


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
