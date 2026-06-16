# CYCLE #13 DEPLOYMENT — Systemd Override Fix

**Issue:** V10.27 TP/SL configuration hotfix was NOT deployed to Hetzner systemd service.
- GitHub Actions updated Python code ✅
- BUT `.env` file is in `.gitignore` (not deployed)
- AND systemd `override.conf` has stale `PAPER_MAX_POSITION_AGE_S=900` (should be 600)

**Result:** All exits are TIMEOUT (100%), TP/SL bands never get chance to execute.

---

## MANUAL DEPLOYMENT STEPS

### Step 1: SSH to Hetzner
```bash
ssh -i "$env:USERPROFILE\.ssh\hetzner_root" root@78.47.2.198
```

### Step 2: Execute Fix Script
```bash
bash /opt/cryptomaster/fix_systemd_override.sh
```

This script will:
1. Backup `/etc/systemd/system/cryptomaster.service.d/override.conf`
2. Update `PAPER_MAX_POSITION_AGE_S=900` → `PAPER_MAX_POSITION_AGE_S=600`
3. Reload systemd daemon
4. Restart cryptomaster service
5. Verify service is running

### Step 3: Verify Fix
```bash
# Check config
systemctl cat cryptomaster.service | grep PAPER_

# Watch logs
journalctl -u cryptomaster.service -f

# Expected output: TP/SL hits within 10 min (PAPER_MAX_POSITION_AGE_S=600)
```

---

## EXPECTED OUTCOME (Post-Fix)

After 30 minutes of monitoring:
- **Exit Distribution:**
  - TP: 30-50% (was 0%)
  - SL: 10-20% (was 0%)
  - TIMEOUT: 30-50% (was 100%)
- **Metrics:**
  - Win Rate: 20-40% (was 0%)
  - Profit Factor: >1.1 (was 1.0)
  - P&L: Break-even to positive (was 0%)
- **Learning System:**
  - SQLite trades table populated (row count >100)
  - Calibration state showing W/L balance

---

## CYCLE #13 MEASUREMENT TIMELINE

| Time | Action | Status |
|------|--------|--------|
| 06:00 UTC | GitHub Actions pushes V10.27 code | ✅ Done |
| 06:05 UTC | Monitoring-remediation-agent detects systemd stale config | 🔴 FAIL |
| 06:10-06:40 UTC | **DEPLOYMENT WINDOW** — Execute fix_systemd_override.sh | ⏳ Pending |
| 06:40-07:10 UTC | **MEASUREMENT WINDOW** — Collect 30 min of post-fix metrics | ⏳ Pending |
| 07:10 UTC | Re-invoke autonomous-monitoring-loop for Cycle #13 result | ⏳ Pending |

---

## TROUBLESHOOTING

**If script fails with permission denied:**
```bash
chmod +x /opt/cryptomaster/fix_systemd_override.sh
bash /opt/cryptomaster/fix_systemd_override.sh
```

**If override.conf not found:**
```bash
ls -la /etc/systemd/system/cryptomaster.service.d/
# Check if directory exists; if not, create it
```

**If service won't start after fix:**
```bash
# Revert backup
cp /etc/systemd/system/cryptomaster.service.d/override.conf.backup.* \
   /etc/systemd/system/cryptomaster.service.d/override.conf
systemctl daemon-reload
systemctl restart cryptomaster.service
```

---

## NOTES FOR CYCLE #13 ORCHESTRATION

- **Autonomy:** Run fix script manually (outside of autonomous loop — requires SSH)
- **Then resume:** After systemd is fixed, invoke `autonomous-monitoring-loop` again to measure post-fix metrics
- **Next decision:** Based on Cycle #13 measurement (should show TP/SL improvement)
  - PASS/CAUTION: Continue monitoring
  - FAIL: Investigate TP/SL logic deeper

---

**Commit:** V10.27 HOTFIX: Systemd override.conf repair script
**Deployed:** 2026-06-16 06:10+ UTC
