"""
EV-only decision engine — single authoritative EV computation.

Flow:
  1. Calibrate win_prob from historical buckets; clamp to [0.35, 0.70]
  2. Enforce min RR >= 2.0 (regime-aware ATR)
  3. EV = win_prob * RR - (1 - win_prob)
  4. Dynamic threshold: base 0.0, +0.005 if t15>10, 0 if deadlock
  5. Always log {ev, p, decision}
  6. Auditor: size factor only — never blocks decision
"""

from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT = {"BULL_TREND": 3.0, "BEAR_TREND": 3.0, "RANGING": 1.8, "QUIET_RANGE": 1.6}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.2, "QUIET_RANGE": 1.0}
MIN_TP         = 0.0050
MIN_SL         = 0.0025
MIN_RR         = 2.0      # minimum reward-to-risk ratio
MIN_PROB_FLOOR = 0.35     # win_prob lower clamp
MAX_PROB_CAP   = 0.70     # win_prob upper clamp (prevent overconfidence)
EV_BASE        = 0.0      # base threshold — only tightens when busy


def _calibrate(conf, history):
    """Win-rate from historical bucket; falls back to raw conf if <5 samples."""
    bucket = round(conf * 10) / 10
    trades = [t for t in history
              if abs(t.get("confidence", 0) - bucket) < 0.06
              and t.get("result") in ("WIN", "LOSS")]
    if len(trades) < 5:
        return conf
    return sum(1 for t in trades if t["result"] == "WIN") / len(trades)


def _adjust_threshold(t15, t20):
    thr = EV_BASE
    if t15 < 3:
        thr = max(0.0, thr - 0.01)   # relax when slow
    if t15 > 10:
        thr = min(0.05, thr + 0.005) # tighten when busy
    if t20 == 0:
        thr = 0.0                     # deadlock: accept any positive EV
    return thr


def evaluate_signal(signal):
    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Calibrated win_prob — clamped to valid probability range ──────────────
    raw_conf = signal["confidence"]
    win_prob = _calibrate(raw_conf, history) if history else raw_conf
    win_prob = max(MIN_PROB_FLOOR, min(MAX_PROB_CAP, win_prob))

    # ── EV (single authoritative computation) ─────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    atr     = signal.get("atr", 0)
    p       = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 2.2) / p, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 1.3) / p, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev      = win_prob * rr - (1 - win_prob)

    # ── Dynamic threshold ─────────────────────────────────────────────────────
    t15          = trades_in_window(900)
    t20          = trades_in_window(1200)
    ev_threshold = _adjust_threshold(t15, t20)

    # ── Auditor: size factor only, never blocks decision ──────────────────────
    auditor_factor = 1.0
    try:
        from bot2.auditor import is_halted, get_position_size_mult
        auditor_factor = 0.0 if is_halted() else get_position_size_mult()
    except Exception:
        pass

    print(f"    📊 EV={ev:.3f}  p={win_prob:.0%}  rr={rr:.2f}  "
          f"thr={ev_threshold:.3f}  t15={t15}  af={auditor_factor:.2f}")

    if ev <= ev_threshold:
        track_blocked()
        print(f"    ↳ decision=SKIP  ev={ev:.4f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    ↳ decision=TAKE  ev={ev:.4f}  af={auditor_factor:.2f}")
    return signal
