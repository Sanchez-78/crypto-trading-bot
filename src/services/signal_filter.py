"""
Signal filter guards — regime-aware loss protection, conv-rate tracking, direction bias.

Supplements inline gates in realtime_decision_engine.py.
All state is module-level (stateless callers, single process).

Modules:
  loss_cluster_check()   — regime-aware cooldown after consecutive losses
  log_signal_outcome()   — track signal accept/reject for conv_rate
  conv_diagnose()        — full diagnostic report
  record_bias()          — record trade result per (sym, action)
  is_biased()            — auto-disable direction if WR < BIAS_DISABLE_T
  bias_summary()         — all pairs sorted by WR ascending
"""

import time
import logging
from collections import deque

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# B15 — LossClusterGuard (regime-aware)
# ══════════════════════════════════════════════════════════════════════════════

# symbol → unblock epoch (float)
_blocked_until: dict[str, float] = {}

# Consecutive-loss threshold per regime before cooldown fires
_LOSS_THRESHOLDS = {
    "BULL_TREND":  5,   # trend continuation valid → allow more losses
    "BEAR_TREND":  5,
    "RANGING":     3,   # default
    "QUIET_RANGE": 3,
    "HIGH_VOL":    2,   # volatile = unpredictable → stricter
}

_BASE_COOLDOWN_S = 1200   # 20 min base
_MAX_COOLDOWN_S  = 3600   # 1 h cap


def loss_cluster_check(sym: str, regime: str) -> tuple[bool, str]:
    """
    Regime-aware loss cluster guard.

    Returns (blocked: bool, reason: str).
    blocked=True  → caller should track_blocked("LOSS_CLUSTER") and skip.
    blocked=False → no action needed.

    Uses sym_recent_pnl from learning_monitor (last 8 pnl across all regimes).
    Cooldown scales with total loss magnitude (larger draw = longer pause).
    """
    now = time.time()

    # Check existing cooldown
    if sym in _blocked_until:
        rem = _blocked_until[sym] - now
        if rem > 0:
            return True, f"LOSS_CLUSTER:cooldown {rem:.0f}s"
        del _blocked_until[sym]

    try:
        from src.services.learning_monitor import sym_recent_pnl as _srp
        sp = _srp.get(sym, [])
    except Exception:
        return False, ""

    if len(sp) < 3:
        return False, ""   # insufficient history — never block new pairs

    max_consec = _LOSS_THRESHOLDS.get(regime, 3)

    # Count consecutive losses from most recent backward
    consec     = 0
    total_loss = 0.0
    for p in reversed(sp):
        if p < 0:
            consec     += 1
            total_loss += abs(p)
        else:
            break

    if consec >= max_consec:
        # Scale cooldown: base × (1 + loss_magnitude)
        cooldown = int(_BASE_COOLDOWN_S * (1 + total_loss * 10))
        cooldown = min(cooldown, _MAX_COOLDOWN_S)
        _blocked_until[sym] = now + cooldown
        reason = (
            f"LOSS_CLUSTER:{consec}losses regime={regime} "
            f"loss_sum={total_loss:.3f} cd={cooldown // 60}min"
        )
        log.warning("LOSS_CLUSTER block %s: %s", sym, reason)
        return True, reason

    return False, ""


def unblock_symbol(sym: str) -> None:
    """Force-remove cooldown for a symbol (e.g. after manual review)."""
    _blocked_until.pop(sym, None)


# ══════════════════════════════════════════════════════════════════════════════
# B16 — ConvRateTracker
# ══════════════════════════════════════════════════════════════════════════════

_signal_log: deque = deque(maxlen=500)   # rolling window of evaluated signals


def log_signal_outcome(sym: str, accepted: bool, reason: str = "") -> None:
    """
    Call at every decision point in evaluate_signal():
      - accepted=True  when decision=TAKE
      - accepted=False when any block fires, reason=block_name
    """
    _signal_log.append({
        "ts":       time.time(),
        "sym":      sym,
        "accepted": accepted,
        "reason":   reason,
    })


def conv_rate() -> float:
    """Fraction of evaluated signals that became trades (accepted=True)."""
    if not _signal_log:
        return 0.0
    opens = sum(1 for s in _signal_log if s["accepted"])
    return opens / len(_signal_log)


def conv_diagnose() -> dict:
    """Full conv-rate diagnostic — call from bot2/main.py or diagnose endpoint."""
    from collections import Counter
    total  = len(_signal_log)
    opens  = sum(1 for s in _signal_log if s["accepted"])
    reject = [s["reason"] for s in _signal_log if not s["accepted"] and s["reason"]]
    top    = dict(Counter(reject).most_common(5))
    cr     = opens / total if total > 0 else 0.0
    diag   = (
        "conv=0: pipeline rejects everything — check TIMING/LOSS_CLUSTER/FAST_FAIL"
        if cr == 0 and total > 10
        else f"low_conv={cr:.0%}: {top}" if cr < 0.10
        else "OK"
    )
    return {
        "total_evaluated":  total,
        "total_accepted":   opens,
        "conv_rate_pct":    round(cr * 100, 1),
        "top_blockers":     top,
        "diagnosis":        diag,
    }


# ══════════════════════════════════════════════════════════════════════════════
# B17 — DirectionBiasGuard
# ══════════════════════════════════════════════════════════════════════════════

_bias_history:  dict[str, deque] = {}   # "SYM_ACTION" → deque(maxlen=100) of pnl
_auto_disabled: set[str]         = set()

BIAS_MIN_N      = 20    # need ≥20 completed trades before acting
BIAS_DISABLE_T  = 0.20  # WR < 20% → auto-disable direction
BIAS_WARN_T     = 0.30  # WR < 30% → log warning (size reduced by caller)


def record_bias(sym: str, action: str, pnl: float) -> None:
    """
    Call on every trade close.  action = "BUY" | "SELL".
    Accumulates WR per (sym, action); auto-disables if WR < BIAS_DISABLE_T.
    """
    key = f"{sym}_{action}"
    if key not in _bias_history:
        _bias_history[key] = deque(maxlen=100)
    _bias_history[key].append(pnl)

    h  = _bias_history[key]
    n  = len(h)
    if n < BIAS_MIN_N:
        return

    wr = sum(1 for p in h if p > 0) / n
    if wr < BIAS_DISABLE_T and key not in _auto_disabled:
        _auto_disabled.add(key)
        log.warning(
            "BIAS_DISABLE %s: WR=%.0f%% n=%d — direction suspended",
            key, wr * 100, n,
        )
    elif wr < BIAS_WARN_T:
        log.debug("BIAS_WARN %s: WR=%.0f%% n=%d", key, wr * 100, n)


def is_biased(sym: str, action: str) -> tuple[bool, str]:
    """
    Returns (blocked, reason).
    blocked=True → caller should track_blocked("BIAS_DISABLED") and skip.
    """
    key = f"{sym}_{action}"
    if key not in _auto_disabled:
        return False, ""
    h  = _bias_history.get(key, deque())
    wr = sum(1 for p in h if p > 0) / len(h) if h else 0.0
    return True, f"BIAS_DISABLED:{key} WR={wr:.0%} n={len(h)}"


def manual_reenable(sym: str, action: str) -> None:
    """Re-enable a direction that was auto-disabled (after manual review)."""
    _auto_disabled.discard(f"{sym}_{action}")


def bias_summary() -> list[dict]:
    """All tracked directions sorted by WR ascending (worst first)."""
    rows = []
    for key, h in _bias_history.items():
        if len(h) < 5:
            continue
        wr     = sum(1 for p in h if p > 0) / len(h)
        status = (
            "DISABLED" if key in _auto_disabled
            else "WARN"   if wr < BIAS_WARN_T
            else "OK"
        )
        rows.append({"pair": key, "wr": round(wr, 3), "n": len(h), "status": status})
    return sorted(rows, key=lambda r: r["wr"])
