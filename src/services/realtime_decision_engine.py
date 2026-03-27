"""
EV-only decision engine — single authoritative EV computation.

Flow:
  1. Calibrate win_prob from historical buckets; p=0/1 → 0.5; clamp [0.35, 0.65]
  2. Enforce min RR >= 2.0 (regime-aware ATR)
  3. EV = win_prob * RR - (1 - win_prob)
  4. Dynamic threshold: base 0.0, relaxes <3 trades/15min, tightens >10
  5. Always log {ev, p, decision}
  6. Auditor: size factor clamped [0.5, 1.0] — never blocks decision
"""

from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT   = {"BULL_TREND": 3.0, "BEAR_TREND": 3.0, "RANGING": 1.8, "QUIET_RANGE": 1.6}
_SL_MULT   = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.2, "QUIET_RANGE": 1.0}
MIN_TP     = 0.0050
MIN_SL     = 0.0025
MIN_RR     = 2.0
EV_BASE    = 0.0


def _calibrate(conf, history):
    """Win-rate from historical bucket.
    Invalid edges (<=0 or >=1) → 0.5. Result clamped to [0.35, 0.65]."""
    # bucket win-rate from history
    bucket = round(conf * 10) / 10
    trades = [t for t in history
              if abs(t.get("confidence", 0) - bucket) < 0.06
              and t.get("result") in ("WIN", "LOSS")]
    raw = (sum(1 for t in trades if t["result"] == "WIN") / len(trades)
           if len(trades) >= 5 else conf)

    if raw <= 0 or raw >= 1:
        return 0.5
    return max(0.35, min(0.65, raw))


def _adjust_threshold(t15):
    thr = EV_BASE
    if t15 < 3:
        thr = max(0.0, thr - 0.01)    # relax when slow
    if t15 > 10:
        thr = min(0.05, thr + 0.005)  # tighten when busy
    return thr


def evaluate_signal(signal):
    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Calibrated win_prob ────────────────────────────────────────────────────
    # Always route through _calibrate — handles empty history gracefully
    # and applies p<=0/p>=1→0.5 guard in all paths
    win_prob = _calibrate(signal["confidence"], history or [])

    # ── EV (single authoritative computation) ─────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    atr     = signal.get("atr", 0)
    price   = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 2.2) / price, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 1.3) / price, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev      = win_prob * rr - (1 - win_prob)

    # ── Dynamic threshold ─────────────────────────────────────────────────────
    t15          = trades_in_window(900)
    ev_threshold = _adjust_threshold(t15)

    # ── Auditor: scale factor clamped [0.5, 1.0] — never blocks ──────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_factor = min(1.0, max(0.5, af_raw))

    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  "
          f"thr={ev_threshold:.3f}  t15={t15}  af={auditor_factor:.2f}")

    if ev <= ev_threshold:
        track_blocked()
        print(f"    decision=SKIP  ev={ev:.4f}  p={win_prob:.4f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  size_af={auditor_factor:.2f}")
    return signal
