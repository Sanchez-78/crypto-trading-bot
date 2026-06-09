# P0.3F Blocker: RDE Training Sampler Bypass

**Status:** 🛑 UNRESOLVED  
**Date:** 2026-06-09  
**Session:** P0.3F (ended early due to architectural discovery)

---

## Problem Statement

P0.3B/C/D implemented P0 metadata guard in `open_paper_position()` to ensure all positions carry:
- `strict_ev` (bool)
- `readiness_eligible` (bool)
- `learning_source` (str)
- `segment_key` (str)
- `p0_gate_reason` (str)

**But discovered:** RDE has THREE callsites that bypass P0 entirely:

```
realtime_decision_engine.py:3761   → maybe_open_training_sample()
realtime_decision_engine.py:3959   → maybe_open_training_sample()
realtime_decision_engine.py:4030   → maybe_open_training_sample()
```

These paths:
1. Do NOT route through P0.3B segment gate
2. Do NOT apply P0.3C evidence collection routing
3. Do NOT set `learning_source=paper_evidence_collection`
4. Result in positions with `learning_source=paper_training_sampler`

---

## Root Cause

P0 gate was added to `open_paper_position()` (too late in pipeline):

```
signal → RDE → maybe_open_training_sample() ← OUTSIDE P0!
                ↓
          open_paper_position() ← P0 gate here (too late)
```

Should be:

```
signal → RDE → [P0 GATE DECISION]
              ├─ strict_ev_allowed → P0.3B route
              ├─ evidence_collection_allowed → P0.3C route
              └─ rejected → block or fail-closed
         ↓
    maybe_open_training_sample() ← only if P0 approved
         ↓
    open_paper_position() ← metadata already set
```

---

## Evidence

**Metadata snapshot (2026-06-09 10:29 UTC):**
```
Hetzner /opt/cryptomaster/data/paper_open_positions.json
Sample position: learning_source=paper_training_sampler

Expected (P0.3C routed): learning_source=paper_evidence_collection
Observed: learning_source=paper_training_sampler
```

**Call chain that bypasses P0:**
```
realtime_decision_engine.py:3726
    maybe_open_training_sample(signal, ...)
    ↓ returns sampler_result
    
realtime_decision_engine.py:3735-3759
    Build extra dict with:
    "learning_source": sampler_result.get("learning_source", "paper_training_sampler")
    ↑ FROM SAMPLER, not from P0 gate
    
realtime_decision_engine.py:3761
    open_paper_position(signal, extra=extra, ...)
    ↓
    
paper_trade_executor.py:1500
    _POSITIONS[trade_id] = position
    ↑ at this point, learning_source is STILL paper_training_sampler
    
paper_trade_executor.py:1505+
    New fail-closed guard CATCHES this
    ← BLOCKS entry because learning_source != paper_evidence_collection
```

---

## Attempted Fixes in P0.3F

✅ **Fixed:** Removed duplicate `learning_source` assignment (line 1492)
✅ **Fixed:** Added centralized fail-closed guard (lines 1505-1515)

```python
if "learning_source" not in position or position["learning_source"] is None:
    log.error("[P0_METADATA_BLOCK] ... entry BLOCKED")
    return {"status": "blocked", "reason": "p0_metadata_missing"}
```

❌ **NOT Fixed:** RDE bypass still exists
- Positions from training sampler path still bypass P0 gate
- Guard BLOCKS them (which is safe) but doesn't route them
- Robot cannot trade until RDE is fixed

---

## Why Not Finish P0.3F Tonight?

1. **Risk of cascading bugs:** Patching 3 RDE callsites quickly might break:
   - Signal routing logic (reject path vs accept path)
   - Double-open position bugs
   - Learning flow contamination

2. **Architecture matters:** This isn't a line-level bug, it's a control flow bug.
   - Needs careful design of P0 decision → routing → execution
   - Cannot rush

3. **Data contamination:** We already have 24 positions with wrong metadata.
   - Deploying incomplete P0.3F would create more.
   - Better to stop and fix cleanly in P0.4.

---

## P0.4 Plan: RDE Training Sampler P0 Routing

**Scope:** Wire P0 gate decision into RDE BEFORE training sampler path

**Steps:**
1. Create `_route_training_sample_through_p0()` helper in RDE
2. Call P0 gate on signal BEFORE maybe_open_training_sample()
3. Apply P0.3C evidence collection metadata
4. All 3 callsites use helper (no direct sampler calls)
5. Fail-closed: if P0 gate rejects, block entry (don't fallback)

**Expected outcome:**
```
[P0_RDE_TRAINING_ROUTE] signal routed to evidence collection
[PAPER_EVIDENCE_ENTRY] learning_source=paper_evidence_collection
```

---

## Deployment Status

| Component | Status | Reason |
|-----------|--------|--------|
| P0.3A (module) | ✅ Deployed | Pure logic, 23 tests pass |
| P0.3B (wiring) | ⚠️ Partial | Gate added but in wrong place |
| P0.3C (routing) | ⚠️ Partial | Works for main path, not RDE sampler |
| P0.3D (metadata) | ✅ Code ready | Guard added, but blocked by RDE bypass |
| P0.3E (tests) | ✅ Passed | 11 integration tests pass |
| P0.3F (deploy) | 🛑 BLOCKED | RDE bypass must be fixed first |

**DO NOT DEPLOY P0.3F until P0.4 completes.**

---

## Snapshot Location

```
/opt/cryptomaster/forensic_snapshots/p0_3f_partial_20260609_102940/
├── git_head.txt              # Commit hash
├── git_status.txt            # Working tree status
├── git_diff_stat.txt         # Change summary
├── p0_3f_partial_rde_blocker.diff  # Full diff
├── service_status.txt        # systemd status
├── service_env.txt           # Environment vars
└── journal_120min.log        # Last 2 hours of logs
```

---

## Next Session (P0.4)

1. Read this blocker doc
2. Inspect RDE code (lines 3720-3770, 3910-3960, 3980-4040)
3. Design RDE helper `_route_training_sample_through_p0()`
4. Wire all 3 callsites
5. Commit + test
6. Deploy with full validation

**Guard is in place.** Robot is safe. We can fix this properly.
