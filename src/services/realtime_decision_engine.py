"""
EV-only decision engine — stable adaptive threshold + online calibration.

Flow:
  1. Calibrate win_prob: empirical WR from online bucket tracker
     Requires 30 samples per bucket; fallback = 0.5 (honest, not raw conf)
  2. TP=1.0×ATR / SL=0.8×ATR → RR=1.25 (tighter exits, faster edge realization)
  3. EV = win_prob × RR - (1 - win_prob)
  4. EV spread guard: if last 50 EVs span < 0.05 → flat distribution = noise → skip
  5. Frequency cap: > 6 trades/15min → skip (prevents overtrading)
  6. Adaptive threshold = 75th percentile of ev_history (top 25% only)
     Cold start: 0.15 until 100 samples; floor 0.10 always
  7. calibrator.update() called from trade_executor after each close
  8. Lazy bootstrap from Firebase history on first signal
  9. Auditor factor floor 0.7 — prevents over-suppression
"""

from collections import deque
from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8, "RANGING": 0.8, "QUIET_RANGE": 0.8}
MIN_TP   = 0.0025
MIN_SL   = 0.0020
MIN_RR   = 1.25

EV_SPREAD_MIN   = 0.05    # flat distribution guard
EV_SPREAD_AFTER = 50      # evaluate spread only after N samples
MAX_TRADES_15   = 5       # frequency cap (trades per 15 min)
MAX_LOSS_STREAK = 5       # halt trading after N consecutive losses


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
        """Empirical WR for bucket; requires ≥30 samples, else 0.5."""
        b = round(p, 1)
        if b in self.buckets and self.buckets[b][1] >= 30:
            return self.buckets[b][0] / self.buckets[b][1]
        return 0.5

    def summary(self):
        return {str(b): {"wr": round(v[0] / v[1], 3), "n": v[1]}
                for b, v in sorted(self.buckets.items()) if v[1] > 0}


calibrator = Calibrator()
ev_history = deque(maxlen=200)   # ALL evaluated EVs (including skipped)
_seeded    = [False]

# ── Self-learning edge feature stats ──────────────────────────────────────────
SCORE_MIN   = 4    # minimum base score (out of 7)
W_SCORE_MIN = 2.5  # minimum weighted score (sum of empirical WRs)

edge_stats = {}    # feature_name -> [wins, total]


def update_edge_stats(features, outcome):
    """Update per-feature win/loss counts. Called after every trade close."""
    for k, v in features.items():
        if isinstance(v, bool) and v:
            if k not in edge_stats:
                edge_stats[k] = [0, 0]
            edge_stats[k][1] += 1
            if outcome == 1:
                edge_stats[k][0] += 1


def feature_weight(k):
    """Empirical WR for feature k. Requires ≥20 samples, else 0.5."""
    if k in edge_stats and edge_stats[k][1] >= 20:
        return edge_stats[k][0] / edge_stats[k][1]
    return 0.5


def weighted_score(features):
    """Sum of empirical WR weights for all active (True) boolean features."""
    return sum(feature_weight(k) for k, v in features.items()
               if isinstance(v, bool) and v)


def update_calibrator(p, outcome):
    """Called by trade_executor after every trade close."""
    calibrator.update(p, outcome)


def _seed_calibrator(trades):
    """One-time bootstrap: replay closed trades into calibrator + edge_stats."""
    for t in trades:
        p        = float(t.get("confidence", 0.5))
        result   = t.get("result")
        features = t.get("features", {})
        if result in ("WIN", "LOSS"):
            outcome = 1 if result == "WIN" else 0
            calibrator.update(p, outcome)
            if features:
                update_edge_stats(features, outcome)
    total = sum(v[1] for v in calibrator.buckets.values())
    edge_n = sum(v[1] for v in edge_stats.values())
    print(f"🎯 Calibrator seeded: {total} samples  buckets={calibrator.summary()}")
    print(f"🧠 Edge stats seeded: {edge_n} feature observations  "
          f"keys={list(edge_stats.keys())}")


def get_ev_threshold():
    """
    Adaptive threshold = 75th percentile of ev_history (top 25% only).
    Cold start: 0.15 until 100 samples; floor 0.10 always.
    """
    if len(ev_history) < 100:
        return 0.25
    s   = sorted(ev_history)
    q75 = s[int(len(s) * 0.75)]
    return max(0.15, q75)


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
    tp_move = max(atr * _TP_MULT.get(regime, 1.0) / price, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 0.8) / price, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev      = win_prob * rr - (1 - win_prob)

    ev_history.append(ev)
    ev_threshold = get_ev_threshold()

    # ── Loss streak guard: halt after N consecutive losses ────────────────────
    from src.services.learning_event import METRICS as _M
    streak = _M.get("loss_streak", 0)
    if streak >= MAX_LOSS_STREAK:
        track_blocked()
        print(f"    decision=SKIP_STREAK  streak={streak}>={MAX_LOSS_STREAK}")
        return None

    # ── EV spread guard: flat distribution = noise, not edge ──────────────────
    if len(ev_history) >= EV_SPREAD_AFTER:
        spread = max(ev_history) - min(ev_history)
        if spread < EV_SPREAD_MIN:
            track_blocked()
            print(f"    decision=SKIP_FLAT  spread={spread:.4f}<{EV_SPREAD_MIN}")
            return None

    # ── Frequency cap ─────────────────────────────────────────────────────────
    t15 = trades_in_window(900)
    if t15 > MAX_TRADES_15:
        track_blocked()
        print(f"    decision=SKIP_FREQ  t15={t15}>{MAX_TRADES_15}")
        return None

    # ── Auditor: floor 0.7 ────────────────────────────────────────────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_factor = min(1.0, max(0.7, af_raw))

    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  "
          f"thr={ev_threshold:.3f}[q75/{len(ev_history)}]  "
          f"t15={t15}  spread={max(ev_history)-min(ev_history):.3f}  af={auditor_factor:.2f}")

    if ev < ev_threshold:
        track_blocked()
        print(f"    decision=SKIP_Q  ev={ev:.4f}  thr={ev_threshold:.4f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  af={auditor_factor:.2f}")
    return signal
