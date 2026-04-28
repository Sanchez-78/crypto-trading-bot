"""V10.13u+20 P1.1: Paper Exploration from Rejected Signals

Enables the bot to explore rejected signals in paper-only mode to build learning
data about which rejects are actually profitable.

Buckets: A (strict TAKE), B (recovery-ready), C (weak EV), D (neg EV control),
         E (no pattern control), F (blocked control - disabled by default)
"""
import os
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# ── Exploration Budget Tracking ────────────────────────────────────────────
_exploration_hourly_caps = {
    "D_NEG_EV_CONTROL": {"max": 1, "count": 0, "window_start": 0},
    "E_NO_PATTERN": {"max": 1, "count": 0, "window_start": 0},
}

_ONE_HOUR_S = 3600

# P1.1i: C_WEAK_EV bucket tuning
_COST_ESTIMATE_FEE_PCT = 0.0015  # round-trip fee ~0.15%
_COST_ESTIMATE_SLIPPAGE_PCT = 0.0003  # slippage ~0.03%
_COST_TOTAL_PCT = (_COST_ESTIMATE_FEE_PCT + _COST_ESTIMATE_SLIPPAGE_PCT) * 100  # ~0.18%
_MIN_EDGE_BUFFER_PCT = 0.05  # 5 bps min edge buffer
_MIN_REQUIRED_MOVE_PCT = _COST_TOTAL_PCT + _MIN_EDGE_BUFFER_PCT  # ~0.23%

# Throttle tracking for bad C_WEAK_EV buckets
_THROTTLED_BUCKETS = set()  # set of "C_WEAK_EV" or "C1_WEAK_EV_MOMENTUM", etc.


def _estimate_expected_move(signal: dict) -> float:
    """Estimate expected move percentage from signal metrics.

    Returns:
        Expected move % (positive), or 0 if unavailable
    """
    # Try to use ATR/volatility if available
    atr = signal.get("atr")
    if atr:
        return float(atr) * 100

    # Fallback: use volatility estimate
    volatility = signal.get("volatility", 0.0)
    if volatility > 0:
        return float(volatility) * 100

    # Last resort: use score as proxy (score * 1.5 ~= expected move %)
    score = float(signal.get("score", 0.0))
    if score > 0:
        return score * 1.5

    return 0.0


def _check_cost_edge(expected_move_pct: float) -> bool:
    """Check if expected move can beat total cost.

    Args:
        expected_move_pct: Expected price movement %

    Returns:
        True if edge exists (move > cost + buffer), False otherwise
    """
    return expected_move_pct >= _MIN_REQUIRED_MOVE_PCT


def _score_direction_quality(signal: dict, ctx: Optional[dict] = None) -> float:
    """Score direction quality based on momentum/reversal signals.

    Returns:
        Score 0.0-1.0; used for C1/C2 sub-bucket selection
    """
    ctx = ctx or {}
    regime = signal.get("regime", "RANGING")
    action = signal.get("action", "BUY")
    ev = float(signal.get("ev", 0.0))

    score = 0.0

    # Momentum alignment
    ema_diff = signal.get("ema_diff", 0.0)
    macd = signal.get("macd", 0.0)
    mom5 = signal.get("mom5", 0.0)
    mom10 = signal.get("mom10", 0.0)

    if action == "BUY":
        # For BUY: positive ema_diff, positive macd, positive momentum is good
        if ema_diff > 0:
            score += 0.2
        if macd > 0:
            score += 0.15
        if mom5 > 0:
            score += 0.1
        if mom10 > 0:
            score += 0.1
        # Penalize if overbought
        rsi = signal.get("rsi", 50)
        if rsi > 70:
            score -= 0.15
    else:  # SELL
        # For SELL: negative ema_diff, negative macd, negative momentum is good
        if ema_diff < 0:
            score += 0.2
        if macd < 0:
            score += 0.15
        if mom5 < 0:
            score += 0.1
        if mom10 < 0:
            score += 0.1
        # Penalize if oversold
        rsi = signal.get("rsi", 50)
        if rsi < 30:
            score -= 0.15

    # Clamp to [0, 1]
    return max(0.0, min(1.0, score))


def _classify_c_weak_ev_sub_bucket(
    signal: dict,
    ctx: Optional[dict] = None,
    direction_quality: float = 0.0,
) -> str:
    """Classify C_WEAK_EV into sub-buckets based on direction quality.

    Args:
        signal: Signal dict
        ctx: Context dict
        direction_quality: Pre-calculated direction quality score (0-1)

    Returns:
        "C1_WEAK_EV_MOMENTUM", "C2_WEAK_EV_REVERSAL", or "C0_WEAK_EV_REJECTED"
    """
    ctx = ctx or {}
    action = signal.get("action", "BUY")
    rsi = signal.get("rsi", 50)
    mom_score = direction_quality

    # C1: momentum aligned (score >= 0.4, not extreme RSI)
    if mom_score >= 0.4:
        # Reject if overbought LONG or oversold SHORT
        if action == "BUY" and rsi > 75:
            return "C0_WEAK_EV_REJECTED"
        if action == "SELL" and rsi < 25:
            return "C0_WEAK_EV_REJECTED"
        return "C1_WEAK_EV_MOMENTUM"

    # C2: reversal signal (RSI extreme)
    if (action == "BUY" and rsi < 30) or (action == "SELL" and rsi > 70):
        return "C2_WEAK_EV_REVERSAL"

    # Default: rejected if no clear direction
    return "C0_WEAK_EV_REJECTED"


def _check_hourly_cap(bucket: str) -> bool:
    """Check if bucket has reached its hourly cap. Reset cap every hour."""
    now = time.time()
    cap_info = _exploration_hourly_caps.get(bucket)

    if not cap_info:
        return True  # No cap for this bucket

    # Reset if window expired
    if now - cap_info["window_start"] >= _ONE_HOUR_S:
        cap_info["count"] = 0
        cap_info["window_start"] = now

    # Check if at cap
    if cap_info["count"] >= cap_info["max"]:
        return False  # At cap

    # Increment and allow
    cap_info["count"] += 1
    return True


def _apply_bucket_throttle(bucket: str, sub_bucket: str = "") -> bool:
    """Check if bucket is throttled due to bad performance.

    Args:
        bucket: Bucket name (e.g., "C_WEAK_EV")
        sub_bucket: Sub-bucket name if applicable

    Returns:
        True if bucket is throttled, False otherwise
    """
    throttle_key = sub_bucket if sub_bucket else bucket
    return throttle_key in _THROTTLED_BUCKETS


def _mark_bucket_throttled(bucket: str, sub_bucket: str = "", reason: str = ""):
    """Mark a bucket as throttled (e.g., due to bad PF).

    Args:
        bucket: Bucket name
        sub_bucket: Sub-bucket name if applicable
        reason: Reason for throttle (e.g., "bad_pf_timeout")
    """
    throttle_key = sub_bucket if sub_bucket else bucket
    _THROTTLED_BUCKETS.add(throttle_key)
    log.warning(
        "[PAPER_BUCKET_THROTTLE] bucket=%s sub_bucket=%s reason=%s",
        bucket,
        sub_bucket or "N/A",
        reason,
    )


def paper_exploration_override(signal: dict, ctx: Optional[dict] = None) -> dict:
    """
    Determine if a rejected signal should be explored in paper-only mode.

    Args:
        signal: Signal dict with symbol, action, ev, score, features, regime, etc.
        ctx: Optional context dict with rejection reason, quality metrics, etc.

    Returns:
        {
            "allowed": bool,                    # Whether to explore this rejection
            "bucket": str,                      # Bucket classification (A-F)
            "reason": str,                      # Human-readable reason
            "size_mult": float,                 # Size multiplier (0.0-1.0)
            "max_hold_s": int,                  # Max hold time in seconds
            "tags": list[str],                  # Tags for learning tracking
            "explore_sub_bucket": str,          # Sub-bucket (C1/C2/etc, P1.1i)
            "direction_quality_score": float,   # Direction quality 0-1 (P1.1i)
            "cost_edge_ok": bool,               # Cost edge exists (P1.1i)
            "tp_pct": float,                    # TP target (P1.1i)
            "sl_pct": float,                    # SL target (P1.1i)
        }

    Never raises. Always returns a valid dict.
    """
    try:
        symbol = signal.get("symbol", "UNKNOWN")
        action = signal.get("action", "BUY")
        ev = float(signal.get("ev") or 0.0)
        score = float(signal.get("score") or 0.0)
        regime = signal.get("regime", "RANGING")

        ctx = ctx or {}
        reject_reason = ctx.get("reject_reason", "UNKNOWN")
        recovery_ready = ctx.get("recovery_ready", False)
        probe_ready = ctx.get("probe_ready", False)

        # Quality metrics (0-1 scale, 0 = all zero)
        quality_p = float(signal.get("p") or 0.0)
        quality_coh = float(signal.get("coherence") or 0.0)
        quality_af = float(signal.get("auditor_factor") or 0.0)
        quality_any = quality_p or quality_coh or quality_af

        # ────────────────────────────────────────────────────────────────
        # Bucket Classification Logic (from P1.1 spec)
        # ────────────────────────────────────────────────────────────────

        # A_STRICT_TAKE: Normal TAKE routed by P0.3 (handled upstream, not here)
        # Return false for bucket A — those go through normal paper routing

        # B_RECOVERY_READY: Weak EV but recovery/deadlock probe ready or near-ready
        if ev >= 0.038 or recovery_ready or probe_ready:
            if not _check_hourly_cap("B_RECOVERY_READY"):
                return {
                    "allowed": False,
                    "bucket": "B_RECOVERY_READY",
                    "reason": "hourly_cap_exceeded",
                    "size_mult": 0.15,
                    "max_hold_s": 900,
                    "tags": [],
                }
            return {
                "allowed": True,
                "bucket": "B_RECOVERY_READY",
                "reason": f"recovery_ready={recovery_ready} probe_ready={probe_ready} ev={ev:.4f}",
                "size_mult": 0.15,
                "max_hold_s": 900,
                "tags": ["recovery_probe"],
            }

        # C_WEAK_EV: Positive EV but below ECON_BAD floor, and has quality
        if ev > 0 and quality_any > 0:
            # P1.1i: Check cost-edge and sub-bucket classification
            expected_move = _estimate_expected_move(signal)
            has_edge = _check_cost_edge(expected_move)
            direction_quality = _score_direction_quality(signal, ctx)
            sub_bucket = _classify_c_weak_ev_sub_bucket(signal, ctx, direction_quality)

            # If no cost edge or rejected sub-bucket, skip C_WEAK_EV
            if not has_edge:
                return {
                    "allowed": False,
                    "bucket": "C_WEAK_EV",
                    "reason": f"cost_edge_too_low expected_move={expected_move:.4f} cost={_COST_TOTAL_PCT:.4f}",
                    "size_mult": 0.0,
                    "max_hold_s": 0,
                    "tags": [],
                    "explore_sub_bucket": "C0_WEAK_EV_REJECTED",
                    "direction_quality_score": direction_quality,
                    "cost_edge_ok": False,
                }

            if sub_bucket == "C0_WEAK_EV_REJECTED":
                return {
                    "allowed": False,
                    "bucket": "C_WEAK_EV",
                    "reason": f"direction_quality_low score={direction_quality:.3f}",
                    "size_mult": 0.0,
                    "max_hold_s": 0,
                    "tags": [],
                    "explore_sub_bucket": sub_bucket,
                    "direction_quality_score": direction_quality,
                    "cost_edge_ok": has_edge,
                }

            # P1.1i: Check if sub-bucket is throttled
            if _apply_bucket_throttle("C_WEAK_EV", sub_bucket):
                return {
                    "allowed": False,
                    "bucket": "C_WEAK_EV",
                    "reason": f"sub_bucket_throttled {sub_bucket}",
                    "size_mult": 0.0,
                    "max_hold_s": 0,
                    "tags": [],
                    "explore_sub_bucket": sub_bucket,
                    "direction_quality_score": direction_quality,
                    "cost_edge_ok": has_edge,
                }

            # P1.1i: Reduced hold times for C_WEAK_EV sub-buckets
            if sub_bucket == "C1_WEAK_EV_MOMENTUM":
                max_hold = 300
                tp_pct = max(0.0025, _COST_TOTAL_PCT / 100.0 + 0.001)  # TP above cost
                sl_pct = max(0.0018, _COST_TOTAL_PCT / 100.0 + 0.0005)  # SL tighter
                size_mult = 0.08
            else:  # C2_WEAK_EV_REVERSAL
                max_hold = 240
                tp_pct = max(0.0020, _COST_TOTAL_PCT / 100.0 + 0.0008)
                sl_pct = max(0.0016, _COST_TOTAL_PCT / 100.0 + 0.0004)
                size_mult = 0.06

            return {
                "allowed": True,
                "bucket": "C_WEAK_EV",
                "reason": f"weak_ev={ev:.4f} quality={quality_any:.3f} sub_bucket={sub_bucket}",
                "size_mult": size_mult,
                "max_hold_s": max_hold,
                "tags": ["weak_ev_positive", sub_bucket.lower()],
                "explore_sub_bucket": sub_bucket,
                "direction_quality_score": direction_quality,
                "cost_edge_ok": has_edge,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
            }

        # D_NEG_EV_CONTROL: Tiny capped sample of negative EV baseline
        if ev <= 0 and "NEGATIVE" in reject_reason:
            if not _check_hourly_cap("D_NEG_EV_CONTROL"):
                return {
                    "allowed": False,
                    "bucket": "D_NEG_EV_CONTROL",
                    "reason": "hourly_cap_exceeded",
                    "size_mult": 0.03,
                    "max_hold_s": 300,
                    "tags": ["control"],
                }
            return {
                "allowed": True,
                "bucket": "D_NEG_EV_CONTROL",
                "reason": f"control_baseline ev={ev:.4f}",
                "size_mult": 0.03,
                "max_hold_s": 300,
                "tags": ["control", "baseline"],
            }

        # E_NO_PATTERN: Tiny capped NO_CANDIDATE_PATTERN baseline
        if "NO_PATTERN" in reject_reason or "NO_CANDIDATE" in reject_reason:
            if not _check_hourly_cap("E_NO_PATTERN"):
                return {
                    "allowed": False,
                    "bucket": "E_NO_PATTERN",
                    "reason": "hourly_cap_exceeded",
                    "size_mult": 0.02,
                    "max_hold_s": 300,
                    "tags": ["control"],
                }
            return {
                "allowed": True,
                "bucket": "E_NO_PATTERN",
                "reason": f"no_pattern_baseline",
                "size_mult": 0.02,
                "max_hold_s": 300,
                "tags": ["control", "pattern_baseline"],
            }

        # F_BLOCKED_CONTROL: Disabled by default
        # Return false — we don't explore F bucket

        # Default: No exploration
        return {
            "allowed": False,
            "bucket": "UNKNOWN",
            "reason": "no_bucket_matched",
            "size_mult": 0.0,
            "max_hold_s": 0,
            "tags": [],
        }

    except Exception as e:
        log.warning(f"[PAPER_EXPLORE_ERROR] {e} — exploration blocked")
        return {
            "allowed": False,
            "bucket": "ERROR",
            "reason": str(e),
            "size_mult": 0.0,
            "max_hold_s": 0,
            "tags": [],
        }


def get_exploration_stats() -> dict:
    """Return current exploration hourly cap stats."""
    return {
        "D_NEG_EV_CONTROL": dict(_exploration_hourly_caps["D_NEG_EV_CONTROL"]),
        "E_NO_PATTERN": dict(_exploration_hourly_caps["E_NO_PATTERN"]),
    }


def reset_exploration_caps() -> None:
    """Reset hourly caps (for testing and day boundaries)."""
    now = time.time()
    for bucket in _exploration_hourly_caps.keys():
        _exploration_hourly_caps[bucket]["count"] = 0
        _exploration_hourly_caps[bucket]["window_start"] = now


def maybe_open_paper_exploration_from_reject(
    signal: dict,
    ctx: Optional[dict] = None,
    *,
    original_decision: str,
    reject_reason: str,
    current_price: Optional[float] = None,
) -> bool:
    """Try opening a paper exploration trade from a rejected real-price signal.

    Called from active reject hooks in production. Returns True if paper position opened.
    Observability/safety only. Never raises.

    Args:
        signal: Signal dict with symbol, ev, score, p, coh, af, regime, etc.
        ctx: Optional context dict
        original_decision: Reject decision (e.g., "REJECT_ECON_BAD_ENTRY")
        reject_reason: Reject reason (e.g., "weak_ev")
        current_price: Current real market price (try this first)

    Returns:
        True if paper position was opened, False otherwise
    """
    try:
        from src.core.runtime_mode import is_paper_mode, paper_exploration_enabled

        if not is_paper_mode() or not paper_exploration_enabled():
            return False

        signal = signal or {}
        ctx = ctx or {}

        # Resolve symbol
        symbol = signal.get("symbol") or ctx.get("symbol") or "UNKNOWN"

        # Resolve real price (priority order)
        price = None
        for price_candidate in [
            current_price,
            signal.get("price"),
            signal.get("last_price"),
            signal.get("current_price"),
            ctx.get("price"),
            ctx.get("last_price"),
            ctx.get("current_price"),
        ]:
            if price_candidate and isinstance(price_candidate, (int, float)) and price_candidate > 0:
                price = price_candidate
                break

        if not price:
            log.warning(
                "[PAPER_EXPLORE_SKIP] reason=no_real_price symbol=%s original_decision=%s reject_reason=%s",
                symbol,
                original_decision,
                reject_reason,
            )
            return False

        # Check if this reject should be explored
        explore_ctx = {
            "reject_reason": reject_reason,
            "recovery_ready": ctx.get("recovery_ready", False),
            "probe_ready": ctx.get("probe_ready", False),
        }
        ov = paper_exploration_override(signal, explore_ctx)

        if not ov.get("allowed"):
            log.warning(
                "[PAPER_EXPLORE_SKIP] reason=%s bucket=%s symbol=%s original_decision=%s reject_reason=%s",
                ov.get("reason", "not_allowed"),
                ov.get("bucket", "UNKNOWN"),
                symbol,
                original_decision,
                reject_reason,
            )
            return False

        # Open paper position with exploration metadata
        from src.services.paper_trade_executor import open_paper_position, _POSITION_SIZE

        base_size_usd = _POSITION_SIZE
        final_size_usd = base_size_usd * ov["size_mult"]

        result = open_paper_position(
            signal,
            price=price,
            ts=time.time(),
            reason="PAPER_EXPLORE",
            extra={
                "paper_source": "exploration_reject",
                "explore_bucket": ov["bucket"],
                "original_decision": original_decision,
                "reject_reason": reject_reason,
                "size_mult": ov["size_mult"],
                "final_size_usd": final_size_usd,
                "max_hold_s": ov["max_hold_s"],
                "tags": ov["tags"],
            },
        )

        if result.get("status") == "opened":
            log.warning(
                "[PAPER_EXPLORE_ENTRY] bucket=%s symbol=%s side=%s original_decision=%s "
                "ev=%.4f score=%.3f price=%.8f base_size_usd=%.2f size_mult=%.4f final_size_usd=%.2f "
                "max_hold_s=%d reject_reason=%s reason=%s",
                ov["bucket"],
                symbol,
                signal.get("action", "BUY"),
                original_decision,
                signal.get("ev", 0.0),
                signal.get("score", 0.0),
                price,
                base_size_usd,
                ov["size_mult"],
                final_size_usd,
                int(ov["max_hold_s"]),
                reject_reason,
                ov["reason"],
            )
            return True

        return False

    except Exception as e:
        log.debug(f"[PAPER_EXPLORE_ERROR] {e}")
        return False
