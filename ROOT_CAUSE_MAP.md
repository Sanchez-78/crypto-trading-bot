# Root-Cause Map: PAPER Continuous Learning Losing-Route Control

**Analysis Date**: 2026-05-26  
**Session**: paper-continuous-learning/losing-route-control topic branch  
**Evidence Source**: Baseline log showing discovery_bucket=PAPER_STARVATION_DISCOVERY with pf=0, avg=-0.15, timeout_rate=100%

---

## Root-Cause #1: PAPER_STARVATION_DISCOVERY Accepted with idle_s=0.0

### Location
`src/services/paper_training_sampler.py:1128-1130`

### Root Cause
Initialization sets `last_eligible_entry_ts = now` on first `maybe_open_training_sample()` call, making idle calculation begin at current time rather than epoch. This causes:

```python
# Line 1128-1130
if _starvation_discovery_state.get("last_eligible_entry_ts", 0.0) == 0.0:
    _starvation_discovery_state["last_eligible_entry_ts"] = now  # BUG: should be 0
    _starvation_discovery_state["idle_s"] = 0.0
```

When check at line 410 (`_is_starvation_discovery_idle()`) calculates idle_s:
```python
idle_s = now - last_eligible_entry_ts  # = now - now = 0 seconds
return idle_s >= 600  # 0 >= 600 = FALSE
```

**But** discovery still gets accepted because idle gate is checked in `_get_training_bucket` (called BEFORE idle timer reset), and the 600s threshold is not truly enforced on first discovery entry in a cold-start session.

### Evidence
- Log line: `[PAPER_STARVATION_DISCOVERY_ACCEPTED] ... idle_s=0.0`
- Expected: Should require `idle_s >= 600` at time of acceptance check

### Fix
Initialize `last_eligible_entry_ts = 0` (not `now`) so idle calculation starts correctly:
```python
if _starvation_discovery_state.get("last_eligible_entry_ts", 0.0) == 0.0:
    _starvation_discovery_state["last_eligible_entry_ts"] = 0  # FIX: epoch/uninitialized
    _starvation_discovery_state["idle_s"] = float('inf')  # or very large number
```

Then properly update on acceptance (keep line 1305 as-is).

---

## Root-Cause #2: Loss-Making Routes Continue Admissions (No Cooldown)

### Location
`src/services/paper_training_sampler.py:765-769` (caps check exists, but NO cooldown logic)
Missing: Cooldown state tracking, activation criteria, and blocking behavior

### Root Cause
Discovery bucket admission gates (lines 766-769) check position caps and rate limits, but do NOT check for:
1. Persistent loss pattern in completed trades
2. Activation of bucket-level or segment-level cooldown
3. Cooldown status before allowing new entries

**Current code**:
```python
if bucket == "PAPER_STARVATION_DISCOVERY":
    discovery_allowed, discovery_reason = _check_starvation_discovery_caps(symbol, open_positions)
    if not discovery_allowed:
        return _skip(discovery_reason, ...)
```

Only checks open caps, rate caps. No loss-triggered circuit breaker.

### Evidence
- Baseline shows 3 PAPER_STARVATION_DISCOVERY closes with pf=0.0, avg_pnl=-0.1549%, timeout_rate=100%
- Yet new discovery entry still logged as ACCEPTED

### Fix
Add `_STARVATION_DISCOVERY_BUCKET_COOLDOWN_STATE` dictionary:
```python
_STARVATION_DISCOVERY_BUCKET_COOLDOWN_STATE = {
    "active": False,
    "activated_at": 0.0,
    "cooldown_s": 3600,
}
```

Before admission, check:
```python
if bucket == "PAPER_STARVATION_DISCOVERY":
    if _is_discovery_bucket_in_cooldown():
        return _skip("discovery_bucket_in_loss_cooldown", ...)
    # ... then normal caps check ...
```

Activate cooldown when discovering loss pattern in closed trades (tied to trade closing logic).

---

## Root-Cause #3: Cost-Edge vs Trade Entry Ambiguity

### Location
`src/services/paper_training_sampler.py:659` (cost_edge_too_low rejection)  
vs `src/services/paper_training_sampler.py:1275-1285` (entry logged)  
vs Missing: `PAPER_ENTRY_ADMISSION_TRUTH` telemetry

### Root Cause
Two separate code paths:
1. **Rejection**: Line 659 returns `_skip("cost_edge_too_low", ...)`  → logs `[PAPER_TRAIN_SKIP]`
2. **Acceptance**: Lines 1275-1285 logs `[COST_EDGE_BYPASS_ACCEPTED]` + `[PAPER_ENTRY_ATTEMPT]`
3. **Missing**: No unified `PAPER_ENTRY_ADMISSION_TRUTH` log that correlates cost_edge status with actual entry

If `cost_edge_too_low` candidate is rejected, then a DIFFERENT candidate (same symbol) accepts, it's impossible to correlate they're the same trade opportunity or different.

### Evidence
- Runtime logs show `[PAPER_EXPLORE_SKIP] reason=cost_edge_too_low symbol=ADAUSDT`
- Followed by `[PAPER_ENTRY] symbol=ADAUSDT ...`
- Cannot determine if same candidate or different entry

### Fix
Add `PAPER_ENTRY_ADMISSION_TRUTH` log after all gates pass (line ~1360):
```python
log.info(
    "[PAPER_ENTRY_ADMISSION_TRUTH] trade_id=%s candidate_id=%s bucket=%s "
    "cost_edge_ok=%s cost_edge_bypassed=%s bypass_reason=%s "
    "expected_move_pct=%.4f required_move_pct=%.4f admission_reason=%s",
    trade_id,  # generated here
    gate_result.get("flow_id", ""),  # candidate correlation
    bucket,
    cost_edge_ok,
    gate_result.get("cost_edge_bypassed", False),
    gate_result.get("cost_edge_bypass_reason", "none"),
    expected_move_pct,
    0.23,  # required_move_pct reference
    admission_reason,
)
```

---

## Root-Cause #4: Segment State Not Available to Admission Policy

### Location
`src/services/paper_adaptive_learning.py:262` (segment state updated)  
vs `src/services/paper_training_sampler.py:766` (admission gate runs, no segment state access)

### Root Cause
Segment metrics (n, pf, expectancy) are tracked in `PaperAdaptiveLearning` class but NOT exported/accessible to `paper_training_sampler` admission path.

**Segment state exists** (in paper_adaptive_learning.py):
```python
segment_weights = {}  # tracks weights per segment
rolling20/50/100 = deque()  # trades per segment embedded
```

**But NOT available in admission**:
```python
# paper_training_sampler.py line 766
if bucket == "PAPER_STARVATION_DISCOVERY":
    discovery_allowed, discovery_reason = _check_starvation_discovery_caps(...)
    # No segment state check possible here
```

### Evidence
- Baseline shows C_WEAK_EV_TRAIN bucket with n=7, pf=0.0, avg=-0.2007%, timeout_rate=71.4%
- Spec requires: segment-level cooldown if n>=2, pf==0, avg<=-0.10
- Current code: No mechanism to check segment metrics during admission

### Fix (Conditional)
**Per spec**: Only implement segment cooldown if SAFE segment state can be exposed to admission path.

**Option A (Safe)**: Export read-only `get_segment_metrics(symbol, regime, side)` function from `PaperAdaptiveLearning`, call it in admission gate ONLY IF learner is safely accessible.

**Option B (Unsafe - NOT IMPLEMENTED)**: If safe segment state NOT available, return `BLOCKED_MISSING_SAFE_SEGMENT_STATE` for C_WEAK_EV_TRAIN segment cooldown, emit telemetry only.

**Decision**: Implement Option A with guard try/except. If learner call fails, skip segment cooldown and log blocker.

---

## Verdict: Ready for Fix Implementation

All four root-causes confirmed:
1. ✅ Idle gate initialization (line 1128-1130) — direct fix
2. ✅ Loss-triggered cooldown missing (lines 765-769) — add state tracking + gate
3. ✅ Cost-edge/entry ambiguity (line 659 vs 1275) — add PAPER_ENTRY_ADMISSION_TRUTH log
4. ✅ Segment state not accessible (paper_adaptive_learning vs paper_training_sampler) — export + guard

**Scope**: PAPER-only, no REAL path changes, no service restart, no Firebase reset
