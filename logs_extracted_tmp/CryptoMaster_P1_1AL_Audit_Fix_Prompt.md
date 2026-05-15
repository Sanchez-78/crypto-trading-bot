# CryptoMaster P1.1AL — Fix Snapshot Audit Counter Bug + Validate P1.1AK Economics

## Context

P1.1AK is deployed on main as `bfaa0ca`. Live/real trading behavior must not change.

Production audit confirms the core diagnostics are mostly working:

- `PAPER_TRAIN_ENTRY_REAL = 2`
- `PAPER_TRAIN_QUALITY_ENTRY = 2`
- `PAPER_TRAIN_QUALITY_MISMATCH = 0`
- `QUALITY_EXIT_MISSING_BY_TRADE_ID = 0`
- `score_missing=False`
- SELL TP/SL normalization appears correct:
  - BTC SELL entry `80476.31265400`
  - TP `79510.59690215`
  - SL `81442.02840585`
- `expected_move_unit_mismatch` is correctly detected and corrected:
  - BTC ATR `22.84508368`
  - reported_pct `22.845`
  - corrected_pct `0.028`

New issue is isolated to the audit script:

```text
PAPER_TRAIN_QUALITY_EXIT:         0
0
PAPER_EXIT:                       0
0
LM_STATE_AFTER_UPDATE:            0
0
...
scripts/p11ag_quality_audit.sh: line 158: [: 0
0: integer expression expected
```

This means some count helper or command substitution returns multiline values like `0\n0`, breaking integer comparisons.

## Goal

Fix `scripts/p11ag_quality_audit.sh` only.

Do **not** change:

- trading logic
- RDE
- sampler logic
- paper execution economics
- TP/SL logic
- learning monitor logic
- live/real behavior

This patch is audit hardening only.

## Required Changes

### 1. Make all audit counters scalar integers

Every counter variable must contain exactly one integer line.

Implement or replace existing counter logic with a safe helper:

```bash
count_pattern() {
  local pattern="$1"
  local value
  value="$(printf '%s\n' "$SNAPSHOT" | grep -E "$pattern" | wc -l | tr -d '[:space:]')"

  case "$value" in
    ''|*[!0-9]*) echo 0 ;;
    *) echo "$value" ;;
  esac
}
```

If the current script uses multiple fallback count paths, remove duplicate echo paths. A count function must emit once and only once.

### 2. Add strict integer normalization

Before any numeric comparison, sanitize values:

```bash
to_int() {
  local v
  v="$(printf '%s\n' "$1" | head -n1 | tr -dc '0-9')"
  [ -n "$v" ] && echo "$v" || echo 0
}
```

Use normalized values before all comparisons:

```bash
PAPER_EXIT_COUNT="$(to_int "$PAPER_EXIT_COUNT")"

if [ "$PAPER_EXIT_COUNT" -gt 0 ]; then
  ...
fi
```

No comparison may operate on raw command output.

### 3. Prevent audit crashes

The script must never emit:

```text
integer expression expected
```

It must stay readable even if:

- journalctl returns malformed lines
- journalctl emits `Bad message`
- grep receives empty input
- counters are empty
- counters accidentally contain multiline output
- no logs exist for the current PID yet

### 4. Preserve P1.1AK behavior

Keep existing P1.1AK audit features:

- snapshot-based audit
- PID filtering
- service start metadata
- git HEAD output
- trade-id correlation
- `QUALITY_EXIT_MISSING_BY_TRADE_ID`
- cost-edge bypass counters
- economic summary counters
- quality exit matching
- LM state reporting

### 5. Add regression coverage

Add a lightweight test or script-level validation that simulates multiline counter output:

```text
0
0
```

Expected:

- normalized to `0`
- printed once
- no integer comparison crash

Also test positive counts:

```text
3
```

Expected:

- stays `3`
- printed once
- comparisons work

Possible test options:

- a shell test script under `tests/`
- a pytest that invokes helper logic through a temporary shell script
- minimal bash validation if the project does not currently test shell scripts

Keep it small and robust.

## Validation Commands

Run locally before commit:

```bash
bash -n scripts/p11ag_quality_audit.sh
pytest -q tests/test_paper_mode.py
```

If adding a shell-specific test:

```bash
pytest -q tests/test_p11ag_quality_audit.py
```

## Production Validation After Deploy

```bash
cd /opt/cryptomaster
git pull --ff-only
git rev-parse --short HEAD

sudo systemctl restart cryptomaster
sleep 10

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

## Pass Criteria Immediately After Restart

```text
No "integer expression expected"
No duplicated counter values like:
  0
  0

Every count is one scalar integer.
PAPER_TRAIN_ENTRY_REAL >= 1 after entries.
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY_REAL.
PAPER_TRAIN_QUALITY_MISMATCH = 0.
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0.
```

## Pass Criteria After 5–7 Minutes

Run again after paper positions can timeout:

```bash
bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

Expected:

```text
PAPER_EXIT_TRAINING_BUCKET >= 1
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET >= PAPER_EXIT_TRAINING_BUCKET
LM_STATE_AFTER_UPDATE or LEARNING_UPDATE ok=True present
Total trades in LM increments
PAPER_TRAIN_ECON_SUMMARY present
```

## Important

This is P1.1AL audit hardening only.

Do not tune strategy quality, TP/SL geometry, cost-edge bypass logic, RDE thresholds, or live/real behavior in this patch.
