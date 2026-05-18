# CryptoMaster — P1.1AN Next Step

## Status

P1.1AN is paused. Do not implement tuning yet.

Current rule:

```text
No calibration until production has >= 10 closed C_WEAK_EV_TRAIN paper-training trades
and diagnostics are clean.
```

## Run this on server

```bash
cd /opt/cryptomaster

echo "=== VERSION ==="
git rev-parse --short HEAD
git merge-base --is-ancestor b1375bc HEAD && echo "OK P1.1AM deployed" || echo "BAD P1.1AM missing"

echo "=== SERVICE ==="
PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
sudo systemctl status cryptomaster --no-pager -l

echo "=== AUDIT ==="
bash scripts/p11ag_quality_audit.sh --since "60 min ago"

echo "=== ATTRIBUTION LOGS ==="
sudo journalctl -u cryptomaster --since "60 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_ECON_ATTRIB|PAPER_TRAIN_ECON_SUMMARY|PAPER_TRAIN_QUALITY_EXIT|PAPER_EXIT|LM_STATE_AFTER_UPDATE|LM_UPDATE_MISMATCH|PAPER_TRAIN_QUALITY_MISMATCH|PAPER_TRAIN_QUALITY_EXIT_MISSING" \
| tail -300
```

## Decision gate

Stop if any condition is false:

```text
closed_training_trades >= 10
quality_entry_mismatch == 0
quality_exit_missing == 0
lm_update_mismatch == 0
```

If closed trades are below 10:

```text
INSUFFICIENT_SAMPLE_FOR_CALIBRATION closed=<n> required>=10
```

## Required PRECHECK output

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

## Case mapping

| Case | Dominant attribution | Action |
|---|---|---|
| A | TP_TOO_FAR_FOR_MFE | Reduce paper-train TP/SL geometry to observed MFE |
| B | FEE_DOMINATED_MOVE | Add minimum expected-move filter + bootstrap quota |
| C | COST_BYPASS_LOSS | Throttle bypass quota + require score floor |
| D | WRONG_DIRECTION | Diagnostics only: symbol/regime/side breakdown |
| E | NEAR_TP_TIMEOUT | Shadow geometry: what if TP = 90% |
| F | BOTH_TOUCH_AMBIGUOUS | Track first-touch timestamps |
