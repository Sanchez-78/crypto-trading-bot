---
name: runtime-log-forensics
description: |
  Extracts runtime evidence from logs and state files for CryptoMaster trading 
  bot. Collects journalctl entries, JSON position snapshots, SQLite trade records. 
  Correlates by timestamp. Separates observed facts from hypotheses. Used when 
  debugging position timeouts, state corruption, signal quality, Firebase quota 
  issues, or any runtime anomaly—always cite exact log lines and file:line code paths.

---

# Runtime Log Forensics Skill

## Purpose

Conduct evidence-based runtime investigations without speculation. Every claim tied to concrete log lines, state dumps, or code execution paths.

## Workflow

### Step 1: Collect Runtime Evidence

**From journalctl (systemd logs):**
```bash
ssh root@hetzner "journalctl -u cryptomaster.service -n 1000 --no-pager | grep -E '[TIMESTAMP_START]|[TIMESTAMP_END]' > /tmp/logs.txt"
```

**From state files:**
- JSON: `/data/paper_open_positions.json` (positions snapshot)
- SQLite: `local_learning_storage/learning_database.sqlite` (trade records)
- Files: Check modification times and content diffs

**From code path:**
- Source file location (e.g., `src/services/paper_trade_executor.py:1556`)
- Function that was executing
- Variables in scope at that moment

### Step 2: Timeline Reconstruction

**Build a timeline by UTC timestamp:**

```
2026-06-08 08:20:38.123 [PAPER_ENTRY] BTCUSDT BUY price=63062.77 trade_id=paper_05e5a608f9b5
2026-06-08 08:20:39.456 [UPDATE_POSITIONS] 1 position, age_s=1.3, price=63075.01
2026-06-08 08:20:40.789 [UPDATE_POSITIONS] 1 position, age_s=2.6, price=63088.00
...
2026-06-08 08:21:38.xxx [TIMEOUT_EVAL] BTCUSDT age=60.0s >= hold=300s? NO
2026-06-08 08:22:38.xxx [TIMEOUT_EVAL] BTCUSDT age=120.0s >= hold=300s? NO
2026-06-08 08:30:38.xxx [TIMEOUT_EVAL] BTCUSDT age=600.0s >= hold=300s? YES → CLOSE
```

### Step 3: Correlate Observations

**State at entry time T0:**
- Position dict keys: `max_hold_s`, `timeout_s`, `training_bucket`, etc.
- Values from JSON snapshot at T0

**Execution path at closure T1:**
- Code line `age_s >= effective_hold` evaluates to true
- `effective_hold` value = ? (add debug logging if not visible)
- `timeout_s` value = ? (from position dict at T1)

**Cross-check:**
- Does the effective_hold match timeout_s or max_hold_s?
- If different, which code path created the discrepancy?

### Step 4: Distinguish Fact From Hypothesis

**FACT (Observable):**
- Log line with exact timestamp: `2026-06-08 08:30:38.123 [TIMEOUT_EVAL] BTCUSDT age=600s >= hold=300s`
- Position field: `"max_hold_s": 300`
- Code execution: File `src/services/paper_trade_executor.py` line 1556 called `_effective_paper_hold_s(pos)`

**HYPOTHESIS (Inference):**
- "Because max_hold_s=300, the timeout must be capped at 300" ← Claim needs log proof
- "The learning tuner set max_hold_s=300" ← Claim needs learning DB entry + timestamp proof

**Acceptable hypothesis if**:
- Supported by multiple facts (logs + code + state)
- Explicitly flagged as hypothesis, not fact

### Step 5: Generate Forensic Report

Report template:

```
## Forensic Investigation: [Symptom]

**Symptom:** Positions closing at 300s instead of 600s

**Evidence Window:** 2026-06-08 08:20:38 → 08:30:50 UTC (10+ min)

### Log Evidence

[Show exact log lines with timestamps and citations]

```
Jun 08 08:20:38: [PAPER_ENTRY] BTCUSDT side=BUY price=63062.77 trade_id=paper_05e5a608f9b5
Jun 08 08:20:38: CREATED position dict with keys: {trade_id, symbol, max_hold_s=300, timeout_s=600, ...}
Jun 08 08:30:38: [TIMEOUT_EVAL] BTCUSDT age=600.0s >= hold=300.0s, closing
```

### State Evidence

**Position snapshot at T0 (creation):**
```json
{
  "trade_id": "paper_05e5a608f9b5",
  "symbol": "BTCUSDT",
  "entry_ts": 1780906838.78,
  "max_hold_s": 300,
  "timeout_s": 600,
  "training_bucket": "A_STRICT_TAKE"
}
```

**Finding:** Position has `max_hold_s=300` AND `timeout_s=600`—two different values!

### Code Path Evidence

**File: `src/services/paper_trade_executor.py`**

Line 1556:
```python
effective_hold = _effective_paper_hold_s(pos)  # Returns 300
```

Line 1573:
```python
elif age_s >= effective_hold:  # Uses effective_hold=300, not timeout_s=600
    exit_reason = "TIMEOUT"
```

**Root Cause:** Code uses `effective_hold` (300) instead of `timeout_s` (600).

### Findings (Facts Only)

1. **Observation:** Positions close after exactly 300 seconds
   - **Evidence:** Log lines at 08:30:38 (600s after 08:20:38 entry) show `[TIMEOUT_EVAL] ... age=600.0s >= hold=300.0s`
   - **Code path:** `src/services/paper_trade_executor.py:1573` uses `effective_hold` variable

2. **Observation:** Position dict has two conflicting timeout fields
   - **Evidence:** JSON snapshot shows `"max_hold_s": 300, "timeout_s": 600`
   - **Root cause:** Function `_effective_paper_hold_s()` returns 300 for this position

3. **Hypothesis (requires proof):** Timeout logic uses wrong variable
   - **Supported by:** Code path + state evidence + log timeline
   - **Needs:** Confirm `_effective_paper_hold_s()` returns 300 (add debug logging if not visible)

### Remaining Questions

- Why does `_effective_paper_hold_s()` return 300 when `timeout_s=600`?
  → **Answer:** Code checks `bucket == "C_WEAK_EV_TRAIN"` and caps at 300; `A_STRICT_TAKE` should return 600

- Is `max_hold_s=300` set at creation or loaded from JSON?
  → **Answer:** Set at creation in `trade_executor.py` line 2866, uses `PAPER_TRAINING_MAX_HOLD_S` env var

## Forensic Commands (CryptoMaster-Specific)

### Collect logs
```bash
journalctl -u cryptomaster.service --since "2026-06-08 08:00:00" --until "2026-06-08 08:35:00" -n 10000 > /tmp/forensics.log
grep -E '\[PAPER_ENTRY\]|\[TIMEOUT_EVAL\]|\[PAPER_EXIT\]' /tmp/forensics.log
```

### Dump position state
```bash
python3 -c "import json; f=open('data/paper_open_positions.json'); d=json.load(f); print(json.dumps(d.get('paper_05e5a608f9b5', {}), indent=2))"
```

### Check learning DB
```bash
sqlite3 local_learning_storage/learning_database.sqlite "SELECT trade_id, exit_reason, hold_s, max_hold_s FROM trades WHERE created_at > 1780906838 ORDER BY created_at LIMIT 10;"
```

### Trace code path
```bash
grep -n "effective_hold\|_effective_paper_hold_s" src/services/paper_trade_executor.py
```

## Key Rules

✅ DO:
- Cite exact log lines with timestamps
- Include file:line code references
- Show state snapshots (JSON/DB content)
- Distinguish facts from hypotheses
- Flag any gaps in evidence

❌ DON'T:
- Recommend patches without concrete evidence
- Assume causality without timeline proof
- Skip missing data ("probably didn't matter")
- Trust logs beyond 15-min retention window
- Mix facts and hypotheses without clear labels
