# Claude Code Prompt — P1.1AP-J2: Emit Missing B_RECOVERY_READY Exit Attribution

## Mode
Implement one **diagnostic-only** follow-up fix. Verify root cause first, then change only the minimal source/test code. Do not change trading behavior, learning behavior, thresholds, or economics.

## Current validated production baseline

Deployed chain:
```text
008559e P1.1AP-K: Normalize ATR price move before C_WEAK cost-edge gate
5e9179b P1.1AP-J: Clarify paper exploration telemetry and B route trigger
07fc451 P1.1AP-I2: Suppress D_NEG legacy LEARNING_UPDATE log
```

Preserve these validated invariants:
```text
P1.1AP-K:
- expected_move_src=atr_abs_price_normalized is live.
- C_WEAK cost-edge skips are currently legitimate; do not alter threshold or normalization.

P1.1AP-J:
- Fresh B entry correctly logs route_trigger:
  [PAPER_EXPLORE_ENTRY] bucket=B_RECOVERY_READY ... reason=route_trigger=ev_threshold recovery_ready=False probe_ready=False ev=0.0399
- Paper Firebase save correctly logs [PAPER_TRADE_SAVED], not fake [LEARNING_UPDATE].

P1.1AP-I2:
- D_NEG is shadow-only with real trade_id.
- D_NEG must not emit canonical LEARNING_UPDATE or LM_STATE_AFTER_UPDATE.
```

## New production evidence: J acceptance is incomplete

Fresh B entry:
```text
[PAPER_EXPLORE_ENTRY] bucket=B_RECOVERY_READY symbol=XRPUSDT side=BUY original_decision=REJECT_ECON_BAD_ENTRY ev=0.0399 score=0.177 price=1.36445000 final_size_usd=15.00 max_hold_s=900 reject_reason=weak_ev (ev=0.0399<0.045) reason=route_trigger=ev_threshold recovery_ready=False probe_ready=False ev=0.0399
```

Fresh matching B close:
```text
[PAPER_TIMEOUT_DUE] trade_id=paper_930e4f9a18e2 symbol=XRPUSDT age_s=900.0 hold_limit_s=900.0 bucket=B_RECOVERY_READY training_bucket=None
[PAPER_EXIT] trade_id=paper_930e4f9a18e2 symbol=XRPUSDT reason=TIMEOUT entry=1.36445000 exit=1.36375000 net_pnl_pct=-0.2313 outcome=LOSS hold_s=900 max_hold_s=900 bucket=B_RECOVERY_READY training_bucket=None
[PAPER_BUCKET_UPDATE] bucket=B_RECOVERY_READY n=1 outcome=LOSS net_pnl_pct=-0.2313
[PAPER_BUCKET_METRICS] bucket=B_RECOVERY_READY n=1 wr=0.0% avg=-0.2313 pf=0.00 timeout_rate=100.0% tp_rate=0.0% sl_rate=0.0%
[PAPER_TRADE_SAVED] source=paper_closed_trade symbol=XRPUSDT bucket=B_RECOVERY_READY outcome=LOSS net_pnl_pct=-0.2313 ok=True
```

Missing for this fresh B close:
```text
[PAPER_TRAIN_ECON_ATTRIB] ... B_RECOVERY_READY ... attribution=...
```

Thus:
```text
B route_trigger: PROD VALIDATED
PAPER_TRADE_SAVED rename: PROD VALIDATED
B exit attribution promised by P1.1AP-J: NOT EMITTED / REGRESSION
```

There is also no shown canonical:
```text
[LM_STATE_AFTER_UPDATE] ... bucket=B_RECOVERY_READY
[LEARNING_UPDATE] ok=True ... bucket=B_RECOVERY_READY
```
Do not introduce either.

## First verify exact root cause

Run:
```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD

sudo journalctl -u cryptomaster --since "2026-05-22 07:52:00" --no-pager | grep "paper_930e4f9a18e2"

grep -R "PAPER_TRAIN_ECON_ATTRIB\|B_RECOVERY_READY\|training_bucket\|explore_bucket\|econ_attrib" -n   src/services/paper_trade_executor.py   src/services/trade_executor.py   src/services/paper_exploration.py   tests | head -350
```

Inspect close and attribution conditions around each match.

Expected root cause to confirm:
```text
The P1.1AP-J B attribution condition relies on training_bucket=="B_RECOVERY_READY"
(or training-sampler path), but the actual B exploratory close is:
bucket=B_RECOVERY_READY training_bucket=None
and likely stores B in explore_bucket.
```

Do not edit until this field/path mismatch is confirmed.

## Required minimal fix

Expected implementation file:
```text
src/services/paper_trade_executor.py
```

Reuse existing economic attribution calculation. Do not create a new formula.

Resolve the effective diagnostic bucket using existing module conventions, or add a narrow helper such as:
```python
def _effective_paper_bucket(pos: dict, pnl_data: dict | None = None) -> str:
    pnl_data = pnl_data or {}
    return (
        pos.get("training_bucket")
        or pos.get("explore_bucket")
        or pos.get("bucket")
        or pnl_data.get("training_bucket")
        or pnl_data.get("explore_bucket")
        or pnl_data.get("bucket")
        or "A_STRICT_TAKE"
    )
```

Then ensure existing attribution logging is also reached for:
```python
effective_bucket == "B_RECOVERY_READY"
```

The B log must identify the true path without mutating semantics:
```text
[PAPER_TRAIN_ECON_ATTRIB] trade_id=... symbol=XRPUSDT ... bucket=B_RECOVERY_READY training_bucket=None source=paper_explore ... attribution=...
```
Use the existing actual log schema where possible; add `bucket=` only if necessary to make B grepable.

## Hard boundaries

Do **not** change:
- B routing: `ev >= 0.038 OR recovery_ready OR probe_ready`
- `route_trigger` implementation
- B hold time, size multiplier, TP/SL, entry acceptance
- C_WEAK cost-edge threshold or P1.1AP-K normalization
- D_NEG shadow isolation
- canonical LM/economic health mutation paths
- live/real trading, RDE, ECON_BAD, P1.1AO
- Firebase schemas/contracts or Android snapshots

This patch restores missing diagnostics only.

## Regression tests

Add focused coverage in the nearest existing test file, likely `tests/test_p1_paper_exploration.py`, or the existing J telemetry tests if present.

### Test 1 — B exploration close emits attribution with `training_bucket=None`
Build a B exploratory position matching production:
```python
{
    "trade_id": "paper_b_diag_1",
    "symbol": "XRPUSDT",
    "action": "BUY",
    "entry": 1.36445,
    "explore_bucket": "B_RECOVERY_READY",
    "training_bucket": None,
    "paper_source": "exploration_reject",
    "max_hold_s": 900,
}
```
Close by TIMEOUT and assert:
```text
PAPER_EXIT emitted
PAPER_TRAIN_ECON_ATTRIB emitted and attributable to B_RECOVERY_READY
PAPER_BUCKET_UPDATE remains emitted
PAPER_TRADE_SAVED remains emitted
```

### Test 2 — B diagnostics do not add canonical learning
For the B close assert no newly caused:
```text
LM_STATE_AFTER_UPDATE
canonical [LEARNING_UPDATE] ok=True ... bucket=B_RECOVERY_READY
```

### Test 3 — C_WEAK unchanged
A C_WEAK training close still emits current attribution and canonical learning behavior.

### Test 4 — D_NEG unchanged
Existing I/I2 tests remain green:
```text
PAPER_LEARNING_SHADOW_SKIP with real trade_id
no canonical D_NEG LEARNING_UPDATE / LM_STATE_AFTER_UPDATE
```

### Test 5 — J/K invariants unchanged
Verify existing tests still cover:
```text
B route_trigger
PAPER_TRADE_SAVED telemetry
ATR expected_move_src / C_WEAK cost-edge normalization
```

## Test commands

Use the server virtualenv, not bare `python`:

```bash
cd /opt/CryptoMaster_srv

./venv/bin/python -m pytest -q tests/test_p1_paper_exploration.py -k "recovery or attribution or route_trigger or expected_move or cost_edge"
./venv/bin/python -m pytest -q tests/test_p11ap_i_d_neg_learning_isolation.py

./venv/bin/python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_p11ap_i_d_neg_learning_isolation.py   tests/test_v10_13u_patches.py

./venv/bin/python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

Full-suite expected baseline before/after:
```text
850 passed, 6 known PytestReturnNotNone warnings in VERIFICATION_V10_13W only
```

## Before commit

```bash
git diff --stat
git diff -- src/services/paper_trade_executor.py tests/test_p1_paper_exploration.py
git status --short
```

Never commit:
```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary terminal/log outputs
```

## Commit only after confirmed fix and passing tests

```bash
git add <only changed source/test files>
git commit -m "P1.1AP-J2: Emit B_RECOVERY_READY exit attribution diagnostics"
git push
```

## Post-deploy validation

Restart after deployment and monitor a fresh B trade:
```bash
sudo systemctl restart cryptomaster

sudo journalctl -u cryptomaster -f -o cat | grep --line-buffered -E "B_RECOVERY_READY|route_trigger=|PAPER_TIMEOUT_DUE|PAPER_EXIT|PAPER_TRAIN_ECON_ATTRIB|PAPER_BUCKET_UPDATE|PAPER_BUCKET_METRICS|PAPER_TRADE_SAVED|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|PAPER_LEARNING_SHADOW_SKIP|Traceback|UnboundLocalError"
```

Acceptance requires fresh B close:
```text
[PAPER_EXIT] ... bucket=B_RECOVERY_READY ...
[PAPER_TRAIN_ECON_ATTRIB] ... B_RECOVERY_READY ... attribution=...
[PAPER_TRADE_SAVED] ... bucket=B_RECOVERY_READY ...
```

Forbidden newly introduced B behavior:
```text
[LM_STATE_AFTER_UPDATE] ... bucket=B_RECOVERY_READY
[LEARNING_UPDATE] ok=True ... bucket=B_RECOVERY_READY
```

## Report back
Return root cause with exact field mismatch, changed files, tests, full-suite result, commit hash, and post-deploy validation status.
