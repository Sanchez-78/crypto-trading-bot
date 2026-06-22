"""
V10.28+: Metric Cross-Validation System
Ensures all data sources are aligned and consistent.
ALWAYS verifies before using metrics for readiness decisions.
"""
import json
import urllib.request
import logging
from typing import Dict, Tuple, Optional

log = logging.getLogger(__name__)

# Configuration
BOT_API_URL = "http://localhost:5000/api/dashboard/metrics"
DASHBOARD_API_URL = "http://localhost:8080/dashboard_modern.html"  # Serves HTML
READINESS_API_URL = "http://localhost:5001/api/dashboard/readiness"

# Metrics to cross-check
CRITICAL_METRICS = [
    "closed_trades",
    "win_rate_pct",
    "profit_factor",
    "net_pnl",
    "open_positions",
]

# Tolerance thresholds for floating point comparison
TOLERANCES = {
    "win_rate_pct": 0.5,      # Allow 0.5% difference
    "profit_factor": 0.05,     # Allow 0.05x difference
    "net_pnl": 0.01,           # Allow $0.01 difference
    "closed_trades": 0,        # Must match exactly (integer)
    "open_positions": 0,       # Must match exactly (integer)
}


def fetch_from_source(url: str, name: str, timeout: int = 3) -> Optional[Dict]:
    """Fetch metrics from a source."""
    try:
        response = urllib.request.urlopen(url, timeout=timeout)
        data = json.loads(response.read().decode())
        log.debug(f"[CROSSCHECK] {name}: OK - fetched {len(data)} fields")
        return data
    except Exception as e:
        log.warning(f"[CROSSCHECK] {name}: UNAVAILABLE - {type(e).__name__}: {str(e)[:100]}")
        return None


def compare_metrics(bot_metrics: Dict, other_metrics: Dict, source_name: str) -> Tuple[bool, str]:
    """Compare metrics between bot API and another source."""
    mismatches = []

    for metric in CRITICAL_METRICS:
        if metric not in bot_metrics or metric not in other_metrics:
            continue

        bot_val = bot_metrics.get(metric)
        other_val = other_metrics.get(metric)
        tolerance = TOLERANCES.get(metric, 0)

        if bot_val is None or other_val is None:
            continue

        # For integers, require exact match
        if isinstance(bot_val, int) and isinstance(other_val, int):
            if bot_val != other_val:
                mismatches.append(
                    f"{metric}: Bot={bot_val} vs {source_name}={other_val}"
                )
        else:
            # For floats, allow tolerance
            diff = abs(float(bot_val) - float(other_val))
            if diff > tolerance:
                mismatches.append(
                    f"{metric}: Bot={bot_val:.4f} vs {source_name}={other_val:.4f} (diff={diff:.4f})"
                )

    if mismatches:
        reason = " | ".join(mismatches)
        return False, reason

    return True, "All metrics aligned"


def crosscheck_all_sources() -> Dict:
    """
    Cross-check metrics from all available sources.
    Returns: {
        "status": "OK" | "WARNING" | "ERROR",
        "authoritative": {...},  # Bot API data
        "sources": {
            "bot_api": {"available": bool, "data": {...}},
            "readiness_api": {"available": bool, "data": {...}},
        },
        "validation": {
            "bot_vs_readiness": {"match": bool, "reason": str},
        },
        "message": str
    }
    """

    # Fetch from all sources
    bot_metrics = fetch_from_source(BOT_API_URL, "Bot API (5000)")
    readiness_data = fetch_from_source(READINESS_API_URL, "Readiness API (5001)")

    if not bot_metrics:
        return {
            "status": "ERROR",
            "authoritative": None,
            "sources": {
                "bot_api": {"available": False, "data": None},
                "readiness_api": {"available": bool(readiness_data), "data": readiness_data},
            },
            "validation": {},
            "message": "Bot API (5000) unavailable - cannot proceed",
        }

    # Cross-check available sources
    validation = {}

    if readiness_data:
        match, reason = compare_metrics(bot_metrics, readiness_data, "Readiness API")
        validation["bot_vs_readiness"] = {"match": match, "reason": reason}
        if not match:
            log.warning(
                f"[CROSSCHECK_DIVERGENCE] Bot API vs Readiness API: {reason}"
            )

    # Determine overall status
    all_match = all(v.get("match", True) for v in validation.values())
    status = "OK" if all_match else "WARNING"

    if not readiness_data:
        status = "OK" if bot_metrics else "ERROR"
        message = "Single source available - using Bot API"
    elif all_match:
        message = f"All sources aligned ({len(validation)} cross-checks passed)"
    else:
        failed = sum(1 for v in validation.values() if not v.get("match", True))
        message = f"Divergence detected ({failed}/{len(validation)} mismatches)"

    return {
        "status": status,
        "authoritative": bot_metrics,  # Always Bot API
        "sources": {
            "bot_api": {"available": bool(bot_metrics), "data": bot_metrics},
            "readiness_api": {"available": bool(readiness_data), "data": readiness_data},
        },
        "validation": validation,
        "message": message,
    }


def get_authoritative_metrics() -> Optional[Dict]:
    """
    Get metrics from authoritative source (Bot API).
    Always performs cross-check first.
    Returns: metrics dict or None if unavailable
    """
    result = crosscheck_all_sources()

    if result["status"] == "ERROR":
        log.error(f"[METRICS] {result['message']}")
        return None

    if result["status"] == "WARNING":
        log.warning(f"[METRICS_CROSSCHECK] {result['message']}")

    # Log status if any divergence
    for check_name, check_result in result.get("validation", {}).items():
        if not check_result.get("match"):
            log.warning(
                f"[METRICS_DIVERGENCE] {check_name}: {check_result.get('reason', 'unknown')}"
            )

    return result["authoritative"]


def format_crosscheck_report(result: Dict) -> str:
    """Format cross-check result as human-readable report."""
    report = []
    report.append("=" * 70)
    report.append("METRIC CROSS-CHECK REPORT")
    report.append("=" * 70)

    report.append(f"\nStatus: {result['status']}")
    report.append(f"Message: {result['message']}\n")

    # Source availability
    report.append("Data Sources:")
    for source, info in result.get("sources", {}).items():
        status_icon = "✓" if info.get("available") else "✗"
        report.append(f"  {status_icon} {source}: {'AVAILABLE' if info.get('available') else 'UNAVAILABLE'}")

    # Validation results
    if result.get("validation"):
        report.append("\nValidation Results:")
        for check, detail in result.get("validation", {}).items():
            icon = "✓" if detail.get("match") else "✗"
            status = "MATCH" if detail.get("match") else "DIVERGE"
            reason = detail.get("reason", "")
            report.append(f"  {icon} {check}: {status}")
            if reason and not detail.get("match"):
                report.append(f"     → {reason}")

    # Authoritative metrics
    if result.get("authoritative"):
        auth = result["authoritative"]
        report.append("\nAuthoritative Metrics (Bot API):")
        for metric in CRITICAL_METRICS:
            if metric in auth:
                value = auth[metric]
                if isinstance(value, float):
                    report.append(f"  {metric}: {value:.4f}")
                else:
                    report.append(f"  {metric}: {value}")

    report.append("=" * 70)
    return "\n".join(report)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = crosscheck_all_sources()
    print(format_crosscheck_report(result))
