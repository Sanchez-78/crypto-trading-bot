# CryptoMaster SAFE_MODE Final UI/Logging Fix Patch

## Goal

Fix remaining SAFE_MODE observability bugs without changing EV/RDE/strategy/execution logic.

Current live logs confirm SAFE_MODE entry blocking works:
- `STAV: SAFE_MODE_FIREBASE_DEGRADED`
- `ENTRIES: BLOCKED`
- `ADVISORY` decisions shown
- `[SAFE_MODE] entry blocked`
- `[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE`
- `[SAFE_MODE] forced explore suppressed`
- `[SAFE_MODE] micro-trade suppressed`

Remaining issues:
1. Top dashboard header still shows `| TRENINK` even when SAFE_MODE is active.
2. RDE/top_rejects/debug lines still print `decision=TAKE` during SAFE_MODE, causing confusion.
3. Runtime error: `Self-heal cycle error: cannot access local variable 'logging' where it is not associated with a value`.

---

## Implementation Rules

- Do **not** change EV math.
- Do **not** change RDE decision thresholds.
- Do **not** change strategy/filter logic.
- Do **not** change position exit management.
- Do **not** reset trades, learning state, Firebase data, or metrics.
- Only modify display/logging/SAFE_MODE suppression guards.
- Existing position management must remain active.
- New entries must remain blocked during SAFE_MODE.

---

## Files Likely Involved

- `bot2/main.py`
- `src/services/runtime_flags.py`
- `src/services/realtime_decision_engine.py`
- `src/services/trade_executor.py`
- Any module where the self-heal cycle is handled

---

## PATCH 1 — Fix Top Dashboard Header State

### Problem

Header still prints:

```text
CRYPTOMASTER | 0h 11m 19s | TRENINK
```

while the dashboard body correctly prints:

```text
STAV: SAFE_MODE_FIREBASE_DEGRADED
```

### Required Behavior

When `is_db_degraded_safe_mode()` is true, the top header must show:

```text
CRYPTOMASTER | <uptime> | SAFE_MODE_FIREBASE_DEGRADED
```

not `TRENINK`.

### Implementation

Find where the dashboard/header status label is computed, likely something like:

```python
mode = "TRENINK" if training else "AKTIVNI"
```

or similar.

Add SAFE_MODE override as the final authority:

```python
from src.services.runtime_flags import is_db_degraded_safe_mode, get_dashboard_status

if is_db_degraded_safe_mode():
    dashboard_status = get_dashboard_status()
    mode_label = dashboard_status.get("state", "SAFE_MODE_FIREBASE_DEGRADED")
```

Ensure this same `mode_label` is used in the top header.

### Acceptance

- No header line may show `| TRENINK` while SAFE_MODE is active.
- Header and body must agree.

---

## PATCH 2 — Fix Misleading `decision=TAKE` in SAFE_MODE Debug/Top-Reject Logs

### Problem

During SAFE_MODE, logs still show:

```text
decision=TAKE ev=...
```

inside RDE/debug/top_reject blocks.

This is confusing because final executor correctly blocks entries.

### Required Behavior

During SAFE_MODE, any display/debug/top_reject line must not show executable `decision=TAKE`.

Use:

```text
decision=ADVISORY_TAKE_BLOCKED_SAFE_MODE
```

or:

```text
decision=TAKE_BLOCKED_SAFE_MODE
```

Preferred:

```text
decision=ADVISORY_TAKE_BLOCKED_SAFE_MODE ev=... p=... coh=...
```

### Implementation

Wherever final decision lines are rendered for dashboard/top_rejects/debug output, wrap display decision:

```python
from src.services.runtime_flags import is_db_degraded_safe_mode, get_db_degraded_reason

display_decision = decision

if is_db_degraded_safe_mode() and str(decision).upper() == "TAKE":
    display_decision = "ADVISORY_TAKE_BLOCKED_SAFE_MODE"
```

Do not change the internal RDE return unless necessary. This is display/logging only.

If the RDE return object/dict is used directly by executor, do not mutate it. Create a display copy:

```python
display = dict(decision_obj)
if is_db_degraded_safe_mode() and display.get("decision") == "TAKE":
    display["decision"] = "ADVISORY_TAKE_BLOCKED_SAFE_MODE"
```

### Acceptance

- SAFE_MODE logs must not print raw `decision=TAKE` in dashboard/top_reject/display sections.
- Executor can still internally receive TAKE and block it at boundary.
- Final entry logs must remain:

```text
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

---

## PATCH 3 — Fix `logging` UnboundLocalError in Self-Heal Cycle

### Problem

Live error:

```text
Self-heal cycle error: cannot access local variable 'logging' where it is not associated with a value
```

This usually means one of these exists inside a function:

```python
import logging
```

after `logging` was already used, or:

```python
logging = ...
```

inside the function.

### Required Fix

In `bot2/main.py` and any self-heal related function:

1. Ensure `import logging` exists only at module top.
2. Remove any local `import logging` inside functions.
3. Remove any assignment like `logging = ...`.
4. Use module-level logger if available:

```python
logger = logging.getLogger(__name__)
```

Then use:

```python
logger.warning(...)
logger.error(...)
```

or keep:

```python
logging.warning(...)
logging.error(...)
```

but only if no local `logging` shadow exists.

### Acceptance

This command must find no suspicious local imports:

```bash
grep -R "^[[:space:]]*import logging" bot2 src | cat
```

Allowed only at file/module top, not inside indented function bodies.

Also run:

```bash
python -m py_compile bot2/main.py
python -m py_compile src/services/runtime_flags.py
python -m py_compile src/services/realtime_decision_engine.py
python -m py_compile src/services/trade_executor.py
```

---

## PATCH 4 — Add SAFE_MODE Dashboard Consistency Check

Add or adjust a lightweight runtime log check. Do not add a heavy test framework unless the project already uses one.

When SAFE_MODE is active, expected log output:

```text
CRYPTOMASTER | ... | SAFE_MODE_FIREBASE_DEGRADED
STAV: SAFE_MODE_FIREBASE_DEGRADED
ENTRIES: BLOCKED
REASON: quota_429
ADVISORY ...
[SAFE_MODE] forced explore suppressed reason=quota_429
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

Forbidden output while SAFE_MODE is active:

```text
CRYPTOMASTER | ... | TRENINK
decision=TAKE
Self-heal cycle error: cannot access local variable 'logging'
WATCHDOG ... boosting exploration
Critical idle ... enabling micro-trades
SELF_HEAL: STALL ... boosting exploration
reason=quota_429 reason=quota_429
STALL 30000
```

---

## Verification Commands

Run locally:

```bash
python -m py_compile bot2/main.py
python -m py_compile src/services/runtime_flags.py
python -m py_compile src/services/realtime_decision_engine.py
python -m py_compile src/services/trade_executor.py
```

Search for risky patterns:

```bash
grep -R "decision=TAKE" bot2 src || true
grep -R "reason=.*reason=" bot2 src || true
grep -R "^[[:space:]]*import logging" bot2 src || true
grep -R "logging =" bot2 src || true
```

After deploy:

```bash
journalctl -u cryptomaster -n 400 --no-pager | grep -E "CRYPTOMASTER|SAFE_MODE|ADVISORY|TAKE_BLOCKED|decision=TAKE|Self-heal cycle error|WATCHDOG|STALL|micro"
```

Expected:

- Header shows `SAFE_MODE_FIREBASE_DEGRADED`.
- Body shows `STAV: SAFE_MODE_FIREBASE_DEGRADED`.
- Entries remain blocked.
- No raw actionable `decision=TAKE` in SAFE_MODE display logs.
- No self-heal logging error.
- No watchdog/self-heal exploration boost during SAFE_MODE.

---

## Deploy / Commit

```bash
git add bot2/main.py src/services/runtime_flags.py src/services/realtime_decision_engine.py src/services/trade_executor.py
git commit -m "fix SAFE_MODE dashboard header and advisory decision logs"
git push
```

---

## Production Verification After Deploy

On server:

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
systemctl status cryptomaster --no-pager
journalctl -u cryptomaster -n 300 --no-pager | grep -E "SAFE_MODE|ADVISORY|TAKE_BLOCKED|decision=TAKE|Self-heal cycle error|WATCHDOG|STALL|micro|CRYPTOMASTER"
```

Pass criteria:

```text
CRYPTOMASTER | ... | SAFE_MODE_FIREBASE_DEGRADED
STAV: SAFE_MODE_FIREBASE_DEGRADED
ENTRIES: BLOCKED
REASON: quota_429
ADVISORY KUPUJ / ADVISORY PRODEJ
[SAFE_MODE] forced explore suppressed reason=quota_429
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

Fail criteria:

```text
CRYPTOMASTER | ... | TRENINK
raw decision=TAKE during SAFE_MODE display
Self-heal cycle error
WATCHDOG boosting exploration during SAFE_MODE
Critical idle enabling micro-trades during SAFE_MODE
reason=quota_429 reason=quota_429
STALL 30000+
```
