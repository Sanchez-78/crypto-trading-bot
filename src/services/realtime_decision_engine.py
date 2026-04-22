"""
EV-only decision engine — stable adaptive threshold + online calibration.

Flow:
  1. Calibrate win_prob: empirical WR from online bucket tracker
     Requires 30 samples per bucket; fallback = 0.5 (honest, not raw conf)
  2. TP=0.5–0.6×ATR / SL=0.35–0.4×ATR → RR≥1.25 (regime-scaled; fits 8-min hold window)
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
import logging
import time as _time
import numpy as np

log = logging.getLogger(__name__)
from src.services.firebase_client import load_history
from src.services.learning_event  import track_blocked, track_regime, trades_in_window
from src.services.adaptive_recovery import (
    ev_gate,
    filter_relaxation,
    stall_recovery,
    micro_trade_mode,
    get_ev_relaxation,
    get_filter_relaxation_state,
    is_micro_trade_active,
    get_position_size_multiplier,
)
from src.services.smart_exit_engine import evaluate_position_exit
from src.services.reward_system import compute_reward


# ── V10.13q: Final kill attribution telemetry (observability for tuning) ────────
# Track the FINAL terminal reason each candidate is rejected
_entry_kill_audit = {
    "cycle_kills": {},        # Current cycle: reason → count
    "cycle_rescues": {},      # Current cycle: rescue_type → count
    "session_kills": {},      # Session totals
    "session_rescues": {},
    "last_summary_ts": _time.time(),
}

def reset_kill_audit():
    """Reset cycle-level kill audit (call at start of each cycle)."""
    global _entry_kill_audit
    _entry_kill_audit["cycle_kills"] = {}
    _entry_kill_audit["cycle_rescues"] = {}

def track_kill(reason: str):
    """Log a final rejection with its terminal reason."""
    global _entry_kill_audit
    _entry_kill_audit["cycle_kills"][reason] = _entry_kill_audit["cycle_kills"].get(reason, 0) + 1
    _entry_kill_audit["session_kills"][reason] = _entry_kill_audit["session_kills"].get(reason, 0) + 1

def track_rescue(rescue_type: str):
    """Log when emergency recovery allows a candidate through."""
    global _entry_kill_audit
    _entry_kill_audit["cycle_rescues"][rescue_type] = _entry_kill_audit["cycle_rescues"].get(rescue_type, 0) + 1
    _entry_kill_audit["session_rescues"][rescue_type] = _entry_kill_audit["session_rescues"].get(rescue_type, 0) + 1

def get_kill_audit_summary() -> dict:
    """Return current cycle kill audit for dashboard."""
    return {
        "cycle_kills": dict(_entry_kill_audit["cycle_kills"]),
        "cycle_rescues": dict(_entry_kill_audit["cycle_rescues"]),
        "session_kills": dict(_entry_kill_audit["session_kills"]),
        "session_rescues": dict(_entry_kill_audit["session_rescues"]),
    }


# ── V10.13s: Reset integrity state validation (detect stale warm-start contamination) ──
# After DB wipe, detect if global metrics are stale but learning state is fresh
_reset_integrity_state = {
    "mismatch_detected": False,
    "mismatch_log": [],
    "effective_completed_trades": 0,
    "stale_metrics_cleared": False,
    "validation_run": False,
}

def validate_runtime_state_consistency() -> dict:
    """
    V10.13s: Detect stale warm-start contamination after DB wipe/reset.
    
    After reset, global metrics (completed_trades, calibration flags) may be 
    stale while learning state (pair/regime counts) is fresh. This creates
    contradictory bot state that confuses thresholds and dashboard.
    
    Returns validation result dict with mismatch detection.
    """
    global _reset_integrity_state
    
    try:
        from src.services.learning_event import METRICS as _M_val
        from src.services.learning_monitor import lm_count as _lc_val, lm_pnl_hist as _lph_val
        
        _global_n = _M_val.get("trades", 0)
        
        # Calculate effective sample count from learning state
        _pair_counts = list(_lc_val.values()) if _lc_val else []
        _median_pair_n = sorted(_pair_counts)[len(_pair_counts)//2] if _pair_counts else 0
        _max_pair_n = max(_pair_counts) if _pair_counts else 0
        _sum_pair_n = sum(_pair_counts)
        _num_pairs = len(_lc_val)
        
        # Detect mismatch: high global trades but sparse local learning
        _mismatch = (
            _global_n >= 100  # Global says mature
            and _num_pairs > 0
            and (_max_pair_n < 15 or _median_pair_n < 5)  # But local is immature
        )
        
        result = {
            "mismatch": _mismatch,
            "global_completed_trades": _global_n,
            "effective_completed_trades": _sum_pair_n,
            "num_pairs": _num_pairs,
            "median_pair_n": _median_pair_n,
            "max_pair_n": _max_pair_n,
            "sum_pair_n": _sum_pair_n,
        }
        
        if _mismatch:
            log.warning(
                f"[V10.13s] STATE MISMATCH DETECTED — stale global state after reset:\n"
                f"    global_completed_trades={_global_n} (stale)\n"
                f"    effective_completed_trades={_sum_pair_n} (from learning state)\n"
                f"    num_pairs={_num_pairs} median_n={_median_pair_n} max_n={_max_pair_n}\n"
                f"    → Clearing stale global metrics"
            )
            _reset_integrity_state["mismatch_detected"] = True
            _reset_integrity_state["mismatch_log"].append({
                "ts": _time.time(),
                "result": result
            })
        
        _reset_integrity_state["validation_run"] = True
        _reset_integrity_state["effective_completed_trades"] = _sum_pair_n
        
        return result
        
    except Exception as _vsc_err:
        log.debug(f"State consistency validation error: {_vsc_err}")
        return {"mismatch": False, "error": str(_vsc_err)}


def apply_reset_integrity_corrections():
    """
    V10.13s: Apply corrections when stale warm-start contamination is detected.
    
    Clears or resets stale global metrics that contradict fresh learning state,
    ensuring calibration status and thresholds reflect reality.
    """
    global _reset_integrity_state
    
    if not _reset_integrity_state.get("mismatch_detected"):
        return  # No mismatch, no action needed
    
    try:
        from src.services.learning_event import METRICS as _M_corr
        from src.services.learning_monitor import lm_count as _lc_corr
        
        # Recompute effective completed trades from trustworthy learning state
        _effective_n = sum(_lc_corr.values()) if _lc_corr else 0
        
        # Update METRICS to reflect real current state
        old_n = _M_corr.get("trades", 0)
        _M_corr["trades"] = _effective_n
        
        # Force recalibration status - cannot claim mature if learning is sparse
        # This will be checked in current_ev_threshold() and current_score_threshold()
        
        log.info(
            f"[V10.13s] RESET_INTEGRITY CORRECTIONS APPLIED:\n"
            f"    completed_trades: {old_n} → {_effective_n}\n"
            f"    action: STALE_GLOBAL_STATE_CORRECTED"
        )
        
        _reset_integrity_state["stale_metrics_cleared"] = True
        
    except Exception as _arc_err:
        log.debug(f"Reset integrity corrections error: {_arc_err}")


# ── V10.13r: Cold-start recovery telemetry (bootstrap deadlock relief) ────────────
# Track bootstrap recovery activities to verify patch effectiveness
_bootstrap_state = {
    "active": False,
    "start_ts": _time.time(),
    "global_n_at_start": 0,
    "relaxed_ofi": 0,          # OFI_HARD softened to soft
    "softened_fast_fail": 0,   # FAST_FAIL_HARD demoted to soft
    "freq_relief": 0,          # FREQ_CAP relaxed
    "threshold_relief": 0,     # EV/score thresholds reduced
    "bootstrap_entries": 0,    # Entries enabled by bootstrap mode
}

def get_bootstrap_summary() -> dict:
    """Return cold-start bootstrap telemetry."""
    return dict(_bootstrap_state)

def reset_bootstrap_state():
    """Reset cycle counters (call at start of each cycle)."""
    global _bootstrap_state
    _bootstrap_state["relaxed_ofi"] = 0
    _bootstrap_state["softened_fast_fail"] = 0
    _bootstrap_state["freq_relief"] = 0
    _bootstrap_state["threshold_relief"] = 0


def is_cold_start() -> bool:
    """
    V10.13r: Detect if bot is in cold-start phase (sparse learning data).
    
    Returns True if:
    - global completed trades < 100 (learning phase)
    OR
    - pair/regime sample counts immature < 15 (insufficient pair history)
    OR
    - uptime < 60 min AND completed trades still low
    
    This enables bootstrap-tolerant filtering during early phase.
    Auto-exits when data accumulates.
    """
    try:
        from src.services.learning_event import METRICS as _M2
        from src.services.learning_monitor import lm_count as _lc2
        
        _global_n = _M2.get("trades", 0)
        
        # Condition 1: global trades < 100 (immature)
        if _global_n < 100:
            return True
        
        # Condition 2: Check if any pair/regime has very few samples
        if _lc2:
            _min_pair_n = min(_lc2.values()) if _lc2 else 0
            if _min_pair_n < 15:
                return True
        
        # Condition 3: Recent restart (uptime < 60 min) + low trades
        _uptime_min = (_time.time() - _bootstrap_state["start_ts"]) / 60.0
        if _uptime_min < 60 and _global_n < 150:
            return True
            
        return False
        
    except Exception as _cse:
        log.debug("cold_start check error: %s", _cse)
        return False  # Default to False (use mature filters)


# ── V10.13q: Improved idle time calculation (fixed timestamp source issues) ─────

def safe_idle_seconds(last_trade_ts: float | None = None, now: float | None = None) -> float:
    """
    V10.13q: Calculate safe idle seconds with better validation and logging.

    Preferred source order:
    1. last_trade_ts param (explicit source of truth)
    2. _last_trade_ts[0] module state (fallback)
    3. 0.0 (safe default when unknown)

    If idle is unrealistic, log once per process uptime and safely clamp.
    Never returns values > 1 day (prevents timestamp contamination from exploding).
    """
    if last_trade_ts is None:
        last_trade_ts = _last_trade_ts[0]

    if now is None:
        now = _time.time()

    # Invalid cases → return 0 (assume just started)
    if not last_trade_ts:
        return 0.0

    try:
        ts = float(last_trade_ts)
    except (ValueError, TypeError):
        return 0.0

    # Negative or future timestamp → safety fallback
    if ts <= 0 or ts > now:
        return 0.0

    idle = now - ts

    # V10.13q: Better detection and one-time logging
    # If idle > 1 day (86400s), log ONCE and clamp
    if idle > 86400:
        # Check if we've already warned about this in this session
        # (avoid log spam by clamping the warning frequency)
        _idle_warnings = getattr(safe_idle_seconds, '_warned_count', [0])
        if len(_idle_warnings) < 1:  # Log max 1 time per session
            log.warning(
                "safe_idle_seconds: unrealistic idle=%.0fs (ts=%.0f, now=%.0f). "
                "Timestamp source may be stale or mixed. Clamping to 0. "
                "Check: (1) last_trade_ts derivation (2) timestamp persistence (3) boot state",
                idle, ts, now
            )
            _idle_warnings.append(1)
            safe_idle_seconds._warned_count = _idle_warnings
        return 0.0

    return max(0.0, idle)


# ── V10.12g: Comprehensive decision logging ──────────────────────────────────

def log_decision(
    decision: str,
    symbol: str,
    regime: str,
    unblock_mode: bool,
    raw_ev: float,
    adj_ev: float,
    raw_score: float,
    adj_score: float,
    ev_threshold: float,
    score_threshold: float,
    timing_mult: float = 1.0,
    ofi_mult: float = 1.0,
    cooldown_remaining: float = float('inf'),
    fallback_considered: bool = False,
    fallback_used: bool = False,
    anti_deadlock: bool = False,
    size_mult: float = 1.0,
    reason: str = "unspecified"
) -> None:
    """
    V10.12g: Log comprehensive decision state for diagnostics.
    
    Captures all decision variables at the final decision point so pipeline
    deadlocks can be diagnosed from logs.
    """
    if cooldown_remaining == float('inf'):
        cooldown_str = "inf"
    else:
        cooldown_str = f"{cooldown_remaining:.0f}"
    
    log.info(
        "decision=%s sym=%s reg=%s unblock=%s ev=%.4f->%.4f score=%.4f->%.4f "
        "thr_ev=%.4f thr_sc=%.4f timing=%.2f ofi=%.2f cooldown=%s "
        "fallback_considered=%s fallback_used=%s anti_deadlock=%s size=%.2f reason=%s",
        decision, symbol, regime, unblock_mode,
        raw_ev, adj_ev, raw_score, adj_score,
        ev_threshold, score_threshold, timing_mult, ofi_mult, cooldown_str,
        fallback_considered, fallback_used, anti_deadlock, size_mult, reason
    )


def log_cycle_result(
    n_symbols: int,
    n_passed: int,
    unblock_mode: bool,
    idle_seconds: float,
    redis_available: bool = True
) -> None:
    """
    V10.12g: Log cycle-level result when zero candidates pass.
    
    Helps diagnose why pipeline is stuck with no passthrough.
    """
    log.info(
        "cycle_result=%s symbols=%d passed=%d unblock=%s idle=%.1f redis=%s",
        "no_candidate" if n_passed == 0 else "has_candidate",
        n_symbols, n_passed, unblock_mode, idle_seconds,
        "available" if redis_available else "unavailable"
    )


def get_current_status() -> dict:
    """
    V10.12g: Return current system status for dashboard display.
    
    Includes real thresholds, unblock mode, idle time, Redis status.
    """
    try:
        from src.services.state_manager import is_redis_available
    except Exception:
        is_redis_available = lambda: False
    
    idle_sec = safe_idle_seconds()
    unblock = is_unblock_mode()
    
    return {
        'idle_seconds': idle_sec,
        'unblock_mode': unblock,
        'ev_threshold': 0.015 if unblock else 0.025,
        'score_threshold': 0.12 if unblock else 0.18,
        'redis_available': is_redis_available(),
        'last_trade_ts': _last_trade_ts[0],
    }


def format_status_for_display() -> str:
    """
    V10.12g: Format status as human-readable string for dashboard.
    """
    status = get_current_status()
    
    redis_status = "OK" if status['redis_available'] else "OFFLINE"
    unblock_str = "UNBLOCK" if status['unblock_mode'] else "NORMAL"
    
    return (
        f"EV threshold: {status['ev_threshold']:.3f} ({unblock_str})  "
        f"Score threshold: {status['score_threshold']:.2f}  "
        f"Idle: {status['idle_seconds']:.0f}s  "
        f"Redis: {redis_status}"
    )



# ── Anti-deadlock state ───────────────────────────────────────────────────────
# Mutable scalar — updated on every trade close via update_calibrator().
_last_trade_ts: list[float] = [_time.time()]  # V10.12g: init to now, not 0.0

_TP_MULT = {"BULL_TREND": 0.6, "BEAR_TREND": 0.6, "RANGING": 0.5, "QUIET_RANGE": 0.4}
_SL_MULT = {"BULL_TREND": 0.4, "BEAR_TREND": 0.4, "RANGING": 0.4, "QUIET_RANGE": 0.35}
MIN_TP   = 0.0025
MIN_SL   = 0.0020
MIN_RR   = 1.25

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


# ════════════════════════════════════════════════════════════════════════════════
# V10.13s: UNIFIED MATURITY ORACLE
# All modules read maturity from here to prevent state divergence
# ════════════════════════════════════════════════════════════════════════════════
_MATURITY_CACHE = {
    "effective_trade_count": 0,
    "bootstrap_mode": True,
    "cold_start_mode": True,
    "cache_ts": 0,
}

def compute_effective_maturity():
    """
    V10.13s: Compute effective maturity after all hydration complete.

    Source priority:
    1. Learning monitor pair counts (freshest after reset)
    2. Global METRICS (fallback if LM empty)

    Assigns bootstrap/cold-start flags based on unified trade count.
    Call once during startup; all modules then read from get_effective_maturity().
    """
    import time as _t
    now = _t.time()

    # Use cache if fresh (< 5s)
    if _MATURITY_CACHE["cache_ts"] > 0 and (now - _MATURITY_CACHE["cache_ts"]) < 5.0:
        return _MATURITY_CACHE.copy()

    try:
        from src.services.learning_monitor import lm_count
        from src.services.learning_event import METRICS as _M

        lm_total = sum(s.get("n", 0) for s in lm_count.values()) if lm_count else 0
        global_total = _M.get("trades", 0)
        effective_n = lm_total if lm_total > 0 else global_total

        # Bootstrap: sparse learning data
        bootstrap = effective_n < 100
        cold_start = effective_n < 100 or (lm_total > 0 and max((s.get("n", 0) for s in lm_count.values()), default=0) < 15)

        _MATURITY_CACHE.update({
            "effective_trade_count": effective_n,
            "bootstrap_mode": bootstrap,
            "cold_start_mode": cold_start,
            "cache_ts": now,
            "lm_total": lm_total,
            "global_total": global_total,
        })
    except Exception as _e:
        pass

    return _MATURITY_CACHE.copy()


def get_effective_maturity() -> dict:
    """V10.13s: Read unified maturity state (call compute_effective_maturity() once at startup)."""
    return _MATURITY_CACHE.copy()


calibrator = Calibrator()
ev_history = deque(maxlen=200)   # ALL evaluated EVs (including skipped)
_seeded    = [False]

# V10.13b: Track RDE state restoration for bootstrap diagnostics
_last_restore_source = "pending"  # "redis", "empty", "error", "pending"
_last_restore_ts = 0.0  # timestamp of last restoration attempt

# V10.13b: Track active thresholds for live dashboard display
_last_ev_threshold = 0.0  # actual EV threshold used in last evaluate_signal() call
_last_score_threshold = 0.0  # actual score threshold used in last call
_last_cycle_blocks = {}  # block reason counts from last cycle

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
    V10.10b: Hard block removed — converted to soft penalty via get_combo_penalty().
    Now always returns True; penalty is applied to sizing in evaluate_signal.
    Also applies exponential decay (×0.995) to all usage counts on each call,
    preventing permanent lockout of old combos.
    """
    # Decay all usage counts — old combos gradually become usable again
    for c in list(combo_usage.keys()):
        combo_usage[c] *= 0.995
        if combo_usage[c] < 1.0:
            del combo_usage[c]
    combo_usage[combo] = combo_usage.get(combo, 0) + 1
    return True   # hard block removed; penalty computed in get_combo_penalty()


def get_combo_penalty(combo: tuple) -> float:
    """
    V10.10b: Soft penalty by combo saturation.
    usage > 200 → 0.70 (high saturation — reduce size, don't block)
    usage > 100 → 0.85 (moderate saturation — slight size reduction)
    else        → 1.00 (no penalty)
    """
    usage = combo_usage.get(combo, 0)
    if usage > 200:
        return 0.70
    if usage > 100:
        return 0.85
    return 1.0


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

    V10.13b: Tracks restore source for bootstrap diagnostics.
    """
    global _last_restore_source, _last_restore_ts
    _last_restore_ts = _time.time()  # Track when restoration attempt began

    try:
        import time as _t
        from src.services.firebase_client import load_model_state
        from src.services.execution       import bayes_stats, bandit_stats
        from src.services.learning_monitor import lm_feature_stats

        state = load_model_state()
        if not state:
            print("📥 [V10.13s] No persisted model state — starting fresh (Firebase collection empty or reset)")
            _last_restore_source = "empty"
            return

        _last_restore_source = "firebase"  # Successfully loaded from Firebase

        # V10.13s: Log recovery success to verify learning state is restored
        cal_size = len(state.get("rde", {}).get("calibrator", {}))
        ev_hist_size = len(state.get("rde", {}).get("ev_history", []))
        edge_stat_size = len(state.get("rde", {}).get("edge_stats", {}))
        print(f"📥 [V10.13s] Model state restored: calibrator={cal_size} buckets, "
              f"ev_history={ev_hist_size} samples, edge_stats={edge_stat_size} feature/regime pairs")

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
        _last_restore_source = "error"  # V10.13b: Mark as error

    # Also hydrate from Redis (faster, per-update granularity vs Firebase every-5th)
    try:
        from src.services.state_manager import hydrate_rde_state
        rdata = hydrate_rde_state()
        if rdata:
            for ev in rdata.get("ev_history", []):
                ev_history.append(float(ev))
            for s in rdata.get("score_history", []):
                score_history.append(float(s))
            for combo_key, v in rdata.get("combo_stats", {}).items():
                pipe = combo_key.rfind("|")
                if pipe > 0:
                    try:
                        import ast as _ast
                        combo_tuple = tuple(_ast.literal_eval(combo_key[:pipe]))
                        reg = combo_key[pipe + 1:]
                        combo_stats[(combo_tuple, reg)] = list(v)
                    except Exception:
                        pass
            for stat_key, v in rdata.get("edge_stats", {}).items():
                fname, reg = stat_key.split("|", 1)
                edge_stats[(fname, reg)] = list(v)
            print(f"  + Redis RDE: {len(rdata.get('ev_history', []))} ev  "
                  f"{len(rdata.get('combo_stats', {}))} combos")
            if _last_restore_source == "firebase":
                _last_restore_source = "firebase+redis"  # Both sources available
    except Exception as exc:
        print(f"⚠️  RDE Redis hydration skipped: {exc}")
        # Keep _last_restore_source as "firebase" if that succeeded


def update_calibrator(p, outcome):
    """Called by trade_executor after every trade close."""
    _last_trade_ts[0] = _time.time()   # V10.10b: track activity for emergency failsafe
    calibrator.update(p, outcome)
    _state_dirty[0] += 1
    if _state_dirty[0] >= _STATE_SAVE_EVERY:
        _state_dirty[0] = 0
        _save_full_state()
    # Redis flush on every update (lower-latency than Firebase every-5th)
    try:
        from src.services.state_manager import flush_rde_state
        cal_buckets = {float(k): list(v) for k, v in calibrator.buckets.items()}
        flush_rde_state(
            list(ev_history),
            list(score_history),
            {f"{k[0]}|{k[1]}": list(v) for k, v in combo_stats.items()},
            cal_buckets,
            {f"{k[0]}|{k[1]}": list(v) for k, v in edge_stats.items()},
        )
    except Exception:
        pass


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


# ════════════════════════════════════════════════════════════════════════════════
# V10.12d: CONTROLLED UNBLOCK MODE — Softens over-aggressive filters
# ════════════════════════════════════════════════════════════════════════════════

def is_unblock_mode(no_trades_seconds: float = None, no_signals_cycles: int = None) -> bool:
    """
    Detect if system should enter controlled unblock mode.
    Unblock activates when system is idle (no trades for 15+ min OR no signals for 40+ cycles).
    During unblock: lower thresholds, reduced position sizes, rate-limited.
    """
    if no_trades_seconds is None:
        try:
            no_trades_seconds = safe_idle_seconds(_last_trade_ts[0])
        except:
            no_trades_seconds = 0.0
    
    if no_signals_cycles is None:
        try:
            from src.services.learning_event import METRICS
            no_signals_cycles = METRICS.get("no_signals_cycles", 0)
        except:
            no_signals_cycles = 0
    
    return (no_trades_seconds >= 900.0) or (no_signals_cycles >= 40)


def current_ev_threshold(no_trades_sec: float = None, no_signals: int = None) -> float:
    """V10.12d: Unblock-aware EV threshold. Normal: 0.025, Unblock: 0.015."""
    return 0.015 if is_unblock_mode(no_trades_sec, no_signals) else 0.025


def current_score_threshold(no_trades_sec: float = None, no_signals: int = None) -> float:
    """V10.12d: Unblock-aware score threshold. Normal: 0.18, Unblock: 0.12."""
    return 0.12 if is_unblock_mode(no_trades_sec, no_signals) else 0.18


def timing_penalty(candle_progress: float, atr_pct: float) -> tuple[float, bool]:
    """
    V10.12d: Graded timing penalty (replaces hard TIMING reject).
    Instead of binary rejection, apply multiplier. Only hard-block if very late + tight spreads.
    Returns: (multiplier ∈ [0,1.0], hard_block: bool)
    """
    late_hard = 0.88 if atr_pct < 0.012 else 0.93
    if candle_progress <= 0.70:
        return 1.00, False
    elif candle_progress <= 0.82:
        return 0.92, False
    elif candle_progress <= late_hard:
        return 0.80, False
    return 0.0, True


def unblock_size_multiplier(no_trades_sec: float = None, no_signals: int = None) -> float:
    """V10.12d: Position size reduction during unblock. 900s+ → 0.25x, 40+ cycles → 0.35x."""
    if no_trades_sec is None:
        try:
            no_trades_sec = safe_idle_seconds(_last_trade_ts[0])
        except:
            no_trades_sec = 0.0
    
    if no_signals is None:
        try:
            from src.services.learning_event import METRICS
            no_signals = METRICS.get("no_signals_cycles", 0)
        except:
            no_signals = 0
    
    return 0.25 if no_trades_sec >= 900.0 else (0.35 if no_signals >= 40 else 1.0)


# ────────────────────────────────────────────────────────────────────────────
# PATCH 2: Disable Hard EV Filter — Probabilistic exploration gate
# ────────────────────────────────────────────────────────────────────────────
def allow_trade(ev, ws, exploration=0.4):
    """V10.13c: Score-gated entry with hard/soft split for borderline cases.

    Combines EV and win-score (WS) into decision_score.
    Thresholds adapt based on system idle state:
    - Normal: score ≥ 0.18 (HARD floor), 0.12-0.18 (SOFT zone)
    - Unblock: score ≥ 0.12 (HARD floor), 0.08-0.12 (SOFT zone)

    V10.13c: Split into hard vs soft:
    - HARD: score < hard_floor → reject
    - SOFT: hard_floor <= score < normal_threshold → apply penalties
    - PASS: score >= normal_threshold → proceed normally

    Args:
        ev: Expected Value score
        ws: Win-score
        exploration: fallback probability when below threshold

    Returns: bool — should this signal proceed to execution?
    """
    import random

    # Compute combined score
    score = decision_score(ev, ws)
    threshold = current_score_threshold()

    # V10.13c: Hard/soft floor split
    hard_floor = threshold - 0.06  # 0.12 normal → 0.06 hard, 0.06 unblock → 0.00 hard
    hard_floor = max(0.05, hard_floor)  # Never go below 0.05

    # V10.12d/13c: Decision logic
    if score >= threshold:
        return True

    # V10.13c: SOFT zone (borderline) - allow with penalties applied downstream
    # This allows borderline cases to reach auditor/position sizing for soft penalties
    if score >= hard_floor:
        return True

    # Below hard floor: probabilistic exploration (allows data collection)
    if random.random() < exploration:
        return True

    return False


def soft_filter_signal(signal, ev, state=None):
    """PATCH 3.3: Soft filter — attenuate signal strength below threshold.
    
    Instead of blocking low-EV signals, reduce their confidence multiplier.
    This preserves data flow for learning while naturally reducing position sizes.
    
    Args:
        signal: dict with 'confidence', 'ev', etc.
        ev: Expected Value score
        state: Optional system state dict
    
    Returns:
        signal: Modified signal with reduced confidence if EV is low
    """
    if ev is None or ev < -0.05:
        # Very negative EV: reduce confidence by 20%
        signal["confidence"] = max(0.1, signal.get("confidence", 0.5) * 0.8)
    elif ev < 0:
        # Slightly negative EV: reduce confidence by 10%
        signal["confidence"] = max(0.2, signal.get("confidence", 0.5) * 0.9)
    
    return signal


def get_ev_threshold():
    """
    V5.1 Adaptive EV gate threshold with stall recovery.

    Combines:
    1. Original adaptive gate (crisis mode, learning mode, cold start)
    2. NEW: Adaptive relaxation curve for zero-trade stall recovery
    3. NEW: Filter relaxation state for deadlock prevention
    """
    # Get base threshold from original logic
    base_threshold = _get_base_ev_threshold()

    # Add adaptive relaxation for stall recovery
    relaxation = get_ev_relaxation()

    # Add filter relaxation if triggered
    filter_state = get_filter_relaxation_state()
    filter_relaxation_offset = filter_state.get("ev_relaxation", 0.0)

    final_threshold = base_threshold + relaxation + filter_relaxation_offset

    return final_threshold


def _get_base_ev_threshold():
    """Original adaptive threshold logic (preserved)."""
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
        # V10.10b: linear decay 0.15→0.0 instead of hard cliff at n=100.
        progress = min(1.0, len(ev_history) / 100.0)
        return 0.15 * (1.0 - progress)
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
        # Do NOT append exploration prior to ev_history — all n<10 pairs return
        # identical 0.03, making spread=0.0000 → SKIP_FLAT kills all trading the
        # moment bootstrap ends (trades≥100). ev_history is used only for the
        # spread guard and adaptive threshold; both need real variance from actual
        # computed EVs, not a uniform exploration constant.
    else:
        m = float(np.mean(pnl[-20:]))
        s = max(float(np.std(pnl[-20:])), 0.002)
        ev = float(np.tanh(m / s))   # bounded (-1,+1); matches true_ev()
        # Only real computed EVs go into history — preserves spread diversity.
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
    
    # V10.13r: Slightly relax thresholds during cold-start (enable more learning flow)
    _cold_start_threshold_relief = False
    if is_cold_start():
        ev_threshold *= 0.95  # Reduce by 5% (e.g., 0.050 → 0.0475)
        _cold_start_threshold_relief = True
        _bootstrap_state["threshold_relief"] += 1

    # V10.13b: Track actual thresholds for live dashboard
    global _last_ev_threshold
    _last_ev_threshold = ev_threshold

    # ── Loss streak + velocity guard ──────────────────────────────────────────
    from src.services.learning_event import METRICS as _M, _recent_results as _rr
    try:
        from src.services.execution import is_bootstrap as _ib
        _bootstrap = _ib()
    except Exception:
        _bootstrap = False

    # ── V10.10b: Soft streak penalty (replaces hard block) ───────────────────
    # streak >= 10 → 0.50× size;  streak >= 5 → 0.75×;  else → 1.0×
    # Hard block at MAX_LOSS_STREAK completely removed — system never stalls.
    streak = _M.get("loss_streak", 0)
    streak_penalty = 1.0
    if not _bootstrap:
        if streak >= 10:
            streak_penalty = 0.50
        elif streak >= 5:
            streak_penalty = 0.75

    # ── V10.10b: Soft velocity penalty (replaces hard block) ─────────────────
    # 5+ losses in last 8 trades → 0.70× size instead of full stop.
    # Deadlock bypass retained: ≤3 trades in 15 min → no penalty (unreliable signal).
    recent_losses = sum(1 for r in list(_rr)[-8:] if r == "LOSS")
    _t15_now      = trades_in_window(900)
    _deadlocked   = _t15_now <= 3
    velocity_penalty = 1.0
    if not _bootstrap and not _deadlocked and recent_losses >= 5:
        velocity_penalty = 0.70

    # ── V10.10b: Emergency activity failsafe ─────────────────────────────────
    # If no trade closed in the last 5 min and we have some history → relax.
    _inactivity   = _time.time() - _last_trade_ts[0] if _last_trade_ts[0] > 0 else 0.0
    emergency_mode = _last_trade_ts[0] > 0 and _inactivity > 300
    if emergency_mode:
        ev_threshold    *= 0.5
        velocity_penalty = max(velocity_penalty, 0.85)
        streak_penalty   = max(streak_penalty,   0.85)

    # EV spread guard REMOVED — caused recurring total trading halts:
    # With few symbols, ev_history fills with a single pair's EV (e.g. -0.042)
    # → spread=0.0000 < threshold → 100% of signals blocked.
    # Protection is redundant: allow_trade (score>0), fast_fail, and pair_block
    # already cover the "noise EV" case without deadlocking.

    # ── Daily drawdown circuit breaker (hard halt at 5% session loss) ────────
    try:
        from src.services.risk_engine import is_daily_dd_safe as _dd_safe
        if not _dd_safe():
            track_blocked(reason="DAILY_DD_HALT")
            print(f"    decision=DAILY_DD_HALT  session loss ≥5%")
            return None
    except Exception:
        pass

    # ── Frequency cap ─────────────────────────────────────────────────────────
    t15 = trades_in_window(900)
    try:
        from src.services.learning_event import METRICS as _M2
        _freq_active = _M2.get("trades", 0) >= 100  # raised 50→100: freq gate was
        # firing at 50 trades and blocking training flow; system needs ~100 trades
        # of clean data before rate-limiting makes sense
    except Exception:
        _freq_active = True
    
    # V10.13r: Relax FREQ_CAP during cold-start (enables more learning flow)
    _freq_cap_threshold = MAX_TRADES_15
    _cold_freq_relief = False
    if is_cold_start() and _freq_active:
        _freq_cap_threshold = int(MAX_TRADES_15 * 1.5)  # Allow 22 instead of 15
        _cold_freq_relief = True
    
    if _freq_active and t15 > _freq_cap_threshold:
        track_blocked(reason="FREQ_CAP")
        _relief_str = " (cold_start_relaxed)" if _cold_freq_relief else ""
        print(f"    decision=SKIP_FREQ  t15={t15}>{_freq_cap_threshold}{_relief_str}")
        return None
    
    if _cold_freq_relief:
        _bootstrap_state["freq_relief"] += 1

    # ── B19: regime-aware RSI neutrality gate ────────────────────────────────
    # RANGING / QUIET_RANGE: neutral RSI (40-60) is FINE — mean reversion valid.
    # TRENDING (BULL/BEAR): neutral RSI = no momentum → skip.
    # QUIET_RANGE extreme: require real extreme (≤35 BUY / ≥65 SELL).
    # Bypassed in bootstrap (<50 trades) so data flows in early learning.
    if _M.get("trades", 0) >= 50:
        _rsi_val    = signal.get("features", {}).get("rsi", 50.0)
        _side       = signal.get("action", "BUY")
        _neutral    = 40.0 <= _rsi_val <= 60.0
        _is_trend   = regime in ("BULL_TREND", "BEAR_TREND")
        _is_quiet   = regime == "QUIET_RANGE"
        _skip_rsi   = False
        if _neutral and _is_trend:
            _skip_rsi = True   # trending market + no momentum → wait
        elif _is_quiet:
            # Dead market: only allow real extremes
            if (_side == "BUY" and _rsi_val > 35) or (_side == "SELL" and _rsi_val < 65):
                _skip_rsi = True
        if _skip_rsi:
            track_blocked(reason="QUIET_RSI")
            print(f"    decision=SKIP_QUIET_RSI  rsi={_rsi_val:.1f}  side={_side}  regime={regime}")
            return None

    # ── V10.12d: Entry timing — graded penalty (not hard block) ─────────────
    # Instead of rejecting bad-timed entries, apply a soft penalty.
    # This allows trades with good EV to proceed even with unfavorable timing.
    # Bypassed during bootstrap (<100 trades) to preserve learning data flow.
    _timing_mult = 1.0
    try:
        _ph = _price_history.setdefault(sym, deque(maxlen=3))
        _ph.append(signal.get("price", 0))
        _t_boot = _M.get("trades", 0)
        if _t_boot >= 30 and len(_ph) >= 2:
            _side = signal.get("action", "BUY")
            _ph3  = list(_ph)
            _bad_timing = (
                (_side == "BUY"  and not (_ph3[-1] > _ph3[-2])) or
                (_side == "SELL" and not (_ph3[-1] < _ph3[-2]))
            )
            if _bad_timing:
                # V10.12d: Apply 0.75× penalty instead of hard reject
                # This allows bad-timed trades with strong EV to pass (data collection)
                # while naturally reducing position sizes via auditor_factor reduction
                _timing_mult = 0.75
    except Exception:
        pass

    # ── B15: regime-aware loss cluster guard (signal_filter) ─────────────────
    try:
        from src.services.signal_filter import loss_cluster_check as _lcc, log_signal_outcome as _lso
        _lc_blocked, _lc_reason = _lcc(sym, regime)
        if _lc_blocked:
            track_blocked(reason="LOSS_CLUSTER")
            _lso(sym, accepted=False, reason="LOSS_CLUSTER")
            print(f"    decision=SKIP_CLUSTER  {sym}  {_lc_reason}")
            return None
    except Exception:
        pass

    # ── V10.13q: Fast-fail reworked — HARD only for hopeless, SOFT is penalty-only ──
    # Root cause: FAST_FAIL_SOFT was dominant killer (114k times in logs).
    # V10.13q: SOFT is truly soft — confidence/size penalty only, never hard kill.
    # HARD only for: WR < 5% AND EV <= 0.0 (truly structural losers).
    # SOFT for: WR < 20% AND EV <= 0.0 (borderline, apply penalty, allow through).
    #
    # Penalty is confidence reduction → softens EV gate but doesn't block.
    _fast_fail_soft = False
    _ff_score_mult = 1.0
    _ff_conf_mult = 1.0

    if _M.get("trades", 0) >= 30:
        try:
            from src.services.learning_monitor import lm_pnl_hist as _lph2
            _ff_pnl = _lph2.get((sym, regime), [])
            _ff_n   = len(_ff_pnl)
            if _ff_n >= 5:
                _ff_wr  = sum(1 for x in _ff_pnl if x > 0) / _ff_n
                _ff_m   = float(np.mean(_ff_pnl))
                _ff_s   = max(float(np.std(_ff_pnl)), 0.002)
                _ff_ev  = float(np.tanh(_ff_m / _ff_s))

                # V10.13r: HARD block softening during cold-start (immature samples)
                # During bootstrap, immature pairs (n < 15) should be soft, not hard
                # This prevents premature rejection of underdeveloped pairs
                _cold_start_active = is_cold_start()
                _immature_samples = _ff_n < 15
                
                # HARD block only for truly hopeless (WR < 5% AND EV <= 0.0)
                # UNLESS in cold-start + immature samples (downgrade to SOFT)
                if _ff_wr < 0.05 and _ff_ev <= 0.0:
                    if _cold_start_active and _immature_samples:
                        # V10.13r: Downgrade HARD to SOFT during cold-start
                        _fast_fail_soft = True
                        _ff_penalty = 0.50  # Moderate penalty for immature losers
                        _ff_conf_mult = _ff_penalty
                        _ff_score_mult = _ff_penalty
                        _bootstrap_state["softened_fast_fail"] += 1
                        track_blocked(reason="FAST_FAIL_SOFT_BOOTSTRAP")
                        print(f"    [V10.13r] FAST_FAIL_SOFT_BOOTSTRAP  {sym}/{regime}  "
                              f"wr={_ff_wr:.0%}  ev={_ff_ev:.3f}  n={_ff_n}  "
                              f"(immature, cold_start, softened from HARD)")
                    else:
                        track_blocked(reason="FAST_FAIL_HARD")
                        print(f"    decision=SKIP_FAST_FAIL_HARD  {sym}/{regime}  "
                              f"wr={_ff_wr:.0%}  ev={_ff_ev:.3f}  n={_ff_n}")
                        return None

                # V10.13q: SOFT — never blocks, only applies confidence penalty
                # This prevents FAST_FAIL_SOFT from acting as a shadow hard filter
                elif _ff_wr < 0.20 and _ff_ev <= 0.0:
                    _fast_fail_soft = True
                    # Graduated penalty: worse stats → lighter multiplier (more aggressive penalty)
                    # WR 19% → 0.60x, WR 10% → 0.45x, WR 5% → 0.30x
                    # The penalty softens EV and win_prob, making gate harder, but never kills
                    _ff_penalty = max(0.30, 0.60 - (_ff_wr * 3.0))
                    _ff_conf_mult = _ff_penalty
                    _ff_score_mult = _ff_penalty  # Score also reduced, but not as hard
                    track_blocked(reason="FAST_FAIL_SOFT")  # Track for diagnostics only
                    print(f"    [V10.13q] FAST_FAIL_SOFT  {sym}/{regime}  "
                          f"wr={_ff_wr:.0%}  ev={_ff_ev:.3f}  n={_ff_n}  "
                          f"conf_penalty={_ff_penalty:.2f} (NOT KILLING, allowing through with reduced confidence)")
        except Exception:
            pass

    # ── V10.13q: Pair+regime block → staged penalty system (CRITICAL FIX) ──────────
    # Root cause: hard blocks were killing entry pipeline entirely. V10.13q converts
    # to graduated penalties with emergency override capability.
    #
    # Tier 1 (Warning): n≥15, WR<40% → pair_penalty×0.75 (keep tradable, reduce size)
    # Tier 2 (Strong):  n≥20, WR<30% → pair_penalty×0.50 + ev_threshold +0.01
    # Tier 3 (Severe):  n≥25, WR<20% → pair_penalty×0.25 + score_threshold +0.02
    # Tier 4 (Extreme): n≥30, WR<10% + no emergency → hard block allowed (rare)
    #
    # Emergency override: when idle+recovery+0-positions, pair penalties soften
    _pair_penalty = 1.0
    _pair_ev_uplift = 0.0
    _pair_score_uplift = 0.0
    _pair_hard_blocked = False
    _pair_block_reason = ""

    try:
        from src.services.learning_monitor import lm_pnl_hist as _lph, lm_count as _lc
        from src.services.adaptive_recovery import is_unblock_mode as _is_recovery
        from src.services.trade_executor import get_open_positions as _get_positions

        _pk = (sym, regime)
        _pn = _lc.get(_pk, 0)
        if _pn > 0:
            _pp  = _lph.get(_pk, [])
            _pwr = sum(1 for x in _pp if x > 0) / len(_pp) if _pp else 0.0

            # Tier evaluation (all penalties are soft unless emergency is OFF)
            _emergency_active = _is_recovery()
            _no_positions = len(_get_positions()) == 0

            # Tier 4 (Extreme): only hard block if emergency OFF
            if _pn >= 30 and _pwr < 0.10:
                if not _emergency_active:
                    _pair_hard_blocked = True
                    _pair_block_reason = f"TIER4_EXTREME (n={_pn}, wr={_pwr:.0%})"
                    track_blocked(reason="PAIR_BLOCK")
                    print(f"    decision=PAIR_BLOCK_HARD  {sym}/{regime}  wr={_pwr:.0%}  n={_pn}  [no_emergency_override]")
                    return None
                else:
                    # Emergency override: allow but with severe penalty
                    _pair_penalty = 0.20  # 80% size reduction
                    _pair_score_uplift = 0.05  # require stronger confirmation
                    _pair_block_reason = f"TIER4_EMERGENCY_OVERRIDE (n={_pn}, wr={_pwr:.0%})"
                    track_blocked(reason="PAIR_BLOCK_SOFT_EMERGENCY")
                    print(f"    [V10.13q] PAIR_BLOCK_TIER4_OVERRIDE  {sym}/{regime}  wr={_pwr:.0%}  n={_pn}  penalty=0.20 score+0.05")

            # Tier 3 (Severe): n≥25, WR<20%
            elif _pn >= 25 and _pwr < 0.20:
                _pair_penalty = 0.25
                _pair_score_uplift = 0.02
                _pair_block_reason = f"TIER3_SEVERE (n={_pn}, wr={_pwr:.0%})"
                track_blocked(reason="PAIR_BLOCK_SOFT")
                print(f"    [V10.13q] PAIR_BLOCK_TIER3  {sym}/{regime}  wr={_pwr:.0%}  n={_pn}  penalty=0.25 score+0.02")

            # Tier 2 (Strong): n≥20, WR<30%
            elif _pn >= 20 and _pwr < 0.30:
                _pair_penalty = 0.50
                _pair_ev_uplift = 0.01
                _pair_block_reason = f"TIER2_STRONG (n={_pn}, wr={_pwr:.0%})"
                track_blocked(reason="PAIR_BLOCK_SOFT")
                print(f"    [V10.13q] PAIR_BLOCK_TIER2  {sym}/{regime}  wr={_pwr:.0%}  n={_pn}  penalty=0.50 ev+0.01")

            # Tier 1 (Warning): n≥15, WR<40%
            elif _pn >= 15 and _pwr < 0.40:
                _pair_penalty = 0.75
                _pair_block_reason = f"TIER1_WARNING (n={_pn}, wr={_pwr:.0%})"
                track_blocked(reason="PAIR_BLOCK_SOFT")
                print(f"    [V10.13q] PAIR_BLOCK_TIER1  {sym}/{regime}  wr={_pwr:.0%}  n={_pn}  penalty=0.75")

    except Exception as _pbe:
        log.debug("pair block eval error: %s", _pbe)

    # ── Auditor: floor 0.7 ────────────────────────────────────────────────────
    af_raw = 1.0
    try:
        from bot2.auditor import get_position_size_mult
        af_raw = get_position_size_mult()
    except Exception:
        pass
    auditor_base = min(1.0, max(0.7, af_raw))

    # ── V10.13q: Apply pair block penalties to auditor_factor (not hard kill) ──
    # Staged penalties reduce size, EV threshold, and score threshold instead of kill
    if _pair_penalty < 1.0:
        auditor_base *= _pair_penalty
        print(f"    [V10.13q_PAIR] {_pair_block_reason} → auditor×{_pair_penalty:.2f}")

    # Apply EV threshold uplift (harder to pass)
    if _pair_ev_uplift > 0:
        ev_threshold += _pair_ev_uplift
        print(f"    [V10.13q_PAIR] EV threshold uplift +{_pair_ev_uplift:.3f}")

    # ── V10.10b: Combo saturation penalty ────────────────────────────────────
    _combo = tuple(sorted(
        k for k, v in signal.get("features", {}).items()
        if isinstance(v, bool) and v
    ))
    combo_pen = get_combo_penalty(_combo)

    # ── V10.13c: Apply SKIP_SCORE_SOFT penalties ───────────────────────────────────
    # Initialized here; re-assigned later in the score gate block (line ~1176)
    _skip_score_soft = False
    _score_penalty = 1.0
    if _skip_score_soft:
        ev *= _score_penalty  # Reduce EV for downstream gates
        win_prob *= _score_penalty  # Reduce win probability
        auditor_base *= _score_penalty  # Also reduce auditor exposure

    # ── V10.13b: Apply FAST_FAIL_SOFT penalties to score and confidence ─────────────
    if _fast_fail_soft:
        ev *= _ff_score_mult  # Reduce EV for downstream gates
        win_prob *= _ff_conf_mult  # Reduce confidence/probability
        auditor_base *= max(0.5, _ff_score_mult)  # Also reduce auditor exposure

    # ── V10.10b: Fold all anti-deadlock penalties into auditor_factor ─────────
    # Penalties can only REDUCE risk — never increase it (min cap at 1.0).
    # Order: auditor base × velocity × streak × combo saturation.
    auditor_factor = auditor_base * velocity_penalty * streak_penalty * combo_pen
    auditor_factor = min(1.0, auditor_factor)   # never boost above base

    # Unified deterministic gate — same rule for all phases.
    _t_ef = _M.get("trades", 0)
    _ws   = signal.get("ws", 0.5)
    _sc   = decision_score(ev, _ws)
    _ev_spread = (max(ev_history) - min(ev_history)) if len(ev_history) >= 2 else 0.0
    print(f"    EV={ev:.3f}  p={win_prob:.2f}  rr={rr:.2f}  ws={_ws:.3f}  "
          f"score={_sc:.3f}[n={_t_ef}]  "
          f"t15={t15}  spread={_ev_spread:.3f}  af={auditor_factor:.2f}")
    print(f"    RDE[v10.10b]: ev={ev:.3f} thr={ev_threshold:.3f} "
          f"vel_pen={velocity_penalty:.2f} streak_pen={streak_penalty:.2f} "
          f"combo_pen={combo_pen:.2f} emergency={emergency_mode}")

    # ── V10.12: Signal coherence — quality-weighted EV modulation ─────────────
    _coh = 1.0
    try:
        from src.services.signal_coherence import coherence_score as _coh_fn
        _coh    = _coh_fn(signal)
        ev_adj  = ev * max(0.60, _coh)
        if abs(ev_adj - ev) > 0.001:
            print(f"    coherence[v10.12]: {_coh:.3f}  ev {ev:.3f}→{ev_adj:.3f}")
        ev = ev_adj
        signal["coherence"] = round(_coh, 4)
    except Exception:
        pass

    # ── Mammon-inspired: Monte Carlo survival + Council environmental gate ────
    # Geometric mean of 3-lane MC survival × weighted ATR/ADX/Vol/Spread score.
    # combined < 0.28 → hard inhibit (INHIBIT_COMBINED)
    # combined < 0.38 → auditor_factor × 0.75 (soft penalty)
    # Regime → ADX proxy used; volume_ratio from volume_surge feature flag.
    try:
        from src.services.monte_council import monte_council_gate as _mcg
        _mc_vol = 1.5 if signal.get("features", {}).get("volume_surge") else 1.0
        _mc_res = _mcg(
            price        = signal["price"],
            atr          = signal.get("atr", signal["price"] * 0.005),
            regime       = signal.get("regime", "RANGING"),
            volume_ratio = _mc_vol,
        )
        if _mc_res["inhibit"]:
            track_blocked(reason="INHIBIT_COMBINED")
            print(f"    decision=INHIBIT_COMBINED  mc={_mc_res['monte_score']:.3f}"
                  f"  council={_mc_res['council_score']:.3f}"
                  f"  combined={_mc_res['combined']:.3f}")
            return None
        if _mc_res["af_mult"] < 1.0:
            auditor_factor *= _mc_res["af_mult"]
            auditor_factor  = min(1.0, auditor_factor)
        signal["monte_score"]   = _mc_res["monte_score"]
        signal["council_score"] = _mc_res["council_score"]
        if _mc_res["soft_penalty"]:
            print(f"    monte_council[mammon]: {_mc_res['reason']}"
                  f"  mc={_mc_res['monte_score']:.3f}"
                  f"  council={_mc_res['council_score']:.3f}"
                  f"  af×{_mc_res['af_mult']:.2f}")
    except Exception as _mc_err:
        log.debug("monte_council gate error: %s", _mc_err)

    # V10.12d: Apply timing penalty to EV before score gate
    _ev_adj = ev * _timing_mult
    _score_threshold = current_score_threshold()
    
    # V10.13r: Slightly relax score threshold during cold-start
    if is_cold_start():
        _score_threshold *= 0.96  # Reduce by 4% to make gate easier during bootstrap
        print(f"    [V10.13r] SCORE_THRESHOLD_COLD_START: relaxed to {_score_threshold:.4f}")

    # V10.13q: Apply pair-block score uplift (harder threshold for weak pairs)
    if _pair_score_uplift > 0:
        _score_threshold += _pair_score_uplift
        print(f"    [V10.13q_PAIR] Score threshold uplift +{_pair_score_uplift:.3f} → {_score_threshold:.3f}")

    _score_adj = decision_score(_ev_adj, _ws)

    # V10.13b: Track score threshold for live dashboard
    global _last_score_threshold
    _last_score_threshold = _score_threshold

    # V10.13c/V10.13i: SKIP_SCORE split into HARD and SOFT with adaptive zones
    # V10.13i: Zone boundaries adapt based on system health & idle time
    _skip_score_soft = False
    _score_penalty = 1.0
    
    # Get adaptive zone config (health-aware hard/soft boundaries)
    _zone_type = "HEALTHY"  # For telemetry
    try:
        from src.services.hardblock_adapter import get_zone_config
        _idle_time = max(0.0, _time.time() - _last_trade_ts[0]) if _last_trade_ts[0] > 0 else 0.0
        _sys_health = _M.get("health", 0.5)
        _zones = get_zone_config(_sys_health, _idle_time)
        _score_hard_floor = _zones["hard_floor"]
        _soft_ceiling = _zones["soft_ceiling"]
        _zone_type = _zones.get("relaxation_level", "HEALTHY")
    except Exception:
        # Fallback to static zones if adapter fails
        _score_hard_floor = max(0.05, _score_threshold - 0.06)
        _soft_ceiling = _score_threshold

    # V10.12e: Bounded unblock fallback TAKE path
    # If normal gate fails but we're in unblock mode and signal meets fallback criteria,
    # accept as micro-trade to prevent infinite deadlock
    _unblock_fallback_used = False
    if not allow_trade(_ev_adj, _ws):
        # V10.13c/V10.13i: Check if this is a soft score case (in the hard_floor zone)
        if _score_adj >= _score_hard_floor:
            # SOFT zone: apply penalties instead of hard reject
            _skip_score_soft = True
            # Graduated penalty: closer to hard floor → heavier penalty
            # Normalize against adaptive soft zone size
            soft_range = max(_soft_ceiling - _score_hard_floor, 0.001)
            progress = (_score_adj - _score_hard_floor) / soft_range
            _score_penalty = max(0.30, progress * 0.60 + 0.30)  # 0.30 → 0.90
            track_blocked(reason="SKIP_SCORE_SOFT")
            
            # V10.13j: Log adaptive zone telemetry
            try:
                from src.services.adaptive_block_telemetry import log_adaptive_block, log_soft_penalty_applied
                _idle_time = max(0.0, _time.time() - _last_trade_ts[0]) if _last_trade_ts[0] > 0 else 0.0
                log_adaptive_block(
                    "SKIP_SCORE_SOFT", sym, _score_adj, _sys_health, _idle_time,
                    _score_hard_floor, _soft_ceiling, _zone_type, "SOFT",
                    f"In soft zone, applying penalty {_score_penalty:.2f}x",
                    _score_penalty
                )
            except Exception:
                pass
            
            print(f"    decision=SKIP_SCORE_SOFT  score={_score_adj:.3f} in soft_zone[{_score_hard_floor:.3f}-{_soft_ceiling:.3f}]  penalty={_score_penalty:.2f}")
        else:
            # HARD floor breached: hard reject
            track_blocked(reason="SKIP_SCORE_HARD")
            try:
                from src.services.signal_filter import log_signal_outcome as _lso2
                _lso2(sym, accepted=False, reason="SKIP_SCORE_HARD")
            except Exception:
                pass
            
            # V10.13j: Log hard reject telemetry
            try:
                from src.services.adaptive_block_telemetry import log_adaptive_block
                _idle_time = max(0.0, _time.time() - _last_trade_ts[0]) if _last_trade_ts[0] > 0 else 0.0
                log_adaptive_block(
                    "SKIP_SCORE_HARD", sym, _score_adj, _sys_health, _idle_time,
                    _score_hard_floor, _soft_ceiling, _zone_type, "HARD",
                    f"Below hard floor (score {_score_adj:.3f} < threshold {_score_hard_floor:.3f})",
                    1.0
                )
            except Exception:
                pass
            
            _timing_str = f" timing×{_timing_mult:.2f}" if _timing_mult < 1.0 else ""
            print(f"    decision=SKIP_SCORE_HARD  ev={_ev_adj:.3f}{_timing_str}  score={_score_adj:.3f}<{_score_hard_floor:.3f}")
            return None

        # Check fallback unblock path (only if not already soft-penalized)
        if not _skip_score_soft and is_unblock_mode() and _ev_adj >= 0.020 and _score_adj >= 0.110:
            # V10.12e: Bounded fallback entry
            # Still respects rate limits, size limits, risk engine
            try:
                from src.services.trade_executor import can_open_unblock_trade, record_unblock_trade
                _can_open, _reason = can_open_unblock_trade()
                if _can_open:
                    _unblock_fallback_used = True
                    record_unblock_trade()
                    log.info(f"[V10.12e_FALLBACK] {sym}  ev={_ev_adj:.4f}  score={_score_adj:.4f}  "
                             f"thr={_score_threshold:.4f}  → TAKE micro-trade")
                else:
                    track_blocked(reason="UNBLOCK_RATE_LIMIT")
                    print(f"    decision=SKIP_UNBLOCK_LIMIT  {_reason}")
                    return None
            except Exception as _ub_err:
                log.debug("unblock fallback error: %s", _ub_err)

    # ── V10.12f: B17 direction bias guard — skip for unblock fallback ─────────
    # V10.12f: Allow fallback unblock trades to bypass optional guards
    # Fallback is already bounded by EV/score, rate limits, and size reduction
    if not _unblock_fallback_used:
        try:
            from src.services.signal_filter import is_biased as _ib2, log_signal_outcome as _lso3
            _bias_blocked, _bias_reason = _ib2(sym, signal.get("action", "BUY"))
            if _bias_blocked:
                track_blocked(reason="BIAS_DISABLED")
                _lso3(sym, accepted=False, reason="BIAS_DISABLED")
                print(f"    decision=BIAS_DISABLED  {_bias_reason}")
                return None
        except Exception:
            pass

    # ── V10.13h: OFI toxicity guard — ultra-selective hard block, bounded soft penalties ─
    # V10.13h: Hard block 0.95+ (ultra-extreme) | Soft 0.70-0.95 (bounded penalty)
    # This narrower split improves selectivity: fewer false hard rejects, more pass-through
    # V10.13r: During cold-start, downgrade OFI hard to soft (preserve learning flow)
    _ofi_size = 1.0
    _ofi_soft_blocked = False
    try:
        from src.services.ofi_guard import is_toxic as _ofi_toxic, ofi_size_factor as _ofi_sf
        _ofi_blocked, _ofi_reason = _ofi_toxic(sym, signal.get("action", "BUY"))

        # V10.13r: Hard OFI block ONLY for ultra-extreme OFI (0.95+)
        # UNLESS in cold-start mode, then apply soft penalty instead
        if _ofi_blocked and not _unblock_fallback_used:
            _cold_start_ofi = is_cold_start()
            if _cold_start_ofi:
                # V10.13r: Soften OFI hard block during bootstrap
                # Apply moderate penalty but don't kill the trade
                _ofi_size = 0.70  # Significant size reduction, but allows through
                _ofi_soft_blocked = True
                _bootstrap_state["relaxed_ofi"] += 1
                track_blocked(reason="OFI_TOXIC_SOFT_BOOTSTRAP")
                print(f"    [V10.13r] OFI_SOFT_BOOTSTRAP  {_ofi_reason}  size×0.70 (cold_start, normally HARD)")
            else:
                # Mature mode: hard block ultra-extreme OFI
                track_blocked(reason="OFI_TOXIC_HARD")
                print(f"    decision=OFI_TOXIC_HARD  {_ofi_reason}")
                
                # V10.13j: Log OFI hard block telemetry
                try:
                    from src.services.adaptive_block_telemetry import log_ofi_block
                    log_ofi_block(
                        "OFI_TOXIC_HARD", sym, signal.get("action", "BUY"), _ofi_reason,
                        1.0, "HARD", "OFI toxicity exceeded 0.95 threshold (ultra-extreme)"
                    )
                except Exception:
                    pass
                
                return None

        # Always apply soft OFI size penalty (even for fallback)
        _ofi_size = _ofi_sf(sym, signal.get("action", "BUY"))
        if _ofi_size < 1.0:
            # V10.13h: Track if this is from soft penalty zone (0.70-0.95)
            # vs lighter penalty zone (0.40-0.70)
            if _ofi_size <= 0.60:
                _ofi_soft_blocked = True
                track_blocked(reason="OFI_TOXIC_SOFT")
            _fallback_str = " (fallback_soften)" if _unblock_fallback_used else ""
            print(f"    OFI penalty: size×{_ofi_size:.2f}{_fallback_str}")
            
            # V10.13j: Log OFI soft penalty telemetry
            try:
                from src.services.adaptive_block_telemetry import log_ofi_block
                penalty_type = "SOFT_HARD" if _ofi_size <= 0.60 else "SOFT_LIGHT"
                penalty_reason = f"OFI toxicity {_ofi_size:.2f}: applying size penalty"
                log_ofi_block(
                    f"OFI_SOFT_{penalty_type}", sym, signal.get("action", "BUY"), 
                    _ofi_reason, _ofi_size, "SOFT", penalty_reason
                )
            except Exception:
                pass
    except Exception:
        pass
    # Apply OFI size factor to auditor_factor
    if _ofi_size < 1.0:
        auditor_factor = min(1.0, auditor_factor * _ofi_size)

    # ════════════════════════════════════════════════════════════════════════════════
    # V10.12f: ANTI-DEADLOCK GUARD — Ensure non-zero pass-through during critical idle
    # ════════════════════════════════════════════════════════════════════════════════
    # If system is in critical idle (900s+) and this signal passes basic safety checks,
    # force acceptance to break deadlock. This is the ultimate fallback.
    _anti_deadlock_triggered = False
    if not _unblock_fallback_used and is_unblock_mode():
        try:
            # Check if signal passes minimum viability checks
            _has_positive_rr = rr >= MIN_RR
            _has_decent_ev = ev > 0.0 or (ev >= -0.05 and spread_pct <= 0.005)
            _is_new_pair = _M.get("trades", 0) < 100  # Still in learning phase
            _no_cluster_forever = sym not in _blocked_until
            
            # Force accept if all basic checks pass and system is stalled
            if _has_positive_rr and (_has_decent_ev or _is_new_pair) and _no_cluster_forever:
                _anti_deadlock_triggered = True
                _unblock_fallback_used = True
                record_unblock_trade()
                log.warning(f"[V10.12f_ANTI_DEADLOCK] {sym}  forcing micro-trade to break 900s+ stall  "
                           f"ev={ev:.4f}  rr={rr:.2f}  spread={spread_pct:.4f}")
        except Exception as _ad_err:
            log.debug("anti-deadlock error: %s", _ad_err)

    # ════════════════════════════════════════════════════════════════════════════════
    # V10.13p: REGIME-PAIR SUPPRESSION — Weak SOL/DOT BEAR_TREND segments
    # ════════════════════════════════════════════════════════════════════════════════
    # V10.13p adds stronger suppression for proven weak regime+pair combinations.
    # Live audit data shows:
    # - SOLUSDT_BEAR_TREND: 19% WR (extremely weak)
    # - DOTUSDT_BEAR_TREND: 31% WR (very weak)
    # Apply pair+regime suppression to reduce exposure to these toxic combinations
    # while preserving learning in other regimes.
    try:
        from src.services.learning_monitor import lm_pair_stats, _last_regime

        # V10.13p: Regime-aware pair suppression
        current_regime = _last_regime or "UNCERTAIN"
        regime_pair_key = f"{sym}_{current_regime}"

        if sym == "SOLUSDT" and current_regime == "BEAR_TREND":
            # SOL in BEAR_TREND: 19% WR — apply 50% size penalty
            rp_record = lm_pair_stats.get(regime_pair_key, {})
            rp_wr = rp_record.get("wr", 0.5)
            if rp_wr < 0.30:  # Well below target
                auditor_factor = min(1.0, auditor_factor * 0.50)  # 50% size penalty
                print(f"    [V10.13p] SOL_BEAR_SUPPRESSION: wr={rp_wr:.1%} → size×0.50")
                log.info(f"[V10.13p] {sym}_{current_regime}: 50% size penalty ({rp_wr:.1%} WR)")

        elif sym == "DOTUSDT" and current_regime == "BEAR_TREND":
            # DOT in BEAR_TREND: 31% WR — apply 40% size penalty
            rp_record = lm_pair_stats.get(regime_pair_key, {})
            rp_wr = rp_record.get("wr", 0.5)
            if rp_wr < 0.35:  # Well below target
                auditor_factor = min(1.0, auditor_factor * 0.60)  # 40% size penalty
                print(f"    [V10.13p] DOT_BEAR_SUPPRESSION: wr={rp_wr:.1%} → size×0.60")
                log.info(f"[V10.13p] {sym}_{current_regime}: 40% size penalty ({rp_wr:.1%} WR)")
    except Exception as _regime_pair_err:
        log.debug("Regime-pair suppression check failed: %s", _regime_pair_err)

    # ════════════════════════════════════════════════════════════════════════════════
    # V10.13s: ABSOLUTE MINIMUM EV FLOOR — Prevent negative-edge trades
    # ════════════════════════════════════════════════════════════════════════════════
    # Log analysis shows trades with EV=-0.2125 being forced through in recovery mode.
    # This is dangerous: even with unblock mode active, reject materially negative EV.
    # Unblock should soften filters, not eliminate edge sanity.
    # V10.13t: HARD enforcement — only positive EV trades
    # BUG FIX: Previous threshold of -0.05 allowed negative EV like -0.0399 through
    # Core principle violation: EV-only means NO negative-expectation trades
    if ev <= 0:
        print(f"    decision=REJECT_NEGATIVE_EV  ev={ev:.4f} ≤ 0 (EV-only violation)")
        track_blocked(reason="NEGATIVE_EV_REJECTION")
        log.warning(f"[V10.13t] {sym}: Rejected negative/zero EV (ev={ev:.4f}) — hard enforcement of EV-only principle")
        return None

    # ════════════════════════════════════════════════════════════════════════════════
    # V10.13o: PAIR-LEVEL CAUTION — ADA size penalty
    # ════════════════════════════════════════════════════════════════════════════════
    # ADA has shown persistent weak performance (42% WR in live data) across multiple
    # checkpoints. Apply a lightweight size penalty (0.75×) to restrict risk until
    # pair-level performance improves. This is not a hard block — ADA can still trade
    # but at reduced size, preserving learning opportunity while limiting downside.
    if sym == "ADAUSDT":
        try:
            from src.services.learning_monitor import lm_pair_stats
            # Check ADA's overall record
            ada_record = lm_pair_stats.get(sym, {})
            ada_wr = ada_record.get("wr", 0.5)

            if ada_wr < 0.45:  # Well below target 54%
                auditor_factor = min(1.0, auditor_factor * 0.75)  # 25% size penalty
                print(f"    [V10.13o] ADA_PAIR_CAUTION: wr={ada_wr:.1%} → size×0.75")
                log.info(f"[V10.13o] {sym}: applying 25% size penalty due to weak pair-level WR ({ada_wr:.1%})")
        except Exception as _ada_err:
            log.debug("ADA pair caution check failed: %s", _ada_err)

    # V10.12e: Add unblock state and size multiplier to signal
    _unblock_size_mult = unblock_size_multiplier()
    _is_unblock = is_unblock_mode()

    signal["confidence"]      = round(win_prob, 4)
    signal["ev"]              = round(ev, 4)
    signal["auditor_factor"]  = round(auditor_factor, 4)
    signal["velocity_penalty"] = round(velocity_penalty, 3)
    signal["streak_penalty"]   = round(streak_penalty, 3)
    signal["combo_penalty"]    = round(combo_pen, 3)
    signal["unblock_mode"]     = _is_unblock
    signal["unblock_fallback"] = _unblock_fallback_used
    signal["anti_deadlock"]    = _anti_deadlock_triggered
    signal["unblock_size_mult"] = _unblock_size_mult
    
    # V10.12f: Enhanced decision logging with unblock state and anti-deadlock info
    _ub_str = f" unblock=True fallback={_unblock_fallback_used} anti_deadlock={_anti_deadlock_triggered} size×{_unblock_size_mult:.2f}" if _is_unblock else ""
    print(f"    decision=TAKE  ev={ev:.4f}  p={win_prob:.4f}  "
          f"af={auditor_factor:.2f}  coh={_coh:.3f}{_ub_str}")

    # B16: conv-rate tracking — signal accepted
    try:
        from src.services.signal_filter import log_signal_outcome as _lso4
        _lso4(sym, accepted=True)
        from src.services.learning_event import METRICS as _M_take
        _M_take["signals_accepted"] = _M_take.get("signals_accepted", 0) + 1
    except Exception:
        pass

    # Update last_signals immediately so dashboard shows current bot intent
    try:
        from src.services.learning_event import track_signal
        track_signal(
            symbol   = signal.get("symbol", ""),
            action   = signal.get("action", "HOLD"),
            price    = float(signal.get("price", 0)),
            confidence = win_prob,
            ev       = ev,
            regime   = signal.get("regime", "RANGING"),
        )
    except Exception:
        pass

    return signal
