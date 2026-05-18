# CryptoMaster — P1.1AS Prompt for Claude Code

## Goal

Implement **P1.1AS** as a diagnostic/consistency patch for the paper-training candidate flow.

P1.1AR proved that candidates are generated, but the flow is still not producing paper entries:

```text
HEAD: 7ce11ec
PAPER_TRAIN_ENTRY_REAL:           0
COST_EDGE_BYPASS_FLOW_CANDIDATE:  13
COST_EDGE_BYPASS_FLOW_DROP:       12
sampler_rate_cap:                 12
COST_EDGE_BYPASS_ACCEPTED:        0
PAPER_ENTRY_ATTEMPT:              3
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT: 3
PAPER_SAMPLER_RATE_CAP_STATE:     0
```

Critical contradiction:

```text
sampler_rate_cap drops exist, but PAPER_SAMPLER_RATE_CAP_STATE = 0.
```

Second contradiction:

```text
COST_EDGE_BYPASS_ACCEPTED = 0
but PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT = 3.
```

This means P1.1AS must first fix instrumentation consistency and expose exact rate-cap state. Do **not** tune trading logic yet.

---

## Hard Scope

Allowed:

- Bash audit script fixes
- Diagnostic logging fixes
- Flow/correlation log consistency fixes
- Read-only paper sampler state inspection helper
- Regression tests for diagnostics

Forbidden:

- Do not change live/real trading behavior
- Do not change EV calculation
- Do not change TP/SL geometry
- Do not change cost-edge acceptance rules
- Do not loosen/tighten sampler caps yet
- Do not implement P1.1AN
- Do not route more trades until the rate-cap state is understood

---

## Observed Production Evidence

Latest audit:

```text
Git HEAD: 7ce11ec
Since: 45 min ago

PAPER_TRAIN_ENTRY_REAL:           0
COST_EDGE_BYPASS:                 25
COST_EDGE_BYPASS_CANDIDATE:       0
COST_EDGE_BYPASS_ACCEPTED:        0

COST_EDGE_BYPASS_FLOW_CANDIDATE:  13
COST_EDGE_BYPASS_FLOW_DROP:       12
PAPER_ENTRY_ATTEMPT:              3
PAPER_ENTRY_DROPPED_AFTER_ACCEPT: 0

sampler_rate_cap:                 12
PAPER_SAMPLER_RATE_CAP_STATE:     0

STARVATION_STATE_LOGS:            1
NEG_EV_PROBE_ACCEPTED:            0
```

Sample logs show repeated:

```text
[COST_EDGE_BYPASS_FLOW] stage=candidate ... flow_id=...
[COST_EDGE_BYPASS_FLOW] stage=drop ... reason=sampler_rate_cap ...
```

But no matching:

```text
[PAPER_SAMPLER_RATE_CAP_STATE]
```

---

## Diagnosis

P1.1AR found the likely blocker:

```text
sampler_rate_cap is dominant.
```

But it did **not** prove whether the cap is legitimate or stale because the rate-cap state log is missing.

The next patch must answer:

```text
When sampler_rate_cap rejects:
- how many recent entries are counted?
- what is the rate limit?
- what timestamps are in the window?
- how long until next slot?
- are counted entries from current PID/session or stale persisted state?
- are accepted/attempt counters being correlated correctly?
```

---

## Required Changes

### 1. Always emit rate-cap state on sampler_rate_cap drop

Find the path that logs:

```text
[COST_EDGE_BYPASS_FLOW] stage=drop reason=sampler_rate_cap
```

Ensure it also emits:

```text
[PAPER_SAMPLER_RATE_CAP_STATE]
```

at the same decision point.

Required fields:

```text
symbol=<symbol>
side=<side>
bucket=<bucket>
source=<source>
flow_id=<flow_id>
reason=sampler_rate_cap
recent_entries=<n>
rate_limit=<limit>
window_s=<window_seconds>
next_allowed_s=<seconds>
oldest_entry_age_s=<seconds|na>
newest_entry_age_s=<seconds|na>
open_symbol=<n>
open_bucket=<n>
open_total=<n>
closed_training=<n>
pid_session=<session_id|boot_ts>
```

Rules:

- Throttle is allowed, but must not suppress all logs in a validation window.
- Throttle key should include `(symbol, bucket, reason)`.
- First rate-cap drop after boot must always log state.
- If state cannot be computed, log `state_error=<error>` instead of failing silently.

---

### 2. Make rate-cap decision return structured state

If current rate-cap check returns only `allowed=False, reason="sampler_rate_cap"`, extend it to return diagnostic context.

Example structure:

```python
{
    "allowed": False,
    "reason": "sampler_rate_cap",
    "recent_entries": recent_entries,
    "rate_limit": rate_limit,
    "window_s": window_s,
    "next_allowed_s": next_allowed_s,
    "oldest_entry_age_s": oldest_age,
    "newest_entry_age_s": newest_age,
}
```

Do not change the actual pass/fail decision.

---

### 3. Fix accepted-to-entry audit contradiction

Current audit showed:

```text
COST_EDGE_BYPASS_ACCEPTED:        0
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT: 3
ACCEPTED_WITHOUT_ENTRY:           0
```

This is logically inconsistent.

Fix `scripts/p11ag_quality_audit.sh` so:

- `PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT` is counted only when a `PAPER_ENTRY_ATTEMPT` line has an accepted/bypass flow marker or matching `flow_id` with a prior `COST_EDGE_BYPASS_ACCEPTED`.
- If `COST_EDGE_BYPASS_ACCEPTED = 0`, then `PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT` must be 0 unless the script explicitly prints `CORRELATION_UNVERIFIED`.
- Add derived counter:

```text
ENTRY_ATTEMPT_WITHOUT_ACCEPT
```

Meaning:

```text
PAPER_ENTRY_ATTEMPT exists, but no matching COST_EDGE_BYPASS_ACCEPTED by flow_id.
```

This is diagnostic-only.

---

### 4. Include flow_id in every related drop log

Current drop logs often do not include `flow_id`:

```text
[COST_EDGE_BYPASS_FLOW] stage=drop symbol=XRPUSDT reason=sampler_rate_cap source=...
```

Add:

```text
flow_id=<same flow_id as candidate>
```

to all drop paths:

- sampler_rate_cap
- sampler_max_open_per_symbol
- sampler_max_open_per_bucket
- duplicate_candidate
- any future drop reason

This allows reliable correlation.

---

### 5. Add optional state inspection script

Create:

```text
scripts/p11as_sampler_state_check.sh
```

Read-only.

It should print:

```text
Git HEAD
systemd PID
service start time
paper_open_positions.json existence/size
open paper positions count
open positions by symbol
open positions by bucket/training_bucket
candidate/rate-cap related journal counters for current PID
last 20 rate-cap state logs
last 20 candidate/drop/accepted/attempt logs
```

Must be safe if files are missing.

No writes.

---

## Audit Script Required Output

Update `scripts/p11ag_quality_audit.sh` to include:

```text
Sampler Rate-Cap State:
-------
PAPER_SAMPLER_RATE_CAP_STATE:      <n>
RATE_CAP_STATE_WITH_ERROR:         <n>
RATE_CAP_WITHOUT_STATE:            <n>

Accepted-to-Entry Correlation:
-------
COST_EDGE_BYPASS_ACCEPTED:         <n>
PAPER_ENTRY_ATTEMPT:               <n>
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT:  <n>
ENTRY_ATTEMPT_WITHOUT_ACCEPT:      <n>
ACCEPTED_WITHOUT_ENTRY:            <n>
PAPER_ENTRY_DROPPED_AFTER_ACCEPT:  <n>
CORRELATION_UNVERIFIED:            <n>
```

Diagnostic interpretation:

```text
IF sampler_rate_cap > 0 AND PAPER_SAMPLER_RATE_CAP_STATE = 0:
  FAIL: RATE_CAP_STATE_MISSING

IF sampler_rate_cap > 0 AND RATE_CAP_WITHOUT_STATE > 0:
  FAIL: RATE_CAP_DROP_WITHOUT_STATE

IF ENTRY_ATTEMPT_WITHOUT_ACCEPT > 0:
  WARN: ENTRY_ATTEMPT_NOT_CORRELATED_TO_ACCEPT

IF COST_EDGE_BYPASS_ACCEPTED = 0 AND PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT > 0:
  FAIL: AUDIT_CORRELATION_BUG
```

---

## Tests Required

Add regression tests. Keep existing 187 tests passing.

Minimum new tests:

1. Rate-cap drop emits `PAPER_SAMPLER_RATE_CAP_STATE`.
2. First rate-cap drop after boot is never throttled.
3. Rate-cap state includes recent_entries/rate_limit/window_s/next_allowed_s.
4. Drop logs include flow_id.
5. `PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT` is zero when no accepted flow exists.
6. `ENTRY_ATTEMPT_WITHOUT_ACCEPT` increments for orphan attempts.
7. `ACCEPTED_WITHOUT_ENTRY` increments only when accepted flow_id has no attempt/entry.
8. Audit script does not print contradictory accepted/attempt counters.
9. `p11as_sampler_state_check.sh` passes `bash -n`.
10. Live/real behavior unchanged.

Run:

```bash
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
bash -n scripts/p11as_sampler_state_check.sh
```

---

## Pass Criteria After P1.1AS

Production audit must clearly land in one of these states:

### State A — Legitimate rate cap

```text
sampler_rate_cap > 0
PAPER_SAMPLER_RATE_CAP_STATE > 0
recent_entries >= rate_limit
next_allowed_s > 0 and reasonable
```

Action:

```text
No code change. Wait until next_allowed_s expires and rerun audit.
```

### State B — Stale rate cap

```text
sampler_rate_cap > 0
PAPER_SAMPLER_RATE_CAP_STATE > 0
recent_entries < rate_limit
or next_allowed_s invalid/huge/negative
```

Action:

```text
Next patch P1.1AT: stale sampler rate-cap cleanup.
```

### State C — Accepted disappears before attempt

```text
COST_EDGE_BYPASS_ACCEPTED > 0
ACCEPTED_WITHOUT_ENTRY > 0
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT = 0
```

Action:

```text
Next patch P1.1AT: accepted-to-entry control-flow fix.
```

### State D — Attempt exists but no entry

```text
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT > 0
PAPER_TRAIN_ENTRY_REAL = 0
PAPER_ENTRY_DROPPED_AFTER_ACCEPT > 0
```

Action:

```text
Patch based on actual drop reason.
```

### State E — Flow restored

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_EXIT appears after timeout
LM_STATE_AFTER_UPDATE increments
```

Action:

```text
Continue collecting trades for P1.1AN.
Do not tune until closed_training_trades >= 10 and attribution dominance is clear.
```

---

## Production Validation Commands

After merge/deploy:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD

sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

Manual grep:

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "COST_EDGE_BYPASS_FLOW|COST_EDGE_BYPASS_ACCEPTED|PAPER_ENTRY_ATTEMPT|PAPER_TRAIN_ENTRY|PAPER_ENTRY_DROPPED_AFTER_ACCEPT|PAPER_SAMPLER_RATE_CAP_STATE" \
| tail -200
```

---

## Final Instruction

Implement P1.1AS as a **diagnostic consistency patch**.

Do not tune.

Do not relax caps.

Do not add new training routes.

The only objective is to make the next audit mathematically consistent and prove whether `sampler_rate_cap` is legitimate or stale.
