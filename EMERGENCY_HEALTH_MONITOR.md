# Emergency Health Monitor — Auto-Detection & Remediation System

**Commit**: 4807ad6  
**Status**: ✅ LIVE  
**Integration**: bot2/main.py (startup)  
**Interval**: 60 seconds (background thread)

---

## Overview

Autonomous health monitoring system that detects 7 critical failure scenarios and provides auto-remediation recommendations. Runs continuously in background, alerts operator when thresholds exceeded.

**Design Principle**: *Detect early, alert loudly, remediate safely*

---

## Monitored Conditions

### 1. ❌ RECON Status != OK
**What it detects**: Diagnostic health checks failing (entries too low, symbols not detected, etc)

**Thresholds**:
- Alert after 2+ consecutive RECON=WARN or RECON=FAIL events
- Cooldown: 5 minutes (don't re-alert too frequently)

**Remediation**:
```
Action: INSPECT_RECON_LOGIC
Details: Check entry counts, symbol/regime detection
```

**Root causes**:
- Entry starvation (< 2 entries/10min)
- Symbol detection failing
- Regime detection disabled
- Learning updates stalled

---

### 2. ❌ Outbox Pending / Failed Events
**What it detects**: Firebase persistence queue stuck with pending events

**Thresholds**:
- Alert if ≥ 10 pending events
- Cooldown: 5 minutes

**Remediation**:
```
Action: FLUSH_OUTBOX_MANUAL
Details: Run: python -c 'from src.services.v5_legacy_bridge import get_v5_bridge; get_v5_bridge().flush_outbox(limit=50)'
```

**Root causes**:
- Firebase temporarily unavailable
- Network issues
- Outbox flush worker crashed
- Queue deadlocked

---

### 3. ❌ Firebase Write Quota Approaching Limit
**What it detects**: Quota usage exceeding thresholds (75% warning, 90% critical)

**Thresholds**:
- Warning: 75% of daily limit (15,000 writes/day)
- Critical: 90% of daily limit (18,000 writes/day)
- Cooldown: 5 minutes

**Remediation**:
```
Action: ENABLE_CACHING
Details: Increase cache TTL, reduce read frequency, wait for quota reset (midnight PT)
```

**Root causes**:
- High trading volume (many learn updates)
- Dashboard publishing too frequently
- Caching disabled or TTL too low
- Quota not resetting (timezone issue?)

---

### 4. ❌ Learning Updates Stalled
**What it detects**: No learning updates for extended period (10+ minutes)

**Thresholds**:
- Alert if no learning update for 600+ seconds
- Repeated alerting if stall continues
- Cooldown: 5 minutes per alert

**Remediation**:
```
Action: CHECK_ENTRY_RATE
Details: Entry starvation preventing learning updates; check cost-edge gates
```

**Root causes**:
- Entry starvation (no entries = no closes = no learning)
- Market too wide (cost-edge blocking all entries)
- Learning eligibility gates too strict
- System in safe mode

---

### 5. ❌ Dashboard Metrics Reset to Zero/False
**What it detects**: Dashboard metrics showing all-zero or stale (>5 min without update)

**Thresholds**:
- Alert if all dashboard metrics = 0 AND multiple fields populated
- Alert if metrics unchanged for 300+ seconds
- Cooldown: 5 minutes

**Remediation**:
```
Action: RESTART_SERVICE
Details: Service likely crashed; run: systemctl restart cryptomaster
```

**Root causes**:
- Service crash (unhandled exception)
- Dashboard rendering thread crashed
- Metrics publishing broken
- State corruption

---

### 6. ❌ PAPER Entries Stuck at Zero (Despite Positive EV Candidates)
**What it detects**: Zero entries for 30+ minutes while EV candidates still exist

**Thresholds**:
- Alert if no entries for 1800+ seconds
- AND EV candidates detected in logs
- Cooldown: 5 minutes

**Remediation**:
```
Action: INSPECT_COST_EDGE
Details: Check expected_move_pct vs required_move_pct logs; may need lower TP or wider entry
```

**Root causes**:
- Cost-edge gate overly restrictive
- Market spreads too wide
- Expected move too low for profitability
- ECON_BAD threshold blocking entries

---

### 7. ❌ Traceback / Runtime Crash
**What it detects**: Traceback, Exception, FATAL, or ERROR in logs

**Thresholds**:
- Alert on first Traceback/Exception/FATAL detected
- Cooldown: 5 minutes

**Remediation** (2 steps):
```
Action: RESTART_SERVICE_FORCE
Details: Run: systemctl restart cryptomaster.service

Action: INSPECT_LOGS
Details: Check full traceback and investigate root cause
```

**Root causes**:
- Unhandled exception in trading logic
- Out of memory
- File descriptor exhaustion
- Invalid state corruption

---

## Architecture

### Core Components

```python
# src/services/emergency_health_monitor.py

class HealthMonitor:
    def run_health_check(get_recent_logs_fn):
        """Run all 7 health checks, return results + alerts + remediation"""
        
        results = {
            "timestamp": current_time,
            "checks": {
                "recon": {...},
                "outbox": {...},
                "quota": {...},
                "learning": {...},
                "dashboard": {...},
                "entries": {...},
                "crashes": {...}
            },
            "alerts": [
                {"severity": "HIGH", "type": "RECON_FAILURE", "message": "..."}
            ],
            "remediation": [
                {"action": "INSPECT_RECON_LOGIC", "details": "..."}
            ]
        }
```

### State Tracking

```python
_monitor_state = {
    "last_recon_check": 0.0,
    "recon_failures": 0,  # Count consecutive failures
    "last_outbox_check": 0.0,
    "outbox_pending_count": 0,
    "last_quota_check": 0.0,
    "quota_warning_issued": False,
    "last_learning_update": 0.0,
    "learning_stall_count": 0,
    "alerts_issued": [],  # Track alerts for cooldown
}
```

### Integration into bot2/main.py

```python
# Startup (after audit worker thread)
def _get_recent_logs():
    """Helper to retrieve recent logs for emergency monitor."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "cryptomaster.service", "-n", "500", "--no-pager"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.split('\n')
    except:
        return []

from src.services.emergency_health_monitor import start_monitoring_thread
_monitor_thread = start_monitoring_thread(get_logs_fn=_get_recent_logs, interval_s=60)
logging.info("[STARTUP] Emergency health monitor initialized")

# Runs every 60 seconds in background, non-blocking
```

---

## Alert Output Example

```
[WARNING] [EMERGENCY_MONITOR] 2 alerts: ['RECON_FAILURE', 'OUTBOX_STUCK']

  [HIGH] RECON_FAILURE: RECON non-OK: [V10.13x.1 RECON] counts_ok=False status=WARN

  [HIGH] OUTBOX_STUCK: Outbox pending: 15 events

[INFO] [EMERGENCY_MONITOR] Suggested remediation:
  INSPECT_RECON_LOGIC: Check entry counts, symbol/regime detection
  FLUSH_OUTBOX_MANUAL: Run: python -c 'from src.services.v5_legacy_bridge import get_v5_bridge; get_v5_bridge().flush_outbox(limit=50)'
```

---

## Thresholds Reference

| Condition | Warning | Critical | Action |
|-----------|---------|----------|--------|
| RECON failures | 1 | 2+ | Inspect logic |
| Outbox pending | 5 | 10+ | Manual flush |
| Quota usage | 65% | 75%+ | Enable caching |
| Learning stall (s) | 300 | 600+ | Check entries |
| Dashboard stale (s) | 180 | 300+ | Restart service |
| Entry stall (s) | 1200 | 1800+ | Inspect cost-edge |
| Crash alert | 1 found | Always | Restart + debug |

---

## Configuration

Edit `src/services/emergency_health_monitor.py` lines 30-50:

```python
_CHECKS_INTERVAL_S = 60.0  # Monitoring frequency
_RECON_FAILURE_THRESHOLD = 2  # Consecutive failures before alert
_OUTBOX_PENDING_THRESHOLD = 10  # Pending events threshold
_QUOTA_WARNING_THRESHOLD = 0.75  # 75% quota usage
_LEARNING_STALL_THRESHOLD = 600  # Seconds without learning update
_DASHBOARD_ZERO_THRESHOLD = 300  # Seconds without dashboard update
_ENTRY_STALL_THRESHOLD = 1800  # Seconds without PAPER entry
_ALERT_COOLDOWN_S = 300  # Don't re-alert same issue for 5 min
```

---

## Operational Usage

### Manual Check (on Hetzner)
```bash
cd /opt/cryptomaster

# Check current monitoring status
journalctl -u cryptomaster.service -n 500 --no-pager | grep "EMERGENCY_MONITOR"

# Run manual check
python -c "from src.services.emergency_health_monitor import run_health_check; \
import json; print(json.dumps(run_health_check(), indent=2))"
```

### Test Scenario (Simulate Failure)
```bash
# Simulate RECON failure (create temp metrics corruption)
python scripts/test_emergency_monitor.py --scenario recon_failure

# Monitor will alert after 2 checks (60+ seconds)
```

---

## Known Limitations

1. **Log parsing**: Relies on specific log format. If log format changes, detection may fail.
   - **Mitigation**: Update regex patterns in detect_* functions

2. **Journalctl availability**: Uses Linux journalctl (not available on Windows dev)
   - **Mitigation**: Falls back to empty logs, skip monitoring on Windows

3. **Alert cooldown**: 5-minute cooldown may hide rapid recurrence
   - **Mitigation**: Adjust `_ALERT_COOLDOWN_S` for more/less frequent alerts

4. **No auto-remediation**: System only *suggests* fixes, doesn't execute them
   - **Mitigation**: Operator acts on alerts, future: add auto-execution for safe operations

5. **Threshold tuning**: Thresholds may be too aggressive/lenient for specific markets
   - **Mitigation**: A/B test thresholds, adjust based on false alert rate

---

## Future Enhancements

### Phase 2 (Next Sprint)
- [ ] Auto-execution for safe remediation (outbox flush, cache clear)
- [ ] Slack/email alerting
- [ ] Custom threshold per condition
- [ ] Metrics dashboard for health monitoring

### Phase 3 (Q3 2026)
- [ ] Machine learning anomaly detection (detect novel failures)
- [ ] Predictive alerting (warn before threshold)
- [ ] Self-healing strategy (auto-restart components)
- [ ] Multi-instance monitoring (across multiple bots)

---

## Emergency Contact Flow

```
1. Monitor detects condition
   ↓
2. Alert logged to journalctl + console
   ↓
3. Operator sees log entry
   ↓
4. Operator reads remediation suggestions
   ↓
5. Operator executes suggested command
   ↓
6. Monitor detects recovery + clears alert
```

---

**Status**: ✅ **LIVE ON HETZNER** — Running since commit 4807ad6

Last updated: 2026-06-02 13:05 UTC
