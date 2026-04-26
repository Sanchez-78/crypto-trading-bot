# CryptoMaster SAFE_MODE Remaining Steps — Implementation Prompt

Use this as one copy-paste prompt for Claude Code / Codex. Implement remaining SAFE_MODE work now. Do not ask for confirmation.

## Goal

SAFE_MODE must be a real protective runtime state, not just a log message.

When Firebase quota/read/write degradation is active:
- new entries are blocked
- forced/random exploration is suppressed
- micro-trades are suppressed
- anti-deadlock TAKE paths are suppressed
- watchdog/self-heal may observe/log but must not escalate into new entries
- existing open positions must still be managed normally by `on_price`
- dashboard must clearly show SAFE_MODE, not only `TRENINK` / `AKTIVNI`

## Current completed work

Already completed earlier:
- `src/services/runtime_flags.py`
  - `is_db_degraded_safe_mode()`
  - `get_db_degraded_reason()`
  - `set_db_degraded_safe_mode()`
  - `get_dashboard_status()`
  - 60s SAFE_MODE throttled logging helpers
- `src/services/firebase_client.py`
  - quota exhaustion detection
  - `set_db_degraded_safe_mode(True, "quota_429")`
  - non-critical write skipping
  - `should_skip_noncritical_write()`
- `src/services/trade_executor.py`
  - `handle_signal()` blocks new entries when SAFE_MODE active
  - logs `TAKE_BLOCKED_SAFE_MODE`
- `src/services/signal_generator.py`
  - forced explore suppression implemented
- `bot2/main.py`
  - periodic dashboard SAFE_MODE status logging partly implemented

## Current live evidence

Observed live logs still show unsafe/incomplete behavior:

```text
STAV: TRENINK
WARNING:root:[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
WARNING:root:[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429 reason=quota_429
WARNING:src.core.anomaly:🚨 ANOMALY: STALL 34780s > 900s
WARNING:src.core.self_heal:SELF_HEAL: STALL (no trades 900s) → boosting exploration
[WATCHDOG] No trades for 600s → boosting exploration
[WATCHDOG] Critical idle (15min) → enabling micro-trades
decision=TAKE ... unblock=True anti_deadlock=False size×0.25
```

These must be fixed.

## Implementation order

Implement exactly in this order:

1. Dashboard SAFE_MODE override
2. Watchdog/self-heal suppression
3. Safe stall timestamp handling
4. Micro-trade + anti-deadlock suppression
5. Duplicate reason logging fix
6. Compile verification
7. Grep verification
8. Short status report

---

# STEP 1 — Dashboard SAFE_MODE override

Files likely:
- `bot2/main.py`
- `src/services/runtime_flags.py`
- dashboard/render/status helper modules if present

When SAFE_MODE is active, dashboard must show SAFE_MODE as the top-level state.

Expected dashboard fields/text:

```text
STAV: SAFE_MODE_FIREBASE_DEGRADED
ENTRIES: BLOCKED
REASON: quota_429
EXISTING POSITIONS: MANAGED NORMALLY
LAST DECISIONS: ADVISORY/CACHED ONLY
```

Rules:
- Never show only `TRENINK` or `AKTIVNI` while SAFE_MODE is active.
- Training/bootstrap info may still be shown, but subordinate:
  - `base_mode=TRENINK`
  - `safe_mode_overlay=ACTIVE`
- Last BUY/SELL decisions may stay visible, but must be clearly marked as non-executable:
  - `ADVISORY KUPUJ`
  - `ADVISORY PRODEJ`
  - `entries blocked by SAFE_MODE`
- Dashboard status should use existing `get_dashboard_status()` if available.
- Do not hide prices, learning info, or exit info.

Acceptance example:

```text
CRYPTOMASTER | 9h 40m | SAFE_MODE_FIREBASE_DEGRADED
SAFE_MODE: ACTIVE | entries=blocked | reason=quota_429
POSLEDNI ROZHODNUTI
BTC ADVISORY KUPUJ ... entries blocked by SAFE_MODE
STAV: SAFE_MODE_FIREBASE_DEGRADED (base=TRENINK, entries blocked, existing positions managed)
```

---

# STEP 2 — Watchdog/self-heal suppression

Files likely:
- `src/core/anomaly.py`
- `src/core/self_heal.py`
- `bot2/main.py`
- any watchdog/idle/unblock helper

Add SAFE_MODE checks before any escalation that can cause new entries.

During SAFE_MODE:
- allowed:
  - detect stall
  - log stall
  - update passive counters
  - show diagnostics
- forbidden:
  - boosting exploration
  - enabling micro-trades
  - enabling anti-deadlock TAKE path
  - relaxing entry gates because of idle/stall
  - setting unblock mode that creates entries

Expected log:

```text
[SAFE_MODE] watchdog escalation suppressed reason=quota_429
[SAFE_MODE] self_heal escalation suppressed reason=quota_429
```

Use existing helpers if present:

```python
from src.services.runtime_flags import is_db_degraded_safe_mode, get_db_degraded_reason
```

Pattern:

```python
if is_db_degraded_safe_mode():
    reason = get_db_degraded_reason() or "unknown"
    logging.warning("[SAFE_MODE] watchdog escalation suppressed reason=%s", reason)
    return
```

Important:
- Do not disable existing-position exit management.
- Do not disable stall observation entirely.
- Only suppress escalation into entry-generation behavior.

---

# STEP 3 — Safe stall timestamp handling

Files likely:
- `src/core/anomaly.py`
- `src/core/self_heal.py`
- `bot2/main.py`

Observed bug:

```text
ANOMALY: STALL 34780s > 900s
```

Implement safe stall calculation. Do not use invalid zero/null timestamps as anchor.

Add helper near stall logic:

```python
def safe_stall_seconds(
    now: float,
    last_trade_ts: float | None,
    runtime_start_ts: float | None,
    last_cycle_ts: float | None,
) -> float:
    candidates = [
        ts for ts in (last_trade_ts, runtime_start_ts, last_cycle_ts)
        if isinstance(ts, (int, float)) and ts > 0 and ts <= now
    ]
    anchor = max(candidates) if candidates else now
    return max(0.0, now - anchor)
```

Rules:
- Do not reset learning state.
- Do not clear trade counters.
- Do not hide stall.
- Bad stall value must never trigger forced entries during SAFE_MODE.
- If no valid timestamp exists, stall should be `0.0`, not huge unix-time-derived value.
- Prefer runtime start / last cycle as fallback over zero.

Acceptance:
- No unrealistic `STALL 30000s+` shortly after runtime start unless genuinely true.
- SAFE_MODE still suppresses escalation even if stall is real.

---

# STEP 4 — Complete micro-trade and anti-deadlock suppression

Files likely:
- `src/services/signal_generator.py`
- `src/services/trade_executor.py`
- `bot2/main.py`
- any anti-deadlock/unblock/micro-trade helper

Existing completed:
- forced explore suppression

Still missing:
- micro-trade suppression
- anti-deadlock entry suppression

During SAFE_MODE:
- micro-trade candidate generation must not produce executable signals
- anti-deadlock/unblock TAKE must not produce executable signals
- counters must be incremented

Add counters/block reasons:
- `MICRO_TRADE_SUPPRESSED_SAFE_MODE`
- `ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE`

Expected logs, throttled:

```text
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] anti-deadlock suppressed reason=quota_429
```

Rules:
- Do not stop passive market stats.
- Do not stop dashboard/cache updates.
- Do not stop existing position exits.
- Do not change EV/RDE/strategy logic.

Pseudo-pattern:

```python
if is_db_degraded_safe_mode():
    reason = get_db_degraded_reason() or "unknown"
    block_reasons["MICRO_TRADE_SUPPRESSED_SAFE_MODE"] += 1
    throttled_log_safe_mode_micro(reason)
    return None
```

For anti-deadlock:

```python
if is_db_degraded_safe_mode():
    reason = get_db_degraded_reason() or "unknown"
    block_reasons["ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE"] += 1
    throttled_log_safe_mode_antideadlock(reason)
    return None
```

---

# STEP 5 — Fix duplicate reason logging

Current bad log:

```text
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429 reason=quota_429
```

Expected:

```text
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

Find the logging call that adds `reason=` twice.

Fix by ensuring only one layer formats the reason:

Good:

```python
logging.warning("[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=%s", reason)
```

Bad:

```python
log_safe_mode_decision_block(f"reason={reason}")
logging.warning("[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=%s", f"reason={reason}")
```

Search:

```bash
grep -R "TAKE_BLOCKED_SAFE_MODE\|reason=.*reason\|reason=%s.*reason" -n src bot2
```

---

# Forbidden changes

Do not change:
- EV logic
- RDE thresholds
- score/coherence formula
- strategy generation rules except SAFE_MODE suppression branches
- TP/SL/trailing/timeout logic
- learning/calibration formula
- existing position exit management
- Firebase credentials/env handling
- deployment files unless compile requires it

Do not:
- reset counters
- clear learning state
- clear completed trades
- hide dashboard
- broad-refactor
- rename public functions unless necessary

This must be a small safety/observability patch.

---

# Verification commands

Run:

```bash
python -m py_compile bot2/main.py
python -m py_compile src/services/runtime_flags.py
python -m py_compile src/services/firebase_client.py
python -m py_compile src/services/trade_executor.py
python -m py_compile src/services/signal_generator.py
python -m py_compile src/core/anomaly.py
python -m py_compile src/core/self_heal.py
```

Run grep checks:

```bash
grep -R "SAFE_MODE_FIREBASE_DEGRADED\|TAKE_BLOCKED_SAFE_MODE\|MICRO_TRADE_SUPPRESSED_SAFE_MODE\|ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE\|watchdog escalation suppressed\|self_heal escalation suppressed\|ADVISORY\|CACHED" -n bot2 src

grep -R "reason=.*reason=" -n src bot2 || true

grep -R "last_trade_ts = 0\|completed_trades.clear\|learning.*clear\|reset.*learning\|trades.clear" -n src bot2 || true
```

Optional live validation after deploy:

```bash
journalctl -u cryptomaster -f | grep -E "SAFE_MODE|FIREBASE_DEGRADED|WATCHDOG|SELF_HEAL|STALL|TAKE_BLOCKED"
```

Expected live behavior during quota exhaustion:

```text
[FIREBASE_DEGRADED] load_history skipped: quota exhausted
[SAFE_MODE] DB_DEGRADED_SAFE_MODE = True reason=quota_429
[SAFE_MODE] dashboard state=SAFE_MODE_FIREBASE_DEGRADED entries=blocked reason=quota_429
STAV: SAFE_MODE_FIREBASE_DEGRADED
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
[SAFE_MODE] forced explore suppressed reason=quota_429
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] anti-deadlock suppressed reason=quota_429
[SAFE_MODE] watchdog escalation suppressed reason=quota_429
[SAFE_MODE] self_heal escalation suppressed reason=quota_429
```

Must NOT appear during SAFE_MODE:

```text
STAV: TRENINK
SELF_HEAL: STALL ... → boosting exploration
[WATCHDOG] Critical idle ... enabling micro-trades
decision=TAKE ... unblock=True
reason=quota_429 reason=quota_429
```

`TRENINK` may appear only as subordinate/base mode, for example:

```text
base=TRENINK
```

---

# Token-safety and implementation-safety rules

Use this patch as a small incremental patch, not a rewrite.

## Token-safe workflow

1. Do not paste full files into chat unless required.
2. Inspect only relevant functions/files:
   - `runtime_flags.py`
   - `firebase_client.py`
   - `trade_executor.py`
   - `signal_generator.py`
   - `bot2/main.py`
   - `src/core/anomaly.py`
   - `src/core/self_heal.py`
3. Prefer targeted search commands:

```bash
grep -R "SAFE_MODE\|FIREBASE_DEGRADED\|WATCHDOG\|SELF_HEAL\|STALL\|micro\|anti_deadlock\|unblock\|TAKE_BLOCKED" -n src bot2
```

4. Patch only the smallest necessary blocks.
5. Summarize changed files and behavior; do not dump entire diffs unless asked.

## Implementation-safe workflow

Before editing:

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
```

After editing:

```bash
git diff -- src/services/runtime_flags.py src/services/firebase_client.py src/services/trade_executor.py src/services/signal_generator.py src/core/anomaly.py src/core/self_heal.py bot2/main.py
```

Reject implementation if diff shows unrelated changes in:
- strategy math
- EV/RDE thresholds
- Firebase credentials
- TP/SL logic
- learning reset logic

Commit message:

```bash
git add bot2/main.py src/services/runtime_flags.py src/services/trade_executor.py src/services/signal_generator.py src/core/anomaly.py src/core/self_heal.py
git commit -m "complete safe mode suppression and dashboard override"
```

---

# Required final report

Return only:

```text
SAFE_MODE remaining steps implemented.

Changed files:
- ...

Behavior changed:
- ...

Verification:
- py_compile: PASS/FAIL
- grep SAFE_MODE terms: PASS/FAIL
- duplicate reason grep: PASS/FAIL
- unsafe reset grep: PASS/FAIL

Remaining risks:
- ...
```
