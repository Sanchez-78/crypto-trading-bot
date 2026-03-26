"""
Trade executor with ATR-based TP/SL and trailing stop.

Risk management:
  TP  = 2.2× ATR   minimum 0.30% of entry price
  SL  = 1.3× ATR   minimum 0.15% of entry price
  RR  ≈ 1.7:1       breakeven WR ≈ 37%
  Timeout = 60 ticks per symbol (~6 min at 2s/tick × 3 symbols)

Trailing stop:
  At 50% of TP → SL moves to break-even (0%)
  At 80% of TP → SL locks in 40% of TP distance as guaranteed profit

Position sizing:
  ≥ 20 trades: half-Kelly × confidence × auditor_size_mult
  < 20 trades: conservative 5% × confidence

Firebase batch flush: every 20 trades OR every 5 minutes.
"""

from src.core.event_bus          import subscribe
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time

BATCH       = []
_positions  = {}
_last_flush = [0.0]

TP_ATR_MULT = 2.2       # was 3.0
SL_ATR_MULT = 1.3       # was 1.5
MIN_SL_PCT  = 0.0015    # 0.15% minimum SL
MIN_TP_PCT  = 0.0030    # 0.30% minimum TP
MAX_TICKS   = 60
FLUSH_EVERY = 300


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

    # Position sizing
    from src.services.learning_event import get_metrics as _gm
    _m  = _gm()
    _wr = _m.get("winrate", 0.5)
    _t  = _m.get("trades",  0)

    try:
        from bot2.auditor import get_position_size_mult
        sz_mult = get_position_size_mult()
    except Exception:
        sz_mult = 1.0

    if _t >= 20:
        kelly = max(0.0, (_wr * 2 - (1 - _wr)) / 2)
        size  = min(0.10, max(0.01, kelly * 0.5 * signal["confidence"])) * sz_mult
    else:
        size = min(0.05, signal["confidence"] * 0.1) * sz_mult

    size = max(0.005, size)  # absolute floor

    # TP/SL: ATR-based with minimum absolute values
    tp_move = max(atr * TP_ATR_MULT / entry, MIN_TP_PCT)
    sl_move = max(atr * SL_ATR_MULT / entry, MIN_SL_PCT)

    _positions[sym] = {
        "action":   signal["action"],
        "entry":    entry,
        "size":     size,
        "tp_move":  tp_move,
        "sl_move":  sl_move,
        "trail_sl": -sl_move,
        "signal":   signal,
        "ticks":    0,
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
    tp = pos["tp_move"]
    if move >= tp * 0.5:
        pos["trail_sl"] = max(pos["trail_sl"], 0.0)
    if move >= tp * 0.8:
        pos["trail_sl"] = max(pos["trail_sl"], tp * 0.4)

    # ── Exit conditions ───────────────────────────────────────────────────────
    if   move >= tp:              reason = "TP"
    elif move <= pos["trail_sl"]: reason = "SL" if move < 0 else "trail"
    elif pos["ticks"] >= MAX_TICKS: reason = "timeout"
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

    from src.services.firebase_client import save_last_trade
    save_last_trade(trade)

    BATCH.append(trade)
    if len(BATCH) >= 20:
        _flush()

    del _positions[sym]


subscribe("signal_created", handle_signal)
subscribe("price_tick",     on_price)
