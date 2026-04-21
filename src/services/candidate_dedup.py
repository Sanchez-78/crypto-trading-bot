"""
Candidate deduplication and bootstrap frequency guards.

Prevents repeated identical setups during cold start and maintains
sanity checks on entry cadence.
"""

import time
import logging

log = logging.getLogger(__name__)

# ── State tracking ─────────────────────────────────────────────────────────────

_recent_fingerprints = {}   # fingerprint -> timestamp of last seen
_recent_opens = []          # timestamps of recent opens (for bootstrap cap)
_open_by_symbol_side = {}   # (symbol, action) -> timestamp of last open

# Deduplication window: candidates older than this are expired
DEDUP_WINDOW_SECONDS = 20

# Bootstrap cap: max opens per minute during cold start
BOOTSTRAP_MAX_PER_MIN = 6

# Symbol+side cooldown: prevent rapid re-opening same side
SYMBOL_SIDE_COOLDOWN = 30


def _candidate_fingerprint(signal: dict) -> tuple:
    """
    Create a deterministic fingerprint for a candidate signal.

    Includes:
      - symbol
      - action (buy/sell)
      - regime
      - entry price (rounded to 0.0001)
      - active feature flags
    """
    sym = signal.get("symbol", "")
    action = signal.get("action", "")
    regime = signal.get("regime", "RANGING")
    price = signal.get("price", 0.0)

    # Round price to 4 decimals to allow tiny price drift
    price_bucket = round(price, 4)

    # Extract boolean features
    features = signal.get("features", {})
    feature_tuple = tuple(sorted(
        (k, v) for k, v in features.items()
        if isinstance(v, bool) and v
    ))

    fingerprint = (sym, action, regime, price_bucket, feature_tuple)
    return fingerprint


def _expire_old_fingerprints(now_ts: float) -> None:
    """Remove fingerprints older than DEDUP_WINDOW_SECONDS."""
    expired = [
        fp for fp, ts in _recent_fingerprints.items()
        if now_ts - ts > DEDUP_WINDOW_SECONDS
    ]
    for fp in expired:
        del _recent_fingerprints[fp]


def _expire_old_opens(now_ts: float) -> None:
    """Remove opens older than 60 seconds for bootstrap frequency cap."""
    while _recent_opens and now_ts - _recent_opens[0] > 60.0:
        _recent_opens.pop(0)


def check_duplicate(signal: dict) -> tuple[bool, str]:
    """
    Check if this candidate is a duplicate of a recent one.

    Returns: (allowed, skip_reason)
      allowed=True   → not a duplicate, proceed
      allowed=False  → is a duplicate, skip with reason
    """
    now = time.time()
    _expire_old_fingerprints(now)

    fp = _candidate_fingerprint(signal)

    if fp in _recent_fingerprints:
        last_seen = _recent_fingerprints[fp]
        age = now - last_seen
        log.debug(f"[DEDUP] candidate is duplicate: {fp[0]}/{fp[1]} "
                 f"regime={fp[2]} price={fp[3]} age={age:.1f}s")
        return False, f"DUPLICATE_CANDIDATE(age={age:.1f}s)"

    # Mark this fingerprint as seen
    _recent_fingerprints[fp] = now
    return True, ""


def check_symbol_side_cooldown(signal: dict) -> tuple[bool, str]:
    """
    Check if we recently opened a position on this symbol+side.

    Returns: (allowed, skip_reason)
    """
    now = time.time()
    sym = signal.get("symbol", "")
    action = signal.get("action", "")
    key = (sym, action)

    if key in _open_by_symbol_side:
        last_open = _open_by_symbol_side[key]
        age = now - last_open

        if age < SYMBOL_SIDE_COOLDOWN:
            log.debug(f"[COOLDOWN] {sym}/{action} opened {age:.1f}s ago "
                     f"(cooldown={SYMBOL_SIDE_COOLDOWN}s)")
            return False, f"SYMBOL_SIDE_COOLDOWN({age:.1f}s)"

    return True, ""


def check_bootstrap_frequency(signal: dict) -> tuple[bool, str]:
    """
    Check if bootstrap frequency cap is exceeded.

    During cold start (< 30 trades), limit new opens to prevent
    position flood.

    Returns: (allowed, skip_reason)
    """
    try:
        from src.services.learning_event import get_metrics
        trades = get_metrics().get("trades", 0)

        if trades >= 30:
            # Not in bootstrap mode anymore
            return True, ""

        now = time.time()
        _expire_old_opens(now)

        if len(_recent_opens) >= BOOTSTRAP_MAX_PER_MIN:
            log.warning(f"[BOOTSTRAP_CAP] {signal.get('symbol', '')} rejected: "
                       f"opened {len(_recent_opens)} trades in last 60s "
                       f"(limit={BOOTSTRAP_MAX_PER_MIN}) during bootstrap "
                       f"(trades_total={trades})")
            return False, f"BOOTSTRAP_FREQ_CAP({len(_recent_opens)}>={BOOTSTRAP_MAX_PER_MIN})"

        return True, ""
    except Exception:
        return True, ""


def record_open(signal: dict) -> None:
    """
    Record that a position was opened for this symbol+side.
    Call this AFTER a position is actually opened.
    """
    now = time.time()
    sym = signal.get("symbol", "")
    action = signal.get("action", "")
    key = (sym, action)

    _open_by_symbol_side[key] = now
    _recent_opens.append(now)

    log.debug(f"[OPEN_RECORDED] {sym}/{action} opens_last_60s={len(_recent_opens)}")


def reset_all() -> None:
    """Reset all dedup state (for testing/debugging)."""
    global _recent_fingerprints, _recent_opens, _open_by_symbol_side
    _recent_fingerprints.clear()
    _recent_opens.clear()
    _open_by_symbol_side.clear()
    log.info("[DEDUP_RESET] All deduplication state cleared")


# Diagnostic: expose state for testing
def get_state() -> dict:
    """Return current dedup state for diagnostics."""
    return {
        "fingerprints_count": len(_recent_fingerprints),
        "recent_opens_count": len(_recent_opens),
        "symbol_side_opens": dict(_open_by_symbol_side),
    }
