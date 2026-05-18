# CryptoMaster — P1.1AR Production Deploy & Validation

## Status

P1.1AR is implemented and pushed.

Commit:

```bash
7ce11ec
```

Purpose:

```text
Diagnostic-only tracing for:
1. sampler_rate_cap legitimacy
2. accepted bypass candidate → entry attempt → final paper entry/drop correlation
```

No trading behavior should change.

---

## Hard Rules

Do not tune P1.1AN yet.

Do not change:

- live/real execution
- EV calculation
- TP/SL geometry
- cost-edge rules
- learning update semantics
- negative-EV probe behavior

P1.1AR only answers where the flow is blocked.

---

## Production Deploy Commands

Run on Hetzner:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD
git merge-base --is-ancestor 7ce11ec HEAD && echo "OK P1.1AR deployed" || echo "BAD P1.1AR missing"

sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "45 min ago"
```

Optional core flow view:

```bash
bash scripts/p11ak_core_flow_viewer_cs.sh --since "45 min ago"
```

---

## Expected New Audit Sections

P1.1AR should add/extend:

```text
Accepted-to-Entry Correlation
Sampler Rate-Cap State
Candidate-to-Entry Flow
Bypass Drop Reasons
```

Look specifically for:

```text
COST_EDGE_BYPASS_ACCEPTED
PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT
ACCEPTED_WITHOUT_ENTRY
PAPER_ENTRY_DROPPED_AFTER_ACCEPT
PAPER_SAMPLER_RATE_CAP_STATE
sampler_rate_cap
```

---

## Key Interpretation

### PASS A — Flow restored

Condition:

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_EXIT appears after timeout
LM_STATE_AFTER_UPDATE increments
```

Meaning:

```text
P1.1AR confirms flow is healthy. No fix needed yet.
Continue collecting trades until P1.1AN gate reaches >=10 closed training trades.
```

---

### PASS B — Rate cap is legitimate

Condition:

```text
Bypass Drop Reasons:
sampler_rate_cap > 0

PAPER_SAMPLER_RATE_CAP_STATE shows:
recent_entries >= rate_limit
next_allowed_s > 0
```

Meaning:

```text
The sampler is blocking correctly.
No stale state bug.
Wait until next_allowed_s expires, then rerun audit.
```

Next action:

```bash
bash scripts/p11ag_quality_audit.sh --since "90 min ago"
```

---

### FAIL C — Rate cap is stale

Condition:

```text
sampler_rate_cap > 0

but PAPER_SAMPLER_RATE_CAP_STATE shows:
recent_entries < rate_limit
or next_allowed_s is negative/impossible/very large
or open counters are inconsistent with actual paper_open_positions.json
```

Meaning:

```text
P1.1AS should fix stale rate-cap state.
Likely issue: old timestamps, stale in-memory sampler state, or persisted open positions not cleaned.
```

Next patch:

```text
P1.1AS — stale sampler rate-cap state cleanup
```

---

### FAIL D — Accepted but no entry attempt

Condition:

```text
COST_EDGE_BYPASS_ACCEPTED > PAPER_ENTRY_ATTEMPT_AFTER_ACCEPT
ACCEPTED_WITHOUT_ENTRY > 0
```

Meaning:

```text
Accepted candidate disappears before open_paper_position / entry attempt.
Likely issue: downstream control flow returns early after acceptance.
```

Next patch:

```text
P1.1AS — accepted-to-entry control-flow fix
```

---

### FAIL E — Attempted but dropped after accept

Condition:

```text
PAPER_ENTRY_DROPPED_AFTER_ACCEPT > 0
```

Meaning:

```text
Entry attempt occurs but another gate blocks after acceptance.
Use the drop reason to target the next patch.
```

Possible next patches:

```text
sampler_max_open_per_symbol → inspect stale open positions / per-symbol cap
sampler_max_open_per_bucket → inspect bucket cap and close logic
sampler_rate_cap → inspect rate state
duplicate_candidate → inspect duplicate marker timing
```

---

## Useful Manual Greps

### Flow trace

```bash
PID=$(systemctl show -p MainPID --value cryptomaster)

sudo journalctl -u cryptomaster --since "45 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "COST_EDGE_BYPASS_FLOW|COST_EDGE_BYPASS_ACCEPTED|PAPER_ENTRY_ATTEMPT|PAPER_TRAIN_ENTRY|PAPER_ENTRY_DROPPED_AFTER_ACCEPT|PAPER_SAMPLER_RATE_CAP_STATE" \
| tail -150
```

### Rate-cap only

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep "PAPER_SAMPLER_RATE_CAP_STATE" \
| tail -50
```

### Accepted without entry

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "COST_EDGE_BYPASS_ACCEPTED|PAPER_ENTRY_ATTEMPT|PAPER_TRAIN_ENTRY" \
| tail -100
```

---

## Current Expected Decision

Based on the previous audit before P1.1AR:

```text
COST_EDGE_BYPASS_FLOW_CANDIDATE: 14
COST_EDGE_BYPASS_FLOW_DROP:      9
sampler_rate_cap:                9
COST_EDGE_BYPASS_ACCEPTED:       1
PAPER_TRAIN_ENTRY_REAL:          0
```

Most likely next diagnosis:

```text
Either:
A) sampler_rate_cap is legitimate and the system simply needs time, or
B) one accepted candidate is disappearing before PAPER_TRAIN_ENTRY.
```

P1.1AR should now distinguish A vs B directly.

---

## Next Output to Paste Back

After deploy, paste the full audit section containing:

```text
Candidate-to-Entry Flow
Bypass Drop Reasons
Accepted-to-Entry Correlation
Sampler Rate-Cap State
Cold-Start Starvation
Sample logs
```

Then the next patch can be chosen safely:

```text
P1.1AS = only if stale cap or accepted-to-entry disappearance is proven.
P1.1AN = only after >=10 closed training trades and clear dominant attribution.
```
