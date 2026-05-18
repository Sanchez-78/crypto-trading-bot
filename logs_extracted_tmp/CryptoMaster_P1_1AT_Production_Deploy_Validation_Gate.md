# CryptoMaster P1.1AT — Production Deploy & Validation Gate

## Current State

```text
P1.1AS: COMPLETE / deployed / validated
P1.1AT: COMPLETE / commit 27b41c9 / ready for production deploy
P1.1AN: LOCKED
Patch expansion: FROZEN
```

P1.1AT fixes the confirmed paper sampler reservation bug:

```text
Before:
rate-cap slots were consumed before a real PAPER_TRAIN_ENTRY existed.

After:
rate-cap slots are committed only after successful paper position creation and persistence.
```

---

## Absolute Rule

Do not implement any new patch after P1.1AT unless production validation proves the surgical fix failed.

Forbidden now:

```text
- new diagnostics
- economic tuning
- attribution changes
- dashboards
- strategy changes
- TP/SL changes
- live/real changes
```

Allowed now:

```text
- deploy P1.1AT
- audit production
- collect training samples
- wait for P1.1AN gate
```

---

## Production Deploy Commands

Run on server:

```bash
cd /opt/cryptomaster

git fetch origin main
git pull --ff-only origin main
git rev-parse --short HEAD
```

Expected:

```text
27b41c9
```

Restart service:

```bash
sudo systemctl restart cryptomaster
sleep 90
sudo systemctl status cryptomaster --no-pager
```

Check current PID and HEAD:

```bash
PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
git rev-parse --short HEAD
```

---

## Immediate Validation

Run:

```bash
cd /opt/cryptomaster
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

---

## PASS Criteria

P1.1AT passes if audit shows:

```text
Git HEAD: 27b41c9
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

And sampler state no longer shows the old contradiction:

```text
recent_entries = 3
rate_limit = 3
PAPER_TRAIN_ENTRY_REAL = 0
open_total = 0
closed_training = 0
```

Correct behavior:

```text
recent_entries tracks successful real entries only
phantom gate passes do not consume slots
rate-cap blocks only after actual entries
```

---

## Acceptable Temporary State

If immediately after restart there are not enough entries yet, this is acceptable for a short window:

```text
PAPER_TRAIN_ENTRY_REAL = 0
recent_entries = 0
rate-cap not blocking
```

In that case, rerun after several minutes:

```bash
bash scripts/p11ag_quality_audit.sh --since "60 min ago"
bash scripts/p11as_sampler_state_check.sh --since "60 min ago"
```

---

## FAIL Criteria

Hard fail if the old contradiction returns:

```text
PAPER_TRAIN_ENTRY_REAL = 0
open_total = 0
closed_training = 0
recent_entries = 3
rate_limit = 3
sampler_rate_cap drops > 0
```

If this happens:

```text
STOP.
Do not add diagnostics.
Inspect the rate-cap accounting function directly.
Find every write to _entry_times_minute and _entry_times_hour.
There must be no pre-entry append path.
```

Useful grep:

```bash
grep -R "_entry_times_minute\|_entry_times_hour\|commit_training_sampler_rate_slot" -n src tests
```

---

## After PASS

Do nothing except collect samples.

Run periodic audit:

```bash
cd /opt/cryptomaster
bash scripts/p11ag_quality_audit.sh --since "120 min ago"
```

Wait until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution > 50%
```

Only then P1.1AN can be considered.

---

## P1.1AN Gate

Current status:

```text
TUNE_ALLOWED = NO
```

P1.1AN remains blocked until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
dominant attribution > 50%
```

If attribution remains tied or sample is below 10:

```text
No tuning.
Keep collecting.
```

---

## Final Operator Summary

```text
1. Deploy 27b41c9.
2. Run 45-minute audit.
3. Confirm no phantom rate-cap reservations.
4. If entries flow, stop patching.
5. Let bot collect >=10 closed training trades.
6. Return to P1.1AN only after gate passes.
```
