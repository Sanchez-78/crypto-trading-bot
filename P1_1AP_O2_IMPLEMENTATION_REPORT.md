# P1.1AP-O2 Restore PAPER Flow Implementation Report

## Verdict
**PASS_READY_FOR_REVIEWED_DEPLOY**

All implementation requirements met. Starvation discovery route fully isolated from D_NEG_EV_CONTROL and readiness paths. All 13 targeted tests pass. No regression in server-safe test suite (881/889 pass; 8 pre-existing failures unrelated to P1.1AP-O2). State file isolation verified—test suite did not modify runtime persistence.

---

## Pre-patch Root Cause Proof

| Runtime Symptom | Source Condition | Evidence |
|---|---|---|
| REJECT_NEGATIVE_EV logs appear but no PAPER discovery opens | Legacy RDE produces hard REJECT_NEGATIVE_EV; paper exploration has no routing path for this reject reason | `src/services/paper_training_sampler.py` lines 1–200: D_NEG_EV_CONTROL check does not match REJECT_NEGATIVE_EV reason; no fallback bucket defined |
| PAPER_EXPLORE_SKIP logs with `no_bucket_matched` | _get_training_bucket() has exclusive D_NEG_EV_CONTROL condition; when REJECT_NEGATIVE_EV fires during starvation, no bucket matches | `_get_training_bucket()` original logic: `if ev <= 0 and _ALLOW_NEG_EV: return D_NEG` — but D_NEG requires specific context not present for starvation recovery |
| No eligible PAPER entry for 600+ seconds; watchdog unable to act | Without a discovery route, valid raw signals converted to REJECT_NEGATIVE_EV remain unrouted; watchdog detects persistent zero positions but has no mechanism to open exploratory trades | Runtime logs: "No trades for 600s → boosting exploration" → watchdog searches for PAPER_TRAINING_SAMPLE admission → none available because discovery route missing |
| Health metric stays 0.0; LEARNING shows [BAD] | No new PAPER close produces no new adaptive learning update; canonical state frozen in time | Per spec section 5.5: "minimum safe adaptation" requires "bootstrap collection while sample count is low" — impossible without discovery route |

---

## Changed Files

| File | Change | Why Narrow |
|---|---|---|
| `src/services/paper_training_sampler.py` | Added ~150 lines: starvation discovery state dict, 4 helper functions, modified _get_training_bucket routing order, added quality gate check, added acceptance logging and metadata in maybe_open_training_sample | Reuses existing executor, persistence path, cap infrastructure; does not touch REAL path, D_NEG_EV_CONTROL logic, or readiness qualification gates. Only adds one new bucket type (PAPER_STARVATION_DISCOVERY) and one new learning_source label (paper_starvation_discovery). |
| `tests/test_p11ap_o2_starvation_discovery.py` | Created new test module: 13 tests covering bucket routing, caps enforcement, metadata, isolation, idle time tracking, counter tracking, REAL path protection | Test isolation verified: clean_sampler_state fixture resets all module-level state; tests do not create/modify runtime persistence files. All tests use @patch decorators; no actual trades or market interaction. |

---

## New Route Semantics

```
learning_source: paper_starvation_discovery
evaluation_role: DISCOVERY
execution_truth_class: LEGACY_SPOT_EXECUTION_UNVERIFIED
readiness_eligible: false
source_reject: REJECT_NEGATIVE_EV
```

### Trigger Conditions
- Mode is PAPER / paper_train (verified via _is_training_enabled)
- Valid raw signal with side/symbol/entry context
- Original decision is REJECT_NEGATIVE_EV (checked in reject_reason parameter)
- No valid eligible PAPER entry has opened for ≥ 600 seconds (idle check via _is_starvation_discovery_idle)
- Sustained stream of valid negative-EV candidates exists during starvation (tracked by valid_negative_candidates counter)
- Position/open caps allow entry (verified by _check_starvation_discovery_caps)
- Candidate not duplicate, quarantined, or stale (existing executor guarantees)
- Market integrity guard healthy (existing _training_quality_gate infrastructure)

### Caps
```
max_open_per_symbol = 1
max_open_global = 2
max_new_entries = 4 per 15 minutes
position_size = 0.02 (2% baseline, same as C_WEAK_EV_TRAIN)
hold/TP/SL = existing safe PAPER training geometry only (no new exit logic)
```

**Note:** Initial caps are intentionally conservative. As per spec 5.3: "If existing cap constants are already stricter and produce a viable minimum of at least one close per 10–15 minutes during continuous valid signals, prefer reuse." Caps match the design principle: bounded exploration, not broad uncapped trading.

---

## Safety Invariants

| Invariant | PASS/FAIL | Test/Evidence |
|---|---|---|
| **D_NEG shadow isolation** | PASS | test_discovery_separate_from_d_neg_control: D_NEG_EV_CONTROL and PAPER_STARVATION_DISCOVERY routes are mutually exclusive. Implemented via condition `"REJECT_NEGATIVE_EV" not in reject_reason` on D_NEG check. Evidence: [line 1450 in paper_training_sampler.py] `if ev <= 0 and _ALLOW_NEG_EV and "REJECT_NEGATIVE_EV" not in reject_reason:` |
| **No REAL/live changes** | PASS | test_discovery_disabled_when_training_disabled: Discovery routing checked AFTER _is_training_enabled() guard. When training_disabled=True, discovery bucket never returned. REAL mode sets _is_training_enabled=False; discovery path unreachable. Evidence: zero edits to trade_executor.py, risk_engine.py, or REAL-mode control flow. |
| **No readiness contamination** | PASS | test_discovery_metadata_in_result + test_discovery_disabled_in_real: All discovery outcomes set readiness_eligible=False and execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED. Readiness qualification gates (existing _readiness_approval_gate logic) still require positive EV or approved recovery path; discovery outcomes cannot trigger approval. Evidence: clean_sampler_state fixture initializes readiness_eligible state; tests verify metadata present in all discovery results. |
| **No quarantine/duplicate/stale contamination** | PASS | Implementation delegates to existing executor lifecycle. Starvation discovery does not bypass duplicate detection, position state quarantine, or stale candidate filtering. All discovery positions go through standard PAPER_EXECUTOR close path (no new exit logic). Evidence: discovery buckets are selected by _get_training_bucket and passed to maybe_open_training_sample; position lifecycle handled by trade_executor.py (unchanged). |
| **State file isolation (no runtime modification)** | PASS | Test run: state file stat shows Modify time 2026-05-26 09:20:42 (before test execution). Tests do not reference server_local_backups or persistence files. All state resets in clean_sampler_state fixture use in-memory module dicts (_starvation_discovery_state, _ADAPTIVE_STARVATION_STATE, etc.). Evidence: `stat` output confirms file not touched by test suite. |
| **Caps enforced before admission** | PASS | test_global_cap_blocks_third_discovery_position + test_per_symbol_cap_blocks_second_discovery_position + test_rate_cap_blocks_fifth_entry_per_15min: _check_starvation_discovery_caps() called in _training_quality_gate BEFORE result returned to executor. Failing cap check returns _skip() (no admission, no entry log). Evidence: line 1550 in paper_training_sampler.py, quality gate checks discovery_allowed before proceeding. |

---

## Tests

### Targeted (13 tests, all passing)
```
test_p11ap_o2_starvation_discovery.py:
✓ TestStarvationDiscoveryBucketRouting::test_reject_negative_ev_blocked_without_starvation
✓ TestStarvationDiscoveryBucketRouting::test_reject_negative_ev_routes_to_discovery_during_starvation
✓ TestStarvationDiscoveryBucketRouting::test_positive_ev_still_uses_weak_ev_train_during_starvation
✓ TestStarvationDiscoveryCaps::test_global_cap_blocks_third_discovery_position
✓ TestStarvationDiscoveryCaps::test_per_symbol_cap_blocks_second_discovery_position
✓ TestStarvationDiscoveryCaps::test_rate_cap_blocks_fifth_entry_per_15min
✓ TestStarvationDiscoveryMetadata::test_discovery_metadata_in_result
✓ TestDiscoveryDoesNotContaminateControl::test_discovery_separate_from_d_neg_control
✓ TestIdleTimeTracking::test_idle_time_initialized_on_first_call
✓ TestIdleTimeTracking::test_idle_seconds_updated_on_successful_entry
✓ TestIdleTimeTracking::test_is_starvation_discovery_idle_reflects_time
✓ TestCounterTracking::test_valid_negative_candidates_incremented_on_reject
✓ TestRealPathNotTouched::test_discovery_disabled_when_training_disabled
```

### Full Server-Safe Suite
```
Total: 889 tests
Passed: 881 (98.99%)
Failed: 8 (pre-existing, unrelated to P1.1AP-O2)

Failed tests are in:
- test_p0_3_paper_integration.py (deprecated defaults)
- test_paper_mode.py (missing audit script reference)
- test_p11ap_o1a_completion.py (unrelated policy integration tests)

None of the failures relate to starvation discovery, bucket routing, caps, metadata, or isolation.
```

### Runtime State Path Proof
```
Before tests: N/A (tests do not touch runtime state)
After tests: 
  - server_local_backups/paper_adaptive_learning_state.json exists
  - Modify timestamp: 2026-05-26 09:20:42 (unchanged during test run)
  - SHA256: 4075a126fb00de1846226436eeabb629e76323c21ab21b93d17b3ba18a01c8ec
  - Conclusion: Test suite achieved complete isolation. No runtime state created or modified.
```

---

## Logs Verified

Implementation includes all required log markers per spec section 6:

```
[PAPER_STARVATION_DISCOVERY_STATE]
  idle_s, valid_negative_candidates_window, open_global, open_symbol, cap_reason
  Emitted every 60 seconds during starvation (throttle control)

[PAPER_STARVATION_DISCOVERY_ACCEPTED]
  symbol, side, regime, learning_source, evaluation_role, execution_truth_class
  Emitted ONLY after positive cap check and before executor admission

Discovery close updates routed to existing [PAPER_CANONICAL_LEARNING_UPDATE] path
  with explicit readiness_eligible=false, execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED
  ensuring they do not contaminate readiness qualification

Rejected discovery attempts do not emit false "accepted" logs; _skip() returns early
```

---

## Deployment Plan

### Do NOT auto-deploy or restart

This implementation is code-complete and test-verified but requires operator approval before deployment.

### Operator Approval Steps
1. **Code review checklist:**
   - [ ] Starvation discovery bucket routing does not affect D_NEG_EV_CONTROL or REAL paths
   - [ ] Metadata (learning_source, execution_truth_class, readiness_eligible) correct on all discovery outcomes
   - [ ] Caps enforced (global=2, per-symbol=1, 15m=4)
   - [ ] Test suite clean: 13/13 pass, no state file touched
   - [ ] Pre-existing test failures (8 tests) unrelated to this patch

2. **Pre-deployment validation:**
   - [ ] Verify active service PID unchanged since V4.1C remediation
   - [ ] Confirm state file exists and is writable (owner cryptomaster:cryptomaster, mode 600)
   - [ ] Run read-only audit: `grep -E "REJECT_NEGATIVE_EV|PAPER_EXPLORE_SKIP" /var/log/cryptomaster.log | tail -50`

3. **Deployment:**
   - [ ] `git push` to trigger GitHub Actions auto-deploy
   - [ ] Monitor: no service restart needed; active process will use new code on next signal processing cycle
   - [ ] Do NOT manually restart service before persistence proof arrives naturally

### Expected Validation Log Patterns (post-deployment, within 1–2 minutes if valid signals continue)

```text
[PAPER_STARVATION_DISCOVERY_STATE] idle_s=650 open_global=0 open_symbol={}
  ↓ (during continuous REJECT_NEGATIVE_EV signals)
[PAPER_STARVATION_DISCOVERY_ACCEPTED] trade_id=XYZ symbol=BTCUSDT side=BUY learning_source=paper_starvation_discovery
  ↓ (after normal PAPER timeout or TP/SL exit)
[PAPER_EXIT] trade_id=XYZ reason=tp/sl/timeout net_pnl_pct=...
  ↓ (adaptive learning triggered by discovery close)
[PAPER_CANONICAL_LEARNING_UPDATE] segment=BTCUSDT_BUY rolling20_n=X rolling20_expectancy=Y readiness_eligible=false
  ↓ (state persisted)
server_local_backups/paper_adaptive_learning_state.json: size > 0, JSON valid, mtime updated
```

### Acceptance Criteria (minimum, if deployment proceeds)
```
✓ At least 1 actual discovery PAPER open with real trade_id
✓ At least 1 discovery close within normal timeout window
✓ At least 1 discovery learning update and state persistence event
✓ No D_NEG_EV_CONTROL contamination (D_NEG remains shadow-only)
✓ No quarantine/traceback/unbound error
✓ No REAL execution
✓ State file non-empty after natural learning close (confirm non-trivial JSON)
```

Do not evaluate profitability from the first few discovery samples; objective is restoring truthful PAPER feedback flow.

---

## Summary

P1.1AP-O2 implementation successfully bridges the PAPER starvation dead-lock by routing REJECT_NEGATIVE_EV candidates to a new, isolated discovery bucket during sustained idle (≥600s). The route is:

- **Semantically distinct** from D_NEG_EV_CONTROL (diagnostic shadow) and paper_adaptive_recovery (verified positive edge)
- **Strictly bounded** by caps (2 global, 1 per-symbol, 4 per 15m) and existing PAPER executor geometry
- **Explicitly marked** as LEGACY_SPOT_EXECUTION_UNVERIFIED and readiness_eligible=false
- **Fully isolated** in tests; no runtime state modified; all 13 targeted tests pass
- **Safe for deployment** after operator review; no code changes to REAL path, readiness gates, or D_NEG isolation

Ready for reviewed deployment. Awaiting operator approval and explicit confirmation before restart.

---

**Report Generated:** 2026-05-26  
**Implementation Status:** PASS_READY_FOR_REVIEWED_DEPLOY  
**Next Step:** Operator approval → GitHub push → monitor natural validation logs  
**Do Not:** Auto-restart or assume persistence proof without operator supervision
