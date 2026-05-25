# CLAUDE CODE — P1.1AP-O1: Connect Adaptive Rolling Policy to PAPER Decisions Without Fabricating Edge

## Mission

Implement the next missing link in the **one integrated PAPER → learning → qualification workflow**:

```text
eligible PAPER close
→ adaptive rolling/segment metrics update
→ those metrics are READ by subsequent PAPER-only candidate selection/policy
→ learning changes future PAPER behavior
```

N2C already proved that a recovery PAPER trade can open, close, retain `learning_source=paper_adaptive_recovery`, and update canonical adaptive metrics. Do not reopen N2C metadata work.

This patch is needed because read-only precheck found:

```text
paper_adaptive_learning writes metrics and logs updates
but realtime_decision_engine has zero reads/imports of paper_adaptive_learning
and PAPER decisions continue to use old canonical PF=0.495 / econ_status=BAD.
```

## Critical boundary: do not invent profitable candidates

Current logs also show a genuine proposal drought:

```text
Last 6 hours: overwhelmingly REJECT_NEGATIVE_EV
Heartbeat: total=26208, neg_ev=26172 (~99.86%), weak_ev=35 (~0.13%)
```

Therefore:

```text
O1 must NOT convert EV <= 0 into canonical learning trades.
O1 must NOT flip a negative EV to positive.
O1 must NOT weaken live/real gates.
O1 can influence only PAPER-only handling/prioritization of candidates that are already structurally valid and have EV > 0,
plus bounded PAPER exploration policy where existing code already permits sampling.
```

If source inspection proves adaptive state cannot meaningfully affect any future PAPER decision without redesigning signal/EV generation, stop and report that instead of implementing a misleading no-op patch.

---

# Accepted baseline and evidence

Current expected HEAD:

```text
956a12e P1.1AP-N2C: Fix recovery metadata wiring in actual paper open path
```

Verified full-suite baseline:

```text
912 passed in 3.95s, 0 failures, 0 warnings
```

## N2C acceptance is complete

Proven recovery lifecycle:

```text
[PAPER_TRAIN_QUALITY_ENTRY]
trade_id=paper_28427715e648
symbol=ADAUSDT side=BUY
source=paper_adaptive_recovery
regime=RANGING ev=0.0300
expected_move_src=atr_abs_price_normalized
cost_edge_ok=False

[PAPER_EXIT]
trade_id=paper_28427715e648
outcome=LOSS net_pnl_pct=-0.1388

[PAPER_CANONICAL_LEARNING_UPDATE]
trade_id=paper_28427715e648
learning_source=paper_adaptive_recovery
rolling20_n=20 rolling20_pf=0.000 rolling20_expectancy=-0.235995
rolling50_n=50 rolling50_pf=1.269 rolling50_expectancy=0.076296
rolling100_n=99 rolling100_pf=1.764 rolling100_expectancy=0.224540
segment=ADAUSDT:RANGING:BUY policy_action=continue_learning
```

Do not modify recovery metadata mechanics except if strictly necessary to consume existing state.

## D_NEG safety is proven and non-negotiable

Audit shows:

```text
PAPER_LEARNING_SHADOW_SKIP = 17
D_NEG canonical updates = 0
```

Do not allow `D_NEG_EV_CONTROL` into adaptive/canonical learning or use it for readiness.

## Current starvation evidence

```text
PAPER_TRAIN_QUALITY_ENTRY              20
source=paper_adaptive_recovery          2   # entry/update log occurrences for one lifecycle
PAPER_CANONICAL_LEARNING_UPDATE         1
PAPER_POLICY_ADAPTATION                 0
REAL_READINESS_CHECK                    0
PAPER_LEARNING_ENTRY_BLOCKED            0
PAPER_ENTRY_BLOCKED                     1
SELF_HEAL: STALL                     2945
WATCHDOG                             6033
```

This proves:
- capacity is not the currently demonstrated blocker;
- useful adaptive closes are far too rare;
- adaptive metrics have not yet changed subsequent decisions.

---

# Required pre-edit inspection

Before changing code, run:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -12

grep -R "paper_adaptive_learning\|get_learner\|record_close\|PAPER_CANONICAL_LEARNING_UPDATE\|PAPER_POLICY_ADAPTATION\|REAL_READINESS_CHECK\|rolling20\|rolling50\|rolling100\|lifecycle" -n src/services tests | head -1000

grep -R "def _get_econ_bad_state\|lm_economic_health\|_econ_bad_entry_quality_gate\|REJECT_NEGATIVE_EV\|REJECT_ECON_BAD_ENTRY\|maybe_open_training_sample\|paper_adaptive_recovery\|cost_edge_too_low" -n src/services tests | head -1200

grep -R "PAPER_MODE\|paper_train\|trade_environment\|execution_mode\|LIVE\|REAL\|ENABLE_REAL" -n src/services start.py main.py tests | head -800
```

Write an implementation note before coding:

```text
A. File:function:lines that write adaptive rolling/segment state.
B. File:function:lines that currently read economic health/PF for PAPER candidate routing.
C. Whether adaptive rolling/segment state is currently read anywhere in decision flow.
D. Where a bounded PAPER-only adaptive-policy read can affect a valid EV>0 candidate.
E. Whether any proposed change would touch raw/final EV generation or live/real routing; if yes, do not implement it.
F. Proven origin/provenance of adaptive lifetime_n=99 / rolling100_n=99, or why readiness must remain locked.
```

---

# Core implementation

## 1. Expose a safe read-only adaptive policy snapshot API

In `src/services/paper_adaptive_learning.py`, reuse existing learner state and add a minimal read API if missing, for example:

```python
get_paper_policy_snapshot(
    symbol: str | None = None,
    regime: str | None = None,
    side: str | None = None,
) -> dict
```

It must return safe defaults if state is absent/corrupt and include only values needed for PAPER decisioning:

```text
lifecycle
lifetime_n / lifetime_pf / lifetime_expectancy
rolling20_n / rolling20_pf / rolling20_expectancy
rolling50_n / rolling50_pf / rolling50_expectancy
rolling100_n / rolling100_pf / rolling100_expectancy
segment key / segment_n / segment_pf / segment_expectancy / segment_weight
unresolved_anomalies count
qualification evidence/provenance status
```

This is a read of the same canonical adaptive state, not a second learner.

Required log only when used in an admission decision, rate-limited:

```text
[PAPER_ADAPTIVE_POLICY_READ]
symbol=... regime=... side=...
rolling20_n=... rolling20_pf=... rolling50_n=... rolling50_pf=...
segment=... segment_n=... segment_weight=...
action=...
```

## 2. PAPER-only decision integration

Connect the adaptive snapshot only in the existing PAPER-training/adaptive-recovery route, ideally in `paper_training_sampler.py` or the narrow PAPER handoff, not in shared live/real EV scoring.

### Required rules

For structurally valid PAPER candidates with `EV > 0`:

```text
A. If rolling/segment sample is insufficient:
   action=collect_bootstrap
   allow existing N2C adaptive recovery behavior under existing caps.

B. If segment_n >= 20 and segment_pf < 0.80 and segment_expectancy < 0:
   bounded downweight/suppress only that PAPER segment;
   action=downweight_losing_segment.

C. If segment_n >= 20 and segment_pf > 1.10 and segment_expectancy > 0:
   bounded preference for that PAPER segment within existing caps;
   action=prefer_improving_segment.

D. If rolling20 evidence is bad while rolling50/100 appears positive:
   do not mark ready; continue carefully bounded PAPER collection.
```

Allowed influence:

```text
- PAPER candidate priority/weight;
- whether an EV>0 adaptive recovery sample is sampled within existing caps;
- logging of policy action.
```

Forbidden influence:

```text
- no EV<=0 candidate may become eligible canonical learning;
- no mutation of raw_ev/final_ev to bypass NEGATIVE_EV;
- no changes to ECON_BAD or cost-edge numeric thresholds;
- no changes to live/real routing;
- no TP/SL/timeout tuning;
- no D_NEG admission to learner.
```

Use existing bounded weights if they already exist. If one minimal multiplier is needed:

```text
min_weight >= 0.25
max_weight <= 2.00
no hard ban before segment_n >= 30
```

Required log when a future PAPER decision is changed by learned state:

```text
[PAPER_POLICY_ADAPTATION]
segment=...
n=...
pf=...
expectancy=...
old_weight=...
new_weight=...
action=collect_bootstrap|downweight_losing_segment|prefer_improving_segment|continue_learning
reason=post_cost_rolling_learning
candidate_ev=...
mode=PAPER
```

## 3. Do not misrepresent starvation

Because current drought is overwhelmingly `REJECT_NEGATIVE_EV`, add or reuse a rate-limited PAPER lifecycle status log showing why adaptive policy cannot act:

```text
[PAPER_ADAPTIVE_STARVATION]
window_s=...
positive_candidates=...
negative_ev_rejects=...
admitted_recovery=...
canonical_closes=...
reason=no_positive_ev_candidates|losing_segments_downweighted|caps|awaiting_samples
```

This is diagnostics necessary to distinguish:
- fixed adaptive integration but no positive candidate supply;
- a real PAPER policy gate blocker.

Do not change negative-EV routing merely to avoid this log.

## 4. Hard-lock REAL_READY until qualification provenance is safe

Current adaptive update reported:

```text
rolling100_n=99 / lifetime_n=99
```

while current PID showed only one canonical recovery update. Unless provenance inspection proves these 99 rows are valid post-integrated eligible PAPER closes under the required qualification epoch, they must **not** be allowed to satisfy REAL_READY.

Implement the minimal safety guard inside existing readiness check:

```text
REAL_READY remains False unless:
- qualification sample count is explicitly proven to be post-integrated eligible PAPER closes;
- count >= 100;
- all existing PF/expectancy/net/drawdown/concentration/stability gates pass.
```

Do not delete adaptive history. It may still guide bounded PAPER collection if it is eligible state; it must not silently unlock real trading without provenance.

Required log:

```text
[REAL_READINESS_CHECK]
eligible=False
reason=qualification_provenance_unverified|insufficient_post_integration_samples|...
rolling100_n=...
qualification_n=...
operator_unlock_required=True
```

If implementing a persisted qualification baseline is necessary, keep it inside existing adaptive state and do not create a parallel learner.

## 5. Keep old PF/BAD for audit, not as the sole PAPER recovery controller

Do not overwrite or erase:

```text
canonical PF=0.495 / BAD
historical dashboard 100-trade baseline
```

For PAPER-only adaptive recovery decisions, read both:

```text
historical_health=BAD
adaptive_policy_snapshot=<rolling/segment state>
```

and log both in the PAPER decision path.

The historical BAD status may remain an audit/risk context; it must no longer be the only state determining whether ongoing PAPER learning can adapt.

No live/real semantics may be changed.

---

# Scope boundaries

Likely permitted after inspection:

```text
src/services/paper_adaptive_learning.py
src/services/paper_training_sampler.py
src/services/realtime_decision_engine.py only if strictly PAPER-path wiring requires it and live/real branches are explicitly guarded
tests/test_paper_adaptive_learning.py
tests/test_p11ap_n2_recovery_admission.py
a new directly-related O1 test file if necessary
```

Do not modify:

```text
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android/dashboard contracts
data/research/*
phase2b_firebase_probe.py
runtime state/log files/backups
TP/SL/timeout geometry
cost-edge or ECON_BAD numeric thresholds
live/real order path
D_NEG learning isolation
```

---

# Tests required

## Read integration

1. Adaptive policy snapshot returns rolling/segment state safely.
2. Missing/corrupt state returns safe collection defaults.
3. PAPER adaptive recovery route actually reads snapshot.
4. Live/real route never reads/applies PAPER adaptive policy.

## Decision impact

5. Valid EV>0 PAPER candidate with insufficient sample remains collectable under existing caps.
6. EV<=0 candidate remains rejected even if segment metrics are excellent.
7. Losing segment with `n>=20`, `pf<0.80`, `expectancy<0` is bounded downweighted in PAPER.
8. Improving segment with `n>=20`, `pf>1.10`, `expectancy>0` is bounded preferred in PAPER.
9. Policy action emits `PAPER_POLICY_ADAPTATION`.
10. Same candidate behaves differently before versus after adaptive metric update, proving learning affects a subsequent PAPER decision.

## Safety/readiness

11. D_NEG remains shadow-only and never changes adaptive policy/readiness.
12. Quarantined/invalid closes remain excluded.
13. Historical PF/BAD remains preserved for audit.
14. Unproven `rolling100_n=99` cannot produce REAL_READY.
15. REAL_READY still requires explicit operator unlock and cannot submit real orders.
16. Negative-EV drought emits truthful starvation diagnostic, not new canonical trades.

## Regression

17. N/N1/N2/N2A/N2B/N2C recovery lifecycle tests pass.
18. I/I2 D_NEG tests pass.
19. J/J2 and K tests pass.
20. Full server-safe suite passes with no failures or warnings.

Run:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py \
  <new O1 tests if created>

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_o1_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1_fullsuite.txt || true
tail -30 /tmp/p11ap_o1_fullsuite.txt
```

Baseline:

```text
P1.1AP-N2C: 912 passed in 3.95s, 0 failures, 0 warnings
```

Required:

```text
>=912 passed plus new tests, 0 failures, 0 warnings
```

---

# Commit/deploy

Do not create a branch.

Before commit:

```bash
git status --short
git diff --name-status
git diff --stat
grep -R "E_ECON_BAD_NEAR_MISS_SHADOW" -n src/services tests || true
```

Commit/push only if scope is allowed, tests are clean, and PAPER-only/live-real isolation is proven:

```bash
git add <allowed source/test files only>
git commit -m "P1.1AP-O1: Apply adaptive rolling policy to PAPER decisions"
git push origin main
```

---

# Post-deploy acceptance

Capture the new PID:

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "CURRENT_PID=$PID"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_ADAPTIVE_POLICY_READ|PAPER_POLICY_ADAPTATION|PAPER_ADAPTIVE_STARVATION|PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_CANONICAL_LEARNING_UPDATE|REAL_READINESS_CHECK|REAL_READY|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Acceptance requires:

```text
1. A PAPER candidate decision logs PAPER_ADAPTIVE_POLICY_READ.
2. A later PAPER decision demonstrably changes according to segment rolling evidence, or truthful STARVATION logs prove no EV>0 supply exists.
3. EV<=0 signals remain rejected; no fabricated edge.
4. D_NEG remains shadow-only with no canonical update.
5. REAL_READY remains false unless qualified post-integration evidence reaches all gates.
6. No crashes.
```

---

# Return report

```text
ROOT CAUSE CONFIRMED WITH FILE:LINES:
ADAPTIVE METRICS READ PATH ADDED:
WHY THIS DOES NOT ADMIT NEGATIVE EV:
QUALIFICATION / REAL_READY SAFETY GUARD:
FILES CHANGED:
TEST RESULTS:
COMMIT/PUSH:
POST-DEPLOY PAPER POLICY READ EVIDENCE:
POST-DEPLOY STARVATION OR ADAPTATION EVIDENCE:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
