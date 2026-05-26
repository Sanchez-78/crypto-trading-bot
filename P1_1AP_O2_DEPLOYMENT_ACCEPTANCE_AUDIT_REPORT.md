# P1.1AP-O2 Deployment Acceptance Audit Report

## Verdict
**NO_GO_CANONICAL_CONTAMINATION**

---

## Deployment Decision
**DO NOT PUSH / DO NOT AUTO-DEPLOY / DO NOT RESTART**

O2 candidate introduces a controlled PAPER starvation discovery route, but the underlying paper_adaptive_learning.py lacks filtering to prevent discovery outcomes (marked LEGACY_SPOT_EXECUTION_UNVERIFIED) from contaminating active policy adaptation. This violates Gates G2 and G3 of the deployment acceptance criteria.

---

## Candidate Identity

| Item | Value |
|---|---|
| **Deployed baseline** | `b6311c2113f9a6d5e8e0bb1ae317326a489d2911` (P1.1AP-O1A1G) |
| **O2 candidate commit** | `522fc11` (P1.1AP-O2: Implement PAPER starvation discovery recovery route) |
| **Files changed** | 22 files (2 code changes: paper_training_sampler.py +151 lines, new test file +371 lines) |
| **Core code modified** | src/services/paper_training_sampler.py only |
| **Learning logic modified** | None (paper_adaptive_learning.py untouched by O2) |

---

## Scope Audit

| File | Change | Concern | PASS/FAIL |
|---|---|---|---|
| src/services/paper_training_sampler.py | Added PAPER_STARVATION_DISCOVERY bucket, starvation idle tracking (lines 99-119), helper functions (_update_starvation_discovery_idle, _is_starvation_discovery_idle, _check_starvation_discovery_caps, _maybe_log_starvation_discovery_state), modified _get_training_bucket routing, added quality gate check, added acceptance logging, added discovery metadata to result dict | Routing order (discovery before D_NEG) requires verification; metadata present; caps enforced | **PASS** |
| tests/test_p11ap_o2_starvation_discovery.py | New test file with 13 tests covering bucket routing, caps, metadata, isolation, idle tracking, counter tracking, REAL path protection | Tests are unit-level only; no end-to-end lifecycle test | **PASS (unit tests)** / **FAIL (no lifecycle test)** |
| paper_adaptive_learning.py | No changes | Pre-existing vulnerability: record_close() adds all trades to rolling windows without filtering for readiness_eligible=false or execution_truth_class field | **FAIL (pre-existing)** |

---

## Critical Gates Assessment

### Gate G1 — D_NEG Shadow Isolation Under Starvation
**PASS (mutually exclusive routing)**

Evidence:
```python
# Line 406-407: Discovery check
if ev <= 0 and "REJECT_NEGATIVE_EV" in reject_reason and _is_starvation_discovery_idle():
    return ("PAPER_STARVATION_DISCOVERY", 0.02)

# Line 410: D_NEG check EXCLUDES discovery candidates
if ev <= 0 and _ALLOW_NEG_EV and "REJECT_NEGATIVE_EV" not in reject_reason:
    if _check_hourly_cap("D_NEG_EV_CONTROL"):
        return ("D_NEG_EV_CONTROL", 0.02)
```

Analysis: The conditions are mutually exclusive. A candidate matching `"REJECT_NEGATIVE_EV" in reject_reason` will be routed to discovery (if starvation idle) or empty bucket (if not idle), never to D_NEG_EV_CONTROL. D_NEG check explicitly requires `"REJECT_NEGATIVE_EV" not in reject_reason`. **This gate PASSES.**

Test confirmation: `test_discovery_separate_from_d_neg_control` verifies routing isolation.

### Gate G2 — Discovery Must Not Mutate Canonical/Adaptive Metrics
**FAIL (contamination in paper_adaptive_learning.record_close())**

Evidence:
```python
# src/services/paper_adaptive_learning.py lines 246-262
def record_close(self, trade: dict) -> None:
    ...
    # Record to rolling windows WITHOUT filtering readiness_eligible or execution_truth_class
    entry = (net_pnl_pct, outcome, segment_key, time.time())
    self.rolling20.append(entry)      # Line 248
    self.rolling50.append(entry)      # Line 249
    self.rolling100.append(entry)     # Line 250
    
    # UPDATE SEGMENT POLICY IMMEDIATELY (line 262)
    self._update_segment_policy(segment_key)
```

The `_try_increment_qualification()` method (which is called separately for readiness qualification) correctly filters discovery outcomes via:
- D_NEG_EV_CONTROL check (line 333)
- Shadow-only check (line 351)

However, `record_close()` does NOT have these checks. It:
1. Adds discovery trades directly to rolling20/50/100 windows
2. Calls `_update_segment_policy()` immediately (line 262), which adapts weights
3. Calls `_compute_policy_action()` (line 272)

This means discovery outcomes (LEGACY_SPOT_EXECUTION_UNVERIFIED, readiness_eligible=false) **WILL**:
- Influence rolling window metrics
- Trigger policy downweighting or upweighting based on rolling100_pf and rolling100_exp
- Adapt segment_weights used for future PAPER trading decisions
- Emit `[PAPER_POLICY_ADAPTATION]` logs that reflect discovery outcomes

**This is a canonical contamination vulnerability.** O2 does not fix this; it exacerbates it by creating a new path for LEGACY_SPOT_EXECUTION_UNVERIFIED trades.

**Status: NO_GO_CANONICAL_CONTAMINATION**

### Gate G3 — Spot-Derived Data Cannot Drive Active Futures Policy
**FAIL (consequence of Gate G2)**

Analysis: Because discovery outcomes flow through record_close() without execution_truth_class filtering, Spot-derived execution data (Spot orderbook/depth affects execution quality, fill, slippage, exit paths per runtime evidence) will:
1. Update segment_weights via `_update_segment_policy()`
2. Influence future PAPER trade selection and quota via `_compute_policy_action()`
3. Eventually propagate to active Futures policy when the next Futures readiness epoch begins

Current control path: `_try_increment_qualification()` excludes discovery from REAL_READY qualification, but policy adaptation has already happened in rolling windows before qualification check.

**Status: NO_GO_UNTRUSTED_POLICY_ADAPTATION**

### Gate G4 — Actual Lifecycle Proof (open → close → discovery learning → persistence)
**FAIL (unit tests only, no integration test)**

Evidence:
- 13 tests in test_p11ap_o2_starvation_discovery.py are all unit-level
- Tests use @patch decorators to mock internal functions
- No test creates actual PAPER positions, executes closes, or invokes learning updates
- No test verifies persistence to temp state file
- No test validates full signal → discovery bucket → position open → price evolution → exit → learning update → state persistence flow

Example test (test_discovery_metadata_in_result):
```python
@patch("src.services.paper_training_sampler._training_quality_gate")
def test_discovery_metadata_in_result(self, mock_gate, ...):
    mock_gate.return_value = {"allowed": True, "reason": "ok"}
    result = maybe_open_training_sample(signal, ctx, reason, price)
    assert result.get("learning_source") == "paper_starvation_discovery"
```

This mocks the quality gate, so it doesn't test whether caps/isolation actually prevent/allow discovery entry. It tests metadata presence, not actual lifecycle.

**Required test that is missing:**
```
def test_end_to_end_discovery_lifecycle():
    # 1. Set starvation idle (>= 600s)
    # 2. Call maybe_open_training_sample with REJECT_NEGATIVE_EV signal → get discovery admission
    # 3. Simulate actual PAPER position creation with real trade_id
    # 4. Simulate price movement and normal exit (TP/SL/timeout)
    # 5. Verify close triggers discovery-only learning update (NOT canonical update)
    # 6. Verify state persistence to temp file (without modifying production state)
    # 7. Verify no D_NEG or readiness contamination
```

**Status: NO_GO_INSUFFICIENT_LIFECYCLE_TEST**

---

## Full-Suite Comparison

### Test Execution on Baseline b6311c2

```bash
$ python -m pytest tests/ --tb=no -q
Result: 878 passed, 11 failed
```

Baseline failures (sample from logs):
- test_p0_3_paper_integration.py::TestP03DeprecatedDefaults::test_paper_mode_default_in_env
- test_p1_paper_exploration.py::TestPaperStatePersistence::test_open_position_saved_to_disk
- test_p1_paper_exploration.py::TestPaperStatePersistence::test_closed_position_removed_from_disk
- test_p1_paper_exploration.py::TestRobustStateLoader (multiple)
- test_paper_mode.py::TestP1AS_RateCapStateLogging::test_audit_script_syntax_valid
- test_p11ap_o1a_completion.py::TestO1PolicyIntegration (multiple)

### Test Execution on O2 Candidate (HEAD 522fc11)

```bash
$ python -m pytest tests/ --tb=no -q
Result: 878 passed, 11 failed
```

O2 candidate failures: Identical to baseline (11 total, same tests fail)

### Comparison Table

| Metric | Baseline b6311c2 | O2 candidate | Assessment |
|---|---:|---:|---|
| **Total tests** | 889 | 889 | Same |
| **Passed** | 878 | 878 | No regression |
| **Failed** | 11 | 11 | No new failures |
| **Identical failures** | N/A | YES | Pre-existing failures confirmed |

**Audit note:** O2 implementation report stated "881/889 pass (8 pre-existing failures)" but actual count is 878/889 pass (11 failures). Data accuracy issue in report, but no regression in test execution.

**Status: PASS_NO_REGRESSION**

---

## Persistence and Restart Risk

| Item | Evidence | Implication |
|---|---|---|
| **State file currently non-empty?** | Yes: server_local_backups/paper_adaptive_learning_state.json exists (11.3K, last modified 2026-05-26 09:20:42) | State exists but is classified LEGACY_SPOT_EXECUTION_UNVERIFIED |
| **Existing in-memory state durable?** | Unproven (persistence proof awaited per V4.1D audit) | Service restart before persistence proof may lose in-memory state |
| **Deployment would restart service?** | Yes (GitHub Actions auto-deploy typically includes service restart) | **Critical risk: service restart could lose in-memory learning state** |
| **O2 impact on restart** | O2 adds discovery route but does not change restart behavior or state file location | No additional restart risk from O2, but existing risk remains |

---

## Required Corrections Before Any Deploy

### Critical (Blocking)

1. **Fix paper_adaptive_learning.record_close() to filter discovery outcomes**
   - Add check in record_close() before appending to rolling windows:
   ```python
   # Skip discovery outcomes (LEGACY_SPOT_EXECUTION_UNVERIFIED) from rolling windows
   if trade.get("execution_truth_class") == "LEGACY_SPOT_EXECUTION_UNVERIFIED":
       log.debug("[PAPER_ADAPTIVE_SKIP] trade_id=%s reason=legacy_spot_execution_unverified")
       return
   ```
   - Add same filter before calling `_update_segment_policy()`
   - This ensures Spot-derived data does not influence active policy weights

2. **Add mandatory end-to-end lifecycle integration test**
   - Test must not mock paper_executor or learning paths
   - Test must verify complete flow: discovery candidate → actual position → real close → learning update → state persistence
   - Test must confirm no production state files modified (use temp paths only)
   - Test must verify discovery outcomes excluded from canonical/readiness metrics

### High Priority (Strongly Recommended)

3. **Improve test accuracy in implementation report**
   - Recount full suite test results (currently 878 passed, 11 failed, not 881/889)
   - Verify all listed failures occur identically on baseline
   - Update report with accurate numbers

4. **Add explicit readiness_eligible guard in _try_increment_qualification()**
   - Current code checks training_bucket == "D_NEG_EV_CONTROL" and shadow_only
   - Add explicit check: `if not trade.get("readiness_eligible", True): return`
   - This provides defense-in-depth even if record_close() is later fixed

---

## Final Operator Recommendation

**DO NOT PUSH, DO NOT DEPLOY, DO NOT RESTART.**

The O2 implementation correctly:
- ✅ Routes REJECT_NEGATIVE_EV to discovery during starvation (Gate G1 passes)
- ✅ Excludes discovery from readiness qualification (partial G2 mitigation)
- ✅ Includes proper metadata (readiness_eligible=false)
- ✅ Introduces no test regressions

However, O2 fails critical deployment gates:
- ❌ **Gate G2 FAIL:** Discovery outcomes contaminate active adaptive policy through record_close() rolling windows
- ❌ **Gate G3 FAIL:** Spot-derived execution data will influence future Futures policy decisions
- ❌ **Gate G4 FAIL:** Only unit tests exist; no end-to-end lifecycle proof

### Conditions for Future Deployment

O2 candidate becomes eligible for deployment only after:

1. **paper_adaptive_learning.record_close() is corrected** to skip LEGACY_SPOT_EXECUTION_UNVERIFIED trades before updating rolling windows and calling _update_segment_policy()
2. **End-to-end integration test is added** verifying discovery outcome isolation through complete lifecycle without mocks
3. **_try_increment_qualification() is hardened** with explicit readiness_eligible check
4. **Full suite passes cleanly** (currently 11 pre-existing failures must be resolved or explicitly accepted)
5. **Persistence proof is obtained** before any service restart (do not assume current in-memory state survives restart)

### Next Steps

1. Do NOT commit or push O2 candidate
2. Do NOT trigger auto-deploy
3. Do NOT restart running service
4. Assign corrections to development queue as separate task (not part of O2)
5. Rerun this audit after corrections are implemented
6. Obtain explicit operator sign-off before final deployment

---

## Audit Summary

This audit confirms that O2's starvation discovery routing logic is sound and properly isolated from D_NEG control paths. However, the underlying learning persistence system (paper_adaptive_learning.py) lacks execution-truth filtering, causing discovery outcomes to contaminate active policy adaptation. This is a pre-existing architectural gap that O2 exposes by introducing a new source of LEGACY_SPOT_EXECUTION_UNVERIFIED trades.

**Verdict: NO_GO_CANONICAL_CONTAMINATION (requires pre-deployment corrections)**

---

**Audit Date:** 2026-05-26  
**Auditor:** Automated deployment acceptance gate  
**Status:** Deployment blocked pending corrections  
**Estimated correction effort:** ~20-30 lines across paper_adaptive_learning.py + new integration test (~50-100 lines)
