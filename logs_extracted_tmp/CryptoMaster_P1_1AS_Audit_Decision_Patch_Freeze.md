# CryptoMaster P1.1AS Audit Decision — Patch Freeze + One Surgical Fix Gate

**Date:** 2026-05-18  
**Observed HEAD:** `d7d7850`  
**Service PID:** `1059730`  
**Scope:** Analyze P1.1AS audit and prevent further diagnostic patch spiral.

---

## Verdict

**Do not add another broad diagnostics patch.**

P1.1AS gave enough signal. The blocker is now specific:

> The paper-training sampler rate-cap is counting/reserving entries before a real `PAPER_TRAIN_ENTRY` is created, which starves the sampler even when there are zero open positions and zero final entries.

This is not an economic-tuning problem and not a P1.1AN calibration problem yet.

---

## Key Evidence

From the audit:

```text
PAPER_TRAIN_ENTRY_REAL:       0
PAPER_TRAIN_QUALITY_ENTRY:    0
PAPER_EXIT_TRAINING_BUCKET:   0
LM_STATE_AFTER_UPDATE:        0

COST_EDGE_BYPASS_FLOW_CANDIDATE: 9
COST_EDGE_BYPASS_FLOW_DROP:      8
sampler_rate_cap:                8
PAPER_SAMPLER_RATE_CAP_STATE:    8
```

Rate-cap state logs show:

```text
recent_entries=3
rate_limit=3
next_allowed_s=47.4 / 47.0 / 46.9 / ...
open_symbol=0
open_bucket=0
open_total=0
closed_training=0
mode=paper_train
```

This means the rate-cap itself is active and internally consistent, but it is counting something that is not a completed paper-training entry.

The strongest contradiction:

```text
recent_entries=3
rate_limit=3
PAPER_TRAIN_ENTRY_REAL=0
open_total=0
closed_training=0
```

So the cap is probably fed by **attempts / reservations / accepted candidates**, not by successful final entries.

There is also an accepted-to-attempt trace:

```text
[COST_EDGE_BYPASS_ACCEPTED] ... flow_id=ETHUSDT:SELL:C_WEAK_EV_TRAIN:1779092553
[PAPER_ENTRY_ATTEMPT] ... flow_id=ETHUSDT:SELL:C_WEAK_EV_TRAIN:1779092553
[PAPER_ENTRY_ATTEMPT] symbol=ETHUSDT bucket=C_WEAK_EV_TRAIN price=2121.77890575
```

But still:

```text
Final entries: 0
PAPER_TRAIN_ENTRY_REAL: 0
PAPER_TRAIN_QUALITY_ENTRY: 0
```

That points to one of two narrow causes:

1. Rate-cap timestamps are recorded before final entry creation and are never rolled back if entry fails.
2. Entry creation fails after attempt without emitting a final `[PAPER_ENTRY_BLOCKED]` / `[PAPER_ENTRY_DROPPED_AFTER_ACCEPT]` / `[PAPER_TRAIN_ENTRY]`.

---

## Decision

**P1.1AN remains blocked.**

```text
TUNE_ALLOWED: NO
reason: no valid closed training sample flow
closed_training_trades: 0 in current window
```

**No economic tuning. No TP/SL tuning. No cost-edge tuning. No strategy tuning.**

---

## Patch Freeze Rule

Allowed next work is only one surgical bugfix, not another diagnostics expansion.

```text
NO P1.1AT diagnostics expansion.
NO new attribution features.
NO new dashboards.
NO new sampler policy changes.
ONLY fix the reservation/entry-finalization bug proven by P1.1AS.
```

---

## Minimal P1.1AT Scope, If Implemented

Name it something like:

```text
P1.1AT — Paper Sampler Rate-Cap Reservation Fix
```

### Goal

Ensure rate-cap accounting is based on **successful paper-training entries**, not candidates, accepted probes, or entry attempts.

### Required behavior

A candidate may go through:

```text
candidate → accepted → attempt
```

But the sampler rate-cap timestamp must be committed only after:

```text
[PAPER_TRAIN_ENTRY]
```

or after the actual in-memory/open-position object is successfully created.

If the entry attempt fails after acceptance, it must not consume the rate-cap slot.

### Required logs

Keep this minimal:

```text
[PAPER_ENTRY_COMMIT] flow_id=<id> symbol=<sym> bucket=C_WEAK_EV_TRAIN rate_slot_committed=True
```

Only emit it after a real entry exists.

If an accepted attempt fails before entry creation, emit one explicit blocker:

```text
[PAPER_ENTRY_ABORTED_AFTER_ATTEMPT] flow_id=<id> symbol=<sym> reason=<reason> rate_slot_committed=False
```

Do not add more diagnostic categories unless needed for this exact path.

---

## Acceptance Criteria

After deploying the fix and running:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

one of these must be true:

### PASS A — Flow restored

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_SAMPLER_RATE_CAP_STATE recent_entries <= actual committed entries in window
```

### PASS B — Legitimate cap

```text
PAPER_TRAIN_ENTRY_REAL > 0
recent_entries=3
rate_limit=3
next_allowed_s decreases normally
```

### FAIL — Still blocked

```text
PAPER_TRAIN_ENTRY_REAL = 0
recent_entries=3
open_total=0
closed_training=0
```

If FAIL remains, stop and inspect the exact function that writes the rate-cap timestamp list.

---

## Claude/Codex Implementation Prompt

```text
You are working in CryptoMaster. Do not change trading strategy, EV calculation, TP/SL geometry, live/real behavior, or attribution logic.

Current production audit at HEAD d7d7850 proves:
- PAPER_TRAIN_ENTRY_REAL=0
- PAPER_TRAIN_QUALITY_ENTRY=0
- sampler_rate_cap drops >0
- PAPER_SAMPLER_RATE_CAP_STATE logs exist
- state shows recent_entries=3, rate_limit=3, next_allowed_s>0
- open_symbol=0, open_bucket=0, open_total=0, closed_training=0
- accepted/attempt logs exist for at least one flow_id, but no final PAPER_TRAIN_ENTRY follows

Task:
Implement P1.1AT as a surgical fix so the paper-training sampler rate-cap commits a timestamp only after a real paper training entry is successfully created.

Constraints:
1. paper_train + training sampler only.
2. No live/real behavior changes.
3. Do not tune economic thresholds.
4. Do not change TP/SL.
5. Do not add broad diagnostics.
6. Do not count candidate, accepted, or attempt as a rate-cap entry.
7. If entry creation fails after acceptance, do not consume a rate slot.
8. Add at most two logs:
   - [PAPER_ENTRY_COMMIT] only after final entry exists
   - [PAPER_ENTRY_ABORTED_AFTER_ATTEMPT] only when accepted/attempted but no entry is created

Implementation steps:
1. Find where sampler rate-cap timestamps/recent_entries are appended.
2. Move/guard the append so it happens only after successful PAPER_TRAIN_ENTRY/open-position creation.
3. Ensure rollback/removal if a downstream exception or duplicate/drop prevents final entry.
4. Keep existing flow_id propagation.
5. Add regression tests proving:
   - candidate rejected before final entry does not increment rate cap
   - accepted but aborted attempt does not increment rate cap
   - successful PAPER_TRAIN_ENTRY increments rate cap exactly once
   - live/real modes unchanged
   - existing P1.1AO–P1.1AS diagnostics still pass
6. Run:
   python -m pytest tests/test_paper_mode.py -q
   bash -n scripts/p11ag_quality_audit.sh
   bash -n scripts/p11as_sampler_state_check.sh

Output:
- changed files
- test results
- exact confirmation that rate-cap timestamps are committed only after successful PAPER_TRAIN_ENTRY
```

---

## Operator Note

This is the last acceptable patch before sample collection. After this fix, stop patching and let the bot collect at least 10 closed training trades before returning to P1.1AN.
