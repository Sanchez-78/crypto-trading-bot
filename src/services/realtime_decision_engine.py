"""
EV-only decision engine — online calibration + adaptive threshold.

Flow:
  1. Calibrate win_prob: empirical WR from online bucket tracker
     Requires 20 samples per bucket; fallback = 0.5 (honest, not raw conf)
  2. TP=1.2×ATR / SL=1.0×ATR → RR=1.2 (tighter exits, fewer timeouts)
  3. EV = win_prob × RR - (1 - win_prob)
  4. Adaptive threshold = 75th percentile of ev_history (top 25% only)
     Falls back to 0.10 until 50 EV samples collected
  5. calibrator.update() called from trade_executor after each close
  6. Lazy bootstrap from Firebase history on first signal
  7. Auditor factor floor 0.7 — prevents over-suppression
"""

from collections import deque
from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT = {"BULL_TREND": 1.2, "BEAR_TREND": 1.2, "RANGING": 1.2, "QUIET_RANGE": 1.2}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.0, "QUIET_RANGE": 1.0}
MIN_TP   = 0.0030
MIN_SL   = 0.0025
MIN_RR   = 1.2


class Calibrator:
    """Online win-rate tracker per confidence bucket (0.1 step bins)."""

    def __init__(self):
        self.buckets = {}   # bin -> [wins, total]

    def update(self, p, outcome):
        """outcome: 1=WIN  0=LOSS"""
        b = round(p, 1)
        if b not in self.buckets:
            self.buckets[b] = [0, 0]
        self.buckets[b][1] += 1
        if outcome == 1:
            self.buckets[b][0] += 1

    def get(self, p):
        """Empirical WR for bucket; requires ≥20 samples, else 0.5."""
        b = round(p, 1)
        if b in self.buckets and self.buckets[b][1] >= 20:
            return self.buckets[b][0] / self.buckets[b][1]
        return 0.5

    def summary(self):
        return {str(b): {"wr": round(v[0] / v[1], 3), "n": v[1]}
                for b, v in sorted(self.buckets.items()) if v[1] > 0}


calibrator = Calibrator()
ev_history = deque(maxlen=200)   # ALL evaluated EVs (including skipped)
_seeded    = [False]


def update_calibrator(p, outcome):
    """Called by trade_executor after every trade close."""
    calibrator.update(p, outcome)


def _seed_calibrator(trades):
    """One-time bootstrap: replay closed trades into calibrator."""
    for t in trades:
        p      = float(t.get("confidence", 0.5))
        result = t.get("result")
        if result in ("WIN", "LOSS"):
            calibrator.update(p, 1 if result == "WIN" else 0)
    total = sum(v[1] for v in calibrator.buckets.values())
    print(f"🎯 Calibrator seeded: {total} samples  "
          f"buckets={calibrator.summary()}")


def get_ev_threshold():
    """
    Adaptive threshold = 75th percentile of recent EVs (top 25% only).
    Static fallback 0.10 until 50 samples collected.
    Hard floor 0.05 — never drops below fees+slippage break-even.
    """
    if len(ev_history) < 50:
        return 0.10
    s = sorted(ev_history)
    q75 = s[int(len(s) * 0.75)]
    return max(0.05, q75)


def evaluate_signal(signal):
    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Lazy one-time bootstrap ────────────────────────────────────────────────
    if not _seeded[0]:
        _seed_calibrator(history or [])
        _seeded[0] = True

    # ── Calibrated win_prob ────────────────────────────────────────────────────
    win_prob = calibrator.get(signal["confidence"])

    # ── EV (single authoritative computation) ─────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    atr     = signal.get("atr", 0)
    price   = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 1.2) / price, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 1.0) / price, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev      = win_prob * rr - (1 - win_prob)

    # ── Adaptive threshold (top 25% EV distribution) ──────────────────────────
    ev_history.append(ev)
    ev_threshold = get_ev_threshold()

    # ── Auditor: floor 0.7 ────────────────────────────────────────────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_factor = min(1.0, max(0.7, af_raw))

    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  "
          f"thr={ev_threshold:.3f}[q75/{len(ev_history)}]  af={auditor_factor:.2f}")

    if ev < ev_threshold:
        track_blocked()
        print(f"    decision=SKIP_Q  ev={ev:.4f}  thr={ev_threshold:.4f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  af={auditor_factor:.2f}")
    return signal
