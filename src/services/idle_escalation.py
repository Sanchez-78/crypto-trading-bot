"""
V10.13t: Idle Escalation Management — Recovery policy based on idle duration.

When the bot is idle (no trades), escalate through modes:
  NORMAL          (idle < 600s)  - strict gates, normal execution
  UNBLOCK_SOFT    (idle 600-1200s) - relax score threshold, allow top forced
  UNBLOCK_MEDIUM  (idle 1200-1800s) - relax spread gates, shorten hold time
  UNBLOCK_HARD    (idle >= 1800s) - micro trades, disable flat-spread block, fastest exits

Each mode has explicit admission + execution deltas, not just more signals.
"""

import logging
import time as _time

log = logging.getLogger(__name__)

# ── Mode thresholds ────────────────────────────────────────────────────────
IDLE_SOFT_SEC = 600      # 10 minutes - mild relaxation
IDLE_MEDIUM_SEC = 1200   # 20 minutes - moderate relaxation
IDLE_HARD_SEC = 1800     # 30 minutes - aggressive recovery

# ── State tracking ────────────────────────────────────────────────────────
_escalation_state = {
    "mode": "NORMAL",
    "idle_seconds": 0.0,
    "last_update_ts": 0.0,
    "mode_entered_ts": 0.0,
    "forced_attempts": 0,
    "forced_passed": 0,
    "micro_attempts": 0,
    "micro_passed": 0,
}


def get_idle_mode(idle_seconds: float) -> str:
    """Determine idle escalation mode based on idle duration."""
    if idle_seconds < IDLE_SOFT_SEC:
        return "NORMAL"
    elif idle_seconds < IDLE_MEDIUM_SEC:
        return "UNBLOCK_SOFT"
    elif idle_seconds < IDLE_HARD_SEC:
        return "UNBLOCK_MEDIUM"
    else:
        return "UNBLOCK_HARD"


def update_escalation_state(idle_seconds: float) -> dict:
    """Update current escalation mode and return state."""
    new_mode = get_idle_mode(idle_seconds)
    now = _time.time()

    # Detect mode change
    if new_mode != _escalation_state["mode"]:
        old_mode = _escalation_state["mode"]
        _escalation_state["mode"] = new_mode
        _escalation_state["mode_entered_ts"] = now
        log.info(
            f"[IDLE_ESCALATION] Mode transition: {old_mode} -> {new_mode} (idle={idle_seconds:.0f}s)"
        )

    _escalation_state["idle_seconds"] = idle_seconds
    _escalation_state["last_update_ts"] = now

    return _escalation_state.copy()


def get_escalation_state() -> dict:
    """Get current escalation state (read-only)."""
    return _escalation_state.copy()


def record_forced_attempt() -> None:
    """Track that a forced-explore signal was evaluated."""
    _escalation_state["forced_attempts"] += 1


def record_forced_pass() -> None:
    """Track that a forced-explore signal passed gates."""
    _escalation_state["forced_passed"] += 1


def record_micro_attempt() -> None:
    """Track that a micro-trade was evaluated."""
    _escalation_state["micro_attempts"] += 1


def record_micro_pass() -> None:
    """Track that a micro-trade passed gates."""
    _escalation_state["micro_passed"] += 1


def reset_recovery_stats() -> None:
    """Reset recovery attempt counters (typically on successful trade)."""
    _escalation_state["forced_attempts"] = 0
    _escalation_state["forced_passed"] = 0
    _escalation_state["micro_attempts"] = 0
    _escalation_state["micro_passed"] = 0


# ── Admission Policy by Mode ────────────────────────────────────────────────

def get_admission_policy(mode: str, branch: str) -> dict:
    """
    Get admission parameters for a given mode + branch combination.

    branch: "normal" | "forced" | "micro"

    Returns dict with:
      spread_min_bps: minimum bid-ask spread in bps
      spread_max_bps: maximum spread in bps
      score_threshold_mult: multiplier on score threshold
      size_mult: position size reduction
      max_hold_sec: maximum hold time
      allow_micro: whether micro trades enabled
      rate_limit_per_window: max trades per 15min window
    """
    if branch == "normal":
        # Normal flow: strict across all modes
        return {
            "spread_min_bps": 5.0,
            "spread_max_bps": 100.0,
            "score_threshold_mult": 1.00,
            "size_mult": 1.00,
            "max_hold_sec": 600,
            "allow_micro": False,
            "rate_limit_per_window": None,  # no limit
        }

    elif branch == "forced":
        if mode == "NORMAL":
            return {
                "spread_min_bps": 5.0,
                "spread_max_bps": 80.0,
                "score_threshold_mult": 0.95,
                "size_mult": 0.25,
                "max_hold_sec": 180,
                "allow_micro": False,
                "rate_limit_per_window": 2,  # max 2 forced per 15min
            }
        elif mode == "UNBLOCK_SOFT":
            return {
                "spread_min_bps": 3.0,
                "spread_max_bps": 80.0,
                "score_threshold_mult": 0.90,
                "size_mult": 0.25,
                "max_hold_sec": 150,
                "allow_micro": False,
                "rate_limit_per_window": 3,
            }
        elif mode == "UNBLOCK_MEDIUM":
            return {
                "spread_min_bps": 2.0,  # much more relaxed
                "spread_max_bps": 100.0,
                "score_threshold_mult": 0.85,
                "size_mult": 0.20,
                "max_hold_sec": 120,
                "allow_micro": False,
                "rate_limit_per_window": 4,
            }
        elif mode == "UNBLOCK_HARD":
            return {
                "spread_min_bps": 1.0,  # very relaxed for hard idle recovery
                "spread_max_bps": 150.0,
                "score_threshold_mult": 0.80,
                "size_mult": 0.15,
                "max_hold_sec": 90,
                "allow_micro": True,
                "rate_limit_per_window": 5,
            }

    elif branch == "micro":
        if mode in ("UNBLOCK_MEDIUM", "UNBLOCK_HARD"):
            return {
                "spread_min_bps": 0.5,  # extremely relaxed
                "spread_max_bps": 150.0,
                "score_threshold_mult": 0.75,
                "size_mult": 0.10,
                "max_hold_sec": 60,
                "allow_micro": True,
                "rate_limit_per_window": 2,
            }
        else:
            return {
                "spread_min_bps": 5.0,
                "spread_max_bps": 100.0,
                "score_threshold_mult": 1.00,
                "size_mult": 0.0,  # disabled in NORMAL
                "max_hold_sec": 0,
                "allow_micro": False,
                "rate_limit_per_window": 0,
            }

    # Default (shouldn't happen)
    return {
        "spread_min_bps": 5.0,
        "spread_max_bps": 100.0,
        "score_threshold_mult": 1.00,
        "size_mult": 1.00,
        "max_hold_sec": 600,
        "allow_micro": False,
        "rate_limit_per_window": None,
    }


def is_rate_limited(branch: str, mode: str, recent_window_count: int) -> bool:
    """Check if branch has hit its rate limit for this mode."""
    policy = get_admission_policy(mode, branch)
    limit = policy.get("rate_limit_per_window")
    if limit is None:
        return False
    return recent_window_count >= limit


def get_execution_profile(mode: str, branch: str) -> dict:
    """
    Get execution parameters for forced/micro trades in a given mode.

    Returns dict with sizing, hold time, exit timing adjustments.
    """
    policy = get_admission_policy(mode, branch)

    return {
        "size_mult": policy["size_mult"],
        "max_hold_sec": policy["max_hold_sec"],
        "force_early_be": mode in ("UNBLOCK_MEDIUM", "UNBLOCK_HARD"),
        "scratch_after_sec": 30 if mode == "UNBLOCK_HARD" else 60,
        "use_fast_scratch": mode == "UNBLOCK_HARD",
    }


# ── Snapshot for telemetry ────────────────────────────────────────────────

def get_idle_escalation_snapshot() -> dict:
    """Return current escalation state for cycle telemetry."""
    state = get_escalation_state()
    mode = state["mode"]
    idle_s = state["idle_seconds"]

    return {
        "idle_mode": mode,
        "idle_seconds": round(idle_s, 0),
        "forced_attempts": state["forced_attempts"],
        "forced_passed": state["forced_passed"],
        "micro_attempts": state["micro_attempts"],
        "micro_passed": state["micro_passed"],
    }
