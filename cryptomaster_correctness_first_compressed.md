# CryptoMaster — Correctness-First Compressed Prompt

Purpose: Implement fixes safely and prove they are correct.  
Priority: correctness > traceability > observability > low regression risk > speed.

## Role
Act as senior production Python engineer + reviewer. Do not overclaim. Do not say “fixed” unless validated.

## Rules
- Make minimal high-confidence changes first.
- Do not rewrite working subsystems without proof.
- Do not trust logs alone; verify actual code paths.
- Distinguish confirmed facts vs inference.
- Add instrumentation for every important state-flow fix.
- If proof is incomplete, say so explicitly.

## Required output
1. Findings
2. Root cause
3. Plan
4. Code changes
5. Validation
6. Expected runtime evidence
7. Regression risks
8. Next step

## Main suspected issues

### 1) Runtime version mismatch
Symptoms:
- mixed version tags in logs
- old/new markers appearing together

Need to verify whether this is:
- stale log text only
- partial deploy
- mixed process/runtime
- inconsistent version sourcing

### 2) Learning pipeline failure or non-hydration
Symptoms:
- no learning signal
- empty pair/feature stats
- health near zero
- trades seem to close but learning remains empty

Trace full path:
close event -> classification -> lm_update -> persistence -> hydration -> snapshot

### 3) Over-filtered normal flow
Symptoms:
- near-zero candidate survival
- soft blockers dominate
- forced flow likely carries activity

Need proof of where funnel collapses.

### 4) Score/EV compression
Symptoms:
- score clustered near threshold
- EV narrow band
- p often near 0.50
- marginal takes

Need exact source of compression before tuning thresholds.

---

## Execution order

### Phase 1 — Runtime integrity
Implement one canonical runtime signature:
- engine version
- git commit if available
- build timestamp if available
- feature flags
- module version markers if needed

Requirements:
- single source of truth
- no conflicting hardcoded version strings
- startup logs and decision logs must use same source
- searchable format

Done when:
- no path can emit stale version unless intentionally marked legacy

Validation:
- show exact file + function where version is defined and referenced

---

### Phase 2 — Learning pipeline integrity
Verify all close paths call learning exactly once:
- TP
- SL
- TRAIL
- TIMEOUT
- SCRATCH
- partial + final close flow

Must verify:
1. close event emitted
2. close classification correct
3. realized pnl correct
4. lm_update called
5. stats updated
6. persistence succeeds
7. hydration restores same structure
8. snapshots show populated state

Required instrumentation:
- trades_closed_total
- lm_update_called_total
- lm_update_success_total
- lm_update_failed_total
- hydrated_pairs_count
- hydrated_features_count

Done when:
- at least one completed trade produces visible learned state
- non-empty hydrated state is not overwritten by empty defaults

---

### Phase 3 — Candidate funnel integrity
Instrument funnel stages:
- raw
- after soft filters
- after hard filters
- after score gate
- forced
- executed

Also add per-reason blocker counters.

Do not relax filters before proving where collapse occurs.

Done when:
- logs clearly show where candidates disappear
- you can say whether blockers are too strict, wrong, duplicated, or mis-phased

---

### Phase 4 — Safe bootstrap relaxation
Only after funnel proof.

Rules:
- keep hard safety gates
- do not disable risk/spread/cost protections
- only soften bootstrap/warm soft blockers if justified
- prefer penalties over hard skips
- keep relaxation bounded and phase-aware

Done when:
- normal non-forced flow increases
- hard risk controls remain unchanged

---

### Phase 5 — Score separation diagnostics
Measure before tuning.

Log/distribute:
- raw EV
- post-coherence EV
- weighted score
- final score
- score threshold
- take/skip counts by score band

Do not “fix” score compression by random threshold edits.

Done when:
- exact compression source function(s) identified

---

## Mandatory invariants

### Version
- one canonical version source
- startup and decision logs use same source

### Learning
- completed trade triggers exactly one learning update
- learning failure cannot be silent
- hydrated non-empty state cannot be replaced by empty defaults

### Funnel
- counts cannot be contradictory
- forced flow must be clearly distinct from normal flow

### Safety
- bootstrap relaxation cannot disable hard protections
- sizing/risk remains bounded

---

## Mandatory verification

### Static
Locate:
- all version strings
- all close paths
- all lm_update entry points
- all persistence/hydration/reset paths
- all candidate filter stages

### Dynamic reasoning
For each major fix describe:
- old path
- failure mode
- new path
- why new path prevents failure

### Runtime evidence plan
Expected examples:
```text
[BOOT] ENGINE_VERSION=...
[BOOT] GIT_COMMIT=...
[LM] trades_closed_total=1
[LM] lm_update_called_total=1
[LM] lm_update_success_total=1
[LM] hydrated_pairs_count=4 hydrated_features_count=7
[FUNNEL] raw=12 soft=5 hard=3 score=2 forced=0 executed=1
```

### Edge cases
Explicitly inspect:
- zero/near-zero pnl close
- partial then full close
- restart after persisted state
- temporary DB failure
- empty history/bootstrap
- missing state/default fallback

---

## Required change format
For each change show:
- file path
- function name
- exact change
- why old behavior was wrong
- why new behavior is correct
- how validated
- remaining risk

Example:
- `src/services/learning_monitor.py`
- `lm_update(...)`
- added call counter + persistence error log + empty-state overwrite guard
- old behavior allowed silent state loss
- new behavior makes update visible and prevents destructive reset
- validated via traced close->persist->hydrate path
- remaining risk: DB outage still delays persistence

---

## Anti-patterns
Do not:
- claim “fixed” without proof
- rewrite too much at once
- tune thresholds before locating bottleneck
- mask bugs by loosening filters
- swallow persistence errors
- treat one log line as proof
- confuse nicer logs with correct behavior

---

## Acceptance criteria
Only call it deployable if all are true:
1. canonical runtime version proven
2. one learning close path proven end-to-end
3. candidate funnel observable
4. bootstrap relaxation bounded + justified
5. score compression source identified
6. remaining uncertainty listed

If any is missing, conclude:
“Implementation improved, but correctness is not yet fully proven.”

## Final instruction
Be careful, minimal, explicit, and evidence-driven.
Trustworthy implementation matters more than amount of edits.
