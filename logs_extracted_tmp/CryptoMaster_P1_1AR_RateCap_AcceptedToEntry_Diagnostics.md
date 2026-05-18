# CryptoMaster P1.1AR — Rate-Cap / Accepted-to-Entry Diagnostic Patch

## Situation

Production after P1.1AQ:

```text
Git HEAD: 2139ab3
P1.1AQ deployed: YES

PAPER_TRAIN_ENTRY_REAL: 0
PAPER_TRAIN_QUALITY_ENTRY: 0
COST_EDGE_BYPASS: 24
COST_EDGE_BYPASS_ACCEPTED: 1

COST_EDGE_BYPASS_FLOW_CANDIDATE: 14
COST_EDGE_BYPASS_FLOW_DROP: 9

Bypass Drop Reasons:
sampler_rate_cap: 9
sampler_max_open_per_symbol: 0
sampler_max_open_per_bucket: 0
duplicate_candidate: 0
```

Sample flow:

```text
[COST_EDGE_BYPASS_FLOW] stage=candidate symbol=ADAUSDT ...
[COST_EDGE_BYPASS_ACCEPTED] symbol=ADAUSDT open_symbol=0 open_bucket=0 open_total=0
```

But no matching:

```text
[PAPER_TRAIN_ENTRY]
[PAPER_TRAIN_QUALITY_ENTRY]
```

## Diagnosis

P1.1AQ proves:

1. Candidate flow exists.
2. Most candidates are blocked by `sampler_rate_cap`.
3. The blocker is not per-symbol cap, bucket cap, or duplicate gate.
4. There is at least one accepted bypass candidate that does not become a paper training entry.

This means P1.1AR should **not tune strategy economics** yet.

P1.1AR should be diagnostic-first and answer two precise questions:

```text
A. Is sampler_rate_cap too strict / stale / miscounting?
B. Where does an accepted bypass candidate disappear before PAPER_TRAIN_ENTRY?
```

---

## Hard Scope

Diagnostics + safe rate-cap introspection only.

Do not change:

```text
live/real trading
RDE EV logic
TP/SL geometry
learning attribution
P1.1AN economic tuning
cost_edge bypass acceptance criteria
```

Allowed:

```text
paper_train-only diagnostics
rate-cap state logging
accepted-to-entry correlation
audit script counters
tests
```

---

## Target Files

Likely files:

```text
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
scripts/p11ag_quality_audit.sh
tests/test_paper_mode.py
```

Only touch files actually needed after code inspection.

---

## Required Implementation

### 1. Add sampler rate-cap state log

When a candidate is dropped due to `sampler_rate_cap`, emit:

```text
[PAPER_SAMPLER_RATE_CAP_STATE]
symbol=<symbol>
bucket=<bucket>
source=<source>
reason=sampler_rate_cap
now=<ts>
window_s=<window>
recent_entries=<n>
rate_limit=<limit>
next_allowed_s=<seconds>
open_symbol=<n>
open_bucket=<n>
open_total=<n>
closed_training=<n>
mode=paper_train
```

Purpose:

```text
Tell whether rate cap is genuinely active or stale/miscalculated.
```

Requirements:

```text
Throttle: 10s per (symbol, bucket, reason)
Paper_train only
No behavior change
```

---

### 2. Correlate accepted bypass to entry attempt

When `[COST_EDGE_BYPASS_ACCEPTED]` is emitted, generate or expose a correlation id.

Preferred:

```text
flow_id=<short_stable_id>
```

Add same `flow_id` to all downstream logs:

```text
[COST_EDGE_BYPASS_ACCEPTED] flow_id=...
[PAPER_ENTRY_ATTEMPT] flow_id=...
[PAPER_ENTRY_BLOCKED] flow_id=...
[PAPER_TRAIN_ENTRY] flow_id=...
[PAPER_TRAIN_QUALITY_ENTRY] flow_id=...
```

If adding `flow_id` to existing logs is too invasive, use existing candidate identity:

```text
symbol + side + bucket + source + timestamp rounded to second
```

But prefer explicit `flow_id`.

---

### 3. Add accepted-without-entry diagnostic

After a bypass candidate is accepted, one of these must happen:

```text
[PAPER_TRAIN_ENTRY]
[PAPER_ENTRY_BLOCKED]
[PAPER_ENTRY_DROPPED_AFTER_ACCEPT]
```

Add a log when the accepted candidate does not reach entry creation:

```text
[PAPER_ENTRY_DROPPED_AFTER_ACCEPT]
flow_id=<id>
symbol=<symbol>
side=<side>
bucket=<bucket>
source=<source>
reason=<reason>
stage=<function_or_gate>
open_symbol=<n>
open_bucket=<n>
open_total=<n>
```

Possible reasons:

```text
missing_price
missing_side
missing_symbol
missing_bucket
invalid_size
paper_executor_reject
portfolio_gate_reject_after_accept
exception
unknown_after_accept
```

Do not silently swallow accepted candidates.

---

### 4. Audit script additions

Update `scripts/p11ag_quality_audit.sh`.

Add section:

```text
Accepted-to-Entry Correlation:
-------
COST_EDGE_BYPASS_ACCEPTED:          <n>
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT:   <n>
PAPER_ENTRY_DROPPED_AFTER_ACCEPT:   <n>
PAPER_TRAIN_ENTRY_AFTER_ACCEPT:     <n>
ACCEPTED_WITHOUT_ENTRY:             <n>
```

Add section:

```text
Sampler Rate-Cap State:
-------
PAPER_SAMPLER_RATE_CAP_STATE:       <n>
RATE_CAP_TOP_SYMBOLS:               ...
RATE_CAP_NEXT_ALLOWED_MAX_S:        ...
```

Diagnostic interpretation:

```text
if ACCEPTED > 0 and PAPER_TRAIN_ENTRY_AFTER_ACCEPT = 0:
  warn: accepted bypass candidates are not reaching paper entry

if sampler_rate_cap > 0:
  print top reason and next_allowed_s if available

if sampler_rate_cap is dominant and next_allowed_s is small:
  recommend waiting / extending audit window

if sampler_rate_cap is dominant and next_allowed_s is huge or stale:
  recommend P1.1AS stale-rate-cap fix
```

---

## Expected Result After P1.1AR

The next audit must classify the state into one of these:

### Case 1 — Rate cap legitimate

```text
sampler_rate_cap dominant
PAPER_SAMPLER_RATE_CAP_STATE shows recent_entries >= limit
next_allowed_s reasonable
```

Action:

```text
No code tuning.
Wait for rate window or run longer audit.
```

---

### Case 2 — Rate cap stale/miscalculated

```text
sampler_rate_cap dominant
recent_entries < limit OR next_allowed_s impossible/huge OR closed/open state inconsistent
```

Action:

```text
Create P1.1AS stale rate-cap fix.
```

---

### Case 3 — Accepted candidate dropped after accept

```text
COST_EDGE_BYPASS_ACCEPTED > 0
PAPER_ENTRY_DROPPED_AFTER_ACCEPT > 0
PAPER_TRAIN_ENTRY_AFTER_ACCEPT = 0
```

Action:

```text
Fix exact reason reported by PAPER_ENTRY_DROPPED_AFTER_ACCEPT.
```

---

### Case 4 — Flow restored

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
LM_STATE_AFTER_UPDATE increments after exits
```

Action:

```text
Leave bot running.
Continue collecting trades for P1.1AN.
```

---

## Tests Required

Add regression tests for:

1. `sampler_rate_cap` emits `[PAPER_SAMPLER_RATE_CAP_STATE]`.
2. Rate-cap log includes recent_entries, limit, next_allowed_s.
3. Rate-cap diagnostics are paper_train-only.
4. `COST_EDGE_BYPASS_ACCEPTED` includes correlation identity.
5. Accepted candidate followed by entry attempt logs attempt.
6. Accepted candidate dropped before entry logs `[PAPER_ENTRY_DROPPED_AFTER_ACCEPT]`.
7. Existing successful entry flow still logs `[PAPER_TRAIN_ENTRY]`.
8. Live/real modes do not emit probe/rate-cap training diagnostics.
9. Audit script parses new counters.
10. Existing P1.1AD–P1.1AQ tests remain passing.

Run:

```bash
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
```

---

## Production Validation

Deploy:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD
git merge-base --is-ancestor <P1_1AR_COMMIT> HEAD && echo "OK P1.1AR deployed" || echo "BAD P1.1AR missing"

sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
```

Audit:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
```

Focused logs:

```bash
PID=$(systemctl show -p MainPID --value cryptomaster)

sudo journalctl -u cryptomaster --since "45 min ago" --no-pager   | grep "cryptomaster\[$PID\]"   | grep -E "COST_EDGE_BYPASS_ACCEPTED|PAPER_SAMPLER_RATE_CAP_STATE|PAPER_ENTRY_ATTEMPT|PAPER_ENTRY_DROPPED_AFTER_ACCEPT|PAPER_ENTRY_BLOCKED|PAPER_TRAIN_ENTRY|PAPER_TRAIN_QUALITY_ENTRY|LM_STATE_AFTER_UPDATE"   | tail -220
```

---

## Do Not Implement Yet

Do not implement economic tuning.

Blocked until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution > 50%
```

Current state still blocks P1.1AN:

```text
closed_training_trades: <10
dominant attribution: not proven
```
