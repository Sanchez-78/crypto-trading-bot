# CryptoMaster P1.1AP-O2 — Restore Continuous PAPER Trading & Learning From Starvation
## Implementation prompt for Claude Code — urgent PAPER-only recovery
**Date:** 2026-05-26  
**Runtime evidence:** active Hetzner service `/opt/cryptomaster`, HEAD `b6311c2113f9a6d5e8e0bb1ae317326a489d2911` (`P1.1AP-O1A1G`), PID `1448746` at evidence collection time  
**Mode:** PAPER only. REAL/live trading remains forbidden.

---

# 0. Executive correction

Stop waiting for persistence proof as the primary next step. Persistence cannot be proven naturally while no new eligible PAPER trade closes.

The live blocker is now proven by runtime logs:

```text
on_price(...): Generated valid signal BUY
[V10.13w DECISION] ... ev_final < 0 ... REJECT (NEGATIVE_EV)
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN
[WATCHDOG] No trades for 600s → boosting exploration
[WATCHDOG] Critical idle (15min) → enabling micro-trades
Positions: 0
LEARNING: health=0.0000 [BAD]
```

Meaning:

```text
valid raw signals exist
→ legacy/historical EV makes them negative
→ hard REJECT_NEGATIVE_EV fires
→ paper exploration does not map this reject into any learning admission bucket
→ watchdog cannot open trades
→ no new PAPER close
→ no new learning update
→ persistence proof waits forever
```

This task must restore a controlled, real PAPER trade flow and learning loop **without treating legacy-negative EV as verified positive edge**.

---

# 1. Current safety context — preserve

Already confirmed:

- Runtime actively runs PAPER mode; do not alter REAL/live behavior.
- `D_NEG_EV_CONTROL` isolation worked in reviewed logs; it emitted `PAPER_LEARNING_SHADOW_SKIP` and did not enter canonical updates.
- Permission remediation created:
  `server_local_backups/paper_adaptive_learning_state.json`
  owned by `cryptomaster:cryptomaster`, mode `600`, initial `{}`.
- Persistence has not yet been proven because no post-fix canonical learning close occurred.
- Existing execution truth is not Futures-qualified:
  runtime uses Binance Spot `stream.binance.com:9443` order-book data for execution quality/fill/slippage/exit paths while outcomes represent USDⓈ-M Futures.
- Therefore all new outcomes produced before market-source correction must be tagged:
  `execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED`
  and must **not** qualify future Futures readiness.

---

# 2. Objective

Implement a narrow PAPER-only starvation recovery path in the existing integrated bot lifecycle:

```text
valid raw signal
→ legacy RDE rejects REJECT_NEGATIVE_EV
→ if sustained PAPER starvation and strict safety gates pass:
     open a bounded PAPER discovery position
→ close through existing PAPER executor
→ update a dedicated active PAPER discovery learner/metrics
→ persist its state using the now-writable state file
→ adapt subsequent PAPER discovery sampling based on observed outcomes
```

This is not REAL readiness and not a declaration of positive edge. It is the minimum mechanism needed for the bot to trade nanečisto and learn from new observations rather than remain permanently deadlocked by historical negative EV.

---

# 3. Work environment and deploy discipline

## Before coding

1. Determine where Claude is running.
2. If working directly inside active server checkout `/opt/cryptomaster`, **do not edit it in place while the service is running**. Create/use a separate development worktree or work from the normal development repository synchronized to `origin/main` at `b6311c2`.
3. Do not restart or stop the production service during investigation or implementation.
4. Do not overwrite the newly created runtime adaptive state file.
5. Do not deploy automatically. Finish with patch/test report and an explicit deployment recommendation.

## Initial evidence capture — read-only on production if accessible

```bash
cd /opt/cryptomaster
systemctl show cryptomaster.service -p ActiveState -p MainPID -p ActiveEnterTimestamp --no-pager
git rev-parse HEAD
journalctl -u cryptomaster.service --since "2026-05-26 07:00:00" --no-pager \
 | grep -E 'Generated valid signal|REJECT_NEGATIVE_EV|PAPER_EXPLORE_SKIP|PAPER_TRAIN_ENTRY|PAPER_LEARNING_ENTRY|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_STATE_SAVE|WATCHDOG|Positions:' \
 | tail -200
```

---

# 4. Required code precheck — find the dead routing path

Before editing, trace exact implementation points:

```bash
rg -n "REJECT_NEGATIVE_EV|negative_ev|PAPER_EXPLORE_SKIP|no_bucket_matched|D_NEG_EV_CONTROL|paper_adaptive_recovery|PAPER_ADAPTIVE|PAPER_LEARNING_ENTRY|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|STARVATION|WATCHDOG|cost_edge" src tests
```

Report before patch:

| Question | Evidence from source |
|---|---|
| Where does RDE create `REJECT_NEGATIVE_EV`? | file:line/function |
| Where is reject routed into paper exploration? | file:line/function |
| Why does `REJECT_NEGATIVE_EV` produce `no_bucket_matched`? | exact conditional |
| What existing path opens `paper_adaptive_recovery` entries? | file:line/function |
| What path updates adaptive learning state on close? | file:line/function |
| What guard preserves `D_NEG_EV_CONTROL` shadow-only isolation? | file:line/function |
| What existing rate/open-position caps can be reused? | file:line/function |

Do not guess names or patch until this table is complete.

---

# 5. Required design: one integrated PAPER discovery recovery, not a second bot

## 5.1 New route semantics

Add a new PAPER-only admission purpose, using existing executor and persistence path:

```text
learning_source = paper_starvation_discovery
evaluation_role = DISCOVERY
readiness_eligible = false
execution_truth_class = LEGACY_SPOT_EXECUTION_UNVERIFIED
source_reject = REJECT_NEGATIVE_EV
```

Name may be adapted to existing enum/schema conventions, but meaning must remain explicit.

This must **not** be mapped to `D_NEG_EV_CONTROL`; D_NEG remains diagnostic shadow-only. The new route exists because the legacy EV is a historical/current-policy veto, not proof that a newly sampled hypothesis has no value.

## 5.2 Trigger conditions

Allow a PAPER discovery admission only when all conditions are true:

```text
mode is PAPER / paper_train only
REAL/live execution path is unreachable
raw signal is valid and contains side/symbol/entry context
original decision is REJECT_NEGATIVE_EV
reject is not NO_CANDIDATE_PATTERN and not missing-side
no valid eligible PAPER entry has opened for >= 600 seconds
a sustained stream of valid negative-EV signal candidates exists during starvation
market/integrity guard is healthy under existing checks
position/open caps allow entry
candidate is not quarantined, duplicate, stale, or test-generated
```

Do not require legacy `ev_final > 0` for this DISCOVERY route; that condition is precisely what is causing starvation.

## 5.3 Caps

Reuse existing tested PAPER sampler cap infrastructure where possible. Add no broad uncapped exploration.

Initial caps for this discovery route:

```text
max_open_per_symbol = 1
max_open_global = 2
max_new_entries = 4 per 15 minutes
hold/TP/SL path = existing safe PAPER training geometry only
```

If existing cap constants are already stricter and produce a viable minimum of at least one close per 10–15 minutes during continuous valid signals, prefer reuse. Report exact chosen caps.

## 5.4 Economic meaning

A discovery entry must never claim verified edge:

```text
readiness_eligible = false
qualifies_real = false
qualification_reason = LEGACY_SPOT_EXECUTION_UNVERIFIED_DISCOVERY
```

But it must be allowed to update **active PAPER discovery metrics** after a normal close, because the project requirement is continuous paper learning and later adaptation.

The update must be explicitly separate from:

- REAL readiness;
- historical comparator;
- `D_NEG_EV_CONTROL`;
- quarantined/stale/test-generated outcomes.

## 5.5 Adaptive feedback after close

Do not merely create trades. On each eligible discovery close:

- record net outcome, MFE/MAE, exit reason and segment `(symbol, regime, side)`;
- emit a discovery learning update;
- persist state via the adaptive state path;
- update future PAPER discovery selection or quota based on discovery outcomes.

Minimum safe adaptation:
- continue bootstrap collection while sample count is low;
- once a discovery segment has enough direct losses under the existing adaptive policy's supported threshold, reduce or suspend that specific segment, not the entire service;
- do not loosen thresholds globally or convert negative outcomes into positive edge.

Use existing `paper_adaptive_learning` architecture if it already supports segment policy; extend it minimally rather than building a second truth store.

---

# 6. Required logs

Logs must prove actual entry success, not only admission attempts.

Add/ensure:

```text
[PAPER_STARVATION_DISCOVERY_STATE]
active=true idle_s=... valid_negative_candidates_window=...
open_global=... open_symbol=... cap_reason=...

[PAPER_STARVATION_DISCOVERY_OPEN]
trade_id=... symbol=... side=... regime=...
source_reject=REJECT_NEGATIVE_EV
learning_source=paper_starvation_discovery
evaluation_role=DISCOVERY
execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED
readiness_eligible=false

[PAPER_STARVATION_DISCOVERY_CLOSE]
trade_id=... outcome=... net_pnl_pct=... mfe_pct=... mae_pct=... exit_reason=...

[PAPER_DISCOVERY_LEARNING_UPDATE]
trade_id=... segment=... lifetime_n=... rolling20_n=...
rolling20_expectancy=... policy_action=...
persist_requested=true
readiness_eligible=false
```

**Critical:** entry log must be emitted only after an actual PAPER position with real `trade_id` was successfully created, not before a max-open/rate-cap rejection.

Persistence proof after deployment should be observable naturally:

```text
new PAPER_DISCOVERY_LEARNING_UPDATE
AND no PAPER_LEARNING_STATE_SAVE failed
AND server_local_backups/paper_adaptive_learning_state.json becomes valid non-empty JSON
```

---

# 7. Preserve existing invariants

Hard requirements:

```text
- D_NEG_EV_CONTROL remains shadow-only; no canonical/discovery adaptive update for D_NEG.
- Quarantined/stale positions never learn.
- Duplicate close never learns twice.
- No REAL/live path modification.
- No source uses state file creation as a reason to restart service before persistence proof.
- No readiness approval from LEGACY_SPOT_EXECUTION_UNVERIFIED outcomes.
- No broad change to TP/SL, execution quality, thresholds, Firebase or Android contract.
- Do not fix Spot→Futures market source in this same patch; only preserve trust labels and isolate readiness.
```

---

# 8. Tests required

Add direct tests for:

1. Under PAPER starvation, valid `REJECT_NEGATIVE_EV` candidate routes to `paper_starvation_discovery`.
2. Same candidate does not route when mode is REAL/live.
3. Same candidate does not route without valid side/raw signal context.
4. Same candidate does not route when starvation idle threshold is not met.
5. Same candidate respects max-open-per-symbol, max-open-global and rate caps.
6. Actual successful open logs `PAPER_STARVATION_DISCOVERY_OPEN` only after position creation and includes `trade_id`.
7. Blocked admission does not falsely log successful open.
8. Discovery trade close updates discovery adaptive metrics and requests persistence.
9. Discovery outcomes have `readiness_eligible=false` and `execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED`.
10. D_NEG close remains `PAPER_LEARNING_SHADOW_SKIP` only and never updates discovery/canonical metrics.
11. Quarantined/stale/duplicate closes cannot update discovery learning.
12. Existing positive `paper_adaptive_recovery` path remains unchanged.
13. State persistence path is not changed and tests redirect it to temporary paths only.
14. No test creates/modifies production runtime state files.

Run targeted tests plus the established server-safe suite used for current main. Print test state-file hash/absence proof before and after suite.

---

# 9. Runtime validation plan after review/deploy
## Do not execute deployment automatically in this task

After tests PASS and separate operator-approved deployment/restart:

Expected within runtime while valid signals continue:

```text
REJECT_NEGATIVE_EV candidates continue to be logged
BUT during starvation:
  PAPER_STARVATION_DISCOVERY_OPEN appears with actual trade_id
  PAPER_EXIT / PAPER_STARVATION_DISCOVERY_CLOSE appears after normal timeout/TP/SL
  PAPER_DISCOVERY_LEARNING_UPDATE appears
  adaptive state JSON becomes non-empty and no Permission denied recurs
```

Acceptance window:

```text
- at least 1 actual discovery PAPER open and close
- at least 1 discovery learning update
- no D_NEG contamination
- no quarantine/traceback/unbound error
- no REAL execution
- state file non-empty after natural learning close
```

Do not evaluate profitability from the first few samples; objective is restoring truthful PAPER feedback flow.

---

# 10. Required final Claude report

```markdown
# P1.1AP-O2 Restore PAPER Flow Implementation Report

## Verdict
PASS_READY_FOR_REVIEWED_DEPLOY | FAIL | BLOCKED_NEEDS_DECISION

## Pre-patch root cause proof
| Runtime symptom | Source condition causing it | Evidence |

## Changed files
| File | Change | Why narrow |

## New route semantics
- learning_source:
- evaluation_role:
- execution_truth_class:
- readiness_eligible:
- trigger conditions:
- caps:

## Safety invariants
| Invariant | PASS/FAIL | Test/evidence |
| D_NEG shadow isolation | ... | ... |
| No REAL changes | ... | ... |
| No readiness contamination | ... | ... |
| Persistence path test isolation | ... | ... |

## Tests
- Targeted:
- Full server-safe:
- Runtime-state path before/after proof:

## Deployment plan
- Do not auto-deploy/restart.
- Exact operator-approved next steps:
- Expected validation log patterns:
```

---

# Stop conditions

Stop and report without deploying if:

```text
- Fix would require REAL/live changes.
- Discovery route cannot be separated from D_NEG/control/readiness metrics.
- Tests touch runtime state.
- Existing state/persistence is overwritten or reset.
- Patch requires bundling Spot→Futures market-source rewrite.
- Full server-safe suite fails.
```
