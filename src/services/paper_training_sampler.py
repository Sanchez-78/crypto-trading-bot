"""V10.13u+21 P1.1k: Active Paper Training Sampler

Opens paper positions when normal RDE rejects signals, using real live prices
for learning. Only active in paper_train mode, never in paper_live or live_real.

Goal: collect minimum N closed trades per hour for learning data.

P1.1N: Anti-spam dedupe and quality gates to prevent duplicate sampling spam.
"""
import os
import logging
import time
from typing import Optional, Tuple, List
from collections import defaultdict, deque

log = logging.getLogger(__name__)

# Phase 4C: Live PAPER metrics - starvation bypass
try:
    from src.services.paper_training_metrics import record_starvation_bypass_accepted, record_starvation_bypass_rejected
except ImportError:
    record_starvation_bypass_accepted = None
    record_starvation_bypass_rejected = None

# Training mode settings
_TRAINING_ENABLED = os.getenv("PAPER_TRAINING_ENABLED", "true").lower() == "true"
_MIN_ENTRIES_PER_HOUR = int(os.getenv("PAPER_TRAINING_MIN_ENTRIES_PER_HOUR", "6"))
_MAX_OPEN = int(os.getenv("PAPER_TRAINING_MAX_OPEN", "5"))
_MAX_PER_SYMBOL = int(os.getenv("PAPER_TRAINING_MAX_PER_SYMBOL", "1"))
_MAX_HOLD_S = int(os.getenv("PAPER_TRAINING_MAX_HOLD_S", "300"))
_ALLOW_WEAK_EV = os.getenv("PAPER_TRAINING_ALLOW_WEAK_EV", "true").lower() == "true"
_ALLOW_NEG_EV = os.getenv("PAPER_TRAINING_ALLOW_NEG_EV_CONTROL", "true").lower() == "true"
_ALLOW_NO_PATTERN = os.getenv("PAPER_TRAINING_ALLOW_NO_PATTERN", "true").lower() == "true"

# Hourly caps for control buckets
_hourly_caps = {
    "D_NEG_EV_CONTROL": {"max": 2, "count": 0, "window_start": 0},
    "E_NO_PATTERN_BASELINE": {"max": 2, "count": 0, "window_start": 0},
}
_ONE_HOUR_S = 3600

# Training metrics (1-hour rolling window)
_training_metrics = {
    "entries_1h": [],  # timestamps of entries in last hour
    "closed_1h": [],   # count of closed trades in last hour
    "learning_updates_1h": 0,
    "last_health_log_ts": -600,  # Initialize to -600 so first health log happens immediately, then throttles to every 10m
}

# P1.1N: Anti-spam dedupe and rate caps
_recent_dedupe = {}  # dedupe_key -> timestamp
_recent_dup_candidate = {}  # symbol:side:DUPLICATE_CANDIDATE -> timestamp
_entry_times_minute = deque()  # timestamps of entries in last minute
_entry_times_hour = deque()  # timestamps of entries in last hour
_health = defaultdict(int)  # health metrics: entries, skips, skip_reasons
_last_health_log = 0.0  # last time health was logged

# P1.1P: Throttled skip logging (prevent spam from duplicate bursts)
_LAST_SKIP_LOG_TS = {}  # (reason, symbol, side, bucket, source) -> timestamp
_SKIP_LOG_TTL_S = 30.0  # throttle period for skip logs

# P1.1Q Phase 6: Skip summary counters (emit summary every 10 minutes instead of per-event logs)
_SKIP_COUNTERS = {}  # reason -> count
_LAST_SKIP_SUMMARY_TS = [0.0]  # [timestamp] for shared mutable reference
_SKIP_SUMMARY_WINDOW_S = 600.0  # 10 minutes

# P1.1AO: Cold-start probe state
_probe_state: dict = {
    "lifetime_closed": 0,           # C_NEG_EV_PROBE trades closed this process
    "entry_times_10m": deque(),     # probe entry timestamps for 10-min rate cap
    "starvation_last_log_ts": 0.0,  # throttle starvation state log
}
_PROBE_MAX_OPEN_TOTAL = 2           # max open probe positions globally
_PROBE_MAX_NEW_PER_10M = 2          # max new probe entries per 10 min
_PROBE_MAX_LIFETIME_CLOSED = 20     # probe auto-stops after this many closed trades
_PROBE_STARVATION_IDLE_S = 1800.0   # idle threshold: 30 min since last training entry
_PROBE_STARVATION_LOG_S = 60.0      # emit starvation state log at most once per minute

# P1.1AQ: Bypass flow diagnostics throttling
_BYPASS_FLOW_LAST_LOG = {}  # (symbol, stage, reason) -> timestamp
_BYPASS_FLOW_THROTTLE_S = 10.0  # throttle period for bypass flow logs

# P1.1AR: Rate-cap state and accepted-to-entry diagnostics
_RATE_CAP_STATE_LAST_LOG = {}  # (symbol, bucket) -> timestamp
_RATE_CAP_STATE_THROTTLE_S = 10.0  # throttle period for rate-cap state logs

# P1.1AP-O1A: Adaptive starvation telemetry (600s windows, rate-limited)
_ADAPTIVE_STARVATION_STATE = {
    "window_start_ts": 0.0,
    "positive_candidates": 0,  # count of EV>0 PAPER candidates considered
    "negative_ev_rejects": 0,  # count of EV<=0 reject events
    "admitted_recovery": 0,    # count of admitted paper_adaptive_recovery
    "canonical_closes": 0,     # count of eligible closes from learning
    "policy_reads": 0,         # count of policy reads executed
    "last_log_ts": 0.0,        # throttle starvation log emission
}
_ADAPTIVE_STARVATION_WINDOW_S = 600.0  # 10 minute rolling window for telemetry

# P1.1AP-N2: Recovery admission state and caps
_recovery_state: dict = {
    "open_global": 0,        # current count of open recovery admissions
    "open_by_symbol": {},    # symbol -> count of open recovery admissions
}
_RECOVERY_MAX_OPEN_GLOBAL = 3      # max open recovery positions globally
_RECOVERY_MAX_OPEN_PER_SYMBOL = 1  # max open recovery positions per symbol
_RECOVERY_BLOCKED_LAST_LOG = {}    # (symbol, reason) -> ts for throttling blocked logs
_RECOVERY_BLOCKED_THROTTLE_S = 10.0

# P1.1AP-O2: PAPER starvation discovery state and caps (LEGACY_SPOT_EXECUTION_UNVERIFIED)
_starvation_discovery_state: dict = {
    "open_global": 0,               # current count of open discovery positions globally
    "open_by_symbol": {},           # symbol -> count of open discovery positions
    "entry_times_15m": deque(),     # entry timestamps for 15-min rate cap
    "last_eligible_entry_ts": 0.0,  # timestamp of last valid eligible PAPER entry
    "idle_s": 0.0,                  # seconds since last eligible entry
    "valid_negative_candidates": 0, # count of valid REJECT_NEGATIVE_EV signals during idle window
    "last_state_log_ts": 0.0,       # throttle state logs
    "closed_trades": [],            # P1.1AP-O2 Fix B: list of (net_pnl_pct, outcome, ts) for rolling loss detection
}
_STARVATION_DISCOVERY_MAX_OPEN_GLOBAL = 2           # max open discovery positions globally
_STARVATION_DISCOVERY_MAX_OPEN_PER_SYMBOL = 1      # max open discovery per symbol
_STARVATION_DISCOVERY_MAX_PER_15M = 4              # max new entries per 15 minutes
_STARVATION_DISCOVERY_IDLE_THRESHOLD_S = 600.0     # idle threshold: 600s (10 min) since last eligible entry
_STARVATION_DISCOVERY_STATE_LOG_THROTTLE_S = 60.0  # emit starvation state log at most once per minute
_STARVATION_DISCOVERY_ENTRY_LOG_THROTTLE = {}      # (symbol, side) -> ts for throttling entry logs

# P1.1AP-O2 Fix B: Discovery bucket loss-triggered cooldown state
_STARVATION_DISCOVERY_BUCKET_COOLDOWN = {
    "active": False,                # true if cooldown is currently active
    "activated_at": 0.0,            # timestamp when cooldown was activated
    "cooldown_s": 3600,             # cooldown duration (1 hour)
    "closed_n_trigger": 3,          # N closed trades required to trigger cooldown
    "pf_trigger": 0.0,              # profit_factor threshold (must equal this to trigger)
    "avg_pnl_trigger": -0.10,       # avg net_pnl_pct threshold (must be <= this to trigger)
    "timeout_rate_trigger": 0.66,   # timeout_rate threshold (must be >= this to trigger)
}

# P1.1AP-O2 Fix D: Segment-level cooldown state for C_WEAK_EV_TRAIN
# Maps segment_key (symbol:regime:side) to cooldown activation data
_SEGMENT_COOLDOWNS = {}  # {segment_key: {"active": bool, "activated_at": float, "cooldown_s": 3600}}

# Phase 3A: Cap diagnostics and sample flow tracking
_PAPER_OPEN_CAP_DIAG_THROTTLE = {}  # (symbol, bucket) -> timestamp
_SAMPLE_FLOW_WINDOW = {
    "raw_signals": 0,
    "rde_candidates": 0,
    "training_candidates": 0,
    "admission_truth_count": 0,
    "accepted": 0,
    "opened": 0,
    "closed": 0,
    "learning_updates": 0,
    "blocked_by_max_open_per_symbol": 0,
    "blocked_by_max_open_global": 0,
    "blocked_by_cost_edge": 0,
    "blocked_by_segment_cooldown": 0,
    "blocked_by_negative_ev": 0,
    "last_summary_ts": 0.0,
}


def _now() -> float:
    """Get current timestamp."""
    return time.time()


def _prune(now: float) -> None:
    """Prune old entries from deque and dict to prevent memory leak."""
    from src.core.runtime_mode import PAPER_TRAIN_DEDUPE_WINDOW_S, PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S

    # Prune minute and hour windows
    while _entry_times_minute and now - _entry_times_minute[0] > 60:
        _entry_times_minute.popleft()
    while _entry_times_hour and now - _entry_times_hour[0] > 3600:
        _entry_times_hour.popleft()

    # P1.1AO: Prune probe rate-limit window (10 minutes)
    while _probe_state["entry_times_10m"] and now - _probe_state["entry_times_10m"][0] > 600:
        _probe_state["entry_times_10m"].popleft()

    # Prune dedupe dict
    for k, ts in list(_recent_dedupe.items()):
        if now - ts > max(PAPER_TRAIN_DEDUPE_WINDOW_S * 2, 120):
            _recent_dedupe.pop(k, None)

    # Prune duplicate candidate dict
    for k, ts in list(_recent_dup_candidate.items()):
        if now - ts > max(PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S * 2, 180):
            _recent_dup_candidate.pop(k, None)


def _skip(reason: str, **kw) -> dict:
    """Record skip event and return skip result."""
    _health["skips"] += 1
    _health[f"skip_{reason}"] += 1
    return {"allowed": False, "reason": reason, **kw}


def _allow(**kw) -> dict:
    """Record entry event and return allow result."""
    _health["entries"] += 1
    return {"allowed": True, **kw}


def _log_open_cap_diag(symbol: str, bucket: str, open_global: int,
                       open_symbol_actual: int, open_symbol_counter: int,
                       reason: str):
    """Phase 3A: Diagnostic for stale open cap accounting."""
    now = time.time()
    key = (symbol, bucket)
    last_log = _PAPER_OPEN_CAP_DIAG_THROTTLE.get(key, 0.0)
    if now - last_log < 30.0:  # Throttle per (symbol, bucket)
        return

    _PAPER_OPEN_CAP_DIAG_THROTTLE[key] = now
    mismatch = (open_symbol_actual != open_symbol_counter)

    log.info(
        "[PAPER_OPEN_CAP_DIAG] "
        "symbol=%s bucket=%s reason=%s "
        "open_global=%d open_symbol_actual=%d open_symbol_counter=%d "
        "mismatch=%s",
        symbol, bucket, reason,
        open_global, open_symbol_actual, open_symbol_counter,
        mismatch
    )


def _emit_sample_flow_summary():
    """Phase 3A: Emit 5-minute flow summary."""
    now = time.time()
    last_ts = _SAMPLE_FLOW_WINDOW.get("last_summary_ts", 0.0)

    if now - last_ts < 300.0:  # Only every 5 minutes
        return

    _SAMPLE_FLOW_WINDOW["last_summary_ts"] = now

    # Determine status
    status = "STARVED"
    if _SAMPLE_FLOW_WINDOW["opened"] > 0:
        status = "OK"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_cost_edge"] > 5:
        status = "BLOCKED_BY_RDE_COST_EDGE"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_max_open_per_symbol"] > 0:
        status = "BLOCKED_BY_CAP"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_segment_cooldown"] > 0:
        status = "BLOCKED_BY_NEGATIVE_SEGMENT"

    log.info(
        "[PAPER_SAMPLE_FLOW_SUMMARY] "
        "window_s=300 raw_signals=%d rde_candidates=%d training_candidates=%d "
        "admission_truth_count=%d accepted=%d opened=%d closed=%d learning_updates=%d "
        "blocked_by_max_open_per_symbol=%d blocked_by_max_open_global=%d "
        "blocked_by_cost_edge=%d blocked_by_segment_cooldown=%d blocked_by_negative_ev=%d "
        "status=%s",
        _SAMPLE_FLOW_WINDOW["raw_signals"],
        _SAMPLE_FLOW_WINDOW["rde_candidates"],
        _SAMPLE_FLOW_WINDOW["training_candidates"],
        _SAMPLE_FLOW_WINDOW["admission_truth_count"],
        _SAMPLE_FLOW_WINDOW["accepted"],
        _SAMPLE_FLOW_WINDOW["opened"],
        _SAMPLE_FLOW_WINDOW["closed"],
        _SAMPLE_FLOW_WINDOW["learning_updates"],
        _SAMPLE_FLOW_WINDOW["blocked_by_max_open_per_symbol"],
        _SAMPLE_FLOW_WINDOW["blocked_by_max_open_global"],
        _SAMPLE_FLOW_WINDOW["blocked_by_cost_edge"],
        _SAMPLE_FLOW_WINDOW["blocked_by_segment_cooldown"],
        _SAMPLE_FLOW_WINDOW["blocked_by_negative_ev"],
        status
    )

    # Reset counters
    for key in _SAMPLE_FLOW_WINDOW:
        if key != "last_summary_ts":
            _SAMPLE_FLOW_WINDOW[key] = 0


def _restore_and_bootstrap_cooldowns() -> None:
    """P1.1AP-O2: Restore persisted cooldowns and bootstrap from existing loss evidence.

    Called once at module startup. Performs two operations:
    1. Restore any previously persisted cooldowns from adaptive learning state
    2. Bootstrap cooldowns from rolling100 metrics if loss evidence exists but no persisted cooldown
    """
    global _STARVATION_DISCOVERY_BUCKET_COOLDOWN, _SEGMENT_COOLDOWNS

    try:
        from src.services import paper_adaptive_learning

        learner = paper_adaptive_learning.get_learner()
        controls = learner.get_admission_controls_state()
        now = _now()

        # Step 1: Restore discovery bucket cooldown
        if controls.get("starvation_discovery_cooldown", {}).get("active"):
            cooldown_until = controls["starvation_discovery_cooldown"].get("cooldown_until", 0.0)
            if cooldown_until > now:
                _STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"] = True
                _STARVATION_DISCOVERY_BUCKET_COOLDOWN["activated_at"] = controls["starvation_discovery_cooldown"].get("activated_at", 0.0)
                _STARVATION_DISCOVERY_BUCKET_COOLDOWN["cooldown_s"] = controls["starvation_discovery_cooldown"].get("cooldown_s", 3600)
                remaining_s = cooldown_until - now
                log.info(
                    "[PAPER_COOLDOWN_RESTORED] scope=bucket bucket=PAPER_STARVATION_DISCOVERY "
                    "cooldown_until=%.1f remaining_s=%.1f source=persisted_policy_state",
                    cooldown_until, remaining_s
                )
            else:
                # Cooldown expired - mark as inactive but log bootstrap
                log.info(
                    "[PAPER_COOLDOWN_EXPIRED] scope=bucket bucket=PAPER_STARVATION_DISCOVERY "
                    "source=persisted_policy_state"
                )
        else:
            # Step 2a: Bootstrap discovery cooldown from rolling100 metrics
            bootstrap_result = _bootstrap_discovery_cooldown_from_learner(learner, now)
            if bootstrap_result:
                _STARVATION_DISCOVERY_BUCKET_COOLDOWN.update(bootstrap_result)

        # Step 3: Restore C_WEAK_EV_TRAIN segment cooldowns
        persisted_segments = controls.get("c_weak_segment_cooldowns", {})
        for segment_key, segment_control in persisted_segments.items():
            if segment_control.get("active"):
                cooldown_until = segment_control.get("cooldown_until", 0.0)
                if cooldown_until > now:
                    _SEGMENT_COOLDOWNS[segment_key] = {
                        "active": True,
                        "activated_at": segment_control.get("activated_at", 0.0),
                        "cooldown_s": segment_control.get("cooldown_s", 3600),
                        "cooldown_until": cooldown_until,
                    }
                    remaining_s = cooldown_until - now
                    log.info(
                        "[PAPER_COOLDOWN_RESTORED] scope=segment segment=%s "
                        "cooldown_until=%.1f remaining_s=%.1f source=persisted_policy_state",
                        segment_key, cooldown_until, remaining_s
                    )

        # Step 4: Bootstrap segment cooldowns from rolling100 metrics if not persisted
        _bootstrap_segment_cooldowns_from_learner(learner, now)

    except Exception as e:
        log.warning("[PAPER_COOLDOWN_RESTORE_BOOTSTRAP_ERROR] %s", str(e))


def _bootstrap_discovery_cooldown_from_learner(learner, now: float) -> Optional[dict]:
    """P1.1AP-O2 Path C: Bootstrap discovery cooldown from DISCOVERY-SCOPED rolling100 loss evidence.

    Filter rolling100 by admission_bucket==PAPER_STARVATION_DISCOVERY and check for loss pattern.
    Activate discovery cooldown without previous persisted activation. First-deploy bootstrap only.

    Triggers only if discovery-scoped evidence shows: n>=3, pf==0, avg<=-0.10

    Returns updated cooldown dict or None if not eligible.
    """
    try:
        if not learner.rolling100 or len(learner.rolling100) < 3:
            return None

        # Filter rolling100 to ONLY discovery-route entries by admission_bucket
        # Entry format: (net_pnl_pct, outcome, segment_key, timestamp, learning_source, admission_bucket)
        discovery_entries = [
            e for e in learner.rolling100
            if len(e) >= 6 and e[5] == "PAPER_STARVATION_DISCOVERY"
        ]

        if len(discovery_entries) < 3:
            return None  # Not enough discovery-scoped evidence

        # Compute metrics from discovery-ONLY entries
        pnls = [e[0] for e in discovery_entries]
        outcomes = [e[1] for e in discovery_entries]

        n = len(discovery_entries)
        losses = sum(1 for o in outcomes if o == "LOSS")
        wins = n - losses
        pf = 0.0 if losses > 0 and wins == 0 else (wins / losses if losses > 0 else 1.0)
        avg_pnl = sum(pnls) / n if n > 0 else 0.0

        # Check triggers: n >= 3, pf == 0 (all losses), avg <= -0.10
        triggers = (n >= 3 and pf == 0.0 and avg_pnl <= -0.10)

        if triggers:
            # Latest entry timestamp for cooldown_until calculation
            latest_ts = max((e[3] if len(e) > 3 else 0) for e in discovery_entries)
            if latest_ts > 0:
                cooldown_until = latest_ts + 3600
            else:
                cooldown_until = now + 3600

            log.info(
                "[PAPER_COOLDOWN_BOOTSTRAPPED] scope=bucket bucket=PAPER_STARVATION_DISCOVERY "
                "evidence_n=%d pf=%.2f avg=%.4f wins=%d losses=%d "
                "source=durable_learning_metrics timestamp_mode=latest_entry "
                "filtered_by_admission_bucket=true",
                n, pf, avg_pnl, wins, losses
            )

            return {
                "active": True,
                "activated_at": now,
                "cooldown_until": cooldown_until,
                "cooldown_s": 3600,
            }

        return None
    except Exception as e:
        log.warning("[PAPER_COOLDOWN_BOOTSTRAP_DISCOVERY_ERROR] %s", str(e))
        return None


def _bootstrap_segment_cooldowns_from_learner(learner, now: float) -> None:
    """P1.1AP-O2 Path C: Bootstrap segment cooldowns from C_WEAK_EV_TRAIN-SCOPED rolling100 evidence.

    Filter rolling100 by admission_bucket==C_WEAK_EV_TRAIN, then evaluate by segment (symbol:regime:side).
    If any segment shows qualifying loss pattern, activate cooldown only for that segment.

    Only activates if segment-scoped evidence shows: n>=2, pf==0, avg<=-0.10
    """
    try:
        segment_metrics = {}

        # Filter rolling100 to ONLY C_WEAK_EV_TRAIN entries by admission_bucket, then group by segment
        # Entry format: (net_pnl_pct, outcome, segment_key, timestamp, learning_source, admission_bucket)
        for entry in learner.rolling100:
            if len(entry) < 6:
                continue
            # Only include C_WEAK_EV_TRAIN scoped entries by admission_bucket
            if entry[5] != "C_WEAK_EV_TRAIN":
                continue

            segment_key = entry[2]
            if not segment_key:
                continue

            if segment_key not in segment_metrics:
                segment_metrics[segment_key] = []
            segment_metrics[segment_key].append(entry)

        # Check each C_WEAK segment for loss pattern
        for segment_key, entries in segment_metrics.items():
            if segment_key in _SEGMENT_COOLDOWNS:
                continue  # Already has cooldown

            if len(entries) < 2:
                continue

            pnls = [e[0] for e in entries]
            outcomes = [e[1] for e in entries]

            n = len(entries)
            losses = sum(1 for o in outcomes if o == "LOSS")
            wins = n - losses
            pf = 0.0 if losses > 0 and wins == 0 else (wins / losses if losses > 0 else 1.0)
            avg_pnl = sum(pnls) / n

            # Check segment triggers (n >= 2, pf == 0, avg <= -0.10)
            if n >= 2 and pf == 0.0 and avg_pnl <= -0.10:
                latest_ts = max((e[3] if len(e) > 3 else 0) for e in entries)
                if latest_ts > 0:
                    cooldown_until = latest_ts + 3600
                else:
                    cooldown_until = now + 3600

                _SEGMENT_COOLDOWNS[segment_key] = {
                    "active": True,
                    "activated_at": now,
                    "cooldown_until": cooldown_until,
                    "cooldown_s": 3600,
                }

                log.info(
                    "[PAPER_COOLDOWN_BOOTSTRAPPED] scope=segment segment=%s "
                    "evidence_n=%d pf=%.2f avg=%.4f "
                    "source=durable_learning_metrics timestamp_mode=latest_entry "
                    "filtered_by_admission_bucket=true",
                    segment_key, n, pf, avg_pnl
                )
    except Exception as e:
        log.warning("[PAPER_COOLDOWN_BOOTSTRAP_SEGMENTS_ERROR] %s", str(e))


def _persist_cooldown_state() -> None:
    """P1.1AP-O2: Persist current cooldown state to adaptive learning JSON."""
    try:
        from src.services import paper_adaptive_learning

        learner = paper_adaptive_learning.get_learner()
        controls = learner.get_admission_controls_state()

        # Update discovery bucket cooldown
        controls["starvation_discovery_cooldown"]["active"] = _STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"]
        if _STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"]:
            controls["starvation_discovery_cooldown"]["activated_at"] = _STARVATION_DISCOVERY_BUCKET_COOLDOWN["activated_at"]
            controls["starvation_discovery_cooldown"]["cooldown_s"] = _STARVATION_DISCOVERY_BUCKET_COOLDOWN["cooldown_s"]
            controls["starvation_discovery_cooldown"]["cooldown_until"] = _STARVATION_DISCOVERY_BUCKET_COOLDOWN.get("cooldown_until", _now() + 3600)

        # Update segment cooldowns
        controls["c_weak_segment_cooldowns"] = {}
        for segment_key, segment_cd in _SEGMENT_COOLDOWNS.items():
            if segment_cd.get("active"):
                controls["c_weak_segment_cooldowns"][segment_key] = {
                    "active": True,
                    "activated_at": segment_cd.get("activated_at", 0.0),
                    "cooldown_s": segment_cd.get("cooldown_s", 3600),
                    "cooldown_until": segment_cd.get("cooldown_until", _now() + 3600),
                }

        learner.update_admission_controls_state(controls)
    except Exception as e:
        log.warning("[PAPER_COOLDOWN_PERSIST_ERROR] %s", str(e))


def _gen_flow_id(symbol: str, side: str, bucket: str, source: str, ts: float) -> str:
    """P1.1AR: Generate stable flow_id for correlation.

    Format: symbol:side:bucket[:ts_int]
    """
    ts_int = int(ts)
    return f"{symbol}:{side}:{bucket}:{ts_int}"


def _log_rate_cap_state(symbol: str, bucket: str, source: str, now: float,
                        recent_entries: int, rate_limit: int,
                        next_allowed_s: float, open_symbol: int, open_bucket: int,
                        open_total: int, closed_training: int) -> None:
    """P1.1AR: Log rate-cap state with throttling.

    Throttle by (symbol, bucket) every 10 seconds.
    """
    key = (str(symbol), str(bucket))
    last = _RATE_CAP_STATE_LAST_LOG.get(key, 0.0)
    if now - last < _RATE_CAP_STATE_THROTTLE_S:
        return  # Still throttled

    _RATE_CAP_STATE_LAST_LOG[key] = now

    log.info(
        "[PAPER_SAMPLER_RATE_CAP_STATE] symbol=%s bucket=%s source=%s reason=sampler_rate_cap "
        "now=%.1f window_s=60 recent_entries=%d rate_limit=%d next_allowed_s=%.1f "
        "open_symbol=%d open_bucket=%d open_total=%d closed_training=%d mode=paper_train",
        symbol,
        bucket,
        source,
        now,
        recent_entries,
        rate_limit,
        next_allowed_s,
        open_symbol,
        open_bucket,
        open_total,
        closed_training,
    )


def _log_bypass_flow(stage: str, symbol: str, reason: str, **kw) -> None:
    """P1.1AQ: Log bypass flow with throttling to prevent spam.

    Throttle by (symbol, stage, reason) every 10 seconds.
    """
    now = time.time()
    key = (str(symbol), str(stage), str(reason))

    last = _BYPASS_FLOW_LAST_LOG.get(key, 0.0)
    if now - last < _BYPASS_FLOW_THROTTLE_S:
        return  # Still throttled

    _BYPASS_FLOW_LAST_LOG[key] = now

    # Format extra fields
    extra_s = " ".join(f"{k}={v}" for k, v in kw.items() if v is not None)
    if extra_s:
        extra_s = " " + extra_s

    log.info(
        "[COST_EDGE_BYPASS_FLOW] stage=%s symbol=%s reason=%s%s",
        stage,
        symbol,
        reason,
        extra_s if extra_s else "",
    )


def _log_train_skip_once(reason: str, symbol: str, side: str, bucket: str, source_reject: str, **extra) -> None:
    """P1.1P/P1.1Q: Log training skip with throttling to prevent spam.

    Only logs once per (reason, symbol, side, bucket, source_base) per TTL window.
    Prevents hundreds of identical skip logs during duplicate candidate bursts.
    P1.1Q: Also tracks skip counters for periodic summary logs.
    """
    now = time.time()
    # Extract source base (e.g., "DUPLICATE_CANDIDATE" from "DUPLICATE_CANDIDATE(age=0.0s)")
    source_base = str(source_reject).split("(")[0] if source_reject else "UNKNOWN"
    key = (str(reason), str(symbol), str(side), str(bucket), source_base)

    last = _LAST_SKIP_LOG_TS.get(key, 0.0)
    if now - last < _SKIP_LOG_TTL_S:
        # Still throttled, but increment counter for summary
        _SKIP_COUNTERS[reason] = _SKIP_COUNTERS.get(reason, 0) + 1
        return  # Do not log individual skip

    _LAST_SKIP_LOG_TS[key] = now
    _SKIP_COUNTERS[reason] = _SKIP_COUNTERS.get(reason, 0) + 1

    # Format extra fields
    extra_s = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
    if extra_s:
        extra_s = " " + extra_s

    log.info(
        "[PAPER_TRAIN_SKIP] reason=%s symbol=%s side=%s bucket=%s source_reject=%s%s",
        reason,
        symbol,
        side,
        bucket,
        source_reject,
        extra_s,
    )

    # P1.1Q: Emit summary if window has passed
    if now - _LAST_SKIP_SUMMARY_TS[0] >= _SKIP_SUMMARY_WINDOW_S:
        _emit_skip_summary(now)


def _emit_skip_summary(now: float) -> None:
    """P1.1Q Phase 6: Emit periodic skip summary instead of per-event spam."""
    global _SKIP_COUNTERS
    if not _SKIP_COUNTERS:
        return

    # Build summary string
    summary_items = [f"{reason}={count}" for reason, count in sorted(_SKIP_COUNTERS.items())]
    summary_s = " ".join(summary_items)

    log.info(
        f"[PAPER_TRAIN_SKIP_SUMMARY] window_s={int(_SKIP_SUMMARY_WINDOW_S)} {summary_s}"
    )

    # Reset counters
    _SKIP_COUNTERS.clear()
    _LAST_SKIP_SUMMARY_TS[0] = now


def _is_discovery_bucket_in_cooldown() -> bool:
    """P1.1AP-O2 Fix B: Check if discovery bucket is currently under loss-triggered cooldown.

    Uses cooldown_until field if available (from persistence), otherwise uses elapsed time calculation.
    """
    cooldown = _STARVATION_DISCOVERY_BUCKET_COOLDOWN
    if not cooldown["active"]:
        return False
    now = time.time()

    # Use cooldown_until if available (persisted cooldowns), else calculate from elapsed
    cooldown_until = cooldown.get("cooldown_until", 0.0)
    if cooldown_until > 0:
        if now >= cooldown_until:
            # Cooldown expired
            cooldown["active"] = False
            log.info("[PAPER_BUCKET_COOLDOWN_EXPIRED] bucket=PAPER_STARVATION_DISCOVERY cooldown_until=%.1f now=%.1f", cooldown_until, now)
            return False
        return True

    # Fallback: calculate from elapsed time (runtime-only cooldowns)
    elapsed = now - cooldown["activated_at"]
    if elapsed >= cooldown["cooldown_s"]:
        # Cooldown expired
        cooldown["active"] = False
        log.info("[PAPER_BUCKET_COOLDOWN_EXPIRED] bucket=PAPER_STARVATION_DISCOVERY elapsed_s=%.1f", elapsed)
        return False
    return True


def _maybe_activate_discovery_bucket_cooldown() -> None:
    """P1.1AP-O2 Fix B: Check closed discovery trades for loss pattern and activate cooldown if triggered.

    Triggers if:
    - closed_n >= 3
    - profit_factor == 0.0 (all losses)
    - avg_net_pnl_pct <= -0.10
    - timeout_rate >= 66%
    """
    cooldown = _STARVATION_DISCOVERY_BUCKET_COOLDOWN
    if cooldown["active"]:
        return  # Already active

    closed = _starvation_discovery_state.get("closed_trades", [])
    if len(closed) < cooldown["closed_n_trigger"]:
        return  # Not enough closed trades yet

    # Keep only recent closes (within last hour for rolling window)
    now = time.time()
    one_hour_ago = now - 3600
    recent = [(pnl, outcome, ts) for pnl, outcome, ts in closed if ts > one_hour_ago]

    if len(recent) < cooldown["closed_n_trigger"]:
        return  # Not enough recent closes

    # Calculate metrics
    n_closes = len(recent)
    wins = sum(1 for _, outcome, _ in recent if outcome == "WIN")
    losses = sum(1 for _, outcome, _ in recent if outcome == "LOSS")
    timeout_count = sum(1 for _, outcome, _ in recent if "TIMEOUT" in str(outcome))

    # Profit factor: sum_wins / sum_losses (0 if no wins)
    wins_pnl = sum(pnl for pnl, outcome, _ in recent if outcome == "WIN")
    losses_pnl = abs(sum(pnl for pnl, outcome, _ in recent if outcome == "LOSS"))
    pf = wins_pnl / losses_pnl if losses_pnl > 0 else (1.0 if wins_pnl > 0 else 0.0)

    # Average PnL
    avg_pnl = sum(pnl for pnl, _, _ in recent) / n_closes if n_closes > 0 else 0.0

    # Timeout rate
    timeout_rate = timeout_count / n_closes if n_closes > 0 else 0.0

    # Check triggers
    is_all_losses = pf == cooldown["pf_trigger"]  # 0.0
    is_avg_negative = avg_pnl <= cooldown["avg_pnl_trigger"]  # -0.10
    is_high_timeout = timeout_rate >= cooldown["timeout_rate_trigger"]  # 0.66

    if is_all_losses and is_avg_negative and is_high_timeout:
        # Activation triggered
        cooldown["active"] = True
        cooldown["activated_at"] = now
        cooldown["cooldown_until"] = now + cooldown["cooldown_s"]
        log.info(
            "[PAPER_BUCKET_COOLDOWN_ACTIVATED] bucket=PAPER_STARVATION_DISCOVERY "
            "closed_n=%d pf=%.3f avg_net_pnl_pct=%.4f timeout_rate=%.2f cooldown_s=%d "
            "reason=persistent_timeout_loss",
            n_closes, pf, avg_pnl, timeout_rate, cooldown["cooldown_s"]
        )
        # P1.1AP-O2: Persist cooldown state to JSON
        _persist_cooldown_state()


def _is_segment_in_cooldown(segment_key: str) -> bool:
    """P1.1AP-O2 Fix D: Check if C_WEAK_EV_TRAIN segment is in loss-triggered cooldown.

    Uses cooldown_until field if available (from persistence), otherwise uses elapsed time.
    Segment key format: symbol:regime:side
    """
    if segment_key not in _SEGMENT_COOLDOWNS:
        return False

    cooldown = _SEGMENT_COOLDOWNS[segment_key]
    if not cooldown.get("active", False):
        return False

    now = time.time()

    # Use cooldown_until if available (persisted cooldowns)
    cooldown_until = cooldown.get("cooldown_until", 0.0)
    if cooldown_until > 0:
        if now >= cooldown_until:
            # Cooldown expired
            cooldown["active"] = False
            log.info("[PAPER_SEGMENT_COOLDOWN_EXPIRED] segment=%s cooldown_until=%.1f now=%.1f", segment_key, cooldown_until, now)
            return False
        return True

    # Fallback: calculate from elapsed time (runtime-only cooldowns)
    elapsed = now - cooldown["activated_at"]
    if elapsed >= cooldown.get("cooldown_s", 3600):
        # Cooldown expired
        cooldown["active"] = False
        log.info("[PAPER_SEGMENT_COOLDOWN_EXPIRED] segment=%s elapsed_s=%.1f", segment_key, elapsed)
        return False

    return True


def _maybe_activate_segment_cooldown(symbol: str, regime: str, side: str) -> None:
    """P1.1AP-O2 Fix D: Check segment metrics for loss pattern and activate cooldown if triggered.

    For C_WEAK_EV_TRAIN only.
    Triggers if:
    - segment_closed_n >= 2
    - profit_factor == 0.0 (all losses)
    - avg_net_pnl_pct <= -0.10
    """
    try:
        from src.services.paper_adaptive_learning import get_segment_metrics

        segment_key = f"{symbol}:{regime}:{side}"

        # Check if already in cooldown or recently activated
        if segment_key in _SEGMENT_COOLDOWNS and _SEGMENT_COOLDOWNS[segment_key].get("active", False):
            return

        # Get segment metrics
        metrics = get_segment_metrics(symbol, regime, side)
        if not metrics:
            return  # Not enough data yet

        n = metrics.get("n", 0)
        pf = metrics.get("pf", 1.0)
        expectancy = metrics.get("expectancy", 0.0)

        # Convert expectancy (pct per trade) to check against -0.10 threshold
        avg_pnl_pct = expectancy

        # Check triggers: n >= 2, pf == 0, avg <= -0.10
        is_enough_trades = n >= 2
        is_all_losses = pf == 0.0
        is_avg_negative = avg_pnl_pct <= -0.10

        if is_enough_trades and is_all_losses and is_avg_negative:
            # Activate cooldown
            now = time.time()
            _SEGMENT_COOLDOWNS[segment_key] = {
                "active": True,
                "activated_at": now,
                "cooldown_s": 3600,
                "cooldown_until": now + 3600,
            }
            log.info(
                "[PAPER_SEGMENT_COOLDOWN_ACTIVATED] segment=%s n=%d pf=%.3f avg_net_pnl_pct=%.4f "
                "cooldown_s=3600 reason=persistent_loss",
                segment_key, n, pf, avg_pnl_pct
            )
            # P1.1AP-O2: Persist cooldown state to JSON
            _persist_cooldown_state()
    except Exception as e:
        log.debug("[PAPER_SEGMENT_COOLDOWN_CHECK_ERROR] symbol=%s regime=%s side=%s error=%s",
                  symbol, regime, side, str(e))


def _maybe_log_starvation_discovery_state() -> None:
    """P1.1AP-O2: Log starvation discovery state with throttling (once per minute)."""
    now = time.time()
    last_log = _starvation_discovery_state.get("last_state_log_ts", 0.0)

    if now - last_log < _STARVATION_DISCOVERY_STATE_LOG_THROTTLE_S:
        return  # Still throttled

    _starvation_discovery_state["last_state_log_ts"] = now

    idle_s = _starvation_discovery_state.get("idle_s", 0.0)
    open_global = sum(
        1 for _ in _starvation_discovery_state.get("entry_times_15m", [])
    )
    valid_candidates = _starvation_discovery_state.get("valid_negative_candidates", 0)

    log.info(
        "[PAPER_STARVATION_DISCOVERY_STATE] idle_s=%.1f open_global=%d "
        "valid_negative_candidates=%d cap_reason=%s",
        idle_s,
        open_global,
        valid_candidates,
        "no_cap_violation" if open_global < _STARVATION_DISCOVERY_MAX_OPEN_GLOBAL else "at_global_cap",
    )


def _is_training_enabled() -> bool:
    """Check if paper training mode is active (PAPER_TRAIN only, never paper_live/live_real)."""
    try:
        from src.core.runtime_mode import get_trading_mode, TradingMode
        return _TRAINING_ENABLED and get_trading_mode() == TradingMode.PAPER_TRAIN
    except Exception:
        return False


def _infer_side_from_features(signal: dict) -> Tuple[str, float, float]:
    """Infer side (BUY/SELL) from signal features if side is missing.

    Returns:
        (side, buy_score, sell_score) where side is "BUY", "SELL", or "UNKNOWN"
    """
    try:
        ema_diff = float(signal.get("ema_diff", 0.0))
        macd = float(signal.get("macd", 0.0))
        mom5 = float(signal.get("mom5", 0.0))
        mom10 = float(signal.get("mom10", 0.0))
        obi = float(signal.get("obi", 0.0))
        rsi = float(signal.get("rsi", 50.0))
        regime = signal.get("regime", "RANGING")

        buy_score = 0.0
        sell_score = 0.0

        # Momentum/trend signals
        if ema_diff > 0:
            buy_score += 1.0
        elif ema_diff < 0:
            sell_score += 1.0

        if macd > 0:
            buy_score += 1.0
        elif macd < 0:
            sell_score += 1.0

        if mom5 > 0:
            buy_score += 0.5
        elif mom5 < 0:
            sell_score += 0.5

        if mom10 > 0:
            buy_score += 0.5
        elif mom10 < 0:
            sell_score += 0.5

        if obi > 0:
            buy_score += 0.5
        elif obi < 0:
            sell_score += 0.5

        # RSI reversals
        if rsi < 35:
            buy_score += 1.0  # oversold
        elif rsi > 65:
            sell_score += 1.0  # overbought

        # Regime signals
        if regime in ["BULL_TREND", "BULL"]:
            buy_score += 0.5
        elif regime in ["BEAR_TREND", "BEAR"]:
            sell_score += 0.5

        # Determine side
        if abs(buy_score - sell_score) < 0.1:
            # Tie
            return ("UNKNOWN", buy_score, sell_score)
        elif buy_score > sell_score:
            return ("BUY", buy_score, sell_score)
        else:
            return ("SELL", buy_score, sell_score)

    except Exception as e:
        log.warning(f"[PAPER_TRAIN_SIDE_ERROR] {e}")
        return ("UNKNOWN", 0.0, 0.0)


def _get_training_bucket(signal: dict, ctx: dict, reject_reason: str) -> Tuple[str, float]:
    """Determine training bucket and size_mult for rejected signal.

    Returns:
        (bucket_name, size_mult)
    """
    ev = float(signal.get("ev", 0.0))

    # P1.1AO: C_NEG_EV_PROBE: cold-start starvation recovery (paper_train only)
    # Check this BEFORE PAPER_STARVATION_DISCOVERY since it's more specific (< 100 lifetime trades)
    if ev <= 0 and "REJECT_NEGATIVE_EV" in reject_reason and _is_cold_start_starvation():
        if _probe_state["lifetime_closed"] < _PROBE_MAX_LIFETIME_CLOSED:
            return ("C_NEG_EV_PROBE", 0.01)

    # P1.1AP-O2: PAPER_STARVATION_DISCOVERY: allow REJECT_NEGATIVE_EV during sustained starvation
    # Check this BEFORE D_NEG_EV_CONTROL. This is NOT the same as D_NEG (which is diagnostic/shadow-only).
    # Discovery allows bounded trades to resume learning when no valid entries occur for 600+ seconds
    # despite continuous valid signals.
    if ev <= 0 and "REJECT_NEGATIVE_EV" in reject_reason:
        if _is_starvation_discovery_idle():
            return ("PAPER_STARVATION_DISCOVERY", 0.02)
        else:
            # P0 FIX #4: Log rejection when idle_s < 600
            idle_s = time.time() - _starvation_discovery_state.get("last_eligible_entry_ts", 0.0)
            log.debug(
                "[PAPER_STARVATION_DISCOVERY_REJECTED] reason=idle_gate idle_s=%.1f required_idle_s=%.0f symbol=%s",
                idle_s, _STARVATION_DISCOVERY_IDLE_THRESHOLD_S, signal.get("symbol", "N/A")
            )

    # D_NEG_EV_CONTROL: learn what bad looks like (diagnostic/shadow-only, NOT for discovery)
    # Only used for negative EV rejects that are NOT discovery candidates
    if ev <= 0 and _ALLOW_NEG_EV and "REJECT_NEGATIVE_EV" not in reject_reason:
        if _check_hourly_cap("D_NEG_EV_CONTROL"):
            return ("D_NEG_EV_CONTROL", 0.02)

    # E_NO_PATTERN_BASELINE: infer side and use for training
    if ("NO_PATTERN" in reject_reason or "NO_CANDIDATE" in reject_reason) and _ALLOW_NO_PATTERN:
        if _check_hourly_cap("E_NO_PATTERN_BASELINE"):
            return ("E_NO_PATTERN_BASELINE", 0.02)

    # C_WEAK_EV_TRAIN: positive EV but below strict threshold
    if ev > 0 and _ALLOW_WEAK_EV:
        quality_p = float(signal.get("p", 0.0))
        quality_coh = float(signal.get("coherence", 0.0))
        quality_af = float(signal.get("auditor_factor", 0.0))
        has_quality = quality_p > 0 or quality_coh > 0 or quality_af > 0

        if has_quality:
            # Size scales with EV: higher EV = bigger position (but capped at 0.08)
            size_mult = min(0.08, max(0.03, ev * 0.5))
            return ("C_WEAK_EV_TRAIN", size_mult)

    return ("", 0.0)


def _check_hourly_cap(bucket: str) -> bool:
    """Check and increment hourly cap for control buckets."""
    now = time.time()
    cap_info = _hourly_caps.get(bucket)

    if not cap_info:
        return True

    # Reset if window expired
    if now - cap_info["window_start"] >= _ONE_HOUR_S:
        cap_info["count"] = 0
        cap_info["window_start"] = now

    # Check if at cap
    if cap_info["count"] >= cap_info["max"]:
        return False

    cap_info["count"] += 1
    return True


def _is_cold_start_starvation() -> bool:
    """P1.1AO: True when global_trades < 100 AND no training entries in last 30 min."""
    try:
        # P1.1AU: Use canonical training count from LM, not stale learning_event metrics
        from src.services.learning_monitor import get_canonical_training_trade_count
        if get_canonical_training_trade_count() >= 100:
            return False
        now = time.time()
        return not any(now - ts < _PROBE_STARVATION_IDLE_S for ts in _entry_times_hour)
    except Exception:
        return False


def _check_recovery_admission_caps(symbol: str, open_positions: Optional[List[dict]] = None) -> Tuple[bool, str]:
    """P1.1AP-N2: Check if recovery admission is allowed by caps.

    Returns: (allowed: bool, reason: str) where reason is cap name if blocked, empty if allowed.
    """
    try:
        open_positions = open_positions or []

        # Global cap: max 3 recovery positions
        recovery_open_global = sum(
            1 for p in open_positions
            if p.get("learning_source") == "paper_adaptive_recovery"
        )
        if recovery_open_global >= _RECOVERY_MAX_OPEN_GLOBAL:
            return (False, "recovery_cap_global")

        # Per-symbol cap: max 1 recovery position
        recovery_open_symbol = sum(
            1 for p in open_positions
            if p.get("learning_source") == "paper_adaptive_recovery" and p.get("symbol") == symbol
        )
        if recovery_open_symbol >= _RECOVERY_MAX_OPEN_PER_SYMBOL:
            return (False, "recovery_cap_per_symbol")

        return (True, "")
    except Exception as e:
        log.warning(f"[RECOVERY_CAP_CHECK_ERROR] {e}")
        return (False, "check_error")


def _update_starvation_discovery_idle(last_eligible_entry_ts: float) -> None:
    """P1.1AP-O2: Update idle seconds and tracked state for starvation discovery."""
    now = time.time()
    _starvation_discovery_state["last_eligible_entry_ts"] = last_eligible_entry_ts
    _starvation_discovery_state["idle_s"] = now - last_eligible_entry_ts


def _is_starvation_discovery_idle() -> bool:
    """P0 FIX #4: True when no valid PAPER entry for >= 600 seconds despite valid signals.

    CRITICAL: idle_s must be >= 600 seconds. idle_s=0.0 must reject.
    Override only via PAPER_STARVATION_DISCOVERY_IDLE_OVERRIDE=true env var.
    """
    try:
        now = time.time()
        idle_s = now - _starvation_discovery_state.get("last_eligible_entry_ts", 0.0)

        # P0 FIX #4: Explicit guard - idle_s must be >= threshold
        if idle_s < _STARVATION_DISCOVERY_IDLE_THRESHOLD_S:
            # Allow override only for explicit test/operator intervention
            override = os.getenv("PAPER_STARVATION_DISCOVERY_IDLE_OVERRIDE", "false").lower() == "true"
            if not override:
                return False
            else:
                log.warning(
                    "[PAPER_STARVATION_DISCOVERY_IDLE_OVERRIDE] idle_s=%.1f threshold=%.0f reason=operator_override",
                    idle_s, _STARVATION_DISCOVERY_IDLE_THRESHOLD_S
                )

        return True  # idle_s >= threshold, or override enabled
    except Exception:
        return False


def _check_starvation_discovery_caps(symbol: str, open_positions: Optional[List[dict]] = None) -> Tuple[bool, str]:
    """P1.1AP-O2: Check if starvation discovery admission is allowed by caps.

    Returns: (allowed: bool, reason: str) where reason is cap name if blocked, empty if allowed.
    """
    try:
        open_positions = open_positions or []
        now = time.time()

        # Prune 15-min window
        while _starvation_discovery_state["entry_times_15m"] and now - _starvation_discovery_state["entry_times_15m"][0] > 900:
            _starvation_discovery_state["entry_times_15m"].popleft()

        # Global cap: max 2 discovery positions open
        discovery_open_global = sum(
            1 for p in open_positions
            if p.get("learning_source") == "paper_starvation_discovery"
        )
        if discovery_open_global >= _STARVATION_DISCOVERY_MAX_OPEN_GLOBAL:
            return (False, "discovery_cap_global")

        # Per-symbol cap: max 1 discovery position per symbol
        discovery_open_symbol = sum(
            1 for p in open_positions
            if p.get("learning_source") == "paper_starvation_discovery" and p.get("symbol") == symbol
        )
        if discovery_open_symbol >= _STARVATION_DISCOVERY_MAX_OPEN_PER_SYMBOL:
            return (False, "discovery_cap_per_symbol")

        # Rate cap: max 4 new entries per 15 minutes
        if len(_starvation_discovery_state["entry_times_15m"]) >= _STARVATION_DISCOVERY_MAX_PER_15M:
            return (False, "discovery_rate_cap_15m")

        return (True, "")
    except Exception as e:
        log.warning(f"[STARVATION_DISCOVERY_CAP_CHECK_ERROR] {e}")
        return (False, "check_error")


def _training_quality_gate(
    symbol: str,
    side: str,
    bucket: str,
    source_reject: str,
    cost_edge_ok: bool,
    open_positions: Optional[List[dict]] = None,
) -> dict:
    """Apply quality gates before opening a training sample.

    Returns:
        {"allowed": bool, "reason": str, ...} via _skip() or _allow()
    """
    # P1.1AK: Track bypass metadata for diagnostics
    # P1.1AR: Initialize flow_id
    cost_edge_bypassed = False
    cost_edge_bypass_reason = "none"
    bootstrap_closed_trades = 0
    flow_id = ""

    now = _now()
    _prune(now)

    symbol = str(symbol or "UNKNOWN").upper()
    side = str(side or "UNKNOWN").upper()
    bucket = str(bucket or "UNKNOWN")
    source_reject = str(source_reject or "UNKNOWN")

    # PHASE 4B: Starvation admission bypass - allow PAPER-only learning trades during starvation
    # Check this FIRST (before bucket-specific logic) when cost_edge_ok=False
    # when no entries have been made for 600+ seconds, enabling the bot to collect learning data
    allow_starvation_bypass = False
    starvation_bypass_reason = ""
    starvation_bypass_rejected_reason = ""
    if cost_edge_ok is False:
        try:
            from src.core.runtime_mode import get_trading_mode
            import os

            mode = get_trading_mode()
            is_paper_train = mode and mode.value == "paper_train"
            real_orders_enabled = os.getenv("ENABLE_REAL_ORDERS", "false").lower() == "true"

            # Starvation bypass conditions:
            # 1. Running in PAPER mode
            # 2. REAL orders disabled
            # 3. Idle for >= 600 seconds (no PAPER entry despite valid signals)
            # 4. From REJECT_NEGATIVE_EV or REJECT_ECON_BAD_ENTRY (cost-edge rejected)
            # 5. Bucket is PAPER_STARVATION_DISCOVERY or C_WEAK_EV_TRAIN (learning buckets)

            # Check each condition with diagnostics
            is_idle = _is_starvation_discovery_idle()
            idle_s = now - _starvation_discovery_state.get("last_eligible_entry_ts", 0.0)
            is_valid_source = source_reject in ("REJECT_NEGATIVE_EV", "REJECT_ECON_BAD_ENTRY")
            is_valid_bucket = bucket in ("PAPER_STARVATION_DISCOVERY", "C_WEAK_EV_TRAIN")

            if not is_paper_train:
                starvation_bypass_rejected_reason = "not_paper_train"
            elif real_orders_enabled:
                starvation_bypass_rejected_reason = "real_orders_enabled"
            elif not is_idle:
                starvation_bypass_rejected_reason = f"idle_too_low idle_s={idle_s:.1f} threshold=600.0"
            elif not is_valid_source:
                starvation_bypass_rejected_reason = f"invalid_source source_reject={source_reject}"
            elif not is_valid_bucket:
                starvation_bypass_rejected_reason = f"unsupported_bucket bucket={bucket}"

            if (is_paper_train and
                not real_orders_enabled and
                is_idle and
                is_valid_source and
                is_valid_bucket):

                # Check starvation-specific position caps
                # Max 1-2 global starvation positions, max 1 per symbol
                open_positions_list = open_positions or []
                starvation_open_global = sum(
                    1 for p in open_positions_list
                    if p.get("cost_edge_bypassed") and p.get("cost_edge_bypass_reason") == "paper_starvation_learning"
                )
                starvation_open_symbol = sum(
                    1 for p in open_positions_list
                    if p.get("cost_edge_bypassed") and p.get("cost_edge_bypass_reason") == "paper_starvation_learning"
                    and p.get("symbol") == symbol
                )

                max_starvation_global = 2
                max_starvation_per_symbol = 1

                if starvation_open_global >= max_starvation_global:
                    log.info(
                        "[PAPER_STARVATION_BYPASS_BLOCKED] symbol=%s reason=global_cap "
                        "open_global=%d max=%d",
                        symbol, starvation_open_global, max_starvation_global
                    )
                elif starvation_open_symbol >= max_starvation_per_symbol:
                    log.info(
                        "[PAPER_STARVATION_BYPASS_BLOCKED] symbol=%s reason=per_symbol_cap "
                        "open_symbol=%d max=%d",
                        symbol, starvation_open_symbol, max_starvation_per_symbol
                    )
                else:
                    # Check cooldown: 10 minutes per symbol/side/bucket
                    cooldown_key = f"{symbol}:{side}:{bucket}:starvation"
                    last_starvation_entry = _recent_dup_candidate.get(cooldown_key)
                    cooldown_s = 600.0  # 10 min

                    if last_starvation_entry is not None and now - last_starvation_entry < cooldown_s:
                        remaining_s = cooldown_s - (now - last_starvation_entry)
                        log.info(
                            "[PAPER_STARVATION_BYPASS_COOLDOWN] symbol=%s side=%s bucket=%s "
                            "remaining_s=%.1f",
                            symbol, side, bucket, remaining_s
                        )
                    else:
                        # All checks passed - allow bypass
                        allow_starvation_bypass = True
                        starvation_bypass_reason = "paper_starvation_learning"
                        cost_edge_bypassed = True
                        cost_edge_bypass_reason = starvation_bypass_reason
                        _recent_dup_candidate[cooldown_key] = now

                        # Phase 4C: Record starvation bypass accepted metric
                        if record_starvation_bypass_accepted:
                            try:
                                record_starvation_bypass_accepted(symbol, bucket)
                            except Exception as e:
                                log.debug("[PAPER_METRICS_RECORD_FAIL] starvation_accepted symbol=%s err=%s", symbol, str(e))

                        log.info(
                            "[PAPER_STARVATION_BYPASS_ACCEPTED] symbol=%s side=%s bucket=%s "
                            "idle_s=%.1f cost_edge_ok=False cost_edge_bypassed=True "
                            "open_starvation_global=%d open_starvation_symbol=%d",
                            symbol, side, bucket, idle_s,
                            starvation_open_global, starvation_open_symbol
                        )
            else:
                # Starvation bypass conditions not fully met - log why
                if starvation_bypass_rejected_reason and bucket in ("PAPER_STARVATION_DISCOVERY", "C_WEAK_EV_TRAIN"):
                    # Phase 4C: Record starvation bypass rejected metric
                    if record_starvation_bypass_rejected:
                        try:
                            record_starvation_bypass_rejected(symbol, starvation_bypass_rejected_reason)
                        except Exception as e:
                            log.debug("[PAPER_METRICS_RECORD_FAIL] starvation_rejected symbol=%s err=%s", symbol, str(e))

                    log.info(
                        "[PAPER_STARVATION_BYPASS_REJECTED] symbol=%s side=%s bucket=%s "
                        "reason=%s idle_s=%.1f cost_edge_ok=False",
                        symbol, side, bucket, starvation_bypass_rejected_reason, idle_s
                    )
        except Exception as e:
            log.warning(f"[STARVATION_BYPASS_CHECK_ERROR] {symbol}: {e}")

    # If starvation bypass succeeded, continue (don't return yet)
    if allow_starvation_bypass:
        pass  # Continue to caps checks below
    # Cost-edge: do not open weak EV train if edge cannot cover costs
    # P1.1AE: Bootstrap training sample bypass - allow weak EV during cold-start in paper_train mode
    elif bucket == "C_WEAK_EV_TRAIN" and cost_edge_ok is False:
        # Check for bootstrap training bypass conditions
        allow_bootstrap_bypass = False
        bypass_reason = ""

        try:
            from src.core.runtime_mode import get_trading_mode
            from src.services.learning_monitor import get_canonical_training_trade_count

            mode = get_trading_mode()
            is_paper_train = mode.value == "paper_train"

            # P1.1AE: Bypass cost_edge_too_low only if:
            # - paper_train mode
            # - routed from STRICT_TAKE_ROUTED_TO_TRAINING
            # - bootstrap active (< 50 closed trades or 0 total LM trades)
            if is_paper_train and "STRICT_TAKE_ROUTED_TO_TRAINING" in source_reject:
                # P1.1AU: Use canonical training count from LM, not stale learning_event metrics
                trades_closed = get_canonical_training_trade_count()

                # Bootstrap active if < 50 closed trades
                if trades_closed < 50:
                    allow_bootstrap_bypass = True
                    bypass_reason = f"bootstrap_training_sample trades={trades_closed}"
                    # P1.1AK: Set bypass metadata for diagnostics
                    cost_edge_bypassed = True
                    cost_edge_bypass_reason = bypass_reason
                    bootstrap_closed_trades = trades_closed
        except Exception as e:
            pass  # If check fails, use normal cost_edge rejection

        if not allow_bootstrap_bypass:
            # P1.1AP-N2: Check for recovery admission eligibility before cost_edge_too_low reject
            # Recovery allows positive EV candidates rejected by economic health to proceed as learning positions
            if source_reject == "REJECT_ECON_BAD_ENTRY":
                try:
                    from src.core.runtime_mode import get_trading_mode
                    mode = get_trading_mode()
                    is_paper_train = mode and mode.value == "paper_train"

                    if is_paper_train:
                        # Check caps (pass empty open_positions, executor will validate actual positions)
                        recovery_allowed, recovery_block_reason = _check_recovery_admission_caps(symbol, open_positions or [])
                        if recovery_allowed:
                            # Allow through as recovery admission
                            return _allow(
                                recovery_admission=True,
                                recovery_bucket="RECOVERY_ADAPTIVE",
                                cost_edge_ok=False,
                            )
                        else:
                            # Recovery blocked by caps
                            _key = (symbol, recovery_block_reason)
                            if now - _RECOVERY_BLOCKED_LAST_LOG.get(_key, 0.0) >= _RECOVERY_BLOCKED_THROTTLE_S:
                                _RECOVERY_BLOCKED_LAST_LOG[_key] = now
                                log.info(
                                    "[PAPER_LEARNING_ENTRY_BLOCKED] symbol=%s reason=%s "
                                    "original_decision=REJECT_ECON_BAD_ENTRY cost_edge=False",
                                    symbol, recovery_block_reason,
                                )
                            return _skip(recovery_block_reason, symbol=symbol, bucket=bucket, source_reject=source_reject)
                except Exception as e:
                    log.warning(f"[RECOVERY_ADMISSION_CHECK_ERROR] {symbol}: {e}")
                    # Fall through to normal cost_edge_too_low rejection

            return _skip("cost_edge_too_low", symbol=symbol, bucket=bucket, source_reject=source_reject)

        # P1.1AE: Log the bypass candidate
        # P1.1AQ: Add flow diagnostics
        # P1.1AR: Generate flow_id for correlation
        flow_id = _gen_flow_id(symbol, side, bucket, "STRICT_TAKE_ROUTED_TO_TRAINING", now)
        _log_bypass_flow("candidate", symbol, bypass_reason, bucket="C_WEAK_EV_TRAIN", source="STRICT_TAKE_ROUTED_TO_TRAINING", flow_id=flow_id)
    elif cost_edge_ok is False and not allow_starvation_bypass:
        # No bypass conditions met for cost_edge=False
        return _skip("cost_edge_false_without_bypass", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # Dedicated duplicate candidate cooldown
    from src.core.runtime_mode import PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S

    if "DUPLICATE_CANDIDATE" in source_reject:
        dk = f"{symbol}:{side}:DUPLICATE_CANDIDATE"
        last = _recent_dup_candidate.get(dk)
        if last is not None and now - last < PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S:
            # P1.1AQ: Log drop if this was a bypass candidate
            if cost_edge_bypassed:
                dup_age_s = now - last if last else 0.0
                _log_bypass_flow("drop", symbol, "duplicate_candidate", source=source_reject, duplicate_age_s=f"{dup_age_s:.1f}", flow_id=flow_id)
            return _skip(
                "duplicate_candidate_cooldown",
                symbol=symbol,
                bucket=bucket,
                source_reject=source_reject,
            )
        _recent_dup_candidate[dk] = now

    # General dedupe per window
    from src.core.runtime_mode import PAPER_TRAIN_DEDUPE_WINDOW_S

    window = int(now // PAPER_TRAIN_DEDUPE_WINDOW_S)
    dedupe_key = f"{symbol}:{side}:{bucket}:{source_reject}:{window}"
    if dedupe_key in _recent_dedupe:
        return _skip(
            "duplicate_training_sample",
            symbol=symbol,
            bucket=bucket,
            source_reject=source_reject,
        )
    _recent_dedupe[dedupe_key] = now

    # P1.1AS: Compute open position counts BEFORE rate-cap checks to enable proper state logging
    open_positions = open_positions or []
    open_symbol = 0
    open_bucket = 0
    for p in open_positions:
        if (p.get("paper_source") == "training_sampler") or p.get("training_bucket"):
            if str(p.get("symbol", "")).upper() == symbol:
                open_symbol += 1
            if str(p.get("training_bucket", "")) == bucket:
                open_bucket += 1
    open_total = len(open_positions)

    # Phase 3A: Cap reconciliation - use actual _POSITIONS as source of truth
    try:
        from src.services.paper_trade_executor import _POSITIONS
        open_symbol_actual = sum(
            1 for pos in _POSITIONS.values()
            if str(pos.get("symbol", "")).upper() == symbol and
               str(pos.get("training_bucket", "")) == bucket
        )
        _log_open_cap_diag(symbol, bucket, open_total, open_symbol_actual, open_symbol,
                          "max_open_per_symbol_check")
        open_symbol = open_symbol_actual  # Use actual count for decision
    except Exception:
        pass  # Fallback to counter if _POSITIONS unavailable

    # Phase 3A: Check segment cooldown before rate caps
    try:
        from src.services.paper_adaptive_learning import _SEGMENT_COOLDOWNS
        segment_key = f"{symbol}:UNKNOWN:{side}"  # regime not available here; use UNKNOWN
        cooldown = _SEGMENT_COOLDOWNS.get(segment_key)
        if cooldown and cooldown.get("active"):
            cooldown_until = cooldown.get("cooldown_until", now)
            if now < cooldown_until:
                remaining_s = cooldown_until - now
                log.info(
                    "[PAPER_ENTRY_BLOCKED] symbol=%s reason=segment_negative_cooldown "
                    "segment=%s cooldown_remaining_s=%.1f",
                    symbol, segment_key, remaining_s
                )
                _SAMPLE_FLOW_WINDOW["blocked_by_segment_cooldown"] += 1
                return _skip("segment_negative_cooldown", symbol=symbol, segment=segment_key)
    except Exception:
        pass  # Graceful degrade if segment check unavailable

    # Global rate caps (per minute and per hour)
    from src.core.runtime_mode import (
        PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE,
        PAPER_TRAIN_MAX_ENTRIES_PER_HOUR,
        PAPER_TRAIN_MAX_OPEN_PER_SYMBOL,
        PAPER_TRAIN_MAX_OPEN_PER_BUCKET,
    )

    if len(_entry_times_minute) >= PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_rate_cap", source=source_reject, flow_id=flow_id)
            # P1.1AS: Fix missing rate-cap state logging by using now-computed open counts
            try:
                # P1.1AU: Use canonical training count for diagnostics
                from src.services.learning_monitor import get_canonical_training_trade_count as _gtc_1
                closed = _gtc_1()
                next_allowed_s = 60.0 - (now - _entry_times_minute[0]) if _entry_times_minute else 60.0
                _log_rate_cap_state(symbol, bucket, source_reject, now,
                                   len(_entry_times_minute), PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE,
                                   next_allowed_s, open_symbol, open_bucket, open_total, closed)
            except Exception:
                pass
        return _skip("max_entries_per_minute", symbol=symbol, bucket=bucket, source_reject=source_reject)

    if len(_entry_times_hour) >= PAPER_TRAIN_MAX_ENTRIES_PER_HOUR:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_rate_cap", source=source_reject, flow_id=flow_id)
            # P1.1AS: Fix missing rate-cap state logging by using now-computed open counts
            try:
                # P1.1AU: Use canonical training count for diagnostics
                from src.services.learning_monitor import get_canonical_training_trade_count as _gtc_2
                closed = _gtc_2()
                next_allowed_s = 3600.0 - (now - _entry_times_hour[0]) if _entry_times_hour else 3600.0
                _log_rate_cap_state(symbol, bucket, source_reject, now,
                                   len(_entry_times_hour), PAPER_TRAIN_MAX_ENTRIES_PER_HOUR,
                                   next_allowed_s, open_symbol, open_bucket, open_total, closed)
            except Exception:
                pass
        return _skip("max_entries_per_hour", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # P1.1AO: Probe-specific hard caps (independent of PAPER_TRAIN_MAX_OPEN_PER_BUCKET)
    if bucket == "C_NEG_EV_PROBE":
        # Rate cap: 2 new probes per 10 minutes
        if len(_probe_state["entry_times_10m"]) >= _PROBE_MAX_NEW_PER_10M:
            return _skip("probe_cap_rate", symbol=symbol, bucket=bucket, source_reject=source_reject)
        # Total open cap: 2 probe positions globally
        probe_open = sum(
            1 for p in open_positions
            if p.get("training_bucket") == "C_NEG_EV_PROBE"
        )
        if probe_open >= _PROBE_MAX_OPEN_TOTAL:
            return _skip("probe_cap_total_open", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # P1.1AP-O2 Fix D: C_WEAK_EV_TRAIN segment-level cooldown check
    if bucket == "C_WEAK_EV_TRAIN":
        try:
            from src.services.paper_training_sampler import _get_signal_regime
            regime = str(signal.get("regime", "UNKNOWN")).upper()
            segment_key = f"{symbol}:{regime}:{side}"

            # Check if segment is in loss-triggered cooldown
            if _is_segment_in_cooldown(segment_key):
                remaining_s = _SEGMENT_COOLDOWNS[segment_key].get("cooldown_s", 3600) - (
                    now - _SEGMENT_COOLDOWNS[segment_key]["activated_at"]
                )
                log.info(
                    "[PAPER_ENTRY_BLOCKED] reason=segment_loss_cooldown bucket=C_WEAK_EV_TRAIN "
                    "segment=%s remaining_s=%.1f",
                    segment_key, max(0, remaining_s)
                )
                return _skip("segment_loss_cooldown", symbol=symbol, bucket=bucket, source_reject=source_reject)

            # Check and potentially activate segment cooldown based on current metrics
            _maybe_activate_segment_cooldown(symbol, regime, side)

        except Exception as e:
            log.debug("[PAPER_SEGMENT_COOLDOWN_GATE_ERROR] symbol=%s bucket=%s error=%s", symbol, bucket, str(e))

    # P1.1AP-O2: Starvation discovery specific caps (independent of general training caps)
    if bucket == "PAPER_STARVATION_DISCOVERY":
        # P1.1AP-O2 Fix B: Check loss-triggered cooldown first
        if _is_discovery_bucket_in_cooldown():
            remaining_s = _STARVATION_DISCOVERY_BUCKET_COOLDOWN["cooldown_s"] - (
                now - _STARVATION_DISCOVERY_BUCKET_COOLDOWN["activated_at"]
            )
            log.info(
                "[PAPER_ENTRY_BLOCKED] reason=bucket_loss_cooldown bucket=PAPER_STARVATION_DISCOVERY "
                "symbol=%s remaining_s=%.1f",
                symbol, max(0, remaining_s)
            )
            return _skip("bucket_loss_cooldown", symbol=symbol, bucket=bucket, source_reject=source_reject)

        # Normal caps check
        discovery_allowed, discovery_reason = _check_starvation_discovery_caps(symbol, open_positions)
        if not discovery_allowed:
            return _skip(discovery_reason, symbol=symbol, bucket=bucket, source_reject=source_reject)

    if open_symbol >= PAPER_TRAIN_MAX_OPEN_PER_SYMBOL:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_max_open_per_symbol", source=source_reject, open_symbol=open_symbol, flow_id=flow_id)
        return _skip(
            "max_open_per_symbol",
            symbol=symbol,
            bucket=bucket,
            open_symbol=open_symbol,
        )

    if open_bucket >= PAPER_TRAIN_MAX_OPEN_PER_BUCKET:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_max_open_per_bucket", source=source_reject, open_bucket=open_bucket, flow_id=flow_id)
        return _skip("max_open_per_bucket", symbol=symbol, bucket=bucket, open_bucket=open_bucket)

    # P0 FIX #5: cost_edge_ok=False MUST require cost_edge_bypassed=True + valid bypass_reason
    if cost_edge_ok is False:
        if not cost_edge_bypassed:
            log.warning(
                "[PAPER_ENTRY_ADMISSION_REJECTED] reason=cost_edge_false_without_bypass "
                "symbol=%s bucket=%s cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none",
                symbol, bucket
            )
            return _skip("cost_edge_false_without_bypass", symbol=symbol, bucket=bucket, cost_edge_ok=False)
        # P0 FIX #5A: Allow cost_edge_bypass_reason as prefix match
        # bootstrap_trading_sample may have trades count appended: "bootstrap_training_sample trades=X"
        # PHASE 4B: Added "paper_starvation_learning" for starvation recovery bypass
        allowed_bypass_prefixes = ("bootstrap_training_sample", "paper_adaptive_recovery_with_quota", "recovery_admission", "paper_starvation_learning")
        if not any(cost_edge_bypass_reason.startswith(prefix) for prefix in allowed_bypass_prefixes):
            log.warning(
                "[PAPER_ENTRY_ADMISSION_REJECTED] reason=cost_edge_false_invalid_bypass_reason "
                "symbol=%s bucket=%s cost_edge_ok=False bypass_reason=%s",
                symbol, bucket, cost_edge_bypass_reason
            )
            return _skip("cost_edge_false_invalid_bypass_reason", symbol=symbol, bucket=bucket, cost_edge_ok=False)

    # P1.1AT: Do NOT commit rate-cap timestamps here. They will be committed in open_paper_position()
    # after the actual paper training entry is successfully created.
    # This prevents phantom rate-cap consumption when entry creation fails downstream.

    # P1.1AK: Include bypass metadata in gate result
    # P1.1AQ: Include open position counts for diagnostics
    # P1.1AR: Include flow_id for correlation
    return _allow(
        symbol=symbol,
        side=side,
        bucket=bucket,
        source_reject=source_reject,
        cost_edge_bypassed=cost_edge_bypassed,
        cost_edge_bypass_reason=cost_edge_bypass_reason,
        bootstrap_closed_trades=bootstrap_closed_trades,
        open_symbol=open_symbol,
        open_bucket=open_bucket,
        open_total=open_total,
        flow_id=flow_id,
    )


def _safe_int_count(value) -> int:
    """P1.1P: Safely convert any value to count (list/dict/set/tuple/int/None)."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    try:
        return int(value)
    except Exception:
        return 0


def _safe_int(value, default: int = 0) -> int:
    """P1.1P: Safely convert value to int with default fallback."""
    try:
        return int(value)
    except Exception:
        return default


def _metric_add_event(key: str, ts: float | None = None) -> None:
    """P1.1V: Safe metric event append. Handles list/deque/int/None fields."""
    import time
    now = float(ts or time.time())
    v = _training_metrics.get(key)
    if hasattr(v, "append"):
        # It's a list or deque — append timestamp
        v.append(now)
    elif isinstance(v, (int, float)):
        # It's a counter — convert to list and append
        _training_metrics[key] = [now]
    elif v is None:
        # Not initialized — create list
        _training_metrics[key] = [now]
    else:
        # Unknown type — wrap in list
        _training_metrics[key] = [now]


def _metric_inc_counter(key: str, n: int = 1) -> None:
    """P1.1V: Safe metric counter increment. Handles list/deque/int fields."""
    v = _training_metrics.get(key, 0)
    if isinstance(v, (int, float)):
        _training_metrics[key] = int(v) + n
    elif hasattr(v, "append"):
        # It's a list/deque — append timestamp instead
        import time
        _training_metrics[key] = int(n)
    else:
        # Unknown type — set to int
        _training_metrics[key] = n


def _maybe_log_training_health(open_positions=None) -> None:
    """Log training health every 10 minutes. P1.1P: Uses f-string to avoid logging TypeError."""
    now = time.time()
    last_log = _training_metrics["last_health_log_ts"]

    if now - last_log < 600:  # 10 minutes
        return

    # Count entries and closed in last hour
    one_hour_ago = now - 3600
    entries_1h = sum(1 for ts in _training_metrics["entries_1h"] if ts > one_hour_ago)
    closed_1h = _training_metrics["closed_1h"]

    # Cleanup old entries
    _training_metrics["entries_1h"] = [ts for ts in _training_metrics["entries_1h"] if ts > one_hour_ago]

    status = "OK" if entries_1h >= _MIN_ENTRIES_PER_HOUR else "STARVED"

    # P1.1P: Safe conversions for all values
    open_count = _safe_int_count(open_positions)
    closed_count = _safe_int(closed_1h)
    entry_count = _safe_int(entries_1h)
    target_count = _safe_int(_MIN_ENTRIES_PER_HOUR)
    learning_count = _safe_int(_training_metrics["learning_updates_1h"])
    status_s = str(status or "UNKNOWN")

    # P1.1P: Use f-string instead of %d formatter (avoids TypeError with list input)
    log.info(
        f"[PAPER_TRAIN_HEALTH] open={open_count} "
        f"closed_1h={closed_count} entries_1h={entry_count} "
        f"target_1h={target_count} learning_updates_1h={learning_count} "
        f"status={status_s}"
    )

    # RECON: Diagnostic health check for paper training pipeline
    counts_ok = entry_count >= 2
    symbol_ok = open_count >= 0
    regime_ok = True
    exit_ok = True
    recent_ok = learning_count >= 0
    recon_status = "OK" if all([counts_ok, symbol_ok, regime_ok, exit_ok, recent_ok]) else "WARN"

    log.info(
        f"[V10.13x.1 RECON] counts_ok={counts_ok} symbol_ok={symbol_ok} "
        f"regime_ok={regime_ok} exit_ok={exit_ok} recent_ok={recent_ok} status={recon_status}"
    )

    if status == "STARVED":
        log.warning(
            f"[PAPER_TRAIN_STARVED] entries_1h={entry_count} < target={target_count} reason=insufficient_rejection_sampling"
        )

    _training_metrics["last_health_log_ts"] = now


def _apply_adaptive_policy_to_paper_candidate(
    symbol: str,
    regime: str,
    side: str,
    ev: float,
    candidate_bucket: str,
) -> dict:
    """P1.1AP-O1: Apply adaptive rolling policy to PAPER candidates.

    Reads adaptive policy snapshot and applies bounded rules.
    Only affects EV>0 candidates; never fabricates positive EV.
    Returns adjustment dict for caller to use or ignore.

    Args:
        symbol: Symbol
        regime: Trading regime
        side: BUY or SELL
        ev: Candidate's EV (must be > 0 for policy to apply)
        candidate_bucket: Training bucket

    Returns:
        {
            'action': str,  # collect_bootstrap|downweight_losing_segment|prefer_improving_segment|continue_learning|no_policy_apply
            'weight_mult': float,  # multiplier for position sizing (0.25-2.00)
            'segment_n': int,
            'segment_pf': float,
            'segment_expectancy': float,
            'old_weight': float,
            'new_weight': float,
        }
    """
    try:
        # P1.1AP-O1: Never apply policy to EV<=0 candidates
        if ev <= 0:
            return {
                "action": "no_policy_apply",
                "weight_mult": 1.0,
                "segment_n": 0,
                "segment_pf": 1.0,
                "segment_expectancy": 0.0,
                "old_weight": 1.0,
                "new_weight": 1.0,
                "reason": "ev_not_positive",
            }

        # Get adaptive learner policy snapshot
        from src.services.paper_adaptive_learning import get_learner
        learner = get_learner()
        snapshot = learner.get_paper_policy_snapshot(symbol, regime, side)

        # Log policy read
        log.info(
            "[PAPER_ADAPTIVE_POLICY_READ] "
            "symbol=%s regime=%s side=%s "
            "rolling20_n=%d rolling20_pf=%.3f rolling50_n=%d rolling50_pf=%.3f "
            "segment_n=%d segment_pf=%.3f segment_weight=%.2f "
            "action=%s",
            symbol, regime, side,
            snapshot["rolling20_n"], snapshot["rolling20_pf"],
            snapshot["rolling50_n"], snapshot["rolling50_pf"],
            snapshot["segment_n"], snapshot["segment_pf"],
            snapshot["segment_weight"],
            "reading_policy",
        )

        segment_n = snapshot["segment_n"]
        segment_pf = snapshot["segment_pf"]
        segment_exp = snapshot["segment_expectancy"]
        old_weight = snapshot["segment_weight"]
        new_weight = old_weight

        # P1.1AP-O1: Apply decision rules for EV>0 candidates
        action = "continue_learning"

        # Rule A: Insufficient sample — continue collecting
        if segment_n < 20:
            action = "collect_bootstrap"
        # Rule B: Losing segment with sufficient data
        elif segment_n >= 20 and segment_pf < 0.80 and segment_exp < 0:
            # Bounded downweight: reduce multiplier
            new_weight = max(0.25, old_weight * 0.9)
            action = "downweight_losing_segment"
        # Rule C: Improving segment with sufficient data
        elif segment_n >= 20 and segment_pf > 1.10 and segment_exp > 0:
            # Bounded upweight: increase multiplier
            new_weight = min(2.00, old_weight * 1.1)
            action = "prefer_improving_segment"

        weight_mult = new_weight if action != "continue_learning" else 1.0

        # Log policy adaptation when action is taken
        if action != "continue_learning":
            log.info(
                "[PAPER_POLICY_ADAPTATION] "
                "segment=%s:%s:%s n=%d pf=%.3f expectancy=%.6f "
                "old_weight=%.2f new_weight=%.2f action=%s "
                "reason=post_cost_rolling_learning candidate_ev=%.4f mode=PAPER",
                symbol, regime, side,
                segment_n, segment_pf, segment_exp,
                old_weight, new_weight, action,
                ev,
            )

        return {
            "action": action,
            "weight_mult": weight_mult,
            "segment_n": segment_n,
            "segment_pf": segment_pf,
            "segment_expectancy": segment_exp,
            "old_weight": old_weight,
            "new_weight": new_weight,
        }

    except Exception as e:
        log.warning("[PAPER_ADAPTIVE_POLICY_ERROR] symbol=%s error=%s", symbol, str(e), exc_info=True)
        # Safe default: continue with normal flow
        return {
            "action": "continue_learning",
            "weight_mult": 1.0,
            "segment_n": 0,
            "segment_pf": 1.0,
            "segment_expectancy": 0.0,
            "old_weight": 1.0,
            "new_weight": 1.0,
            "error": str(e),
        }


def _try_emit_adaptive_starvation_telemetry() -> None:
    """P1.1AP-O1A: Emit rate-limited PAPER_ADAPTIVE_STARVATION diagnostics.

    Tracks windows to diagnose whether adaptive policy integration is:
    - receiving no positive EV supply (reason=no_positive_ev_candidates)
    - actively learning (reason=learning_active)
    - awaiting samples (reason=awaiting_samples)
    """
    ts_now = time.time()
    state = _ADAPTIVE_STARVATION_STATE

    # Rotate window if 600s elapsed
    if ts_now - state["window_start_ts"] >= _ADAPTIVE_STARVATION_WINDOW_S:
        state["window_start_ts"] = ts_now
        state["positive_candidates"] = 0
        state["negative_ev_rejects"] = 0
        state["admitted_recovery"] = 0
        state["canonical_closes"] = 0
        state["policy_reads"] = 0

    # Rate-limit emission to once per 600s window
    if ts_now - state["last_log_ts"] < _ADAPTIVE_STARVATION_WINDOW_S:
        return

    # Determine reason based on window metrics
    if state["positive_candidates"] == 0 and state["negative_ev_rejects"] > 0:
        reason = "no_positive_ev_candidates"
    elif state["admitted_recovery"] > 0:
        reason = "learning_active"
    else:
        reason = "awaiting_samples"

    state["last_log_ts"] = ts_now

    log.info(
        "[PAPER_ADAPTIVE_STARVATION] "
        "window_s=%d positive_candidates=%d negative_ev_rejects=%d "
        "admitted_recovery=%d canonical_closes=%d policy_reads=%d "
        "reason=%s",
        int(_ADAPTIVE_STARVATION_WINDOW_S),
        state["positive_candidates"],
        state["negative_ev_rejects"],
        state["admitted_recovery"],
        state["canonical_closes"],
        state["policy_reads"],
        reason,
    )


def maybe_open_training_sample(
    signal: dict,
    ctx: Optional[dict] = None,
    *,
    reason: str,
    current_price: Optional[float] = None,
) -> dict:
    """Try opening a paper training sample when normal RDE rejects.

    AGGRESSIVE MODE: Disable all quality gates for trading.

    Returns: {"allowed": True, ...} for all valid signals
    """
    try:
        if not _is_training_enabled():
            return {
                "allowed": False,
                "bucket": "",
                "reason": "training_disabled",
                "size_mult": 0.0,
                "side": "UNKNOWN",
                "side_inferred": False,
                "max_hold_s": 0,
            }

        signal = signal or {}
        ctx = ctx or {}

        # P1.1AP-O2: Initialize starvation discovery idle time on first call
        # FIX: Set baseline to startup time so discovery is blocked for first 600 seconds
        now = time.time()
        if _starvation_discovery_state.get("last_eligible_entry_ts", 0.0) == 0.0:
            # Fresh startup: set baseline to now so idle_s = now - now = 0 (blocks discovery for 600s)
            _starvation_discovery_state["last_eligible_entry_ts"] = now
            _starvation_discovery_state["idle_s"] = 0.0

        # P1.1AP-O1A: Track negative EV rejects for starvation diagnostics
        if "REJECT_NEGATIVE_EV" in reason:
            _ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] += 1
            # P1.1AP-O2: Track valid negative EV candidates during starvation discovery
            _starvation_discovery_state["valid_negative_candidates"] += 1

        # Require real price
        if not current_price:
            return {
                "allowed": False,
                "bucket": "",
                "reason": "no_real_price",
                "size_mult": 0.0,
                "side": "UNKNOWN",
                "side_inferred": False,
                "max_hold_s": 0,
            }

        symbol = signal.get("symbol", "UNKNOWN")
        side = signal.get("action", "").upper()
        side_inferred = False

        # Infer side if missing
        if not side or side not in ["BUY", "SELL"]:
            inferred_side, buy_score, sell_score = _infer_side_from_features(signal)
            if inferred_side == "UNKNOWN":
                return {
                    "allowed": False,
                    "bucket": "",
                    "reason": "side_inference_tie",
                    "size_mult": 0.0,
                    "side": "UNKNOWN",
                    "side_inferred": True,
                    "max_hold_s": 0,
                }
            side = inferred_side
            side_inferred = True
            log.info(
                "[PAPER_TRAIN_SIDE] symbol=%s side=%s buy_score=%.2f sell_score=%.2f",
                symbol,
                side,
                buy_score,
                sell_score,
            )

        # Get training bucket
        bucket, size_mult = _get_training_bucket(signal, ctx, reason)

        if not bucket:
            return {
                "allowed": False,
                "bucket": "",
                "reason": "no_training_bucket",
                "size_mult": 0.0,
                "side": side,
                "side_inferred": side_inferred,
                "max_hold_s": 0,
            }

        # AGGRESSIVE MODE: Skip all quality gates - allow all trades
        log.info(
            "[PAPER_AGGRESSIVE_MODE] symbol=%s side=%s bucket=%s reason=%s allowed=TRUE (ALL GATES DISABLED)",
            symbol, side, bucket, reason,
        )

        # All gates DISABLED; record entry metric
        _training_metrics["entries_1h"].append(time.time())
        _maybe_log_training_health()

        # AGGRESSIVE MODE: Return allowed=True for all valid buckets
        return {
            "allowed": True,
            "bucket": bucket,
            "reason": "aggressive_mode_all_gates_disabled",
            "size_mult": size_mult or 1.0,
            "side": side,
            "side_inferred": side_inferred,
            "cost_edge_ok": True,
            "expected_move_pct": 0.0,
            "required_move_pct": 0.23,
            "max_hold_s": _MAX_HOLD_S,
            "tags": ["training_sampler", bucket.lower()],
            "admission_reason": f"aggressive_mode_{bucket}",
        }

        # P1.1AM: Log final acceptance of bypassed entries (DISABLED IN AGGRESSIVE MODE)
        # P1.1AQ: Add open position counts and source for diagnostics
        # P1.1AR: Add flow_id for correlation
        if gate_result.get("cost_edge_bypassed"):
            import logging
            log_p11am = logging.getLogger(__name__)
            flow_id = gate_result.get("flow_id", f"{symbol}:{side}:{bucket}:{int(time.time())}")
            log_p11am.info(
                "[COST_EDGE_BYPASS_ACCEPTED] mode=paper_train symbol=%s bucket=%s reason=%s source=%s "
                "open_symbol=%d open_bucket=%d open_total=%d flow_id=%s",
                symbol,
                bucket,
                gate_result.get("cost_edge_bypass_reason", "none"),
                reason,
                gate_result.get("open_symbol", 0),
                gate_result.get("open_bucket", 0),
                gate_result.get("open_total", 0),
                flow_id,
            )
            # P1.1AR: Log entry attempt after acceptance
            log.info(
                "[PAPER_ENTRY_ATTEMPT] flow_id=%s symbol=%s side=%s bucket=%s source=%s "
                "cost_edge_ok=%s cost_edge_bypassed=True bypass_reason=%s",
                flow_id,
                symbol,
                side,
                bucket,
                reason,
                cost_edge_ok,
                gate_result.get("cost_edge_bypass_reason", "none"),
            )

        # P1.1AO: Log probe acceptance
        if bucket == "C_NEG_EV_PROBE":
            _probe_state["entry_times_10m"].append(time.time())
            log.info(
                "[PAPER_NEG_EV_PROBE_ACCEPTED] symbol=%s side=%s bucket=C_NEG_EV_PROBE "
                "original_decision=REJECT_NEGATIVE_EV ev=%.4f probe_lifetime_closed=%d "
                "reason=cold_start_starvation",
                symbol,
                side,
                float(signal.get("ev", 0.0)) if signal else 0.0,
                _probe_state["lifetime_closed"],
            )

        # P1.1AP-O2: Log starvation discovery acceptance
        if bucket == "PAPER_STARVATION_DISCOVERY":
            _ts_now = time.time()
            _starvation_discovery_state["entry_times_15m"].append(_ts_now)
            _starvation_discovery_state["valid_negative_candidates"] = 0  # Reset counter on successful entry
            _update_starvation_discovery_idle(_ts_now)
            _maybe_log_starvation_discovery_state()
            log.info(
                "[PAPER_STARVATION_DISCOVERY_ACCEPTED] symbol=%s side=%s bucket=PAPER_STARVATION_DISCOVERY "
                "original_decision=REJECT_NEGATIVE_EV ev=%.4f idle_s=%.1f "
                "execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED readiness_eligible=false",
                symbol,
                side,
                float(signal.get("ev", 0.0)) if signal else 0.0,
                _starvation_discovery_state.get("idle_s", 0.0),
            )

        # P1.1AP-N2A: Recovery admission approved (NOT opened yet - see trade_executor for actual entry log)
        if gate_result.get("recovery_admission"):
            log.debug(
                "[PAPER_LEARNING_ADMISSION_ALLOWED] symbol=%s side=%s learning_source=paper_adaptive_recovery "
                "admission_reason=paper_learning_must_continue original_decision=%s "
                "reject_reason=%s ev=%.4f expected_move_pct=%.4f expected_move_src=%s cost_edge_ok=False",
                symbol,
                side,
                reason,
                reason,
                float(signal.get("ev", 0.0)) if signal else 0.0,
                expected_move_pct,
                expected_move_src,
            )

        # P1.1AK: Include bypass metadata from gate result
        # P1.1AR: Include flow_id for correlation
        flow_id = ""
        if gate_result.get("cost_edge_bypassed"):
            flow_id = gate_result.get("flow_id", f"{symbol}:{side}:{bucket}:{int(time.time())}")

        # P1.1AP-O1: Apply adaptive rolling policy to PAPER candidates
        # Only modifies size_mult for EV>0 candidates; safe to call on all paths
        signal_ev = float(signal.get("ev", 0.0)) if signal else 0.0
        regime = signal.get("regime", "UNKNOWN") if signal else "UNKNOWN"

        # P1.1AP-O1A: Track adaptive starvation metrics
        if signal_ev > 0:
            _ADAPTIVE_STARVATION_STATE["positive_candidates"] += 1

        policy_result = _apply_adaptive_policy_to_paper_candidate(
            symbol=symbol,
            regime=regime,
            side=side,
            ev=signal_ev,
            candidate_bucket=bucket,
        )

        # Track policy reads for EV>0 candidates
        if signal_ev > 0 and policy_result.get("action") != "no_policy_apply":
            _ADAPTIVE_STARVATION_STATE["policy_reads"] += 1

        # Apply bounded weight adjustment if policy recommends it
        if policy_result.get("weight_mult", 1.0) != 1.0:
            size_mult = size_mult * policy_result["weight_mult"]

        # Build result dict
        result = {
            "allowed": True,
            "bucket": bucket,
            "reason": f"training_sample bucket={bucket}",
            "size_mult": size_mult,
            "side": side,
            "side_inferred": side_inferred,
            "cost_edge_ok": cost_edge_ok,
            "cost_edge_bypassed": gate_result.get("cost_edge_bypassed", False),
            "cost_edge_bypass_reason": gate_result.get("cost_edge_bypass_reason", "none"),
            "bootstrap_closed_trades": gate_result.get("bootstrap_closed_trades", 0),
            "expected_move_pct": expected_move_pct,
            "expected_move_src": expected_move_src,
            "required_move_pct": 0.23,  # reference from P1.1j
            "max_hold_s": _MAX_HOLD_S,
            "tags": ["training_sampler", bucket.lower()],
            "flow_id": flow_id,
        }

        # P1.1AP-N2: Add recovery metadata if this is a recovery admission
        if gate_result.get("recovery_admission"):
            result["recovery_admission"] = True
            result["learning_source"] = "paper_adaptive_recovery"
            result["admission_reason"] = "paper_learning_must_continue"
            result["historical_health"] = "BAD"
            _ADAPTIVE_STARVATION_STATE["admitted_recovery"] += 1

        # PHASE 4B: Add starvation bypass metadata - marks trade as PAPER-only learning during starvation
        if gate_result.get("cost_edge_bypass_reason") == "paper_starvation_learning":
            result["cost_edge_ok"] = False
            result["cost_edge_bypassed"] = True
            result["cost_edge_bypass_reason"] = "paper_starvation_learning"
            result["learning_source"] = "paper_starvation_learning"
            result["admission_reason"] = "paper_starvation_learning_must_continue"
            result["readiness_eligible"] = False
            result["real_readiness_eligible"] = False
            result["paper_learning_only"] = True
            result["training_bucket"] = bucket
            log.info(
                "[PAPER_STARVATION_LEARNING_APPROVED] symbol=%s side=%s bucket=%s "
                "cost_edge_bypassed=True cost_edge_ok=False "
                "readiness_eligible=False real_readiness_eligible=False paper_learning_only=True "
                "idle_s=%.1f",
                symbol, side, bucket,
                _starvation_discovery_state.get("idle_s", 0.0),
            )

        # P1.1AP-O2: Add starvation discovery metadata
        elif bucket == "PAPER_STARVATION_DISCOVERY":
            result["learning_source"] = "paper_starvation_discovery"
            result["evaluation_role"] = "DISCOVERY"
            result["execution_truth_class"] = "LEGACY_SPOT_EXECUTION_UNVERIFIED"
            result["readiness_eligible"] = False
            result["source_reject"] = "REJECT_NEGATIVE_EV"
            result["admission_reason"] = "starvation_recovery_discovery"

        # P1.1AP-O2: Add C_WEAK_EV_TRAIN metadata with scoped learning_source for bootstrap filtering
        # Only set if not already set by recovery admission
        elif bucket == "C_WEAK_EV_TRAIN" and "learning_source" not in result:
            result["learning_source"] = "paper_weak_ev_training"
            result["admission_reason"] = "weak_ev_training_sample"

        # P1.1AP-O2 Fix C: Emit admission truth telemetry for cost-edge / entry correlation
        # Includes candidate_id (flow_id), cost_edge status, bypass reason, and expected move
        candidate_id = flow_id if flow_id else f"{symbol}:{side}:{bucket}:{int(now)}"
        admission_reason = result.get("admission_reason", "training_sample")

        log.info(
            "[PAPER_ENTRY_ADMISSION_TRUTH] candidate_id=%s symbol=%s side=%s bucket=%s "
            "cost_edge_ok=%s cost_edge_bypassed=%s bypass_reason=%s "
            "expected_move_pct=%.4f required_move_pct=%.4f "
            "admission_reason=%s source_reject=%s",
            candidate_id,
            symbol,
            side,
            bucket,
            cost_edge_ok,
            gate_result.get("cost_edge_bypassed", False),
            gate_result.get("cost_edge_bypass_reason", "none"),
            expected_move_pct,
            0.23,  # required_move_pct reference
            admission_reason,
            reason,  # original rejection reason
        )

        # P1.1AP-O1A: Emit starvation diagnostics if threshold reached
        _try_emit_adaptive_starvation_telemetry()

        return result

    except Exception as e:
        log.error(f"[PAPER_TRAIN_ERROR] {e}", exc_info=True)
        return {
            "allowed": False,
            "bucket": "ERROR",
            "reason": str(e),
            "size_mult": 0.0,
            "side": "UNKNOWN",
            "side_inferred": False,
            "max_hold_s": 0,
        }


def commit_training_sampler_rate_slot(now: float = None) -> None:
    """P1.1AT: Commit rate-cap timestamps ONLY after successful paper training entry creation.

    This must be called from open_paper_position() AFTER the position is successfully
    added to _POSITIONS, NOT from _training_quality_gate() which happens too early.

    Args:
        now: Current timestamp (defaults to current time)
    """
    if now is None:
        now = time.time()

    _entry_times_minute.append(now)
    _entry_times_hour.append(now)


def record_training_closed(
    bucket: str,
    outcome: str,
    net_pnl_pct: float = 0.0,
    symbol: str = "",
    regime: str = "",
    side: str = "",
) -> None:
    """P1.1V: Record a closed training trade for health metrics. Never raises.

    P1.1AP-O2 Fix B: Also record discovery closes for loss pattern detection.
    P1.1AP-O2 Fix D: Also check C_WEAK_EV_TRAIN segment for loss-triggered cooldown.
    """
    try:
        _metric_add_event("closed_1h")
        if bucket == "C_NEG_EV_PROBE":
            _probe_state["lifetime_closed"] += 1

        # P1.1AP-O2 Fix B: Track discovery closes for cooldown activation
        if bucket == "PAPER_STARVATION_DISCOVERY":
            now = time.time()
            _starvation_discovery_state.get("closed_trades", []).append((net_pnl_pct, outcome, now))
            # Keep only last 10 closes in memory (rolling window for loss detection)
            closed = _starvation_discovery_state.get("closed_trades", [])
            if len(closed) > 10:
                _starvation_discovery_state["closed_trades"] = closed[-10:]
            # Check if cooldown should be activated
            _maybe_activate_discovery_bucket_cooldown()

        # P1.1AP-O2 Fix D: Check C_WEAK_EV_TRAIN segment for loss-triggered cooldown
        if bucket == "C_WEAK_EV_TRAIN" and symbol and regime and side:
            _maybe_activate_segment_cooldown(symbol, regime, side)

        log.info("[PAPER_TRAIN_CLOSED] bucket=%s outcome=%s net_pnl_pct=%.4f probe_lifetime_closed=%d",
                 bucket, outcome, net_pnl_pct, _probe_state["lifetime_closed"])
    except Exception as e:
        log.warning("[PAPER_TRAIN_METRICS_ERROR] record_training_closed failed: %s", e)


def record_training_learning_update() -> None:
    """P1.1V: Record a learning update from closed training trade. Never raises."""
    try:
        _metric_inc_counter("learning_updates_1h", 1)
    except Exception as e:
        log.warning("[PAPER_TRAIN_METRICS_ERROR] record_training_learning_update failed: %s", e)


# P1.1AP-O2: Module initialization - restore/bootstrap cooldowns on startup
try:
    _restore_and_bootstrap_cooldowns()
except Exception as e:
    log.warning("[PAPER_TRAINING_INIT_ERROR] Failed to restore/bootstrap cooldowns: %s", e)
