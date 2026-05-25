# Claude Code Prompt — P1.1AP-L: Post-Bootstrap ECON_BAD Near-Miss Shadow Sampler

## Goal
Implement one narrow **paper-only, shadow-only diagnostic lane** for the confirmed post-bootstrap starvation gap. Investigate first; stop and report if equivalent functionality already exists.

This patch must collect evidence only. It must **not** lower thresholds, revive cold-start probe logic, or update canonical learning/economic health.

## Validated baseline
Current HEAD:
```text
321f10b Tests: Replace legacy boolean-return pytest checks with assertions
eb259e3 P1.1AP-J2: Emit B_RECOVERY_READY exit attribution diagnostics
008559e P1.1AP-K: Normalize ATR price move before C_WEAK cost-edge gate
07fc451 P1.1AP-I2: Suppress D_NEG legacy LEARNING_UPDATE log
```

Preserve:
```text
- Server-safe suite baseline: 854 passed, 0 warnings.
- D_NEG_EV_CONTROL: PAPER_LEARNING_SHADOW_SKIP; no canonical LEARNING_UPDATE / LM_STATE_AFTER_UPDATE.
- P1.1AP-K: normalized cost-edge input and required_move_pct=0.2300 unchanged.
- P1.1AP-J/J2: B route_trigger and B exit attribution behavior unchanged.
```

## Production evidence
Cold-start is over:
```text
[ECON_CANONICAL_ACTIVE] pf=0.49 source=canonical_closed_trades closed_trades=100
net_pnl=-0.00023955 economic_score=0.335 status=BAD
Total trades in LM: 200
```

P1.1AO is correctly inactive because its scope is `<100` closed/canonical trades.

Prolonged post-bootstrap starvation:
```text
[ECON_BAD_DIAG_HEARTBEAT] ... total=822 neg_ev=650 weak_ev=172
best_symbol=XRPUSDT best_ev=0.0348 best_score=0.166
probe_ready=False probe_block=below_probe_ev

[PAPER_EXPLORE_SKIP_SUMMARY] window_s=600 cost_edge_too_low=220 ... entries=0
[PAPER_EXPLORE_SKIP_SUMMARY] window_s=600 cost_edge_too_low=245 ... entries=0
```

Only D_NEG shadow controls still close:
```text
[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ...
```

Missing:
```text
B_RECOVERY_READY
canonical C_WEAK close
LEARNING_UPDATE / LM_STATE_AFTER_UPDATE
```

## Confirmed gap to investigate
Negative-EV candidates have D_NEG shadow diagnostics. Weak-positive post-bootstrap candidates rejected under ECON_BAD/cost-edge have no low-rate outcome sampling path:
```text
best_ev≈0.0348 < B_RECOVERY_READY ev threshold 0.038
best_ev≈0.0348 < ECON_BAD normal threshold 0.045
C_WEAK cost-edge rejects are legitimate after P1.1AP-K
```

Do not "fix" by loosening filters. Add diagnostics only if no existing equivalent lane exists.

## Investigation commands
```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short

grep -R "D_NEG_EV_CONTROL\|B_RECOVERY_READY\|C_WEAK_EV_TRAIN\|C_NEG_EV_PROBE\|PAPER_LEARNING_SHADOW_SKIP\|PAPER_TRADE_SAVED_SHADOW" -n src/services tests | head -400
grep -R "ECON_BAD\|lm_economic_health\|canonical_closed_trades\|get_canonical_training_trade_count\|probe_ready\|route_trigger" -n src/services tests | head -400
grep -R "cost_edge_too_low\|expected_move_src\|_check_cost_edge\|paper_exploration_override" -n src/services tests | head -400
```

Confirm:
1. D_NEG's exact routing and canonical-isolation path.
2. B_RECOVERY routing and priority.
3. C_WEAK cost-edge admission and K normalization.
4. Whether a post-bootstrap weak-positive shadow sampler already exists.
5. A safe source for "no canonical/B/C evidence entry for 60 minutes."

If equivalent behavior already exists, do not add another bucket; report its condition/logs and why it has not activated.

## Proposed new bucket
Use a unique diagnostic bucket after collision check, preferably:
```text
E_ECON_BAD_NEAR_MISS_SHADOW
```

## Narrow eligibility
Admit only when all are true:
```text
- paper_train/paper diagnostic mode only; never live/real
- economic_status == BAD
- canonical/global closed trade count >= 100
- no accepted canonical/B/C paper evidence entry during last 60 minutes
- decision is REJECT_ECON_BAD_ENTRY for weak positive EV
- candidate has valid side and required position metadata
- 0 < ev < B_RECOVERY_READY threshold (currently 0.038)
- candidate did not qualify for existing B route or normal C_WEAK route
- shadow caps below permit admission
```

Prefer using an existing constant for B threshold. If an EV floor is needed to avoid noise, use a named, test-covered diagnostic constant that captures the observed 0.0300–0.0348 near misses; do not change existing entry thresholds.

A below-cost-edge candidate may enter **this shadow lane only**, because the purpose is to measure rejected outcomes. It must remain excluded from canonical learning.

## Mandatory caps and priority
```text
- max 1 new E-shadow entry per 30 minutes
- max 1 open E-shadow globally
- max 1 open E-shadow per symbol
- lifetime cap: 20 closed E-shadow samples
- reuse an existing safe paper observation hold limit; do not expand risk/horizon
- valid existing B or C_WEAK candidate has priority over E-shadow
- E-shadow must not consume/block normal candidate capacity where avoidable
```

## Entry/exit telemetry
Entry should be explicit:
```text
[PAPER_ECON_BAD_NEAR_MISS_SHADOW_ENTRY]
trade_id=... symbol=... side=... ev=... score=...
economic_status=BAD canonical_closed_trades=...
idle_since_canonical_entry_s=...
cost_edge_ok=... expected_move_pct=... expected_move_src=...
route_trigger=postbootstrap_econ_bad_shadow
```

Exit should provide diagnostic quality and attribution:
```text
[PAPER_EXIT] ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW ...
[PAPER_TRAIN_QUALITY_EXIT] ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW ...
[PAPER_TRAIN_ECON_ATTRIB] ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW ... attribution=...
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW reason=postbootstrap_econ_bad_near_miss_shadow_only
[PAPER_BUCKET_UPDATE] / [PAPER_BUCKET_METRICS] ...
```

If diagnostic save exists, use:
```text
[PAPER_TRADE_SAVED_SHADOW]
```

Forbidden:
```text
[LEARNING_UPDATE] ok=True ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW
[LM_STATE_AFTER_UPDATE] ... bucket=E_ECON_BAD_NEAR_MISS_SHADOW
```

## Implementation guidance
Likely files after investigation:
```text
src/services/paper_exploration.py
src/services/paper_training_sampler.py          # only if existing path requires it
src/services/paper_trade_executor.py
src/services/trade_executor.py                  # only for downstream shadow save suppression
tests/test_p1_paper_exploration.py
tests/test_p11ap_i_d_neg_learning_isolation.py  # or new focused shadow test file
```

Prefer generalizing proven D_NEG shadow detection into a well-tested shadow-only helper rather than duplicating canonical-skip logic.

## Hard boundaries
Do **not** change:
```text
- ECON_BAD threshold 0.045
- B_RECOVERY_READY threshold 0.038 or route_trigger
- C_WEAK required_move_pct=0.2300 / P1.1AP-K normalization
- P1.1AO cold-start activation/lifetime logic
- D_NEG behavior/isolation
- canonical LM, PF, economic_health, feature weights
- live/real trading, RDE, sizing, TP/SL
- Firebase/Android contracts
```

## Required tests
Add tests proving:

1. Activation: BAD, closed_trades=100, idle >=60m, weak-positive `ev=0.0348`, rejected normally, no B/C eligibility → E-shadow admitted.
2. No activation for `closed_trades=99`.
3. No activation for `ev<=0`; D_NEG remains owner.
4. No stealing B: an existing B-eligible candidate remains B.
5. No stealing normal C_WEAK: normal accepted candidate remains normal route.
6. Rate cap: 1 E-shadow / 30m.
7. Open and per-symbol caps: max 1.
8. Lifetime cap: blocks after 20 closed E-shadow samples.
9. Normal B/C priority is not blocked by an E-shadow position.
10. E-shadow exit emits EXIT, QUALITY_EXIT, ECON_ATTRIB, SHADOW_SKIP and bucket metrics.
11. E-shadow exit does not call canonical learning and emits no canonical LEARNING_UPDATE/LM_STATE_AFTER_UPDATE.
12. D_NEG I/I2 tests unchanged.
13. B J/J2 tests unchanged.
14. K expected_move/cost-edge tests unchanged.
15. No route in live/real mode.

## Validation
```bash
cd /opt/CryptoMaster_srv

./venv/bin/python -m pytest -q \
  tests/test_p1_paper_exploration.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ab_stale_position_quarantine.py \
  tests/test_v10_13u_patches.py

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Expected baseline before new tests:
```text
854 passed, 0 warnings
```

## Commit hygiene
Before commit:
```bash
git diff --stat
git diff -- src/services tests
git status --short
```

Do not commit runtime/local artifacts:
```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary outputs
```

Commit only after tests pass:
```text
P1.1AP-L: Add post-bootstrap ECON_BAD near-miss shadow sampler
```

## Post-deploy verification
```bash
sudo journalctl -u cryptomaster -f -o cat | grep --line-buffered -E \
"ECON_BAD|E_ECON_BAD_NEAR_MISS_SHADOW|PAPER_ECON_BAD_NEAR_MISS_SHADOW_ENTRY|B_RECOVERY_READY|C_WEAK_EV_TRAIN|D_NEG_EV_CONTROL|PAPER_EXIT|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_ECON_ATTRIB|PAPER_LEARNING_SHADOW_SKIP|PAPER_TRADE_SAVED_SHADOW|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|Traceback|UnboundLocalError"
```

Acceptance:
```text
- Low-frequency E-shadow near-miss entry appears only under post-bootstrap BAD starvation.
- It closes with attribution and shadow skip.
- It never mutates canonical learning or PF/health.
- Existing D_NEG/B/C behavior is unchanged.
```

## Report back
Return: evidence that no existing lane covered this gap; chosen bucket/caps; changed files; tests; commit hash; and runtime verification evidence.
