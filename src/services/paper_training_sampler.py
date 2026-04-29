"""V10.13u+21 P1.1k: Active Paper Training Sampler

Opens paper positions when normal RDE rejects signals, using real live prices
for learning. Only active in paper_train mode, never in paper_live or live_real.

Goal: collect minimum N closed trades per hour for learning data.
"""
import os
import logging
import time
from typing import Optional, Tuple

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


def _is_training_enabled() -> bool:
    """Check if paper training mode is active (paper_train, not paper_live/live_real)."""
    try:
        from src.core.runtime_mode import is_paper_mode, is_live_trading_enabled
        # paper_train = paper_mode + NOT live_trading_enabled
        return _TRAINING_ENABLED and is_paper_mode() and not is_live_trading_enabled()
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


def _maybe_log_training_health() -> None:
    """Log training health every 10 minutes."""
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

    log.info(
        "[PAPER_TRAIN_HEALTH] open=... closed_1h=%d entries_1h=%d target_1h=%d "
        "learning_updates_1h=%d status=%s",
        closed_1h,
        entries_1h,
        _MIN_ENTRIES_PER_HOUR,
        _training_metrics["learning_updates_1h"],
        status,
    )

    if status == "STARVED":
        log.warning(
            "[PAPER_TRAIN_STARVED] entries_1h=%d < target=%d reason=insufficient_rejection_sampling",
            entries_1h,
            _MIN_ENTRIES_PER_HOUR,
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

        # Calculate cost edge (for logging, not blocking in training)
        from src.services.paper_exploration import _estimate_expected_move, _check_cost_edge
        expected_move_dec, expected_move_pct = _estimate_expected_move(signal)
        cost_edge_ok = _check_cost_edge(expected_move_dec)

        # Log entry
        log.info(
            "[PAPER_TRAIN_ENTRY] bucket=%s symbol=%s side=%s price=%.8f size_mult=%.3f "
            "ev=%.4f cost_edge_ok=%s expected_move_pct=%.4f side_inferred=%s source_reject=%s",
            bucket,
            symbol,
            side,
            current_price,
            size_mult,
            float(signal.get("ev", 0.0)),
            cost_edge_ok,
            expected_move_pct,
            side_inferred,
            reason,
        )

        # Record entry metric
        _training_metrics["entries_1h"].append(time.time())
        _maybe_log_training_health()

        return {
            "allowed": True,
            "bucket": bucket,
            "reason": f"training_sample bucket={bucket}",
            "size_mult": size_mult,
            "side": side,
            "side_inferred": side_inferred,
            "cost_edge_ok": cost_edge_ok,
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
    """Record a closed training trade for health metrics."""
    _training_metrics["closed_1h"] += 1
    log.info("[PAPER_TRAIN_CLOSED] bucket=%s outcome=%s", bucket, outcome)


def record_training_learning_update() -> None:
    """Record a learning update from closed training trade."""
    _training_metrics["learning_updates_1h"] += 1
