"""
Trade executor with ATR-based Take Profit / Stop Loss.

Risk management (research-backed):
  TP = 2.0× ATR  (target)
  SL = 1.5× ATR  (stop)   → RR ≈ 1.33:1
  Timeout = 20 ticks per symbol (~2 min at 6s/tick)

Position sizing: confidence-scaled, capped at 10% of unit.
One open position per symbol at a time.
"""

from src.core.event_bus import subscribe
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time

BATCH      = []
_positions = {}  # symbol -> position dict

TP_ATR_MULT = 2.0
SL_ATR_MULT = 1.5
MAX_TICKS   = 20


def get_open_positions():
    return dict(_positions)


def handle_signal(signal):
    sym = signal["symbol"]
    if sym in _positions:
        return  # one position per symbol

    entry = signal["price"]
    atr   = signal.get("atr", entry * 0.003)
    size  = min(0.1, signal["confidence"] * 0.2)

    tp_move = atr * TP_ATR_MULT / entry
    sl_move = atr * SL_ATR_MULT / entry

    _positions[sym] = {
        "action":  signal["action"],
        "entry":   entry,
        "size":    size,
        "tp_move": tp_move,
        "sl_move": sl_move,
        "signal":  signal,
        "ticks":   0,
    }


def on_price(data):
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

    if move >= pos["tp_move"]:
        reason = "TP"
    elif move <= -pos["sl_move"]:
        reason = "SL"
    elif pos["ticks"] >= MAX_TICKS:
        reason = "timeout"
    else:
        return

    profit = move * pos["size"]
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

    BATCH.append(trade)
    if len(BATCH) >= 20:
        save_batch(BATCH)
        BATCH.clear()

    del _positions[sym]


subscribe("signal_created", handle_signal)
subscribe("price_tick",     on_price)
