---
name: autonomous-goal-achievement-orchestrator
description: |
  Master autonomous orchestrator for CryptoMaster goal achievement. Continuously
  monitors trading bot metrics (win rate, P&L) and invokes evidence-based-patch-orchestrator
  to fix issues autonomously. Runs in infinite loop until GOAL REACHED: Win Rate > 50% 
  AND Positive P&L. Maximum parallel agent execution with autonomous decision-making.
  Integrates deploy-verify-agent for atomic deployments. Detects regression spirals.
  
  **PRIMARY ENTRY POINT:** Use `autonomous-monitoring-loop` skill instead (easier, better UX).
  This skill is the meta-orchestrator used by autonomous-monitoring-loop.
  
  Use for: "achieve 50% win rate + positive P&L" or any goal-driven trading bot improvement.
  Agent team coordinates continuously without manual intervention until goal achieved.
---

# Autonomous Goal-Achievement Orchestrator

## Master Goal
**WIN RATE > 50% + POSITIVE P&L**

Keep agents working in parallel, autonomously fixing issues, until goal is reached.

---

## Architecture

**Team Mode:** Parallel agents with supervisor
- 🤖 **Monitoring Agent**: Reads metrics every 30 min
- 🔍 **Diagnosis Agent**: Analyzes root cause
- 🔧 **Evidence Agent**: Forensics + validation (parallel)
- 📝 **Patch Agent**: Authors minimal fix
- ✅ **Review Agent**: Safety gate
- 🚀 **Deploy Agent**: Push + verify
- 📊 **Goal Checker**: Verify if target reached
- 🔄 **Loop Controller**: Decide next action

All agents work in parallel where possible (diagnostic + forensics in parallel, then sequential patch → review → deploy).

---

## Continuous Workflow (Repeats Until Goal)

### Phase 1: Metrics Monitoring (Every 30 min)
- Read live logs: `journalctl -u cryptomaster.service --since 30 min ago`
- Calculate: Win Rate %, P&L %
- Check: Firebase quota status
- **Output:** Current metrics + status (PASS/CAUTION/FAIL)

**Decision Logic:**
```
if WR > 50% AND P&L > 0:
  → GOAL REACHED! Stop loop, report success
elif WR > 40% AND P&L > -0.05%:
  → CAUTION: Close to goal, minor issue only
elif WR < 20% OR P&L < -0.15%:
  → FAIL: Critical issue, invoke forensics NOW
else:
  → Normal: Proceed to diagnosis
```

### Phase 2: Parallel Issue Diagnosis (Concurrent Agents)

**Diagnostic Agent** (Main):
- Analyzes last 30-min logs
- Identifies pattern (peak entries? zero-EV? timeout? duplicates?)
- Root cause hypothesis

**Evidence Agent** (Parallel - 5 concurrent validations):
- **Runtime Forensics**: Collect evidence
- **Learning Validation**: Check if learning improving
- **Firebase Quota**: Verify safety
- **Trading Safety**: Confirm PAPER-only
- **Test Regression**: Check test suite baseline

**Decision:**
```
if evidence_conclusive:
  → Proceed to patch authoring with evidence
elif evidence_inconclusive:
  → Run extended diagnostic (more logs)
else:
  → Skip this cycle, wait 30 min for more data
```

### Phase 3: Patch Authoring (Sequential)

**Patch Author Agent** (triggered by diagnostics):
- Receives: Root cause + evidence
- Writes: Minimal code change ONLY
- Validates: Invariants preserved
- **Output:** Commit ready to push

**Safety Gates** (Concurrent validation):
- Quota check: Will patch exceed quota?
- Safety check: No real trading exposed?
- Learning check: Does learning still work?
- Test check: Tests pass?

**Decision:**
```
if all_gates_pass:
  → Deploy immediately
elif one_gate_fails:
  → Patch author revises, revalidate
elif multiple_gates_fail:
  → Revert to forensics, new hypothesis
```

### Phase 4: Autonomous Deployment

**Deploy Agent**:
1. Commit patch to main
2. Push to origin
3. Wait 30 seconds for auto-deploy to Hetzner
4. Verify service restarted cleanly
5. Run 2-min sanity check (logs clean? no errors?)

**Decision:**
```
if deploy_successful:
  → Wait 30 min for impact measurement
  → Loop to Phase 1 (new metrics)
elif deploy_failed:
  → Revert commit
  → New hypothesis
  → Return to diagnosis
```

### Phase 5: Goal Verification

After each deployment, wait 30 min for bot to accumulate new trades.
Check:
- New WR in last 30 min
- New P&L accumulated
- Update progress tracker

```
PROGRESS:
  Cycle 1: WR 0% → 5% (+5%, deploy: timeout fix)
  Cycle 2: WR 5% → 12% (+7%, deploy: ev gating fix)
  Cycle 3: WR 12% → 28% (+16%, deploy: entry timing fix)
  Cycle 4: WR 28% → 45% (+17%, deploy: learning improvement)
  Cycle 5: WR 45% → 52% (+7%, GOAL REACHED! ✅)
```

**Decision:**
```
if cycle >= MAX_CYCLES (100):
  → Hit cycle limit, stop and report (may indicate stuck bot)
elif WR > 50% AND P&L > 0:
  → GOAL ACHIEVED! Exit loop with success
else:
  → Continue to next cycle
```

---

## Key Safeguards

1. **Quota Guardian**: Before each fix, check Firebase quota
   - Stop if within 10% of daily limit
   - Resume after reset (07:00 UTC next day)

2. **Deploy-Verify Agent**: Atomic deployment with auto-revert
   - Pushes to main via git
   - Polls GitHub Actions for completion
   - Verifies service health (systemctl, dashboard, logs)
   - On any check failure: `git revert HEAD --no-edit && git push`
   - Guarantees no broken code stays deployed

3. **Regression Spiral Detection**: Stop before thrashing
   - Track last 3 cycles' WR changes
   - If all 3 show WR decline: **STOP** and escalate to human
   - Prevents infinite loop in broken bot state

4. **Max Cycles**: Hard limit of 100 iterations
   - Prevents infinite loop if bot is fundamentally broken
   - Reports "goal unreachable with current strategy"

5. **Evidence Gate**: Every fix requires forensic evidence
   - No hypothesis-only patches
   - Minimum 3 log lines supporting root cause

6. **Parallel Safety**: All validation agents run concurrently
   - If one fails, others still report
   - All gate results collected before decision

7. **Progress Persistence**: Save state to JSON
   - `_workspace/monitoring_progress.json` tracks all cycles
   - Resumable across user sessions
   - Audit trail of every fix applied

---

## Team Communication Protocol

**Monitoring → Diagnosis** (Broadcast):
- "Metrics ready: WR=X%, P&L=Y%, Status=Z"
- Diagnosis responds: "Root cause identified: {issue}"

**Diagnosis → Evidence Agents** (Parallel):
- "Run forensics on issue: {type}"
- Evidence agents respond (all in parallel): 
  - Forensics: "Evidence found: {log lines}"
  - Learning: "Learning status: {ok/warning}"
  - Quota: "Quota status: {safe/warning}"
  - Safety: "Safety status: {ok/warning}"
  - Tests: "Tests status: {pass/fail}"

**All Evidence → Patch Author**:
- "All evidence collected, proceed with patch"
- Patch author: "Patch ready: {file}:{line} {change}"

**Patch → Review** (Sequential validation):
- "Patch ready for review"
- Review agents (parallel): "Gate 1 PASS/FAIL", "Gate 2 PASS/FAIL", etc.

**All Gates → Deploy-Verify Agent**:
- "All gates passed, deploy now"
- Deploy-Verify agent: Atomically pushes to main, polls GH Actions, verifies service, auto-reverts if failed
- Result: "Deploy complete, service verified" OR "Deploy failed, reverted to previous version"

**Deploy → Monitor** (Cycle completes):
- "New cycle begins in 30 min"

---

## Success Criteria

✅ **GOAL ACHIEVED when:**
- Win Rate > 50% (measured over last 30 min, minimum 5 trades)
- P&L > 0% (positive return)
- No pending fixes
- Service stable (no errors in logs)

**Delivery:**
- Stop orchestrator
- Print final report with all cycle improvements
- Save progress file: `/opt/cryptomaster/goal_achievement_report.md`

---

## Error Handling

| Error | Action | Retry |
|-------|--------|-------|
| Deploy failed | Revert + diagnose new issue | Yes, new cycle |
| Quota exhausted | Wait for reset (next day 07:00 UTC) | Yes, after reset |
| All gates fail | Escalate to human review | No (manual intervention) |
| Service crash | Restart service, collect crash logs | Yes, new forensics |
| Cycle limit (100) hit | Stop, report "unreachable" | No (design issue) |

---

## Test Scenarios

**Scenario 1: Simple Fix**
1. Monitor detects: Peak entry timing issue
2. Evidence: "All entries at market tops, 0% winning"
3. Patch: Add peak detection gate
4. Deploy: Success
5. Result: WR jumps 20% in next 30 min → Continue loop

**Scenario 2: Complex Multi-Issue**
1. Monitor detects: WR 20%, P&L -0.15%
2. Evidence (parallel): Forensics finds 3 issues
3. Patch: Prioritize highest impact (evidence scoring)
4. Deploy: Success
5. Result: WR 35% → Loop again for next issue

**Scenario 3: Deployment Fails**
1. Patch ready, deploy starts
2. Service restart hangs
3. Timeout → Auto-revert
4. New forensics needed
5. Loop returns to diagnosis phase

**Scenario 4: Goal Reached**
1. Cycle 5: WR 52%, P&L +0.02%
2. Goal check: SUCCESS!
3. Report printed
4. Loop exits with summary

---

## Metrics Tracking

Each cycle produces:
```json
{
  "cycle": 1,
  "timestamp": "2026-06-11T10:30:00Z",
  "metrics_before": {"wr": 0.00, "pnl": -0.163},
  "issue_detected": "peak_entry_timing",
  "fix_applied": "src/services/trade_executor.py:2746",
  "deploy_status": "success",
  "metrics_after": {"wr": 0.05, "pnl": -0.12},
  "progress": "WR +5%, P&L +0.043%"
}
```

Report aggregates all cycles for final output.

---

## References

- **Evidence-Based Patch Orchestrator**: Use for fix generation
- **Monitoring-Remediation Agent**: Use for 30-min metric cycles
- **Runtime-Forensic-Agent**: Use for evidence collection
- **Paper-Learning-Agent**: Verify learning still improving
- **Firebase-Quota-Agent**: Check quota before each patch
- **Trading-Safety-Agent**: Confirm PAPER-only safety
- **Test-Regression-Agent**: Verify tests still passing
- **Patch-Author-Agent**: Generate minimal code changes
- **Reviewer-Agent**: Final safety gate
