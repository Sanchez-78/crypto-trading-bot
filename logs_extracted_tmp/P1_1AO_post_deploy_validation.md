# P1.1AO Post-Deploy Validation — a7afaa9

## Verdict

P1.1AO is now deployed correctly.

```text
Git HEAD: a7afaa9
Deployment check: ✓ P1.1AO deployed
Audit contains: Cold-Start Starvation section
```

This confirms the previous problem is fixed: production is no longer stuck on `b1375bc`.

## Current audit interpretation

### Good signs

```text
PAPER_TRAIN_ENTRY:          2
PAPER_TRAIN_QUALITY_ENTRY:  2
PAPER_TRAIN_QUALITY_MISMATCH: 0
STARVATION_STATE_LOGS:      1
STATE_MISMATCH_LOGS:        0
Latest Total trades in LM:  1
```

Meaning:

- P1.1AO code is active.
- Normal `C_WEAK_EV_TRAIN` entries are being created.
- Quality-entry logging is intact.
- No LM/RDE state mismatch is currently reported.
- Probe bucket is not accepted yet because normal training flow is not fully starved.

### Not alarming yet

```text
NEGATIVE_EV_REJECTS:       0
UNKNOWN_BUCKET_SKIPS:      0
NEG_EV_PROBE_ACCEPTED:     0
NEG_EV_PROBE_BLOCKED:      0
NEG_EV_PROBE_EXITS:        0
```

This is acceptable right after restart because the bot already opened normal `C_WEAK_EV_TRAIN` entries. The probe is a fallback for negative-EV starvation, not the preferred path.

### Watch item

```text
PAPER_EXIT:                 1
PAPER_EXIT_TRAINING_BUCKET: 0
PAPER_TRAIN_QUALITY_EXIT:   0
LM_STATE_AFTER_UPDATE:      0
```

The exit shown by the core flow viewer was:

```text
ADAUSDT outcome=LOSS pnl=-0.1800 reason=TIMEOUT
```

But current visible quality entries are:

```text
ETHUSDT
BTCUSDT
```

Likely explanation: ADAUSDT was a persisted/orphan paper position from before restart, not a clean current training-bucket trade. Do not patch based on this single mismatch yet.

## Immediate next validation

Wait until the current ETHUSDT/BTCUSDT entries have time to close. Since hold limit is 300 seconds, run this after at least 6–8 minutes from restart:

```bash
cd /opt/cryptomaster

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "45 min ago"

bash scripts/p11ak_core_flow_viewer.sh --since "45 min ago"
```

## PASS condition

P1.1AO is healthy if the next audit shows:

```text
PAPER_TRAIN_ENTRY_REAL >= 2
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_MISMATCH = 0
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
PAPER_EXIT_TRAINING_BUCKET >= 1
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET >= PAPER_EXIT_TRAINING_BUCKET
LM_STATE_AFTER_UPDATE >= PAPER_EXIT_TRAINING_BUCKET
LM_UPDATE_MISMATCH = 0
```

And either:

```text
Normal C_WEAK_EV_TRAIN entries continue
```

or, if negative-EV starvation returns:

```text
NEG_EV_PROBE_ACCEPTED > 0
NEG_EV_PROBE_EXITS > 0 after 300s
LM_STATE_AFTER_UPDATE increments after probe exits
```

## FAIL condition

Create a follow-up patch only if one of these persists after the current ETH/BTC entries close:

```text
PAPER_EXIT_TRAINING_BUCKET > 0
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET < PAPER_EXIT_TRAINING_BUCKET
```

or:

```text
PAPER_EXIT_TRAINING_BUCKET > 0
LM_STATE_AFTER_UPDATE stays 0
```

or:

```text
STARVATION_STATE_LOGS > 0
NEGATIVE_EV_REJECTS > 0
UNKNOWN_BUCKET_SKIPS > 0
NEG_EV_PROBE_ACCEPTED = 0
Normal C_WEAK_EV_TRAIN entries = 0
```

## Suggested Claude prompt if FAIL persists

Use only if the next audit fails after current entries close.

```markdown
# CryptoMaster P1.1AP — Post-P1.1AO Validation Fix

You are working in an existing Python 3.11+ crypto trading bot.

## Context

P1.1AO is deployed at commit `a7afaa9`. It added cold-start EV starvation recovery and probe counters.

Post-deploy audit confirms:
- P1.1AO is deployed.
- Cold-Start Starvation audit section exists.
- Normal `C_WEAK_EV_TRAIN` entries resumed.
- `PAPER_TRAIN_ENTRY == PAPER_TRAIN_QUALITY_ENTRY`.
- No quality-entry mismatch.
- Probe is not yet active because normal training entries exist.

Potential issue:
A `PAPER_EXIT` appeared without `PAPER_EXIT_TRAINING_BUCKET`, `PAPER_TRAIN_QUALITY_EXIT`, or `LM_STATE_AFTER_UPDATE`. It may be a persisted/orphan pre-restart position. Do not change trading logic unless the issue repeats for current training-bucket trades.

## Task

Implement only if validation proves a real mismatch after current entries close.

### Required analysis first

1. Inspect `paper_trade_executor.py`, `paper_training_sampler.py`, and the persistence path for `data/paper_open_positions.json`.
2. Determine whether restored paper positions can lack:
   - `training_bucket`
   - `bucket`
   - `trade_id`
   - quality metadata
   - source metadata
3. Determine whether orphan/restored paper positions should:
   - be closed but excluded from LM
   - or be backfilled with `training_bucket=C_WEAK_EV_TRAIN` when metadata proves they are training samples
4. Do not infer training status from symbol alone.

## Patch rules

- Do not change live/real trading behavior.
- Do not tune strategy, TP/SL, EV, score thresholds, or P1.1AN economics.
- Only fix diagnostics/state integrity if needed.
- Preserve P1.1AD–P1.1AO behavior.

## Acceptance criteria

After restart and at least one 300s close:

```text
PAPER_TRAIN_ENTRY_REAL >= 1
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_MISMATCH = 0
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
PAPER_EXIT_TRAINING_BUCKET == PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET
LM_STATE_AFTER_UPDATE increments for every training-bucket paper close
LM_UPDATE_MISMATCH = 0
```

If restored/orphan positions are intentionally excluded, log:

```text
[PAPER_RESTORED_ORPHAN_EXIT]
```

with reason and missing fields, and ensure the audit script reports them separately from training exits.

## Tests

Add regression tests for:
1. Restored training position with full metadata closes and updates LM.
2. Restored orphan position without training metadata closes but does not create false LM mismatch.
3. Audit counters separate orphan exits from training exits.
4. Live/real behavior unchanged.
```

## Current decision

Do not start P1.1AN yet.

P1.1AN still requires:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one dominant attribution > 50%
```

Current sample is still too small.
