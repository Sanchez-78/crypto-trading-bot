# CryptoMaster P1.1AN Post-Audit Decision

_Source: uploaded production audit `Vlozeny text.txt`, May 18._

## Verdict

**Do not patch now.**  
P1.1AT is fixed, P1.1AN is active, paper training is flowing, and LearningMonitor updates are working.

Current state:

```text
PAPER_TRAIN_ENTRY_REAL:      32
PAPER_TRAIN_QUALITY_ENTRY:   32
PAPER_TRAIN_QUALITY_EXIT:    35
PAPER_EXIT_TRAINING_BUCKET:  35
PAPER_EXIT_NON_TRAINING:     0
LM_STATE_AFTER_UPDATE:       35
LM_UPDATE_MISMATCH:          0
Latest Total trades in LM:   37
```

This means the old blocker is gone:

```text
rate-cap phantom reservation: fixed
paper entries: flowing
quality entry/exit: consistent
LM state: updating
probe: not required
```

## P1.1AN Gate Check

```text
closed_training_trades >= 10:      PASS
quality_entry_mismatch = 0:        PASS
quality_exit_missing = 0:          PASS
lm_update_mismatch = 0:            PASS
dominant attribution > 50%:        FAIL
```

Attribution distribution:

```text
WRONG_DIRECTION:          13 / 35 = 37.1%
FEE_DOMINATED_MOVE:       11 / 35 = 31.4%
COST_EDGE_BYPASS_LOSS:     3 / 35 =  8.6%
TP_TOO_FAR_FOR_MFE:        1 / 35 =  2.9%
LOW_VOL_TIMEOUT:           0 / 35 =  0.0%
OTHER / NORMAL / NEAR_TP:  7 / 35 = 20.0%
```

No attribution dominates above 50%, so **no next economic patch is justified yet**.

## Interpretation

P1.1AN worked structurally:

```text
geometry_calibrated=True appears in entries
tp_pct is now around 0.20–0.45%, not 1.20%
sl_pct is around 0.45%
TP, SL, TIMEOUT, and near-TP cases now appear
```

The current losses are mixed:

1. Wrong direction is the largest group, but not dominant.
2. Fee-dominated trades are still significant, but not dominant.
3. TP-too-far is now low, so the original P1.1AN target was mostly solved.
4. Normal wins and near-TP cases exist, so the geometry is no longer completely unrealistic.

## Important Non-Blockers

### `LEARNING_UPDATE ok=True = 0`

Not a blocker because:

```text
LM_STATE_AFTER_UPDATE = 35
LM_UPDATE_MISMATCH = 0
Latest Total trades in LM = 37
```

The audit already recognizes learning updates via canonical LM state logs.

### `PAPER_TRAIN_QUALITY_EXIT > PAPER_TRAIN_ENTRY`

Not a blocker because:

```text
PAPER_EXIT_NON_TRAINING = 0
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

Likely explanation: some positions were opened before the audit window and closed inside the window.

### `ENTRY_ATTEMPT_NOT_CORRELATED`

Not a trading blocker now because:

```text
PAPER_ENTRY_DROPPED_AFTER_ACCEPT = 0
ACCEPTED_WITHOUT_ENTRY = 0
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_EXIT_TRAINING_BUCKET > 0
LM_STATE_AFTER_UPDATE > 0
```

Treat it as audit/log-correlation noise, not a reason for another patch.

## Decision

```text
PATCH_ALLOWED = NO
TUNING_ALLOWED = NO
DIAGNOSTICS_EXPANSION_ALLOWED = NO
DATA_COLLECTION_ALLOWED = YES
```

## Next Action

Let the bot run and collect a larger sample.

Recommended next audit:

```bash
cd /opt/cryptomaster
source venv/bin/activate
bash scripts/p11ag_quality_audit.sh --since "360 min ago"
```

Target sample:

```text
minimum useful: 50 closed training exits
better:         80 closed training exits
```

## Future Decision Rules

Only consider another patch if the larger audit shows one clear dominant cause:

```text
WRONG_DIRECTION > 50%
→ investigate signal direction quality, regime alignment, side selection, and anti-trend mistakes.

FEE_DOMINATED_MOVE > 50%
→ investigate min edge, fee drag, TP floor, and entry quality.

TP_TOO_FAR_FOR_MFE > 30%
→ TP is still too far for the 300s learning horizon.

NEAR_TP_TIMEOUT high
→ consider timeout/late-exit handling, not TP geometry first.

NORMAL_WIN increasing
→ no patch; continue learning.
```

## Hard Rule

Do not make live/real trading changes from this sample.  
All observations are paper-training cold-start diagnostics only.
