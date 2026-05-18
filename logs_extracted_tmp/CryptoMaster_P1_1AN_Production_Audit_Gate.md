# CryptoMaster — P1.1AN Production Audit Gate

Purpose: do **not** implement P1.1AN until production data from P1.1AM attribution is sufficient.

## Current confirmed state

Deployed/ready:

- P1.1AK — snapshot audit + diagnostics wiring
- P1.1AL — scalar-safe audit counters
- P1.1AM — per-trade economic attribution + summary breakdown

P1.1AN is paused.

## Rule

P1.1AN must be:

- evidence-based
- minimal
- targeted to one dominant attribution
- paper_train + C_WEAK_EV_TRAIN only
- no live/real behavior changes

## Run production audit

```bash
cd /opt/cryptomaster

git rev-parse --short HEAD
git merge-base --is-ancestor b1375bc HEAD && echo "OK P1.1AM deployed" || echo "BAD P1.1AM missing"

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "60 min ago"

sudo journalctl -u cryptomaster --since "60 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_ECON_ATTRIB|PAPER_TRAIN_ECON_SUMMARY|PAPER_TRAIN_QUALITY_EXIT|PAPER_EXIT|LM_STATE_AFTER_UPDATE|LM_UPDATE_MISMATCH|PAPER_TRAIN_QUALITY_MISMATCH|PAPER_TRAIN_QUALITY_EXIT_MISSING" \
| tail -300
```

## Hard stop gate

If closed training trades are below 10:

```text
INSUFFICIENT_SAMPLE_FOR_CALIBRATION closed=<n> required>=10
Next action: keep bot running and rerun audit later.
```

Do not implement P1.1AN.

## P1.1AN decision matrix

| Case | Dominant attribution | Action |
|---|---|---|
| A | TP_TOO_FAR_FOR_MFE | Reduce paper-train TP/SL geometry to match observed MFE |
| B | FEE_DOMINATED_MOVE | Add minimum expected-move filter + bootstrap quota |
| C | COST_BYPASS_LOSS | Throttle bypass quota + require score floor |
| D | WRONG_DIRECTION | Diagnostics only: breakdown by symbol/regime/side |
| E | NEAR_TP_TIMEOUT | Shadow geometry diagnostics: what if TP = 90% |
| F | BOTH_TOUCH_AMBIGUOUS | Track first-touch timestamps |

## Required Claude output before any implementation

```text
P1.1AN PRECHECK

HEAD: <hash>
P1.1AM deployed: YES/NO
PID: <pid>
closed_training_trades: <n>
quality_entry_mismatch: <n>
quality_exit_missing: <n>
lm_update_mismatch: <n>

Dominant attribution:
1. <ATTR>: <count> / <percent>
2. <ATTR>: <count> / <percent>
3. <ATTR>: <count> / <percent>

Decision:
- TUNE_ALLOWED: YES/NO
- Selected case: A/B/C/D/E/F/NONE
- Recommended P1.1AN action: <one sentence>
```

## Implementation rule

Only after `closed_training_trades >= 10` and mismatches are zero:

1. Choose exactly one dominant case.
2. Implement only the smallest patch needed for that case.
3. Add regression tests for that case.
4. Confirm live/real behavior unchanged.
5. Preserve all diagnostics from P1.1AD through P1.1AM.
