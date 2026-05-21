"""
signal_summary_contract.py — Canonical signal pipeline summary for Android.

Builds a single Firestore document for signal_summary/latest.
Pure builder, no Firebase/runtime imports.

Schema version: signal_summary_v1
Android reads: signal_summary/latest (one document)
"""

import time as _time
from typing import Optional


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        v = float(value)
        if v != v or v == float('inf') or v == float('-inf'):  # NaN / inf check
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_str(value, default: str = "") -> str:
    try:
        return str(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def build_signal_summary_snapshot(
    *,
    session_metrics: Optional[dict] = None,
    rejection_breakdown: Optional[dict] = None,
    last_signals: Optional[dict] = None,
    now: Optional[float] = None,
) -> dict:
    """
    Build canonical signal pipeline summary snapshot.

    Args:
        session_metrics:     Current session metrics with signal counts
        rejection_breakdown: Dict of rejection reason -> count
        last_signals:        {symbol: signal_dict} latest signals per symbol
        now:                 Current timestamp

    Returns:
        dict — snapshot ready for Firestore set()
    """
    if now is None:
        now = _time.time()

    session_metrics = session_metrics or {}
    rejection_breakdown = rejection_breakdown or {}
    last_signals = last_signals or {}

    # ── Signal Counters ──────────────────────────────────────────────────────
    signals_generated_count = _safe_int(session_metrics.get("signals_generated_count"))
    signals_filtered_count = _safe_int(session_metrics.get("signals_filtered_count"))
    signals_executed_count = _safe_int(session_metrics.get("signals_executed_count"))
    signals_blocked_count = _safe_int(session_metrics.get("signals_blocked_count"))

    # Rejection reasons breakdown
    rejection_breakdown_normalized = {}
    total_rejections = 0
    for reason, count in (rejection_breakdown or {}).items():
        c = _safe_int(count)
        rejection_breakdown_normalized[_safe_str(reason)] = c
        total_rejections += c

    # Top rejection reasons (by count)
    top_rejection_reasons = sorted(
        rejection_breakdown_normalized.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]

    # ── Last Signals ──────────────────────────────────────────────────────────
    latest_signals = []
    if isinstance(last_signals, dict):
        for symbol, signal_data in list(last_signals.items())[:20]:  # Max 20 symbols
            if not isinstance(signal_data, dict):
                continue

            sig_ts = _safe_float(signal_data.get("ts") or signal_data.get("timestamp"))
            age_s = round(now - sig_ts, 1) if sig_ts > 0 else None

            latest_signals.append({
                "symbol": _safe_str(symbol),
                "action": _safe_str(signal_data.get("action"), "HOLD").upper(),
                "confidence": _safe_float(signal_data.get("confidence") or signal_data.get("p")),
                "timestamp": sig_ts,
                "age_seconds": age_s,
            })

    # Sort by timestamp descending
    latest_signals.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # ── Last accepted signals (if available) ───────────────────────────────────
    last_accepted_signal_ts = _safe_float(session_metrics.get("last_accept_ts") or session_metrics.get("last_accepted_signal_ts"))
    last_signal_ts = _safe_float(session_metrics.get("last_signal_ts"))

    # ── Build Snapshot ────────────────────────────────────────────────────────
    snapshot = {
        "schema_version": "signal_summary_v1",
        "generated_at": now,
        "source": "cryptomaster_bot",

        # Signal counts
        "signal_counts": {
            "generated": signals_generated_count,
            "filtered": signals_filtered_count,
            "executed": signals_executed_count,
            "blocked": signals_blocked_count,
            "total_rejections": total_rejections,
        },

        # Rejection breakdown
        "rejections": {
            "breakdown": rejection_breakdown_normalized,
            "top_reasons": [{"reason": r[0], "count": r[1]} for r in top_rejection_reasons],
        },

        # Latest signals
        "latest_signals": latest_signals,

        # Timestamps
        "timestamps": {
            "last_signal_ts": last_signal_ts,
            "last_accepted_signal_ts": last_accepted_signal_ts,
        },

        # Metadata
        "metadata": {
            "symbols_with_signals": len(latest_signals),
            "note": "Signal counts are cumulative in session. Timestamps are unix seconds.",
        },
    }

    return snapshot
