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
    "last_health_log_ts": 0,
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

    # D_NEG_EV_CONTROL: learn what bad looks like
    if ev <= 0 and _ALLOW_NEG_EV:
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

    # P1.1AO: C_NEG_EV_PROBE: cold-start starvation recovery (paper_train only)
    if ev <= 0 and _is_cold_start_starvation():
        if _probe_state["lifetime_closed"] < _PROBE_MAX_LIFETIME_CLOSED:
            return ("C_NEG_EV_PROBE", 0.01)

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
        from src.services.learning_event import get_metrics
        if get_metrics().get("trades", 0) >= 100:
            return False
        now = time.time()
        return not any(now - ts < _PROBE_STARVATION_IDLE_S for ts in _entry_times_hour)
    except Exception:
        return False


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
    cost_edge_bypassed = False
    cost_edge_bypass_reason = "none"
    bootstrap_closed_trades = 0

    now = _now()
    _prune(now)

    symbol = str(symbol or "UNKNOWN").upper()
    side = str(side or "UNKNOWN").upper()
    bucket = str(bucket or "UNKNOWN")
    source_reject = str(source_reject or "UNKNOWN")

    # Cost-edge: do not open weak EV train if edge cannot cover costs
    # P1.1AE: Bootstrap training sample bypass - allow weak EV during cold-start in paper_train mode
    if bucket == "C_WEAK_EV_TRAIN" and cost_edge_ok is False:
        # Check for bootstrap training bypass conditions
        allow_bootstrap_bypass = False
        bypass_reason = ""

        try:
            from src.core.runtime_mode import get_trading_mode
            from src.services.learning_event import get_metrics as _gm_p11ae

            mode = get_trading_mode()
            is_paper_train = mode.value == "paper_train"

            # P1.1AE: Bypass cost_edge_too_low only if:
            # - paper_train mode
            # - routed from STRICT_TAKE_ROUTED_TO_TRAINING
            # - bootstrap active (< 50 closed trades or 0 total LM trades)
            if is_paper_train and "STRICT_TAKE_ROUTED_TO_TRAINING" in source_reject:
                metrics = _gm_p11ae()
                trades_closed = metrics.get("trades", 0)

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
            return _skip("cost_edge_too_low", symbol=symbol, bucket=bucket, source_reject=source_reject)

        # P1.1AE: Log the bypass candidate
        # P1.1AQ: Add flow diagnostics
        _log_bypass_flow("candidate", symbol, bypass_reason, bucket="C_WEAK_EV_TRAIN", source="STRICT_TAKE_ROUTED_TO_TRAINING")

    # Dedicated duplicate candidate cooldown
    from src.core.runtime_mode import PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S

    if "DUPLICATE_CANDIDATE" in source_reject:
        dk = f"{symbol}:{side}:DUPLICATE_CANDIDATE"
        last = _recent_dup_candidate.get(dk)
        if last is not None and now - last < PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S:
            # P1.1AQ: Log drop if this was a bypass candidate
            if cost_edge_bypassed:
                dup_age_s = now - last if last else 0.0
                _log_bypass_flow("drop", symbol, "duplicate_candidate", source=source_reject, duplicate_age_s=f"{dup_age_s:.1f}")
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

    # Global rate caps (per minute and per hour)
    from src.core.runtime_mode import (
        PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE,
        PAPER_TRAIN_MAX_ENTRIES_PER_HOUR,
        PAPER_TRAIN_MAX_OPEN_PER_SYMBOL,
        PAPER_TRAIN_MAX_OPEN_PER_BUCKET,
    )

    if len(_entry_times_minute) >= PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_rate_cap", source=source_reject)
        return _skip("max_entries_per_minute", symbol=symbol, bucket=bucket, source_reject=source_reject)

    if len(_entry_times_hour) >= PAPER_TRAIN_MAX_ENTRIES_PER_HOUR:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_rate_cap", source=source_reject)
        return _skip("max_entries_per_hour", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # P1.1AO: Probe-specific hard caps (independent of PAPER_TRAIN_MAX_OPEN_PER_BUCKET)
    if bucket == "C_NEG_EV_PROBE":
        # Rate cap: 2 new probes per 10 minutes
        if len(_probe_state["entry_times_10m"]) >= _PROBE_MAX_NEW_PER_10M:
            return _skip("probe_cap_rate", symbol=symbol, bucket=bucket, source_reject=source_reject)
        # Total open cap: 2 probe positions globally
        probe_open = sum(
            1 for p in (open_positions or [])
            if p.get("training_bucket") == "C_NEG_EV_PROBE"
        )
        if probe_open >= _PROBE_MAX_OPEN_TOTAL:
            return _skip("probe_cap_total_open", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # Open-position caps per symbol and bucket
    open_positions = open_positions or []
    open_symbol = 0
    open_bucket = 0
    for p in open_positions:
        if (p.get("paper_source") == "training_sampler") or p.get("training_bucket"):
            if str(p.get("symbol", "")).upper() == symbol:
                open_symbol += 1
            if str(p.get("training_bucket", "")) == bucket:
                open_bucket += 1

    if open_symbol >= PAPER_TRAIN_MAX_OPEN_PER_SYMBOL:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_max_open_per_symbol", source=source_reject, open_symbol=open_symbol)
        return _skip(
            "max_open_per_symbol",
            symbol=symbol,
            bucket=bucket,
            open_symbol=open_symbol,
        )

    if open_bucket >= PAPER_TRAIN_MAX_OPEN_PER_BUCKET:
        if cost_edge_bypassed:
            _log_bypass_flow("drop", symbol, "sampler_max_open_per_bucket", source=source_reject, open_bucket=open_bucket)
        return _skip("max_open_per_bucket", symbol=symbol, bucket=bucket, open_bucket=open_bucket)

    # Count total open positions
    open_total = len(open_positions)

    # All gates passed; record entry times for rate limiting
    _entry_times_minute.append(now)
    _entry_times_hour.append(now)

    # P1.1AK: Include bypass metadata in gate result
    # P1.1AQ: Include open position counts for diagnostics
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

    if status == "STARVED":
        log.warning(
            f"[PAPER_TRAIN_STARVED] entries_1h={entry_count} < target={target_count} reason=insufficient_rejection_sampling"
        )

    _training_metrics["last_health_log_ts"] = now


def maybe_open_training_sample(
    signal: dict,
    ctx: Optional[dict] = None,
    *,
    reason: str,
    current_price: Optional[float] = None,
) -> dict:
    """Try opening a paper training sample when normal RDE rejects.

    Only runs in paper_train mode. Never touches live_real. Uses real live prices.

    Args:
        signal: Signal dict
        ctx: Optional context dict
        reason: Rejection reason (e.g., "REJECT_ECON_BAD_ENTRY")
        current_price: Current market price (required)

    Returns:
        {
            "allowed": bool,
            "bucket": str,
            "reason": str,
            "size_mult": float,
            "side": str,
            "side_inferred": bool,
            "cost_edge_ok": bool,
            "expected_move_pct": float,
            "required_move_pct": float,
            "max_hold_s": int,
        }
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

        # P1.1AO: Starvation state log (throttled, 60s interval)
        _ts_now = time.time()
        if _is_cold_start_starvation() and _ts_now - _probe_state["starvation_last_log_ts"] >= _PROBE_STARVATION_LOG_S:
            _probe_state["starvation_last_log_ts"] = _ts_now
            try:
                from src.services.learning_event import get_metrics as _gm_ao
                _ao_gt = _gm_ao().get("trades", 0)
                log.info(
                    "[PAPER_TRAIN_STARVATION_STATE] mode=paper_train global_trades=%d "
                    "probe_lifetime_closed=%d ev=%.4f reason=cold_start_starvation",
                    _ao_gt,
                    _probe_state["lifetime_closed"],
                    float(signal.get("ev", 0.0)) if signal else 0.0,
                )
                # State mismatch: probe closed but global_trades still zero
                if _probe_state["lifetime_closed"] > 0 and _ao_gt == 0:
                    log.warning(
                        "[PAPER_TRAIN_STATE_MISMATCH] probe_lifetime_closed=%d "
                        "global_trades=0 reason=probe_closed_but_lm_not_counting",
                        _probe_state["lifetime_closed"],
                    )
            except Exception:
                pass

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

        # Calculate cost edge
        from src.services.paper_exploration import _estimate_expected_move, _check_cost_edge
        expected_move_dec, expected_move_pct = _estimate_expected_move(signal)
        cost_edge_ok = _check_cost_edge(expected_move_dec)

        # Apply quality gates (P1.1N: anti-spam dedupe and rate caps)
        gate_result = _training_quality_gate(
            symbol=symbol,
            side=side,
            bucket=bucket,
            source_reject=reason,
            cost_edge_ok=cost_edge_ok,
            open_positions=None,  # executor will enforce position caps
        )

        if not gate_result.get("allowed"):
            # P1.1P: Use throttled skip logger to prevent spam from duplicate bursts
            _log_train_skip_once(
                reason=gate_result.get("reason", "unknown"),
                symbol=symbol,
                side=side,
                bucket=bucket,
                source_reject=reason,
            )
            return {
                "allowed": False,
                "bucket": bucket,
                "reason": gate_result.get("reason"),
                "size_mult": 0.0,
                "side": side,
                "side_inferred": side_inferred,
                "cost_edge_ok": cost_edge_ok,
                "max_hold_s": 0,
            }

        # All gates passed; record entry metric
        _training_metrics["entries_1h"].append(time.time())
        _maybe_log_training_health()

        # P1.1AM: Log final acceptance of bypassed entries
        # P1.1AQ: Add open position counts and source for diagnostics
        if gate_result.get("cost_edge_bypassed"):
            import logging
            log_p11am = logging.getLogger(__name__)
            log_p11am.info(
                "[COST_EDGE_BYPASS_ACCEPTED] mode=paper_train symbol=%s bucket=%s reason=%s source=%s "
                "open_symbol=%d open_bucket=%d open_total=%d",
                symbol,
                bucket,
                gate_result.get("cost_edge_bypass_reason", "none"),
                reason,
                gate_result.get("open_symbol", 0),
                gate_result.get("open_bucket", 0),
                gate_result.get("open_total", 0),
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

        # P1.1AK: Include bypass metadata from gate result
        return {
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
            "required_move_pct": 0.23,  # reference from P1.1j
            "max_hold_s": _MAX_HOLD_S,
            "tags": ["training_sampler", bucket.lower()],
        }

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


def record_training_closed(bucket: str, outcome: str) -> None:
    """P1.1V: Record a closed training trade for health metrics. Never raises."""
    try:
        _metric_add_event("closed_1h")
        if bucket == "C_NEG_EV_PROBE":
            _probe_state["lifetime_closed"] += 1
        log.info("[PAPER_TRAIN_CLOSED] bucket=%s outcome=%s probe_lifetime_closed=%d",
                 bucket, outcome, _probe_state["lifetime_closed"])
    except Exception as e:
        log.warning("[PAPER_TRAIN_METRICS_ERROR] record_training_closed failed: %s", e)


def record_training_learning_update() -> None:
    """P1.1V: Record a learning update from closed training trade. Never raises."""
    try:
        _metric_inc_counter("learning_updates_1h", 1)
    except Exception as e:
        log.warning("[PAPER_TRAIN_METRICS_ERROR] record_training_learning_update failed: %s", e)
