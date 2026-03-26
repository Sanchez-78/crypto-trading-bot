"""
Trade executor with ATR-based TP/SL and trailing stop.

Risk management:
  TP  = 3.0× ATR   (RR 2:1 — breakeven WR = 33%, was 1.33:1)
  SL  = 1.5× ATR
  Timeout = 60 ticks per symbol (~6 min at 2s/tick × 3 symbols)

Trailing stop:
  At 50% of TP → SL moves to break-even (0%)
  At 80% of TP → SL locks in 40% of TP distance as minimum profit

Position sizing: confidence-scaled, capped at 10% of unit.
One open position per symbol at a time.
Firebase batch flush: every 20 trades OR every 5 minutes.
"""

from src.core.event_bus import subscribe
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time

BATCH       = []
_positions  = {}        # symbol -> position dict
_last_flush = [0.0]     # mutable so on_price can update it

TP_ATR_MULT = 3.0       # RR 2:1  (SL=1.5 → TP=3.0)
SL_ATR_MULT = 1.5
MAX_TICKS   = 60        # ~6 min per position
FLUSH_EVERY = 300       # seconds — time-based batch flush


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
        return  # one position per symbol

    entry = signal["price"]
    atr   = signal.get("atr", entry * 0.003)
    from src.services.learning_event import get_metrics as _gm
    _m   = _gm()
    _wr  = _m.get("winrate", 0.5)
    _t   = _m.get("trades", 0)
    if _t >= 20:
        # Half-Kelly: f = (WR*RR - (1-WR)) / RR, RR=2
        kelly = max(0.0, (_wr * 2 - (1 - _wr)) / 2)
        size  = min(0.10, max(0.01, kelly * 0.5 * signal["confidence"]))
    else:
        size = min(0.05, signal["confidence"] * 0.1)  # conservative during warmup

    tp_move = atr * TP_ATR_MULT / entry
    sl_move = atr * SL_ATR_MULT / entry

    _positions[sym] = {
        "action":   signal["action"],
        "entry":    entry,
        "size":     size,
        "tp_move":  tp_move,
        "sl_move":  sl_move,
        "trail_sl": -sl_move,   # current SL floor as fraction of entry move
        "signal":   signal,
        "ticks":    0,
    }


def on_price(data):
    # Time-based flush — save unsent trades every FLUSH_EVERY seconds
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
    tp = pos["tp_move"]
    if move >= tp * 0.5:
        # 50% to TP → move SL to break-even
        pos["trail_sl"] = max(pos["trail_sl"], 0.0)
    if move >= tp * 0.8:
        # 80% to TP → lock in 40% of TP distance as guaranteed profit
        pos["trail_sl"] = max(pos["trail_sl"], tp * 0.4)

    # ── Exit conditions ───────────────────────────────────────────────────────
    if move >= tp:
        reason = "TP"
    elif move <= pos["trail_sl"]:
        reason = "SL" if move < 0 else "trail"
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
        _flush()

    del _positions[sym]


subscribe("signal_created", handle_signal)
subscribe("price_tick",     on_price)
