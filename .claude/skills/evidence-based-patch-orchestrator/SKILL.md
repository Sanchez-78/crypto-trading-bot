---
name: evidence-based-patch-orchestrator
description: |
  Master orchestrator for CryptoMaster evidence-based patch workflow. Coordinates 
  8 specialized agents to investigate issues, validate learning, ensure safety, 
  author minimal patches, and obtain final approval. Prevents patch treadmill by 
  requiring evidence at every step. Use for any bug fix or feature request.
  
  **Invoke when:** User reports trading bug, dashboard issue, timeout anomaly, 
  learning failure, or any code change request. Orchestrator decides if evidence 
  needed, farms out to agents, synthesizes findings, blocks risky patches.

---

# Evidence-Based Patch Orchestrator

## Master Workflow (7 Phases)

### Phase 0: Intake & Scope

**Input:** User request ("positions timing out at 300s")

**Questions:**
1. Is this a bug report (symptom) or feature request?
2. What's the symptom? How to reproduce?
3. Do we have logs/state from incident?
4. What time window?

**Output:** Scoped issue statement + evidence requirements

### Phase 1: Runtime Forensics

**Agent:** runtime-forensic-agent
**Skill:** runtime-log-forensics

**Deliverable:**
- Timeline of events (logs + state snapshots)
- Root cause hypothesis with evidence
- Code path(s) implicated

**Gate:** Must have concrete log + state + code evidence

### Phase 2: Parallel Validation (Agents 2-6)

Launch all validation agents in parallel:

**paper-learning-agent** (if learning involved)
- Validates learning loop still working
- Confirms new behavior improves metrics

**firebase-quota-agent**
- Checks quota safe after code change
- Verifies no new per-tick operations

**trading-safety-agent**
- Ensures no real trading paths exposed
- Confirms PAPER-only deployment

**test-regression-agent**
- Runs full test suite baseline
- Ready to re-run post-patch

**android-contract-agent** (if UI/metrics involved)
- Validates dashboard contract
- Checks Czech localization

### Phase 3: Patch Authoring

**Agent:** patch-author-agent
**Skill:** narrow-patch-authoring

**Input:** Forensic findings + validation results

**Deliverable:**
- Minimal code change (root cause only)
- No refactoring, no bloat
- Commit message with evidence citation

**Gate:** Must pass invariant checks

### Phase 4: Independent Review

**Agent:** reviewer-agent
**Skill:** (integrated in agent definition)

**Checklist:**
- [ ] Safety gate: PASS
- [ ] Test gate: PASS
- [ ] State persistence: Atomic
- [ ] Quota: Safe
- [ ] Invariants: Preserved

**Gate:** APPROVED or REJECT with feedback

### Phase 5: Deployment Readiness

**Skill:** deployment-readiness-review

**Final checks:**
- All gates PASS
- Tests passing
- No regressions
- Ready to deploy

### Phase 6: Deploy

**Action:**
- For PAPER_LIVE: Push to main (auto-deploys via GH Actions)
- For REAL_LIVE: Requires CEO authorization (blocked in this harness)

**Post-deploy monitoring:**
- Service running
- Logs clean
- Metrics updating
- No new anomalies (30 min window)

## Execution Model

**Team mode:** Multi-agent team coordinates via `TeamCreate`, `SendMessage`, `TaskCreate`

**Data flow:**
- Phase 0-1: Sequential (intake → forensics)
- Phase 2: Parallel (5 agents validate simultaneously)
- Phase 3-6: Sequential (author → review → readiness → deploy)

## Error Handling

| Blocker | Action |
|---------|--------|
| Forensics incomplete | Request more logs/state; don't author patch |
| Validation fails | Return to Phase 1 for more evidence |
| Patch fails review | Author fixes or gathers more evidence |
| Tests fail | Require patch author to fix, re-test |
| Quota violation | Hold deployment pending reset or refactoring |
| Safety audit fails | BLOCK deployment; escalate |

## Workflow State Tracking

Orchestrator maintains state in `_workspace/` directory:

```
_workspace/
├── 01_intake.md          (Phase 0 summary)
├── 02_forensics.md       (Phase 1: findings from runtime-forensic-agent)
├── 03_learning_val.md    (Phase 2a: paper-learning-agent report)
├── 03_quota_val.md       (Phase 2b: firebase-quota-agent report)
├── 03_safety_val.md      (Phase 2c: trading-safety-agent report)
├── 03_test_val.md        (Phase 2d: test-regression-agent report)
├── 03_android_val.md     (Phase 2e: android-contract-agent report)
├── 04_patch.md           (Phase 3: patch from patch-author-agent)
├── 05_review.md          (Phase 4: review from reviewer-agent)
├── 06_readiness.md       (Phase 5: final gate)
└── FINAL_REPORT.md       (Summary for user)
```

## Orchestrator Commands

```bash
# Start fresh investigation
evidence-based-patch-orchestrator: investigate trading bot bug

# Re-run from specific phase
evidence-based-patch-orchestrator: continue from phase 2 (validation)

# Check current state
evidence-based-patch-orchestrator: show current state
```

## Example Session

**User:** "Positions are timing out at 300 seconds instead of 600."

**Orchestrator (Phase 0):** 
```
This looks like a timeout evaluation bug. I'll:
1. Collect logs from when symptom occurred
2. Trace timeout evaluation code path
3. Validate learning, quota, safety
4. Author minimal fix
5. Get final approval
6. Deploy

Time window? (e.g., "2026-06-08 08:00-09:00 UTC")
```

**User:** "2026-06-08 08:20-08:30 UTC"

**Orchestrator (Phase 1):** 
```
[Spawning runtime-forensic-agent]
→ Collecting journalctl entries 08:20-08:30
→ Found positions created at 08:20:38, closed at 08:30:38 (600s later)
→ Found timeout evaluation at 300s mark in code
→ Root cause: max_hold_s=300 used instead of timeout_s=600

[Forensic findings ready]
```

**Orchestrator (Phase 2):**
```
[Launching 5 agents in parallel]
✓ learning-agent: Learning loop still working
✓ quota-agent: Quota safe
✓ safety-agent: No real trading touched
✓ test-agent: Tests baseline ready
✓ android-agent: Contract unchanged

[All validations PASS → Continue to Phase 3]
```

**Orchestrator (Phase 3):**
```
[Spawning patch-author-agent]
→ Writing minimal fix (1 line change)
→ Preserving all invariants
→ Commit ready

[Patch ready for review]
```

**Orchestrator (Phase 4):**
```
[Spawning reviewer-agent]
→ Safety: PASS
→ Tests: PASS
→ Invariants: PASS
→ Quota: PASS

[APPROVED for deployment]
```

**Orchestrator (Phase 5):**
```
Final readiness check: ✅
All gates PASS. Ready to deploy.
```

**Orchestrator (Phase 6):**
```
Deploying to main...
→ Service restarted on Hetzner
→ Monitoring logs (30 min)...
→ ✓ No new errors
→ ✓ Positions now timing out at 600s

Deployment SUCCESS.
```

## Harness Discipline Rules

**Hard rules (violations block deployment):**
1. No patch without forensic evidence
2. No deployment without all agent approvals
3. No REAL trading changes without CEO authorization
4. No tests skipped or disabled
5. No state contamination allowed

**Soft guidelines (recommendations):**
- Keep patches minimal
- Test in isolation
- Monitor post-deploy
- Gather user feedback for harness improvement
