# CryptoMaster — P1.1AS Production Validation

## Status

P1.1AS completed.

Commit:

```bash
d7d7850
```

Purpose:

```text
Diagnostic consistency patch only.
No trading tuning.
No EV changes.
No TP/SL changes.
No live/real behavior changes.
```

---

## What P1.1AS Fixed

Production contradiction before P1.1AS:

```text
sampler_rate_cap drops:          12
PAPER_SAMPLER_RATE_CAP_STATE:    0
COST_EDGE_BYPASS_ACCEPTED:       0
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT: 3
```

Root cause:

```text
_training_quality_gate() logged rate-cap state before open_symbol/open_bucket/open_total were computed.
The try/except silently swallowed the failure.
```

P1.1AS fix:

```text
open_symbol/open_bucket/open_total are now computed before rate-cap checks.
Rate-cap drops now include state diagnostics.
flow_id is included in drop logs.
Audit correlation counters are made logically consistent.
```

---

## Deploy Commands

Run on production server:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD
git merge-base --is-ancestor d7d7850 HEAD && echo "OK P1.1AS deployed" || echo "BAD P1.1AS missing"

sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
```

---

## Main Validation

Run:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
```

Then run the new state checker:

```bash
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

Manual trace:

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "COST_EDGE_BYPASS_FLOW|COST_EDGE_BYPASS_ACCEPTED|PAPER_ENTRY_ATTEMPT|PAPER_TRAIN_ENTRY|PAPER_ENTRY_DROPPED_AFTER_ACCEPT|PAPER_SAMPLER_RATE_CAP_STATE" \
| tail -200
```

---

## Expected Result Categories

### State A — Legitimate Rate Cap

```text
sampler_rate_cap > 0
PAPER_SAMPLER_RATE_CAP_STATE > 0
recent_entries >= rate_limit
next_allowed_s > 0 and reasonable
```

Decision:

```text
No patch.
Wait until next_allowed_s expires.
Rerun audit.
```

---

### State B — Stale Rate Cap

```text
sampler_rate_cap > 0
PAPER_SAMPLER_RATE_CAP_STATE > 0
recent_entries < rate_limit
or next_allowed_s is invalid, huge, negative, or impossible
```

Decision:

```text
P1.1AT needed: stale sampler rate-cap cleanup.
```

---

### State C — Accepted Disappears Before Entry

```text
COST_EDGE_BYPASS_ACCEPTED > 0
ACCEPTED_WITHOUT_ENTRY > 0
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT = 0
```

Decision:

```text
P1.1AT needed: accepted-to-entry control-flow fix.
```

---

### State D — Attempt Exists But No Entry

```text
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT > 0
PAPER_TRAIN_ENTRY_REAL = 0
PAPER_ENTRY_DROPPED_AFTER_ACCEPT > 0
```

Decision:

```text
Patch based only on actual drop reason.
```

---

### State E — Flow Restored

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_EXIT appears after timeout
LM_STATE_AFTER_UPDATE increments
```

Decision:

```text
No tuning.
Continue collecting trades for P1.1AN.
P1.1AN still blocked until closed_training_trades >= 10 and attribution dominance is clear.
```

---

## Hard Stop Rules

Do not implement P1.1AT unless the audit proves one exact blocker.

Do not implement P1.1AN unless:

```text
closed_training_trades >= 10
quality_entry_mismatch == 0
quality_exit_missing == 0
lm_update_mismatch == 0
one attribution dominates clearly > 50%
```

---

## Quick Interpretation Checklist

After audit, check these lines first:

```text
PAPER_TRAIN_ENTRY_REAL
COST_EDGE_BYPASS_FLOW_CANDIDATE
COST_EDGE_BYPASS_FLOW_DROP
sampler_rate_cap
PAPER_SAMPLER_RATE_CAP_STATE
COST_EDGE_BYPASS_ACCEPTED
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT
ENTRY_ATTEMPT_WITHOUT_ACCEPT
ACCEPTED_WITHOUT_ENTRY
PAPER_ENTRY_DROPPED_AFTER_ACCEPT
LM_STATE_AFTER_UPDATE
```

Best outcome:

```text
PAPER_TRAIN_ENTRY_REAL > 0
QUALITY_ENTRY count matches entries
LM_STATE_AFTER_UPDATE increments after exits
```

Worst diagnostic outcome:

```text
sampler_rate_cap > 0
PAPER_SAMPLER_RATE_CAP_STATE = 0
```

That means P1.1AS did not fully close the diagnostic gap.
