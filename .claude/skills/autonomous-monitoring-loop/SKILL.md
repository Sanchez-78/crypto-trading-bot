---
name: autonomous-monitoring-loop
description: |
  Autonomous monitoring loop for CryptoMaster trading bot. Runs every 30 minutes to 
  check bot health (Win Rate, P&L, Profit Factor, Firebase quota). On FAIL status, 
  triggers autonomous diagnosis and fix cycle. On GOAL_REACHED (WR > 50% + P&L > 0%), 
  stops and reports success. Persists progress to JSON. 
  
  **Invoke when:** "spusť autonomní monitoring", "start autonomous loop", "fix bot sám", 
  "monitoruj bota autonomně", "opravuj chyby automaticky", "run autonomous trading fix".
  
  **Entry point:** This is the main skill to start autonomous bot optimization. 
  Coordinates all specialized agents until goal metrics are reached.

---

# Autonomous Monitoring Loop — Main Entry Point

## Master Workflow (Phases 0-7)

### Phase 0: Initialization & Resume Detection

**Goal:** Determine if this is a fresh start or resuming from a previous run.

1. Check for `_workspace/monitoring_progress.json`
   - **Not found**: Fresh start
     - Initialize: `cycle = 0`, `start_time = now`, `cycles = []`, `goal_reached = false`
   - **Found**: Resume from previous run
     - Load: `cycle`, `cycles` history, `current_wr`, `current_pnl`, `start_time`
     - Log: "Resuming cycle #{cycle+1} after {elapsed} hours"

2. Create `_workspace/` directory if not present

3. Continue to Phase 1

### Phase 1: Metric Collection & Status Assessment

**Goal:** Read live bot metrics and determine action (GOAL_REACHED | CAUTION | FAIL | QUOTA_WAIT).

1. Invoke `monitoring-remediation-agent`
   - Input: `{"action": "collect_metrics", "time_window": "30 min"}`
   - Receive: Metrics report with `wr_pct`, `pf`, `pnl_pct`, `quota_status`, `closed_trades`, `open_positions`, `status`

2. Parse response:
   - `status` ∈ {PASS, CAUTION, FAIL, QUOTA_WAIT}
   - Extract: `wr_before`, `pf_current`, `pnl_pct_current`, `quota_used_pct`

3. **Decision tree:**

   **3a. GOAL_REACHED** (if `wr_pct > 50` AND `pnl_pct > 0` AND no active alarms)
   - Print success report (see Phase 6 Success)
   - Save final progress
   - **STOP** (return success)

   **3b. QUOTA_WAIT** (if `quota_used_pct > 75`)
   - Log: "Firebase quota {quota_used_pct}% — waiting for reset at 07:00 UTC"
   - Sleep: `ScheduleWakeup(1800, "Quota reset check at 07:00 UTC, resuming monitoring")`
   - Return

   **3c. CAUTION** (metrics improving or stable, no critical blocker)
   - Log: "Metrics stable: WR {wr_pct}%, PF {pf}, P&L {pnl_pct}% — monitoring continues"
   - Save cycle snapshot (see Phase 6 Progress)
   - Sleep: `ScheduleWakeup(1800, "Continue monitoring in 30 minutes")`
   - Return

   **3d. FAIL** (critical blocker identified)
   - Extract blocker from report: `blocker_type` ∈ {safe_mode, no_closes, high_losses, single_symbol, error_rate, quota_critical}
   - Log: "🔴 FAIL — Blocker: {blocker_type}"
   - Continue to Phase 2

### Phase 2: Evidence Collection (On FAIL)

**Goal:** Collect forensic evidence before patch authoring.

1. Invoke `runtime-forensic-agent` (via evidence-based-patch-orchestrator later)
   - For now, store symptom: `{"symptom": "{blocker_type}", "time_window": "last 30 min"}`
   - Will be passed to Phase 4

### Phase 3: Regression Spiral Detection

**Goal:** Detect if bot is in a downward loop and stop to prevent thrashing.

1. Check `cycles` history for last 3 entries
2. If `cycles[-3:]` all show `wr_after < wr_before`: **REGRESSION SPIRAL DETECTED**
   - Log error: "❌ Regression spiral detected (3 consecutive WR drops) — stopping autonomous loop"
   - Save state
   - Print recommendation: "Manual intervention required — review latest patches and logs"
   - **STOP**

3. Else: continue to Phase 4

### Phase 4: Invoke Evidence-Based Fix Orchestrator (On FAIL)

**Goal:** Trigger the full patch pipeline.

1. Call `evidence-based-patch-orchestrator` skill with:
   ```
   {
     "symptom": "{blocker_type}",
     "time_window": "30 min",
     "autonomy_mode": true
   }
   ```

2. Wait for orchestrator to complete (may take 10–15 min)
   - Orchestrator handles: forensics → parallel validation → patch authoring → review → approve/reject
   - Receive: `patch_result` ∈ {APPROVED, REJECTED, MANUAL_ESCALATION}

3. **Decision:**
   - **APPROVED**: Proceed to Phase 5 (Deploy)
   - **REJECTED**: Log reason, mark cycle as "patch_rejected", ScheduleWakeup(1800), return
   - **MANUAL_ESCALATION**: Log evidence, create `.md` report, return with escalation flag

### Phase 5: Deploy & Verify (On APPROVED)

**Goal:** Atomically deploy patch and verify service health.

1. Get commit hash from patch-author-agent output
2. Invoke `deploy-verify-agent` with:
   ```
   {
     "commit_hash": "{SHA}",
     "patch_description": "{one-line summary from patch}",
     "timeout_secs": 300
   }
   ```

3. Wait for deploy result:
   - **PASS**: Service deployed, healthy, continue to Phase 6
   - **FAIL_REVERTED**: Service reverted, previous version running — log failure, mark cycle, ScheduleWakeup(3600, "Deploy failed, waiting 1 hour before retry"), return

### Phase 6: Progress Tracking & Report

**Goal:** Record cycle outcome and plan next action.

**6a. Normal cycle completion (after Phase 1 CAUTION/FAIL → deploy)**

1. Store cycle data:
   ```json
   {
     "cycle": {cycle_num},
     "timestamp": "{ISO8601}",
     "wr_before": {wr_before_pct},
     "wr_after": {wr_after_pct},
     "pf_before": {pf_before},
     "pf_after": {pf_after},
     "pnl_before": {pnl_before_pct},
     "pnl_after": {pnl_after_pct},
     "blocker": "{blocker_type}",
     "fix_applied": "{patch_summary}",
     "commit": "{SHA}",
     "deploy_result": "PASS" | "FAIL_REVERTED",
     "elapsed_mins": {N}
   }
   ```

2. Append to `cycles[]` in `_workspace/monitoring_progress.json`

3. Update aggregate:
   ```json
   {
     "cycle": {cycle+1},
     "start_time": "{ISO8601}",
     "total_cycles_completed": {N},
     "current_wr": {wr_after},
     "current_pnl": {pnl_after},
     "total_wr_gain": {wr_after - initial_wr},
     "goal_reached": false,
     "last_update": "{ISO8601}",
     "status": "monitoring" | "goal_reached" | "failed" | "escalated"
   }
   ```

4. Print cycle report:
   ```
   ═══════════════════════════════════════════════════════════════
   🤖 MONITORING CYCLE #{cycle_num} | {timestamp}
   ═══════════════════════════════════════════════════════════════

   📊 METRICS (30-min delta):
     Win Rate: {wr_before}% → {wr_after}% ({delta:+0.0f}%)
     Profit Factor: {pf_before:.2f}x → {pf_after:.2f}x
     P&L: {pnl_before}% → {pnl_after}% ({delta:+0.0f}%)
     Closed trades: {N}

   🔴 BLOCKER IDENTIFIED:
     Type: {blocker_type}
     Evidence: {log line count} supporting lines

   🔧 FIX APPLIED:
     File: {file.py}:{line}
     Change: {one-line summary}
     Commit: {SHA}
     Deploy: ✅ successful

   📈 PROGRESS TRACKER:
     Total cycles: {N}
     Total WR gain: {delta}%
     Cycles to goal: ~{estimated_cycles} (at {avg_wr_gain_per_cycle}% per cycle)

   ⏱️ NEXT:
     Waiting 30 minutes for effect measurement...
   ═══════════════════════════════════════════════════════════════
   ```

5. Schedule next cycle: `ScheduleWakeup(1800, "Resume monitoring cycle #{cycle+2}")`

**6b. Success scenario (Phase 1 GOAL_REACHED)**

1. Print success report:
   ```
   ═══════════════════════════════════════════════════════════════
   ✅ GOAL ACHIEVED! | {timestamp}
   ═══════════════════════════════════════════════════════════════

   🎯 TARGET METRICS:
     Win Rate: {wr}% (target: > 50%) ✅
     P&L: {pnl}% (target: > 0%) ✅
     Profit Factor: {pf}x (quality: {rating})

   📊 FINAL SUMMARY:
     Total cycles: {N}
     Time to goal: {elapsed_hours}h
     Total WR improvement: +{total_gain}%
     Patches deployed: {N} (all evidence-backed)
     All safety gates: ✅ PASSED

   🎯 CYCLE HISTORY:
     Cycle 1: {wr_before}% → {wr_after}% (+{delta}%) — {fix1}
     Cycle 2: {wr_before}% → {wr_after}% (+{delta}%) — {fix2}
     ...

   📌 NEXT STEPS:
     1. Continue monitoring for stability (24h+ at goal metrics)
     2. Prepare for real trading authorization (if applicable)
     3. Archive this run: copy monitoring_progress.json to reports/

   ✅ AUTONOMOUS MONITORING COMPLETE
   ═══════════════════════════════════════════════════════════════
   ```

2. Save final state to `_workspace/monitoring_progress.json` with `goal_reached: true`

3. **STOP** (do not schedule next cycle)

### Phase 7: Safeguards & Loop Control

**Cycle limit:** Stop if `cycle >= 100` (hard cap to prevent infinite loops)

**Quota exhaustion:** Stop if `quota_used_pct > 80%` on 3 consecutive checks (no patch can fix quota depletion)

**Timeout per cycle:** Warn if any single cycle > 60 min (may indicate GH Actions delay or network issue)

**Regression spiral:** See Phase 3

**Escalation markers:** If `evidence-based-patch-orchestrator` returns MANUAL_ESCALATION, stop and create escalation report

## Critical Safety Rules

1. **Never skip forensics** — Every fix must have concrete log evidence (≥3 log lines cited)
2. **Never deploy unreviewed code** — All patches reviewed by `reviewer-agent` before deployment
3. **Never touch real trading paths** — All commits verified by `trading-safety-agent` (TRADING_MODE=paper_live only)
4. **Atomic deployment only** — Deploy fails → auto-revert to previous version (no partial states)
5. **No concurrent cycles** — Wait for deployment to stabilize (30 min) before next fix attempt
6. **Firebase quota respect** — Stop if quota < 10% until reset at 07:00 UTC

## Technical Implementation Notes

### SSH to Hetzner (monitoring-remediation-agent does this internally)
```bash
ssh -i "$env:USERPROFILE\.ssh\hetzner_root" root@78.47.2.198
journalctl -u cryptomaster.service --since "30 min ago" --no-pager
curl http://localhost:5001/api/dashboard/metrics
```

### Progress JSON Schema
```json
{
  "cycle": 0,
  "start_time": "2026-06-15T10:00:00Z",
  "goal_reached": false,
  "total_cycles_completed": 0,
  "current_wr": 0,
  "current_pnl": -0.16,
  "total_wr_gain": 0,
  "quota_max_used_pct": 45,
  "last_update": "2026-06-15T10:00:00Z",
  "status": "monitoring",
  "cycles": [
    {
      "cycle": 1,
      "timestamp": "2026-06-15T10:30:00Z",
      "wr_before": 0,
      "wr_after": 5,
      "pf_before": 0.8,
      "pf_after": 0.85,
      "pnl_before": -0.16,
      "pnl_after": -0.12,
      "blocker": "signal_inversion",
      "fix_applied": "Remove unconditional BUY↔SELL flip in signal_generator.py:386-390",
      "commit": "abc123def456",
      "deploy_result": "PASS",
      "elapsed_mins": 15
    }
  ]
}
```

## Entry Points (Trigger Keywords)

This skill triggers on any of these user messages:
- "spusť autonomní monitoring"
- "start autonomous loop"
- "fix bot sám" / "opravuj bot autonomně"
- "monitoruj bota" / "monitor bot"
- "run autonomous trading fix"
- "autonomní loop" / "autonomous loop"
- Any request combining "autonomous" + "monitor" or "autonomous" + "fix"

## Continuation After Interrupt

If user interrupts the loop (Ctrl+C or timeout):
1. Progress is saved to JSON
2. User can resume with same command (Phase 0 detects saved state)
3. Next invocation resumes from `cycle+1`

## Error Recovery

| Error | Recovery |
|-------|----------|
| SSH timeout to Hetzner | Retry 1x in monitoring-remediation-agent, then escalate |
| GH Actions timeout (>3 min) | Cancel workflow, revert, wait 1h, retry |
| Deploy fails | Auto-revert, mark cycle, wait 1h |
| Quota exhausted mid-cycle | Log quota depletion, wait until 07:00 UTC reset, resume |
| Patch rejected by reviewer | Log rejection reason, wait 30 min, retry with new evidence |
| Service crash post-deploy | Revert immediately, new forensics cycle |

---

## Example Execution Flow

```
User: "spusť autonomní monitoring"

1. Phase 0: Check _workspace/monitoring_progress.json → not found → FRESH START
2. Phase 1: Get metrics → WR=0%, PF=0.8x, P&L=-0.16%, status=FAIL
3. Phase 3: No regression spiral yet
4. Phase 4: Invoke evidence-based-patch-orchestrator
   └─ runtime-forensic-agent: "Signal inverted (BULL→SELL)"
   └─ patch-author: "Remove flip in signal_generator.py:386"
   └─ reviewer: "✅ APPROVED"
5. Phase 5: deploy-verify-agent pushes & verifies → ✅ PASS
6. Phase 6: Report cycle #1: WR 0%→5%, save progress, ScheduleWakeup(1800s)
   
   [30 min later, user invokes skill again]
   
1. Phase 0: Resume cycle #2 from saved state
2. Phase 1: Get metrics → WR=5%, PF=0.85x, P&L=-0.12%, status=CAUTION
3. Phase 6: CAUTION → report, ScheduleWakeup(1800s)

   [30 min later]
   
1. Phase 0: Resume cycle #3
2. Phase 1: Get metrics → WR=50.2%, P&L=+0.01%, status=GOAL_REACHED
3. Phase 6b: SUCCESS REPORT
   └─ GOAL ACHIEVED ✅
   └─ Total cycles: 3, Time to goal: 1.5h
   └─ Patches: 3 (all evidence-backed)
   └─ STOP (no more ScheduleWakeup)
```

---

**Conclusion:** This skill is the master control loop that drives the bot toward autonomous profitability. It coordinates all specialized agents and persists state across sessions, making the optimization process auditable and resumable.
