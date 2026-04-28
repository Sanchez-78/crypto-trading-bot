"""V10.13u+20 P1.1e: Bucket learning metrics aggregation.

Tracks closed paper trade stats by explore_bucket to measure
exploration effectiveness per bucket.
"""
import logging
import time
from typing import Dict, Optional

log = logging.getLogger(__name__)

# Bucket metrics: {bucket_name -> {count, wins, losses, flats, ...}}
_BUCKET_METRICS: Dict[str, Dict] = {}
_LAST_METRICS_LOG_TS = 0
_METRICS_LOG_INTERVAL_S = 600  # Log metrics every 10 minutes


def _init_bucket_metrics(bucket: str) -> None:
    """Initialize metrics dict for a bucket."""
    if bucket not in _BUCKET_METRICS:
        _BUCKET_METRICS[bucket] = {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "wr": 0.0,  # win rate %
            "avg_net_pnl_pct": 0.0,
            "sum_net_pnl_pct": 0.0,
            "profit_factor": 0.0,
            "timeout_count": 0,
            "tp_count": 0,
            "sl_count": 0,
            "timeout_rate": 0.0,
            "tp_rate": 0.0,
            "sl_rate": 0.0,
            "last_close_ts": 0,
        }


def update_bucket_metrics(closed_trade: dict) -> None:
    """Update bucket metrics after a closed exploration trade.

    Args:
        closed_trade: Closed trade dict with explore_bucket, outcome, net_pnl_pct, exit_reason, explore_sub_bucket (optional)
    """
    try:
        bucket = closed_trade.get("explore_bucket", "A_STRICT_TAKE")
        sub_bucket = closed_trade.get("explore_sub_bucket", "")  # P1.1i
        outcome = closed_trade.get("outcome", "FLAT")
        net_pnl_pct = float(closed_trade.get("net_pnl_pct", 0.0))
        exit_reason = closed_trade.get("exit_reason", "UNKNOWN")

        _init_bucket_metrics(bucket)
        metrics = _BUCKET_METRICS[bucket]

        # P1.1i: Also track sub-bucket if present
        if sub_bucket:
            sub_bucket_key = f"{bucket}_{sub_bucket}"
            _init_bucket_metrics(sub_bucket_key)
            sub_metrics = _BUCKET_METRICS[sub_bucket_key]
        else:
            sub_metrics = None

        # Update counts
        metrics["count"] += 1
        metrics["sum_net_pnl_pct"] += net_pnl_pct
        metrics["avg_net_pnl_pct"] = metrics["sum_net_pnl_pct"] / metrics["count"]
        metrics["last_close_ts"] = time.time()

        if sub_metrics:
            sub_metrics["count"] += 1
            sub_metrics["sum_net_pnl_pct"] += net_pnl_pct
            sub_metrics["avg_net_pnl_pct"] = sub_metrics["sum_net_pnl_pct"] / sub_metrics["count"]
            sub_metrics["last_close_ts"] = time.time()

        # Immediate compact log on every closed exploration trade
        log.info(
            f"[PAPER_BUCKET_UPDATE] bucket={bucket} n={metrics['count']} "
            f"outcome={outcome} net_pnl_pct={net_pnl_pct:.4f}"
        )
        if sub_metrics:
            log.info(
                f"[PAPER_BUCKET_UPDATE] bucket={bucket} sub_bucket={sub_bucket} n={sub_metrics['count']} "
                f"outcome={outcome} net_pnl_pct={net_pnl_pct:.4f}"
            )

        # Update outcome counts
        if outcome == "WIN":
            metrics["wins"] += 1
            if sub_metrics:
                sub_metrics["wins"] += 1
        elif outcome == "LOSS":
            metrics["losses"] += 1
            if sub_metrics:
                sub_metrics["losses"] += 1
        else:
            metrics["flats"] += 1
            if sub_metrics:
                sub_metrics["flats"] += 1

        # Win rate
        if metrics["count"] > 0:
            metrics["wr"] = (metrics["wins"] / metrics["count"]) * 100.0
        if sub_metrics and sub_metrics["count"] > 0:
            sub_metrics["wr"] = (sub_metrics["wins"] / sub_metrics["count"]) * 100.0

        # Profit factor (avoid divide by zero)
        if metrics["losses"] > 0:
            winning_pnl = sum(
                float(t.get("net_pnl_pct", 0.0))
                for t in _BUCKET_METRICS.get(bucket, {}).get("_closed_trades", [])
                if t.get("outcome") == "WIN"
            )
            losing_pnl = abs(sum(
                float(t.get("net_pnl_pct", 0.0))
                for t in _BUCKET_METRICS.get(bucket, {}).get("_closed_trades", [])
                if t.get("outcome") == "LOSS"
            ))
            if losing_pnl > 1e-9:
                metrics["profit_factor"] = winning_pnl / losing_pnl
        else:
            metrics["profit_factor"] = 1.0 if metrics["wins"] > 0 else 0.0

        # Exit reason rates
        if exit_reason == "TIMEOUT":
            metrics["timeout_count"] += 1
            if sub_metrics:
                sub_metrics["timeout_count"] += 1
        elif exit_reason == "TP":
            metrics["tp_count"] += 1
            if sub_metrics:
                sub_metrics["tp_count"] += 1
        elif exit_reason == "SL":
            metrics["sl_count"] += 1
            if sub_metrics:
                sub_metrics["sl_count"] += 1

        if metrics["count"] > 0:
            metrics["timeout_rate"] = (metrics["timeout_count"] / metrics["count"]) * 100.0
            metrics["tp_rate"] = (metrics["tp_count"] / metrics["count"]) * 100.0
            metrics["sl_rate"] = (metrics["sl_count"] / metrics["count"]) * 100.0

        if sub_metrics and sub_metrics["count"] > 0:
            sub_metrics["timeout_rate"] = (sub_metrics["timeout_count"] / sub_metrics["count"]) * 100.0
            sub_metrics["tp_rate"] = (sub_metrics["tp_count"] / sub_metrics["count"]) * 100.0
            sub_metrics["sl_rate"] = (sub_metrics["sl_count"] / sub_metrics["count"]) * 100.0

        # P1.1i: Throttle detection for C_WEAK_EV
        if bucket == "C_WEAK_EV" and metrics["count"] >= 10:
            pf = metrics.get("profit_factor", 0.0)
            avg_pnl = metrics.get("avg_net_pnl_pct", 0.0)
            timeout_rate = metrics.get("timeout_rate", 0.0)

            if pf < 0.70 and avg_pnl < 0 and timeout_rate > 80:
                # Throttle the bucket
                from src.services.paper_exploration import _mark_bucket_throttled
                _mark_bucket_throttled(bucket, sub_bucket or "", "bad_pf_timeout")

        # Periodic log (every 10 minutes)
        _maybe_log_bucket_metrics()

    except Exception as e:
        log.warning(f"[BUCKET_METRICS_ERROR] {e}")


def _maybe_log_bucket_metrics() -> None:
    """Log bucket metrics if enough time has passed."""
    global _LAST_METRICS_LOG_TS
    now = time.time()

    if now - _LAST_METRICS_LOG_TS >= _METRICS_LOG_INTERVAL_S:
        for bucket_key, metrics in _BUCKET_METRICS.items():
            if metrics["count"] > 0:
                # P1.1i: Parse bucket and sub_bucket from composite key
                if "_" in bucket_key and bucket_key.startswith("C_WEAK_EV_"):
                    # Sub-bucket format: "C_WEAK_EV_C1_WEAK_EV_MOMENTUM"
                    parts = bucket_key.split("_", 1)
                    parent_bucket = parts[0]
                    sub_bucket = parts[1] if len(parts) > 1 else ""
                    log.info(
                        f"[PAPER_BUCKET_METRICS] bucket={parent_bucket} sub_bucket={sub_bucket} n={metrics['count']} "
                        f"wr={metrics['wr']:.1f}% avg={metrics['avg_net_pnl_pct']:.4f} "
                        f"pf={metrics['profit_factor']:.2f} "
                        f"timeout_rate={metrics['timeout_rate']:.1f}% "
                        f"tp_rate={metrics['tp_rate']:.1f}% sl_rate={metrics['sl_rate']:.1f}%"
                    )
                else:
                    log.info(
                        f"[PAPER_BUCKET_METRICS] bucket={bucket_key} n={metrics['count']} "
                        f"wr={metrics['wr']:.1f}% avg={metrics['avg_net_pnl_pct']:.4f} "
                        f"pf={metrics['profit_factor']:.2f} "
                        f"timeout_rate={metrics['timeout_rate']:.1f}% "
                        f"tp_rate={metrics['tp_rate']:.1f}% sl_rate={metrics['sl_rate']:.1f}%"
                    )
        _LAST_METRICS_LOG_TS = now


def get_bucket_metrics(bucket: Optional[str] = None) -> Dict:
    """Get bucket metrics snapshot.

    Args:
        bucket: Specific bucket name, or None for all buckets

    Returns:
        dict of bucket metrics
    """
    if bucket:
        return dict(_BUCKET_METRICS.get(bucket, {}))
    return {b: dict(m) for b, m in _BUCKET_METRICS.items()}


def reset_bucket_metrics() -> None:
    """Reset all bucket metrics (for testing)."""
    global _LAST_METRICS_LOG_TS
    _BUCKET_METRICS.clear()
    _LAST_METRICS_LOG_TS = 0
