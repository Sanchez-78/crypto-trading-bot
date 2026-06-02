"""Emergency Health Monitor — Auto-detection & remediation for critical failures

Monitors for:
1. RECON status != OK
2. Outbox pending/failed events
3. Firebase quota approaching limit
4. Learning updates stalled
5. Dashboard metrics reset to zero
6. Paper entry rate stuck at zero
7. Runtime crashes/tracebacks

Auto-remediation strategies:
- Restart affected components
- Clear problematic caches
- Force metrics refresh
- Trigger manual outbox flush
- Alert operator

Usage: Run periodically (every 60-300 seconds) or on event
"""
import logging
import time
import threading
from typing import Dict, List, Optional, Tuple
from collections import deque

log = logging.getLogger(__name__)

# State tracking
_monitor_state = {
    "last_recon_check": 0.0,
    "recon_failures": 0,
    "last_outbox_check": 0.0,
    "outbox_pending_count": 0,
    "last_quota_check": 0.0,
    "quota_warning_issued": False,
    "last_learning_update": 0.0,
    "learning_stall_count": 0,
    "last_dashboard_metrics": {},
    "last_entry_rate": 0,
    "entry_stall_count": 0,
    "crash_detection_enabled": True,
    "alerts_issued": [],  # Track issued alerts to avoid spam
}

_CHECKS_INTERVAL_S = 60.0  # Run health checks every 60 seconds
_RECON_FAILURE_THRESHOLD = 2  # Alert if RECON fails 2+ times
_OUTBOX_PENDING_THRESHOLD = 10  # Alert if 10+ pending events
_QUOTA_WARNING_THRESHOLD = 0.75  # Alert at 75% quota usage
_LEARNING_STALL_THRESHOLD = 600  # Alert if no learning for 10 minutes
_DASHBOARD_ZERO_THRESHOLD = 300  # Alert if dashboard metrics zero for 5 minutes
_ENTRY_STALL_THRESHOLD = 1800  # Alert if zero entries for 30 minutes despite EV candidates
_ALERT_COOLDOWN_S = 300  # Don't re-alert for same issue within 5 minutes

# Thresholds for remediation
_AUTO_REMEDIATE = {
    "recon_failure": 2,
    "outbox_stuck": 15,  # minutes
    "quota_critical": 0.90,
    "learning_stall": 900,  # 15 minutes
    "dashboard_zero": 600,  # 10 minutes
    "entry_stall": 3600,  # 60 minutes
}


def detect_recon_failure(last_logs: List[str]) -> Tuple[bool, str]:
    """Detect if RECON status is not OK.

    Returns: (is_failure, reason)
    """
    for log_line in last_logs[-50:]:  # Check last 50 log lines
        if "[V10.13x.1 RECON]" in log_line:
            if "status=WARN" in log_line or "status=FAIL" in log_line:
                return True, f"RECON non-OK: {log_line[:100]}"
            # Latest RECON found and it's OK
            return False, "RECON OK"

    return True, "RECON not found in logs (initialization pending)"


def detect_outbox_stuck(last_logs: List[str]) -> Tuple[bool, int, str]:
    """Detect if outbox has pending/failed events.

    Returns: (is_stuck, pending_count, reason)
    """
    pending_count = 0
    for log_line in last_logs[-100:]:
        if "[V5_BRIDGE_OUTBOX_FLUSH]" in log_line:
            if "pending" in log_line:
                try:
                    # Try to extract pending count
                    parts = log_line.split("pending=")
                    if len(parts) > 1:
                        pending_count = int(parts[1].split()[0])
                except:
                    pending_count += 1

    is_stuck = pending_count >= _OUTBOX_PENDING_THRESHOLD
    reason = f"Outbox pending: {pending_count} events" if pending_count > 0 else "Outbox clean"

    return is_stuck, pending_count, reason


def detect_quota_approaching(last_logs: List[str]) -> Tuple[bool, Dict[str, int], str]:
    """Detect if Firebase quota approaching limit.

    Returns: (approaching, quota_dict, reason)
    """
    quota = {"reads": 0, "writes": 0, "max_reads": 50000, "max_writes": 10000}

    for log_line in last_logs[-50:]:
        if "[V5_BRIDGE_QUOTA_STATE]" in log_line:
            try:
                # Parse: reads=0/50000 writes=1509/10000
                if "reads=" in log_line:
                    reads_part = log_line.split("reads=")[1].split()[0]
                    quota["reads"] = int(reads_part.split("/")[0])
                if "writes=" in log_line:
                    writes_part = log_line.split("writes=")[1].split()[0]
                    quota["writes"] = int(writes_part.split("/")[0])
            except:
                pass

    reads_pct = quota["reads"] / quota["max_reads"] if quota["max_reads"] > 0 else 0
    writes_pct = quota["writes"] / quota["max_writes"] if quota["max_writes"] > 0 else 0

    approaching = reads_pct > _QUOTA_WARNING_THRESHOLD or writes_pct > _QUOTA_WARNING_THRESHOLD
    critical = reads_pct > _AUTO_REMEDIATE["quota_critical"] or writes_pct > _AUTO_REMEDIATE["quota_critical"]

    reason = f"Quota: reads {reads_pct*100:.0f}%, writes {writes_pct*100:.0f}%"

    return approaching or critical, quota, reason


def detect_learning_stall(last_logs: List[str], current_time: float) -> Tuple[bool, str]:
    """Detect if learning updates stalled.

    Returns: (is_stalled, reason)
    """
    for log_line in last_logs[-100:]:
        if "V5_BRIDGE_LEARNING_UPDATE" in log_line or "PAPER_CANONICAL_LEARNING_UPDATE" in log_line:
            # Found recent learning update
            _monitor_state["last_learning_update"] = current_time
            _monitor_state["learning_stall_count"] = 0
            return False, "Learning active"

    time_since_learning = current_time - _monitor_state["last_learning_update"]

    if time_since_learning > _LEARNING_STALL_THRESHOLD:
        _monitor_state["learning_stall_count"] += 1
        return True, f"Learning stalled: {time_since_learning:.0f}s without update"

    return False, f"Learning OK (last: {time_since_learning:.0f}s ago)"


def detect_dashboard_zero(last_logs: List[str], current_time: float) -> Tuple[bool, str]:
    """Detect if dashboard metrics reset to zero/false.

    Returns: (is_zero, reason)
    """
    for log_line in last_logs[-50:]:
        if "[V5_BRIDGE_DASHBOARD_METRICS]" in log_line:
            metrics = {}
            try:
                if "closed_today=" in log_line:
                    metrics["closed_today"] = int(log_line.split("closed_today=")[1].split()[0])
                if "paper_exits_1h=" in log_line:
                    metrics["exits_1h"] = int(log_line.split("paper_exits_1h=")[1].split()[0])
                if "learning_updates=" in log_line:
                    metrics["learning_updates"] = int(log_line.split("learning_updates=")[1].split()[0])
            except:
                pass

            _monitor_state["last_dashboard_metrics"] = metrics
            _monitor_state["last_dashboard_metrics"]["timestamp"] = current_time

            # Check if all metrics are zero (unlikely unless crashed)
            all_zero = all(v == 0 for k, v in metrics.items() if k != "timestamp")
            if all_zero and len(metrics) > 0:
                return True, f"Dashboard all-zero: {metrics}"

    # Check if metrics haven't updated for too long
    time_since_update = current_time - _monitor_state["last_dashboard_metrics"].get("timestamp", current_time)
    if time_since_update > _DASHBOARD_ZERO_THRESHOLD:
        return True, f"Dashboard stale: {time_since_update:.0f}s without update"

    return False, "Dashboard metrics flowing"


def detect_entry_stall(last_logs: List[str], current_time: float) -> Tuple[bool, str]:
    """Detect if PAPER entries stuck at zero despite positive EV candidates.

    Returns: (is_stalled, reason)
    """
    has_ev_candidates = False
    has_entries = False

    for log_line in last_logs[-200:]:
        if "candidate_ev=" in log_line and ("positive_ev" in log_line or float(log_line.split("candidate_ev=")[1].split()[0]) > 0):
            has_ev_candidates = True
        if "PAPER_ENTRY\|admission_reason=paper_learning" in log_line:
            has_entries = True
            _monitor_state["last_entry_rate"] = current_time
            _monitor_state["entry_stall_count"] = 0
            return False, "Entries flowing"

    time_since_entry = current_time - _monitor_state["last_entry_rate"]

    if has_ev_candidates and time_since_entry > _ENTRY_STALL_THRESHOLD:
        _monitor_state["entry_stall_count"] += 1
        return True, f"Entry stall: {time_since_entry:.0f}s despite EV candidates"

    return False, "Entry rate OK"


def detect_crashes(last_logs: List[str]) -> Tuple[bool, List[str]]:
    """Detect Traceback / runtime crashes.

    Returns: (has_crash, crash_lines)
    """
    crash_lines = []

    for log_line in last_logs[-100:]:
        if "Traceback" in log_line or "Exception" in log_line or "FATAL" in log_line or "ERROR" in log_line:
            crash_lines.append(log_line[:150])

    return len(crash_lines) > 0, crash_lines


def run_health_check(get_recent_logs_fn=None) -> Dict[str, any]:
    """Run all health checks.

    Args:
        get_recent_logs_fn: Function that returns recent log lines (called if provided)

    Returns:
        Health check results dictionary
    """
    current_time = time.time()

    # Only run checks at interval
    if current_time - _monitor_state["last_recon_check"] < _CHECKS_INTERVAL_S:
        return {"status": "skipped", "reason": "interval not reached"}

    _monitor_state["last_recon_check"] = current_time

    results = {
        "timestamp": current_time,
        "checks": {},
        "alerts": [],
        "remediation": []
    }

    # Mock log retrieval if not provided
    recent_logs = []
    if get_recent_logs_fn:
        try:
            recent_logs = get_recent_logs_fn()
        except:
            log.warning("[EMERGENCY_MONITOR] Failed to retrieve logs")

    # 1. Check RECON status
    recon_failed, recon_reason = detect_recon_failure(recent_logs)
    results["checks"]["recon"] = {"failed": recon_failed, "reason": recon_reason}
    if recon_failed:
        _monitor_state["recon_failures"] += 1
        if _monitor_state["recon_failures"] >= _RECON_FAILURE_THRESHOLD:
            alert_key = "recon_failure"
            if _should_alert(alert_key):
                results["alerts"].append({
                    "severity": "HIGH",
                    "type": "RECON_FAILURE",
                    "message": recon_reason
                })
                results["remediation"].append({
                    "action": "INSPECT_RECON_LOGIC",
                    "details": "Check entry counts, symbol/regime detection"
                })
    else:
        _monitor_state["recon_failures"] = 0

    # 2. Check outbox
    outbox_stuck, pending, outbox_reason = detect_outbox_stuck(recent_logs)
    results["checks"]["outbox"] = {"stuck": outbox_stuck, "pending": pending, "reason": outbox_reason}
    if outbox_stuck:
        alert_key = "outbox_stuck"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "HIGH",
                "type": "OUTBOX_STUCK",
                "message": outbox_reason
            })
            results["remediation"].append({
                "action": "FLUSH_OUTBOX_MANUAL",
                "details": f"Run: python -c 'from src.services.v5_legacy_bridge import get_v5_bridge; get_v5_bridge().flush_outbox(limit=50)'"
            })

    # 3. Check quota
    quota_approaching, quota_dict, quota_reason = detect_quota_approaching(recent_logs)
    results["checks"]["quota"] = {"approaching": quota_approaching, "quota": quota_dict, "reason": quota_reason}
    if quota_approaching:
        alert_key = "quota_warning"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "CRITICAL" if quota_dict["writes"] > quota_dict["max_writes"] * _AUTO_REMEDIATE["quota_critical"] else "WARNING",
                "type": "QUOTA_APPROACHING",
                "message": quota_reason
            })
            results["remediation"].append({
                "action": "ENABLE_CACHING",
                "details": "Increase cache TTL, reduce read frequency, wait for quota reset (midnight PT)"
            })

    # 4. Check learning
    learning_stalled, learning_reason = detect_learning_stall(recent_logs, current_time)
    results["checks"]["learning"] = {"stalled": learning_stalled, "reason": learning_reason}
    if learning_stalled:
        alert_key = "learning_stall"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "HIGH",
                "type": "LEARNING_STALL",
                "message": learning_reason
            })
            results["remediation"].append({
                "action": "CHECK_ENTRY_RATE",
                "details": "Entry starvation preventing learning updates; check cost-edge gates"
            })

    # 5. Check dashboard
    dashboard_zero, dashboard_reason = detect_dashboard_zero(recent_logs, current_time)
    results["checks"]["dashboard"] = {"zero": dashboard_zero, "reason": dashboard_reason}
    if dashboard_zero:
        alert_key = "dashboard_zero"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "CRITICAL",
                "type": "DASHBOARD_ZERO",
                "message": dashboard_reason
            })
            results["remediation"].append({
                "action": "RESTART_SERVICE",
                "details": "Service likely crashed; run: systemctl restart cryptomaster"
            })

    # 6. Check entry rate
    entry_stalled, entry_reason = detect_entry_stall(recent_logs, current_time)
    results["checks"]["entries"] = {"stalled": entry_stalled, "reason": entry_reason}
    if entry_stalled:
        alert_key = "entry_stall"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "MEDIUM",
                "type": "ENTRY_STALL",
                "message": entry_reason
            })
            results["remediation"].append({
                "action": "INSPECT_COST_EDGE",
                "details": "Check expected_move_pct vs required_move_pct logs; may need lower TP or wider entry"
            })

    # 7. Check crashes
    has_crash, crash_lines = detect_crashes(recent_logs)
    results["checks"]["crashes"] = {"detected": has_crash, "lines": crash_lines[:5]}
    if has_crash:
        alert_key = "crash_detected"
        if _should_alert(alert_key):
            results["alerts"].append({
                "severity": "CRITICAL",
                "type": "CRASH_DETECTED",
                "message": f"Runtime error: {crash_lines[0] if crash_lines else 'Unknown'}"
            })
            results["remediation"].append({
                "action": "RESTART_SERVICE_FORCE",
                "details": "Run: systemctl restart cryptomaster.service"
            })
            results["remediation"].append({
                "action": "INSPECT_LOGS",
                "details": "Check full traceback and investigate root cause"
            })

    # Log results
    if results["alerts"]:
        log.warning(f"[EMERGENCY_MONITOR] {len(results['alerts'])} alerts: {[a['type'] for a in results['alerts']]}")
        for alert in results["alerts"]:
            log.error(f"  [{alert['severity']}] {alert['type']}: {alert['message']}")

    if results["remediation"]:
        log.info(f"[EMERGENCY_MONITOR] Suggested remediation: {[r['action'] for r in results['remediation']]}")
        for rem in results["remediation"]:
            log.info(f"  {rem['action']}: {rem['details']}")
    else:
        log.info("[EMERGENCY_MONITOR] All checks passed")

    return results


def _should_alert(alert_key: str) -> bool:
    """Check if enough time has passed to re-alert on same issue."""
    current_time = time.time()

    # Find previous alert
    for prev_alert in _monitor_state["alerts_issued"]:
        if prev_alert["key"] == alert_key:
            if current_time - prev_alert["time"] < _ALERT_COOLDOWN_S:
                return False  # Too soon to re-alert
            break

    # Record this alert
    _monitor_state["alerts_issued"].append({"key": alert_key, "time": current_time})

    # Cleanup old alerts
    _monitor_state["alerts_issued"] = [a for a in _monitor_state["alerts_issued"]
                                       if current_time - a["time"] < _ALERT_COOLDOWN_S * 2]

    return True


# Entry point for periodic monitoring
def start_monitoring_thread(get_logs_fn=None, interval_s: float = 60.0):
    """Start background monitoring thread.

    Args:
        get_logs_fn: Function to retrieve recent logs
        interval_s: Check interval in seconds
    """
    def monitor_loop():
        while True:
            try:
                run_health_check(get_logs_fn)
            except Exception as e:
                log.error(f"[EMERGENCY_MONITOR] Health check failed: {e}")

            time.sleep(interval_s)

    thread = threading.Thread(target=monitor_loop, daemon=True, name="EmergencyHealthMonitor")
    thread.start()
    log.info("[EMERGENCY_MONITOR] Background monitoring started")
    return thread
