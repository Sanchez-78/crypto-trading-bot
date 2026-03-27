"""
EV-only signal filter.

Flow:
  1. Drawdown halt check (auditor)
  2. Calibrate win_prob from historical confidence buckets (fallback: raw conf)
  3. EV = win_prob * RR - (1 - win_prob)  with regime-aware RR
  4. Dynamic threshold: 0.02 base, -0.01 if <3 trades/15min, 0 if deadlock
  5. Pass if EV > threshold — only gate allowed
"""

from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime

_TP_MULT = {"BULL_TREND": 3.0, "BEAR_TREND": 3.0, "RANGING": 1.8, "QUIET_RANGE": 1.6}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.2, "QUIET_RANGE": 1.0}
MIN_TP   = 0.0050
MIN_SL   = 0.0025


def _calibrate(conf, history):
    """Calibrated win probability from historical confidence buckets.
    Returns raw conf if fewer than 5 trades in the bucket."""
    bucket = round(conf * 10) / 10
    trades = [t for t in history
              if abs(t.get("confidence", 0) - bucket) < 0.06
              and t.get("result") in ("WIN", "LOSS")]
    if len(trades) < 5:
        return conf
    return sum(1 for t in trades if t["result"] == "WIN") / len(trades)


def evaluate_signal(signal):
    # ── Drawdown halt ──────────────────────────────────────────────────────────
    try:
        from bot2.auditor import is_halted
        if is_halted():
            track_blocked()
            return None
    except Exception:
        pass

    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Calibrated win probability ─────────────────────────────────────────────
    win_prob = _calibrate(signal["confidence"], history) if history else signal["confidence"]

    # ── EV = win_prob * RR - (1 - win_prob) ───────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    atr     = signal.get("atr", 0)
    p       = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 2.2) / p, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 1.3) / p, MIN_SL)
    rr      = tp_move / sl_move
    ev      = win_prob * rr - (1 - win_prob)

    # ── Dynamic EV threshold ───────────────────────────────────────────────────
    from src.services.learning_event import trades_in_window
    t15          = trades_in_window(900)
    ev_threshold = 0.02
    if t15 < 3:
        ev_threshold = max(0.01, ev_threshold - 0.01)
    if t15 == 0:
        ev_threshold = 0.0   # deadlock guard: accept any positive EV
    if t15 > 10:
        ev_threshold = min(0.05, ev_threshold + 0.005)  # tighten when active

    print(f"    📊 EV={ev:.3f}  p={win_prob:.0%}  rr={rr:.2f}  thr={ev_threshold:.3f}  t15={t15}")

    if ev <= ev_threshold:
        track_blocked()
        return None

    signal["confidence"] = round(min(win_prob, 1.0), 4)
    signal["ev"]         = round(ev, 4)
    return signal
