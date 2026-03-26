from src.core.event_bus import subscribe
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time

BATCH = []

# Open positions: symbol -> position dict
_positions = {}

TAKE_PROFIT = 0.005  # close at +0.5% move
STOP_LOSS   = 0.003  # close at -0.3% move
MAX_TICKS   = 15     # close after 15 price ticks (~30s) regardless


def handle_signal(signal):
    sym = signal["symbol"]

    # Only one open position per symbol at a time
    if sym in _positions:
        return

    size = min(0.1, signal["confidence"] * 0.2)

    _positions[sym] = {
        "action":      signal["action"],
        "entry_price": signal["price"],
        "size":        size,
        "signal":      signal,
        "ticks":       0,
    }


def on_price(data):
    sym = data["symbol"]
    if sym not in _positions:
        return

    pos = _positions[sym]
    pos["ticks"] += 1
    current = data["price"]
    entry   = pos["entry_price"]

    move = (current - entry) / entry
    if pos["action"] == "SELL":
        move *= -1   # SELL profits when price falls

    profit = move * pos["size"]

    # Determine if position should be closed
    if move >= TAKE_PROFIT:
        reason = "TP"
    elif move <= -STOP_LOSS:
        reason = "SL"
    elif pos["ticks"] >= MAX_TICKS:
        reason = "timeout"
    else:
        return  # keep position open

    result = "WIN" if profit > 0 else "LOSS"
    short  = sym.replace("USDT", "")
    icon   = "✅" if result == "WIN" else "❌"
    print(f"    {icon} {short} {pos['action']} ${entry:,.4f}→${current:,.4f}  {profit:+.6f}  [{reason}]")

    trade = {
        **pos["signal"],
        "profit":       profit,
        "result":       result,
        "exit_price":   current,
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
subscribe("price_tick",    on_price)
