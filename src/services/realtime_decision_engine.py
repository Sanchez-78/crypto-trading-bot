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
import ast
import numpy as np
from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window

_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0, "RANGING": 1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8, "RANGING": 0.8, "QUIET_RANGE": 0.8}
MIN_TP   = 0.0025
MIN_SL   = 0.0020
MIN_RR   = 1.25

EV_SPREAD_MIN   = 0.02    # flat distribution guard — lowered 0.05→0.02:
                          # exploration prior ev=0.03 (n<10 pairs) + STO ev=0.07
                          # gives spread=0.04 < 0.05 → SKIP_FLAT fired and halted
                          # trading for 1+ hour. Once ADA/BTC reach n=10 their
                          # negative EVs will push spread to 1.0+ permanently.
EV_SPREAD_AFTER = 50      # evaluate spread only after N samples
MAX_TRADES_15   = 15      # frequency cap raised 5→8→15: STO (71% WR, EV:+0.123)
                          # is the only converged pair and trades ~11/15min; capping
                          # at 8 was throttling the best edge in the system; 15 allows
                          # proven pairs to trade freely while still blocking runaway
MAX_LOSS_STREAK = 15      # halt trading after N consecutive losses (raised: 5 was too tight)


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
        """
        Empirical WR for bucket; requires ≥30 samples, else 0.5.
        Floor at 0.35: a 0% WR from 33 samples is statistically uncertain
        and would poison EV to −1.0, permanently blocking learning.
        Post-bootstrap this floor decays naturally as better data accumulates.
        """
        b = round(p, 1)
        if b in self.buckets and self.buckets[b][1] >= 30:
            wr = self.buckets[b][0] / self.buckets[b][1]
            # Floor lowered 0.35→0.10: the old floor mapped a real 2% WR to 35%,
            # producing EV = 0.35×1.25 − 0.65 = −0.21, which still passed the
            # −0.30 learning-mode gate and hid the actual crisis from the system.
            # 0.10 floor: EV = 0.10×1.25 − 0.90 = −0.775, correctly flagged as
            # very poor edge so get_ev_threshold() crisis path fires.
            return max(wr, 0.10)
        return 0.5

    def summary(self):
        return {str(b): {"wr": round(v[0] / v[1], 3), "n": v[1]}
                for b, v in sorted(self.buckets.items()) if v[1] > 0}


calibrator = Calibrator()
ev_history = deque(maxlen=200)   # ALL evaluated EVs (including skipped)
_seeded    = [False]

# ── Self-learning edge feature stats ──────────────────────────────────────────
SCORE_MIN    = 3      # minimum base score (out of 7)
                      # was 4: BTC/ADA consistently score 3/7 in trending markets
                      # (confirmed: 540 ticks generated, 1 po_filtru in 8-min session —
                      #  all blocked at Gate 2 because only ETH scored 4/7 at boot).
                      # 3 still filters random noise; Gate 5 (w_score) is the quality gate.
W_SCORE_MIN  = 0.50   # cold-start floor for weighted avg score
DECAY        = 0.98   # exponential decay applied to counts each update
score_history = deque(maxlen=200)   # w_scores of all evaluated winning-dir setups

edge_stats     = {}   # (feature_name, regime) -> [eff_wins, eff_total]  (decayed)
combo_stats    = {}   # (combo_tuple, regime)  -> [eff_wins, eff_total]  (decayed)
combo_usage    = {}   # combo_tuple -> int  (session use count; resets on restart)
archive_combos = {}   # pruned combos kept for inspection (not used in decisions)

# V6 L4: entry_timing — last 3 prices per symbol for micro-momentum check
_price_history: dict = {}   # sym → deque(maxlen=3)



def prune_combos():
    """
    Soft-prune: move 50 worst-WR combos to archive when dict exceeds 200.
    Archived combos are preserved for inspection but excluded from decisions.
    """
    if len(combo_stats) <= 200:
        return
    worst = sorted(combo_stats.items(),
                   key=lambda x: x[1][0] / max(x[1][1], 1.0))[:50]
    for k, v in worst:
        archive_combos[k] = v
        del combo_stats[k]


def epsilon():
    """
    Decaying exploration rate: starts 10%, floors at 2%.
    Decay driven by total trade count — less exploration as system matures.
    """
    import math
    try:
        from src.services.learning_event import METRICS
        tc = METRICS.get("trades", 0)
    except Exception:
        tc = 0
    return max(0.02, 0.10 * math.exp(-tc / 1000.0))


def equity_guard():
    """Return 0.5 if drawdown > 10%, else 1.0. Halves size during drawdown."""
    try:
        from src.services.learning_event import METRICS
        dd = METRICS.get("drawdown", 0.0)
        eq = METRICS.get("equity_peak", 1.0) or 1.0
        dd_pct = dd / eq
        if dd_pct > 0.10:
            return 0.5
    except Exception:
        pass
    return 1.0


def update_edge_stats(features, outcome, regime="RANGING"):
    """
    Update regime-split feature stats AND combo stats, both with decay.
    Prunes combo dict if it exceeds 200 entries (keeps highest-WR combos).
    """
    active = tuple(sorted(k for k, v in features.items()
                          if isinstance(v, bool) and v))
    # Combo update with decay
    if active:
        key = (active, regime)
        if key not in combo_stats:
            combo_stats[key] = [0.0, 0.0]
        combo_stats[key][0] *= DECAY
        combo_stats[key][1] *= DECAY
        combo_stats[key][1] += 1.0
        if outcome == 1:
            combo_stats[key][0] += 1.0
        prune_combos()

    # Individual feature update with decay
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
    Limit each combo to 200 uses per session.
    Raised 20→200: with proper debounce (1 call/30s per symbol), 3 symbols
    exhaust 20 uses in 200s (~3 min). Confirmed in log: po_filtru=1 for 18 min
    because even after debounce fix, combo_usage hit 20 within first 3 minutes.
    200 uses = ~100 min at 30s debounce, sufficient for any trading session.
    """
    if combo_usage.get(combo, 0) >= 200:
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


# ── Persistent model state ────────────────────────────────────────────────────
# Save after every N calibrator updates (≈ N trade closes).
# One Firestore write per save; at ~40 trades/day this costs ~8 writes/day.

_STATE_SAVE_EVERY = 5
_state_dirty      = [0]


def _save_full_state():
    """
    Persist calibrator buckets + EV/score histories + bayes/bandit stats
    + edge_stats + combo_stats + lm_feature_stats.

    edge_stats / combo_stats / lm_feature_stats are the richest learning
    signal in the system (feature WR per regime, combo WR per regime) but
    were not persisted — lost on every restart, cold-starting the weighted_score
    gate after every GitHub Actions run. Adding them here means feature learning
    survives restarts just like calibrator and bayes do.
    """
    try:
        import time as _t
        from src.services.firebase_client import save_model_state
        from src.services.execution       import bayes_stats, bandit_stats
        from src.services.learning_monitor import lm_feature_stats

        rde = {
            "calibrator":    {str(k): list(v) for k, v in calibrator.buckets.items()},
            "ev_history":    list(ev_history)[-200:],
            "score_history": list(score_history)[-200:],
            # Feature WR per regime — drives weighted_score() gate
            "edge_stats":    {f"{k[0]}|{k[1]}": list(v) for k, v in edge_stats.items()},
            # Combo WR per regime — drives combo_weight() blending
            "combo_stats":   {f"{str(k[0])}|{k[1]}": list(v) for k, v in combo_stats.items()},
            # Per-feature fractional attribution — drives lm_feature_quality()
            "lm_feature_stats": {k: list(v) for k, v in lm_feature_stats.items()},
        }
        exc = {
            "bayes":  {f"{k[0]}|{k[1]}": list(v) for k, v in bayes_stats.items()},
            "bandit": {f"{k[0]}|{k[1]}": list(v) for k, v in bandit_stats.items()},
        }
        save_model_state({"rde": rde, "exec": exc})
    except Exception as e:
        print(f"⚠️  model state save: {e}")


def _restore_full_state():
    """
    Load persisted model state on startup (called at top of _seed_calibrator).
    Calibrator replay still runs after this — adding recent trades is harmless
    (WR ratios are preserved; counts inflate by ~10% at 100-trade history).
    EV/score histories are NOT re-added from trade replay, so adaptive
    thresholds work immediately instead of waiting for cold-start accumulation.

    Also restores edge_stats, combo_stats, lm_feature_stats — these were
    previously lost on every restart, cold-starting the weighted_score gate
    even when hundreds of historical trades already established feature WR.
    """
    try:
        import time as _t
        from src.services.firebase_client import load_model_state
        from src.services.execution       import bayes_stats, bandit_stats
        from src.services.learning_monitor import lm_feature_stats

        state = load_model_state()
        if not state:
            print("📥 No persisted model state — starting fresh")
            return

        rde = state.get("rde", {})
        # Calibrator buckets — keyed as floats in memory, strings in Firestore
        for b_str, v in rde.get("calibrator", {}).items():
            calibrator.buckets[float(b_str)] = list(v)
        # Histories (deques with maxlen) — extend, don't overwrite
        for ev in rde.get("ev_history", []):
            ev_history.append(float(ev))
        for s in rde.get("score_history", []):
            score_history.append(float(s))

        # Restore edge_stats: "feature_name|regime" → [eff_wins, eff_total]
        for k_str, v in rde.get("edge_stats", {}).items():
            fname, reg = k_str.split("|", 1)
            edge_stats[(fname, reg)] = list(v)

        # Restore combo_stats: "('f1','f2',...)|regime" → [eff_wins, eff_total]
        for k_str, v in rde.get("combo_stats", {}).items():
            pipe = k_str.rfind("|")
            if pipe > 0:
                try:
                    combo_tuple = tuple(ast.literal_eval(k_str[:pipe]))
                    reg = k_str[pipe + 1:]
                    combo_stats[(combo_tuple, reg)] = list(v)
                except Exception:
                    pass

        # Restore lm_feature_stats: feature_name → [wins, total]
        for fname, v in rde.get("lm_feature_stats", {}).items():
            lm_feature_stats[fname] = list(v)

        exc = state.get("exec", {})
        for k_str, v in exc.get("bayes", {}).items():
            sym, reg = k_str.split("|", 1)
            bayes_stats[(sym, reg)] = tuple(v)
        for k_str, v in exc.get("bandit", {}).items():
            sym, reg = k_str.split("|", 1)
            bandit_stats[(sym, reg)] = tuple(v)

        age_min = (_t.time() - float(state.get("saved_at", _t.time()))) / 60
        print(f"🔄 Model state restored ({age_min:.0f}min old): "
              f"{len(calibrator.buckets)} cal buckets  "
              f"{len(ev_history)} ev_hist  "
              f"{len(bayes_stats)} bayes pairs  "
              f"{len(edge_stats)} edge_stats  "
              f"{len(combo_stats)} combos")
    except Exception as e:
        print(f"⚠️  model state restore: {e}")


def update_calibrator(p, outcome):
    """Called by trade_executor after every trade close."""
    calibrator.update(p, outcome)
    _state_dirty[0] += 1
    if _state_dirty[0] >= _STATE_SAVE_EVERY:
        _state_dirty[0] = 0
        _save_full_state()


def _seed_calibrator(trades):
    """One-time bootstrap: restore persisted state then replay recent trades."""
    _restore_full_state()   # ← load calibrator + histories + bayes/bandit first
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


def decision_score(ev, ws):
    """Weighted combination: EV drives 70%, WS contributes 30%."""
    return 0.7 * ev + 0.3 * ws


def allow_trade(ev, ws):
    """
    Deterministic hard threshold — score = 0.7×ev + 0.3×ws > 0.0.
    Tightened -0.05 → 0.0: requires net-positive combined score.
    At ws=0.5: passes when ev > -0.214. Exploration prior ev=0.03 →
    score=0.171 ✓ still passes. Truly negative EV signals blocked here
    before reaching pair_block (n≥25) / regime_block (n≥25).
    """
    return decision_score(ev, ws) > 0.0


def get_ev_threshold():
    """
    Adaptive EV gate threshold.
    Crisis mode (trades >= 50 AND WR < 5%):   0.15  ← near-halt
      WR < 5% after 50 trades is statistically confirmed failure — the old
      learning-mode floor of -0.30 kept accepting all signals forever, meaning
      the system could never self-protect.  At 0.15 only strong EVs pass.
    Learning mode (trades < 200 OR WR < 20%): -0.30
      Permits negative-EV signals so data can flow in — calibration is
      unreliable when WR is near 0%.
    Cold start (ev_history < 100 samples):    0.15
    Live (ev_history >= 100):                 q75 of ev_history, floor 0.10
    """
    try:
        from src.services.learning_event import METRICS as _m
        _t  = _m.get("trades", 0)
        _wr = _m.get("wins", 0) / max(_t, 1)
        # Crisis gate: confirmed failure after enough data → near-halt
        if _t >= 50 and _wr < 0.05:
            return 0.15
        if _t < 200 or _wr < 0.20:
            return -0.30
    except Exception:
        pass
    if len(ev_history) < 100:
        return 0.15
    s   = sorted(ev_history)
    q75 = s[int(len(s) * 0.75)]
    return max(0.10, q75)


def evaluate_signal(signal):
    history = load_history()
    track_regime(signal.get("regime", "RANGING"))

    # ── Lazy one-time bootstrap ────────────────────────────────────────────────
    if not _seeded[0]:
        _seed_calibrator(history or [])
        _seeded[0] = True

    # ── Calibrated win_prob ────────────────────────────────────────────────────
    win_prob = calibrator.get(signal["confidence"])

    # ── EV (True Empirical Computation) ─────────────────────────────────────
    regime  = signal.get("regime", "RANGING")
    sym     = signal.get("sym", signal.get("symbol", ""))
    
    from src.services.learning_monitor import lm_pnl_hist
    pnl = lm_pnl_hist.get((sym, regime), [])
    if len(pnl) < 10:
        # Exploration prior: 0.03 instead of 0.0 so underdeveloped pairs can
        # pass a rising EV gate (currently 0.005) and accumulate the remaining
        # trades to reach n=10. At n=10, real EV kicks in — if negative (e.g.
        # ETH 30% WR) the pair gets permanently blocked. Using 0.0 caused a
        # catch-22: pairs were blocked before they could collect enough data to
        # be evaluated (and ETH was stuck at n=7, unable to reach n=10 block).
        ev = 0.03
    else:
        m = float(np.mean(pnl[-20:]))
        s = max(float(np.std(pnl[-20:])), 0.002)
        ev = float(np.tanh(m / s))   # bounded (-1,+1); matches true_ev()

    # Record raw ev BEFORE floor into history — the floor collapses all
    # exploration pairs to identical 0.05, making spread=0 → SKIP_FLAT fires.
    # ev_history is used only for spread guard and adaptive threshold, both of
    # which need real variance, not the artificially uniform floored value.
    ev_history.append(ev)

    # Floor for gate decisions only (prevent micro-signal collapse at gate)
    if abs(ev) < 0.05:
        ev = 0.05 if ev >= 0 else -0.05

    # Keep structural info for printing / metadata
    atr     = signal.get("atr", 0)
    price   = signal.get("price", 1) or 1
    tp_move = max(atr * _TP_MULT.get(regime, 1.0) / price, MIN_TP)
    sl_move = max(atr * _SL_MULT.get(regime, 0.8) / price, MIN_SL)
    rr      = max(tp_move / sl_move, MIN_RR)
    ev_threshold = get_ev_threshold()

    # ── Loss streak + velocity guard ──────────────────────────────────────────
    from src.services.learning_event import METRICS as _M, _recent_results as _rr
    try:
        from src.services.execution import is_bootstrap as _ib
        _bootstrap = _ib()
    except Exception:
        _bootstrap = False

    streak = _M.get("loss_streak", 0)
    if not _bootstrap and streak >= MAX_LOSS_STREAK:
        track_blocked(reason="STREAK_GUARD")
        print(f"    decision=SKIP_STREAK  streak={streak}>={MAX_LOSS_STREAK}")
        return None
    # Velocity guard: 5+ losses in last 8 trades → temporary pause.
    # Window 5→8, threshold 3→5:
    #   Old (3/5): at WR=55%, P(trigger) = 40% per 5-trade window → froze
    #   the system every ~12 trades on average; threshold too sensitive.
    #   New (5/8): P(trigger) ≈ 4% → fires only during genuine loss streaks.
    # Deadlock bypass: if no trade executed in last 15 min (t15=0), the guard
    #   may have deadlocked (Positions=0 → no wins possible → guard never lifts).
    #   Allow one signal through to break the cycle.
    recent_losses = sum(1 for r in list(_rr)[-8:] if r == "LOSS")
    _t15_now = trades_in_window(900)
    # Deadlock bypass: ≤1 trade in last 15min (not just 0) — a single stale win
    # keeps t15=1 for 15 min after it executes, blocking the bypass the entire time.
    _deadlocked = (_t15_now <= 1 and len(list(_rr)) >= 5)
    if not _bootstrap and not _deadlocked and recent_losses >= 5:
        track_blocked(reason="VELOCITY_GUARD")
        print(f"    decision=SKIP_VELOCITY  recent_losses={recent_losses}/8")
        return None

    # ── EV spread guard: flat distribution = noise, not edge ──────────────────
    # [HOTFIX] Blokace vypnuta během Bootstrapu, jinak se EV křivky nikdy nevytvoří (zůstaly by nelineární)
    if not _bootstrap and len(ev_history) >= EV_SPREAD_AFTER:
        spread = max(ev_history) - min(ev_history)
        if spread < EV_SPREAD_MIN:
            track_blocked(reason="FLAT_SPREAD")
            print(f"    decision=SKIP_FLAT  spread={spread:.4f}<{EV_SPREAD_MIN}")
            return None

    # ── Frequency cap ─────────────────────────────────────────────────────────
    t15 = trades_in_window(900)
    try:
        from src.services.learning_event import METRICS as _M2
        _freq_active = _M2.get("trades", 0) >= 100  # raised 50→100: freq gate was
        # firing at 50 trades and blocking training flow; system needs ~100 trades
        # of clean data before rate-limiting makes sense
    except Exception:
        _freq_active = True
    if _freq_active and t15 > MAX_TRADES_15:
        track_blocked(reason="FREQ_CAP")
        print(f"    decision=SKIP_FREQ  t15={t15}>{MAX_TRADES_15}")
        return None

    # ── QUIET_RANGE RSI extreme gate ─────────────────────────────────────────
    # In a dead market, only trade real extremes (RSI ≤ 35 BUY / ≥ 65 SELL).
    # Mid-range entries score 3/7 on trend+bounce+mom alone — that's noise,
    # not a mean-reversion edge. Bypassed in bootstrap (<50 trades) so data flows.
    if regime == "QUIET_RANGE" and _M.get("trades", 0) >= 50:
        _rsi_val = signal.get("features", {}).get("rsi", 50.0)
        _side    = signal.get("action", "BUY")
        if (_side == "BUY" and _rsi_val > 35) or (_side == "SELL" and _rsi_val < 65):
            track_blocked(reason="QUIET_RSI")
            print(f"    decision=SKIP_QUIET_RSI  rsi={_rsi_val:.1f}  side={_side}")
            return None

    # ── Entry timing — 1-tick momentum confirmation ──────────────────────────
    # Require last price tick to move in signal direction (soft: 1 tick, not 3).
    # Old 3-tick check blocked too many valid entries — requiring 3 consecutive
    # moves in the same direction at 2s/tick is rare in sideways/ranging markets
    # and was a large contributor to signal drop-out even with good EV.
    # Bypassed during bootstrap (<100 trades) to preserve learning data flow.
    try:
        _ph = _price_history.setdefault(sym, deque(maxlen=3))
        _ph.append(signal.get("price", 0))
        _t_boot = _M.get("trades", 0)
        if _t_boot >= 100 and len(_ph) >= 2:
            _side = signal.get("action", "BUY")
            _ph3  = list(_ph)
            _bad_timing = (
                (_side == "BUY"  and not (_ph3[-1] > _ph3[-2])) or
                (_side == "SELL" and not (_ph3[-1] < _ph3[-2]))
            )
            if _bad_timing:
                track_blocked(reason="TIMING")
                return None
    except Exception:
        pass

    # ── V6 L10: loss cluster per symbol — 4/5 recent sym-level losses → pause ─
    try:
        from src.services.learning_monitor import sym_recent_pnl as _srp
        _sp = _srp.get(sym, [])
        if len(_sp) >= 5 and sum(1 for x in _sp[-5:] if x < 0) >= 4:
            track_blocked(reason="LOSS_CLUSTER")
            print(f"    decision=SKIP_CLUSTER  {sym}  4/5 recent losses")
            return None
    except Exception:
        pass

    # ── Pair+regime block: n≥10 and WR<30% → proven loser, skip ─────────────
    # Spec patch 5 (modified): lower threshold than regime hard-block (n≥15,
    # WR<35% in trade_executor) — catches losers earlier in the pipeline using
    # in-session lm_pnl_hist data.  n=25 minimum — fresh DB needs enough trades
    # before pair_block fires (bootstrap safety).
    # WR<30% threshold leaves room for low-WR high-RR pairs if truly profitable.
    try:
        from src.services.learning_monitor import lm_pnl_hist as _lph, lm_count as _lc
        _pk = (sym, regime)
        _pn = _lc.get(_pk, 0)
        if _pn >= 25:
            _pp = _lph.get(_pk, [])
            if _pp:
                _pwr = sum(1 for x in _pp if x > 0) / len(_pp)
                if _pwr < 0.30:
                    track_blocked(reason="PAIR_BLOCK")
                    print(f"    decision=SKIP_PAIR  {sym}/{reg}  wr={_pwr:.0%}  n={_pn}")
                    return None
    except Exception:
        pass

    # ── Auditor: floor 0.7 ────────────────────────────────────────────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_factor = min(1.0, max(0.7, af_raw))

    # Unified deterministic gate — same rule for all phases.
    # Bootstrap/live split removed: sigmoid was blocking ~35% of valid signals
    # randomly; the hard floor (-0.20) was never consistent with the live gate.
    # Now both phases use the same threshold: score = 0.7*ev + 0.3*ws > -0.05.
    _t_ef = _M.get("trades", 0)
    _ws   = signal.get("ws", 0.5)
    _sc   = decision_score(ev, _ws)
    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  ws={_ws:.3f}  "
          f"score={_sc:.3f}[n={_t_ef}]  "
          f"t15={t15}  spread={max(ev_history)-min(ev_history):.3f}  af={auditor_factor:.2f}")

    if not allow_trade(ev, _ws):
        track_blocked(reason="SKIP_SCORE")
        print(f"    decision=SKIP_SCORE  ev={ev:.3f}  ws={_ws:.3f}  score={_sc:.3f}")
        return None

    signal["confidence"]     = round(win_prob, 4)
    signal["ev"]             = round(ev, 4)
    signal["auditor_factor"] = round(auditor_factor, 4)
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  af={auditor_factor:.2f}")
    return signal
