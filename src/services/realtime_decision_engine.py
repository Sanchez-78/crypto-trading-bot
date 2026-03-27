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
SCORE_MIN    = 4      # minimum base score (out of 7)
W_SCORE_MIN  = 0.50   # cold-start floor for weighted avg score
DECAY        = 0.98   # exponential decay applied to counts each update
score_history = deque(maxlen=200)   # w_scores of all evaluated winning-dir setups

edge_stats  = {}   # (feature_name, regime) -> [eff_wins, eff_total]  (decayed)
combo_stats = {}   # (combo_tuple, regime)  -> [wins, total]  (no decay, Laplace gate)
combo_usage = {}   # combo_tuple -> int  (session use count; resets on restart)


def _std(lst):
    """Population std without numpy dependency."""
    n = len(lst)
    if n < 2:
        return 0.0
    m = sum(lst) / n
    return (sum((x - m) ** 2 for x in lst) / n) ** 0.5


def update_edge_stats(features, outcome, regime="RANGING"):
    """
    Update regime-split feature stats (decayed) AND regime-split combo stats.
    Regime split prevents bull-market weights polluting bear-market decisions.
    """
    active = tuple(sorted(k for k, v in features.items()
                          if isinstance(v, bool) and v))
    # Combo update — no decay (needs stable counts for Laplace gate)
    if active:
        key = (active, regime)
        if key not in combo_stats:
            combo_stats[key] = [0, 0]
        combo_stats[key][1] += 1
        if outcome == 1:
            combo_stats[key][0] += 1

    # Individual feature update with exponential decay
    for k, v in features.items():
        if isinstance(v, bool) and v:
            fk = (k, regime)
            if fk not in edge_stats:
                edge_stats[fk] = [0.0, 0.0]
            edge_stats[fk][0] *= DECAY
            edge_stats[fk][1] *= DECAY
            edge_stats[fk][1] += 1.0
            if outcome == 1:
                edge_stats[fk][0] += 1.0


def feature_weight(k, regime="RANGING"):
    """Laplace-smoothed regime-aware WR: (wins+5)/(total+10). Prior=0.5."""
    fk = (k, regime)
    if fk in edge_stats:
        w, t = edge_stats[fk]
        return (w + 5.0) / (t + 10.0)
    return 0.5


def combo_weight(features, regime="RANGING"):
    """
    Laplace-smoothed WR of exact feature combo in this regime.
    Requires ≥ 30 observations; else None.
    """
    active = tuple(sorted(k for k, v in features.items()
                          if isinstance(v, bool) and v))
    key = (active, regime)
    if key in combo_stats and combo_stats[key][1] >= 30:
        w, t = combo_stats[key]
        return (w + 5.0) / (t + 10.0)
    return None


def allow_combo(combo):
    """
    Limit each combo to 3 uses per session — forces pattern diversity.
    Resets on restart (in-memory). Returns True if allowed, increments count.
    """
    if combo_usage.get(combo, 0) >= 3:
        return False
    combo_usage[combo] = combo_usage.get(combo, 0) + 1
    return True


def weighted_score(features, regime="RANGING"):
    """
    Regime-aware average Laplace weight. Bad features (WR<0.4) penalised -0.2.
    Blended 50/50 with regime-split combo WR if ≥30 combo observations.
    """
    weights = []
    for k, v in features.items():
        if isinstance(v, bool) and v:
            w = feature_weight(k, regime)
            if w < 0.4:
                w -= 0.2
            weights.append(w)
    if not weights:
        return 0.0
    base = sum(weights) / len(weights)
    cw   = combo_weight(features, regime)
    return (base + cw) / 2.0 if cw is not None else base


def get_ws_threshold():
    """
    Adaptive w_score gate: 75th percentile of score_history (top 25% only).
    Cold-start floor W_SCORE_MIN until 50 samples collected.
    Hard floor 0.45 — never trades sub-random edge.
    """
    if len(score_history) < 50:
        return W_SCORE_MIN
    s   = sorted(score_history)
    q75 = s[int(len(s) * 0.75)]
    return max(0.45, q75)


def update_calibrator(p, outcome):
    """Called by trade_executor after every trade close."""
    calibrator.update(p, outcome)


def _seed_calibrator(trades):
    """One-time bootstrap: replay closed trades into calibrator + edge_stats."""
    for t in trades:
        p        = float(t.get("confidence", 0.5))
        result   = t.get("result")
        features = t.get("features", {})
        regime   = t.get("regime", "RANGING")
        if result in ("WIN", "LOSS"):
            outcome = 1 if result == "WIN" else 0
            calibrator.update(p, outcome)
            if features:
                update_edge_stats(features, outcome, regime)
    total   = sum(v[1] for v in calibrator.buckets.values())
    edge_n  = sum(v[1] for v in edge_stats.values())
    combo_n = sum(v[1] for v in combo_stats.values())
    print(f"🎯 Calibrator seeded: {total} samples  buckets={calibrator.summary()}")
    print(f"🧠 Edge stats seeded: {edge_n:.0f} feature obs  "
          f"{combo_n} combo obs  keys={list(edge_stats.keys())}")


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
