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
        closed_trade: Closed trade dict with explore_bucket, outcome, net_pnl_pct, exit_reason
    """
    try:
        bucket = closed_trade.get("explore_bucket", "A_STRICT_TAKE")
        outcome = closed_trade.get("outcome", "FLAT")
        net_pnl_pct = float(closed_trade.get("net_pnl_pct", 0.0))
        exit_reason = closed_trade.get("exit_reason", "UNKNOWN")

        _init_bucket_metrics(bucket)
        metrics = _BUCKET_METRICS[bucket]

        # Update counts
        metrics["count"] += 1
        metrics["sum_net_pnl_pct"] += net_pnl_pct
        metrics["avg_net_pnl_pct"] = metrics["sum_net_pnl_pct"] / metrics["count"]
        metrics["last_close_ts"] = time.time()

        # Immediate compact log on every closed exploration trade
        log.info(
            f"[PAPER_BUCKET_UPDATE] bucket={bucket} n={metrics['count']} "
            f"outcome={outcome} net_pnl_pct={net_pnl_pct:.4f}"
        )

        # Update outcome counts
        if outcome == "WIN":
            metrics["wins"] += 1
        elif outcome == "LOSS":
            metrics["losses"] += 1
        else:
            metrics["flats"] += 1

        # Win rate
        if metrics["count"] > 0:
            metrics["wr"] = (metrics["wins"] / metrics["count"]) * 100.0

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
        elif exit_reason == "TP":
            metrics["tp_count"] += 1
        elif exit_reason == "SL":
            metrics["sl_count"] += 1

        if metrics["count"] > 0:
            metrics["timeout_rate"] = (metrics["timeout_count"] / metrics["count"]) * 100.0
            metrics["tp_rate"] = (metrics["tp_count"] / metrics["count"]) * 100.0
            metrics["sl_rate"] = (metrics["sl_count"] / metrics["count"]) * 100.0

        # Periodic log (every 10 minutes)
        _maybe_log_bucket_metrics()

    except Exception as e:
        log.warning(f"[BUCKET_METRICS_ERROR] {e}")


def _maybe_log_bucket_metrics() -> None:
    """Log bucket metrics if enough time has passed."""
    global _LAST_METRICS_LOG_TS
    now = time.time()

    if now - _LAST_METRICS_LOG_TS >= _METRICS_LOG_INTERVAL_S:
        for bucket, metrics in _BUCKET_METRICS.items():
            if metrics["count"] > 0:
                log.info(
                    f"[PAPER_BUCKET_METRICS] bucket={bucket} n={metrics['count']} "
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
