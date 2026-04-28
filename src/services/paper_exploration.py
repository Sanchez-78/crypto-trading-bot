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


def paper_exploration_override(signal: dict, ctx: Optional[dict] = None) -> dict:
    """
    Determine if a rejected signal should be explored in paper-only mode.

    Args:
        signal: Signal dict with symbol, action, ev, score, features, regime, etc.
        ctx: Optional context dict with rejection reason, quality metrics, etc.

    Returns:
        {
            "allowed": bool,           # Whether to explore this rejection
            "bucket": str,             # Bucket classification (A-F)
            "reason": str,             # Human-readable reason
            "size_mult": float,        # Size multiplier (0.0-1.0)
            "max_hold_s": int,         # Max hold time in seconds
            "tags": list[str],         # Tags for learning tracking
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
            return {
                "allowed": True,
                "bucket": "C_WEAK_EV",
                "reason": f"weak_ev={ev:.4f} quality={quality_any:.3f}",
                "size_mult": 0.08,
                "max_hold_s": 600,
                "tags": ["weak_ev_positive"],
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
                "ev=%.4f score=%.3f price=%.8f base_size_usd=%.2f size_mult=%.4f final_size_usd=%.2f reject_reason=%s reason=%s",
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
                reject_reason,
                ov["reason"],
            )
            return True

        return False

    except Exception as e:
        log.debug(f"[PAPER_EXPLORE_ERROR] {e}")
        return False
