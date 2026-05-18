# CryptoMaster — P1.1AN Hard Stop Gate

## Status

P1.1AN implementation remains paused.

P1.1AM economic attribution diagnostics are deployed on production.

```text
HEAD: b1375bc
Tests: 173 passing
Service: running
Diagnostics: clean
```

## Production Audit Result

```text
closed_training_trades: 2
quality_entry_mismatch: 0
quality_exit_missing: 0
lm_update_mismatch: 0
```

Attribution distribution:

```text
WRONG_DIRECTION:      1 / 50%
FEE_DOMINATED_MOVE:   1 / 50%
```

## Decision

```text
TUNE_ALLOWED: NO
Reason: INSUFFICIENT_SAMPLE_FOR_CALIBRATION
closed=2 required>=10
```

Do not tune from this sample. The result is too small and tied 50/50, so any P1.1AN calibration would be speculative.

## Why Hard Stop Is Correct

The P1.1AN gate requires:

```text
P1.1AM deployed: YES
quality_entry_mismatch == 0
quality_exit_missing == 0
lm_update_mismatch == 0
closed_training_trades >= 10
dominant attribution is clear
```

Current state:

```text
P1.1AM deployed: YES
quality diagnostics clean: YES
closed_training_trades >= 10: NO
dominant attribution clear: NO
```

## Next Action

No code changes now.

Keep the bot running and rerun the audit after more paper-training exits.

Recommended command:

```bash
cd /opt/cryptomaster

git rev-parse --short HEAD
git merge-base --is-ancestor b1375bc HEAD && echo "OK P1.1AM deployed" || echo "BAD P1.1AM missing"

bash scripts/p11ag_quality_audit.sh --since "120 min ago"
```

## P1.1AN Resume Conditions

Resume implementation only when:

```text
closed_training_trades >= 10
quality_entry_mismatch == 0
quality_exit_missing == 0
lm_update_mismatch == 0
one attribution is clearly dominant
```

If still tied or unclear:

```text
TUNE_ALLOWED: NO
Reason: ATTRIBUTION_INCONCLUSIVE
Action: extend audit window and rerun
```

## Case Mapping When Ready

| Case | Dominant attribution | P1.1AN action |
|---|---|---|
| A | TP_TOO_FAR_FOR_MFE | Reduce paper-train TP/SL geometry to observed MFE |
| B | FEE_DOMINATED_MOVE | Add minimum expected-move filter + bootstrap quota |
| C | COST_BYPASS_LOSS | Throttle bypass quota + require score floor |
| D | WRONG_DIRECTION | Diagnostics only: symbol/regime/side breakdown |
| E | NEAR_TP_TIMEOUT | Shadow geometry: what if TP = 90% |
| F | BOTH_TOUCH_AMBIGUOUS | Track first-touch timestamps |

## Required PRECHECK When Audit Is Ready

```text
P1.1AN PRECHECK

HEAD: <hash>
P1.1AM deployed: YES/NO
closed_training_trades: <n>
quality_entry_mismatch: <n>
quality_exit_missing: <n>
lm_update_mismatch: <n>

Dominant attribution:
1. <ATTR>: <count> / <percent>
2. <ATTR>: <count> / <percent>
3. <ATTR>: <count> / <percent>

Decision:
TUNE_ALLOWED: YES/NO
Selected case: A/B/C/D/E/F/NONE
Recommended action: <short action>
```
