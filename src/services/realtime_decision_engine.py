"""
EV-only decision engine — single authoritative EV computation.

Flow:
  1. Calibrate win_prob from historical buckets; no-history → 0.5 (honest fallback)
  2. TP=1.2×ATR / SL=1.0×ATR → RR=1.2 (tighter exits, reduces timeouts)
  3. EV = win_prob * RR - (1 - win_prob)
  4. Hard threshold 0.15 — only real edge taken (ev<0.15 = noise)
     Dynamic: relax to 0.12 at t15<3, tighten to 0.18 at t15>10
  5. Always log {ev, p, decision}
  6. Auditor: size factor floor 0.7 — prevents over-suppression
"""

from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT = {"BULL_TREND": 1.2, "BEAR_TREND": 1.2, "RANGING": 1.2, "QUIET_RANGE": 1.2}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.0, "QUIET_RANGE": 1.0}
MIN_TP   = 0.0030   # 0.30% min TP (covers fees)
MIN_SL   = 0.0025   # 0.25% min SL
MIN_RR   = 1.2      # matches 1.2×ATR / 1.0×ATR
EV_BASE  = 0.15     # hard floor — ev<0.15 = statistical noise


def _calibrate(conf, history):
    """Win-rate from historical bucket.
    No history (< 5 trades) → 0.5 honest fallback (not raw conf which is miscalibrated).
    Invalid edges (<=0 or >=1) → 0.5. Result clamped to [0.4, 0.6]."""
    bucket = round(conf * 10) / 10
    trades = [t for t in history
              if abs(t.get("confidence", 0) - bucket) < 0.06
              and t.get("result") in ("WIN", "LOSS")]
    raw = (sum(1 for t in trades if t["result"] == "WIN") / len(trades)
           if len(trades) >= 5 else 0.5)   # ← 0.5, not conf (conf is uncalibrated)

    if raw <= 0 or raw >= 1:
        return 0.5
    return max(0.4, min(0.6, raw))


def _adjust_threshold(t15):
    thr = EV_BASE                              # 0.15 base
    if t15 < 3:
        thr = max(0.12, thr - 0.03)           # relax to 0.12 — avoid deadlock
    if t15 > 10:
        thr = min(0.18, thr + 0.02)           # tighten to 0.18 when busy
    return thr


def evaluate_signal(signal):
    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Calibrated win_prob ────────────────────────────────────────────────────
    win_prob = _calibrate(signal["confidence"], history or [])

    # ── EV (single authoritative computation) ─────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    atr     = signal.get("atr", 0)
    price   = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 1.2) / price, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 1.0) / price, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev      = win_prob * rr - (1 - win_prob)

    # ── Dynamic threshold ──────────────────────────────────────────────────────
    t15          = trades_in_window(900)
    ev_threshold = _adjust_threshold(t15)

    # ── Auditor: floor 0.7 — prevents ×0.3 over-suppression ──────────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_factor = min(1.0, max(0.7, af_raw))

    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  "
          f"thr={ev_threshold:.3f}  t15={t15}  af={auditor_factor:.2f}")

    if ev < ev_threshold:
        track_blocked()
        print(f"    decision=SKIP_LOW_EDGE  ev={ev:.4f}  p={win_prob:.4f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  af={auditor_factor:.2f}")
    return signal
