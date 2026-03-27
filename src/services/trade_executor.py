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
MIN_TP_PCT  = 0.0030    # 0.30% min TP
MIN_SL_PCT  = 0.0025    # 0.25% min SL
MAX_TICKS   = 60
FLUSH_EVERY = 60

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

    # Position sizing: EV-scaled, auditor floor 0.7, strong-EV boost
    from src.services.learning_event      import get_metrics as _gm
    from src.services.realtime_decision_engine import get_ev_threshold
    _t   = _gm().get("trades", 0)
    ev   = signal.get("ev", 0.05)
    af   = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))
    base = 0.05 if _t >= 20 else 0.025
    size = base * min(3.0, max(0.5, ev * 6)) * af
    if ev > get_ev_threshold() * 1.5:
        size *= 1.5                          # strong-edge boost
    size = max(0.005, size)

    # TP/SL: flat ATR-based
    regime  = signal.get("regime", "RANGING")
    tp_move = max(atr * _TP_MULT.get(regime, 1.2) / entry, MIN_TP_PCT)
    sl_move = max(atr * _SL_MULT.get(regime, 1.0) / entry, MIN_SL_PCT)

    _positions[sym] = {
        "action":       signal["action"],
        "entry":        entry,
        "size":         size,
        "tp_move":      tp_move,
        "sl_move":      sl_move,
        "trail_sl":     -sl_move,
        "trail_offset": _TRAIL * sl_move,
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

    # ── Calibration feedback: update empirical WR bucket ──────────────────────
    try:
        from src.services.realtime_decision_engine import update_calibrator
        p = float(pos["signal"].get("confidence", 0.5))
        update_calibrator(p, 1 if result == "WIN" else 0)
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
