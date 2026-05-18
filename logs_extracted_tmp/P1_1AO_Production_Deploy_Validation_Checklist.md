# P1.1AO Production Deploy & Validation Checklist

> Status: P1.1AO implementation complete.  
> Purpose: deploy and verify that cold-start EV starvation is fixed without changing live/real behavior.

---

## 1. What P1.1AO Should Fix

Current blocker:

```text
valid signal
→ REJECT_NEGATIVE_EV / SKIP_SCORE_HARD
→ PAPER_EXPLORE_SKIP bucket=UNKNOWN
→ no PAPER_TRAIN_ENTRY
→ no PAPER_EXIT
→ no LM_STATE_AFTER_UPDATE
→ cannot reach P1.1AN >=10 closed training trades
```

Expected after P1.1AO under cold-start starvation:

```text
valid signal
→ REJECT_NEGATIVE_EV / SKIP_SCORE_HARD
→ PAPER_TRAIN_STARVATION_STATE
→ PAPER_NEG_EV_PROBE_ACCEPTED
→ PAPER_TRAIN_ENTRY bucket=C_NEG_EV_PROBE source=NEGATIVE_EV_PROBE
→ PAPER_EXIT training_bucket=C_NEG_EV_PROBE
→ LM_STATE_AFTER_UPDATE increments
```

---

## 2. Pre-Deploy Checks

Run locally before production deploy:

```bash
python -m pytest tests/test_paper_mode.py -q
python -m pytest -q
bash -n scripts/p11ag_quality_audit.sh
```

Required:

```text
test_paper_mode.py: PASS
full pytest: PASS
audit script syntax: PASS
```

If full pytest was not run yet, run it before deploy.

---

## 3. Deploy to Production

On server:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD
```

Confirm expected P1.1AO commit is present:

```bash
git merge-base --is-ancestor <P1_1AO_COMMIT> HEAD && echo "OK P1.1AO" || echo "BAD P1.1AO missing"
```

Restart service:

```bash
sudo systemctl restart cryptomaster
sleep 15

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
```

---

## 4. Immediate Audit

```bash
bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

Important counters:

```text
PAPER_TRAIN_STARVATION_STATE
PAPER_TRAIN_STATE_MISMATCH
NEGATIVE_EV_REJECTS
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET
PAPER_NEG_EV_PROBE_ACCEPTED
PAPER_NEG_EV_PROBE_BLOCKED
PAPER_TRAIN_ENTRY
PAPER_EXIT
LM_STATE_AFTER_UPDATE
QUALITY_EXIT_MISSING_BY_TRADE_ID
LM_UPDATE_MISMATCH
```

---

## 5. Manual Probe Check

```bash
sudo journalctl -u cryptomaster --since "30 min ago" --no-pager | grep "cryptomaster\[$PID\]" | grep -E "PAPER_TRAIN_STARVATION_STATE|PAPER_TRAIN_STATE_MISMATCH|PAPER_NEG_EV_PROBE_ACCEPTED|PAPER_NEG_EV_PROBE_BLOCKED|C_NEG_EV_PROBE|NEGATIVE_EV_PROBE|PAPER_TRAIN_ENTRY|PAPER_EXIT|LM_STATE_AFTER_UPDATE|PAPER_EXPLORE_SKIP" | tail -200
```

Probe-specific:

```bash
sudo journalctl -u cryptomaster --since "60 min ago" --no-pager | grep "cryptomaster\[$PID\]" | grep -E "C_NEG_EV_PROBE|NEGATIVE_EV_PROBE|PAPER_NEG_EV_PROBE" | tail -200
```

---

## 6. Pass Criteria

### PASS A — normal paper training resumed

```text
PAPER_TRAIN_ENTRY > 0
PAPER_NEG_EV_PROBE_ACCEPTED = 0 or low
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET no longer exploding
LM_STATE_AFTER_UPDATE increments after exits
```

Meaning: P1.1AO did not need to activate much because normal training recovered.

---

### PASS B — probe active and working

```text
PAPER_TRAIN_STARVATION_STATE >= 1
PAPER_NEG_EV_PROBE_ACCEPTED >= 1
PAPER_TRAIN_ENTRY contains bucket=C_NEG_EV_PROBE
PAPER_EXIT contains training_bucket=C_NEG_EV_PROBE
LM_STATE_AFTER_UPDATE increments
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

Meaning: cold-start recovery path works.

---

### FAIL C — still starved

```text
NEGATIVE_EV_REJECTS high
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET high
PAPER_NEG_EV_PROBE_ACCEPTED = 0
PAPER_TRAIN_ENTRY = 0
```

Action: inspect `PAPER_NEG_EV_PROBE_BLOCKED` reasons. Do not tune P1.1AN yet.

---

### FAIL D — probe entries open but do not close

```text
PAPER_NEG_EV_PROBE_ACCEPTED > 0
PAPER_TRAIN_ENTRY bucket=C_NEG_EV_PROBE > 0
PAPER_EXIT training_bucket=C_NEG_EV_PROBE = 0 after > 6 minutes
```

Action: inspect timeout scan and open positions:

```bash
sudo journalctl -u cryptomaster --since "20 min ago" --no-pager | grep "cryptomaster\[$PID\]" | grep -E "PAPER_TIMEOUT_SCAN|PAPER_TIMEOUT_DUE|C_NEG_EV_PROBE|PAPER_EXIT" | tail -200
```

---

### FAIL E — LM not updating

```text
PAPER_EXIT training_bucket=C_NEG_EV_PROBE > 0
LM_STATE_AFTER_UPDATE = 0
LM_UPDATE_MISMATCH > 0
```

Action: inspect learning update path; do not proceed to P1.1AN.

---

## 7. When to Resume P1.1AN

Only resume P1.1AN when:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution reason > 50%
```

Then rerun:

```bash
bash scripts/p11ag_quality_audit.sh --since "120 min ago"
```

Expected P1.1AN PRECHECK format:

```text
HEAD: <hash>
P1.1AM deployed: YES
P1.1AO deployed: YES
closed_training_trades: <n>
quality_entry_mismatch: 0
quality_exit_missing: 0
lm_update_mismatch: 0

Dominant attribution:
1. <ATTR>: <count> / <percent>
2. <ATTR>: <count> / <percent>
3. <ATTR>: <count> / <percent>

Decision: TUNE_ALLOWED YES/NO, Case A/B/C/D/E/F
```

---

## 8. Safety Reminder

P1.1AO must remain:

```text
paper_train only
C_NEG_EV_PROBE only
strictly capped
diagnostic/sample recovery only
no live/real negative-EV trading
no P1.1AN tuning
```
