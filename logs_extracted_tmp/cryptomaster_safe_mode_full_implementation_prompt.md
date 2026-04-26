# CryptoMaster — SAFE_MODE Full Implementation Prompt

Use this as one complete, implementation-safe prompt for Claude Code / Codex.

Goal: make Firebase quota exhaustion or Firebase degraded mode explicit, safe, observable, and non-destructive.

Primary rule: SAFE_MODE must block only **new entries / random exploration / emergency entry escalation**, while preserving **existing position management and critical exit persistence**.

---

## 0. Current Known Problem From Live Logs

Observed live behavior after quota exhaustion:

```text
[FIREBASE_DEGRADED] load_history skipped: quota exhausted (50000/50000)
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429 reason=quota_429
STAV: TRENINK
decision=TAKE ...
WATCHDOG ... boosting exploration
SELF_HEAL: STALL ... boosting exploration
Firebase writes: 20,573/20,000
```

Problems to fix:

1. SAFE_MODE is active, but dashboard still shows `TRENINK`.
2. Last decisions still look actionable as BUY/SELL/TAKE.
3. Watchdog/self-heal still boosts exploration during SAFE_MODE.
4. Duplicate reason appears: `reason=quota_429 reason=quota_429`.
5. Forced/micro/anti-deadlock entry paths may still generate candidates before being blocked later.
6. Firebase write quota can exceed configured budget.
7. Stall anomaly is huge and may trigger unsafe entry escalation.
8. Critical exit writes must remain allowed even in SAFE_MODE.

---

## 1. Implementation Order

Implement in this exact order. After each step, run the related verification before moving on.

---

# STEP 1 — Runtime SAFE_MODE state source

Target file:

```text
src/services/runtime_flags.py
```

Add/verify one canonical source of truth for Firebase degraded safe mode.

Required helpers:

```python
def is_db_degraded_safe_mode() -> bool:
    ...

def get_db_degraded_reason() -> str:
    ...

def set_db_degraded_safe_mode(active: bool, reason: str = "") -> None:
    ...

def get_dashboard_status() -> dict:
    ...
```

Required dashboard return when active:

```python
{
    "state": "SAFE_MODE_FIREBASE_DEGRADED",
    "entries": "blocked",
    "reason": "quota_429",
    "note": "existing positions managed normally"
}
```

Required throttled log helpers:

```python
log_safe_mode_dashboard()
log_forced_explore_suppressed()
log_micro_trade_suppressed()
log_anti_deadlock_suppressed()
log_watchdog_escalation_suppressed()
log_entry_blocked()
log_decision_blocked()
```

Use 60-second throttles. No per-tick spam.

Fix duplicate reason bug. Never produce:

```text
reason=quota_429 reason=quota_429
```

Expected log:

```text
[SAFE_MODE] dashboard state=SAFE_MODE_FIREBASE_DEGRADED entries=blocked reason=quota_429
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

Verification:

```bash
python -m py_compile src/services/runtime_flags.py
grep -R "def get_dashboard_status\|def is_db_degraded_safe_mode\|SAFE_MODE_FIREBASE_DEGRADED" -n src/services/runtime_flags.py
grep -R "reason=.*reason=" -n src bot2 || true
```

---

# STEP 2 — Firebase degraded mode + write safety

Target file:

```text
src/services/firebase_client.py
```

Required behavior:

- On quota exhausted / 429 / read budget exhausted, set SAFE_MODE active:
  - `set_db_degraded_safe_mode(True, "quota_429")`
- Non-critical reads may return cache.
- Non-critical writes may be skipped.
- Critical exit writes must never be skipped purely because SAFE_MODE is active.

Critical write kinds include:

```text
position_close
exit_attribution
realized_pnl
sl_exit
tp_exit
trailing_exit
timeout_exit
scratch_exit
portfolio_after_close
emergency_risk_close
exit_audit
trade_close
closed_trade
```

Implementation rule:

```python
CRITICAL_EXIT_WRITE_KINDS = {
    "position_close",
    "exit_attribution",
    "realized_pnl",
    "sl_exit",
    "tp_exit",
    "trailing_exit",
    "timeout_exit",
    "scratch_exit",
    "portfolio_after_close",
    "emergency_risk_close",
    "exit_audit",
    "trade_close",
    "closed_trade",
}

def is_critical_exit_write(write_kind: str | None) -> bool:
    return bool(write_kind) and write_kind in CRITICAL_EXIT_WRITE_KINDS
```

Write guard rule:

```python
if is_db_degraded_safe_mode() and not is_critical_exit_write(write_kind):
    skip_noncritical_write()
else:
    write_or_queue()
```

If the current Firebase write API does not have `write_kind`, add it backward-compatibly:

```python
def save_xxx(..., write_kind: str | None = None):
    ...
```

Do not break existing call sites.

Verification:

```bash
python -m py_compile src/services/firebase_client.py
grep -R "CRITICAL_EXIT_WRITE_KINDS\|is_critical_exit_write\|quota_429" -n src/services/firebase_client.py
```

---

# STEP 3 — Entry blocking at executor boundary

Target file:

```text
src/services/trade_executor.py
```

In `handle_signal()` or the single canonical new-entry path:

Required behavior:

- If SAFE_MODE active:
  - block only new position entries
  - log `TAKE_BLOCKED_SAFE_MODE`
  - do not mutate EV/RDE/score/strategy logic
  - do not block `on_price`
  - do not block exit management for existing positions

Required pattern:

```python
from src.services.runtime_flags import (
    is_db_degraded_safe_mode,
    get_db_degraded_reason,
    log_entry_blocked,
    log_decision_blocked,
)

def handle_signal(...):
    if is_db_degraded_safe_mode():
        reason = get_db_degraded_reason()
        log_entry_blocked(reason)
        log_decision_blocked(reason)
        return {
            "decision": "TAKE_BLOCKED_SAFE_MODE",
            "reason": reason,
            "safe_mode": True,
        }
    ...
```

Do not log duplicated reason.

Verification:

```bash
python -m py_compile src/services/trade_executor.py
grep -R "TAKE_BLOCKED_SAFE_MODE\|log_entry_blocked\|log_decision_blocked" -n src/services/trade_executor.py
```

---

# STEP 4 — Forced/random exploration suppression

Target file:

```text
src/services/signal_generator.py
```

Required behavior:

Suppress only these entry-creation branches while SAFE_MODE is active:

- forced explore
- random explore
- bootstrap forced explore
- anti-deadlock generated candidate
- micro-trade generated candidate

Do **not** blindly return `[]` from the whole generator unless that function is exclusively an entry-candidate function.

Preserve:

- price updates
- feature extraction
- passive market stats
- dashboard/advisory cached state
- health logs

Required logs:

```text
[SAFE_MODE] forced explore suppressed reason=quota_429
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] anti-deadlock suppressed reason=quota_429
```

Required counters/block reasons:

```text
FORCED_EXPLORE_SUPPRESSED_SAFE_MODE
MICRO_TRADE_SUPPRESSED_SAFE_MODE
ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE
```

Verification:

```bash
python -m py_compile src/services/signal_generator.py
grep -R "FORCED_EXPLORE_SUPPRESSED_SAFE_MODE\|MICRO_TRADE_SUPPRESSED_SAFE_MODE\|ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE" -n src/services/signal_generator.py
grep -n "return \[\]" src/services/signal_generator.py
```

Manually inspect any `return []` and confirm it does not stop passive/cache/dashboard updates.

---

# STEP 5 — Watchdog/self-heal must respect SAFE_MODE

Target files likely:

```text
src/core/anomaly.py
src/core/self_heal.py
bot2/main.py
```

Required behavior:

When SAFE_MODE is active, watchdog/self-heal may observe and log, but must not escalate entries.

Suppress during SAFE_MODE:

- boosting exploration
- forced explore
- micro-trades
- anti-deadlock TAKE
- emergency bootstrap entry relaxation

Allowed during SAFE_MODE:

- monitor health
- log stall
- manage existing positions
- close existing positions
- reconnect market data
- recover Firebase
- heartbeat / runtime status

Required pattern:

```python
if is_db_degraded_safe_mode():
    log_watchdog_escalation_suppressed(get_db_degraded_reason())
    return
```

Expected log:

```text
[SAFE_MODE] watchdog escalation suppressed reason=quota_429
```

Verification:

```bash
python -m py_compile src/core/anomaly.py
python -m py_compile src/core/self_heal.py
python -m py_compile bot2/main.py
grep -R "watchdog escalation suppressed\|is_db_degraded_safe_mode" -n src/core bot2
```

---

# STEP 6 — Fix stall timestamp fallback safely

Target files likely:

```text
src/core/anomaly.py
src/core/self_heal.py
bot2/main.py
```

Problem log:

```text
ANOMALY: STALL 34780s > 900s
```

Required behavior:

- Do not reset learning state.
- Do not reset trade counters.
- Do not clear history.
- Do not fake successful trades.
- Do not hide stall logs.
- Fix only timestamp fallback and escalation behavior.

Safe stall calculation:

```python
def safe_stall_seconds(now: float, last_trade_ts: float | None, runtime_start_ts: float | None, last_cycle_ts: float | None) -> float:
    candidates = [
        ts for ts in (last_trade_ts, runtime_start_ts, last_cycle_ts)
        if isinstance(ts, (int, float)) and ts > 0 and ts <= now
    ]
    anchor = max(candidates) if candidates else now
    return max(0.0, now - anchor)
```

During SAFE_MODE, bad stall value must never trigger forced entries.

Verification:

```bash
grep -R "safe_stall_seconds\|last_trade_ts" -n src/core bot2
grep -R "last_trade_ts = 0\|completed_trades.clear\|learning.*clear\|reset.*learning" -n src bot2 || true
```

---

# STEP 7 — Dashboard SAFE_MODE override

Target file likely:

```text
bot2/main.py
```

Required behavior:

When SAFE_MODE active, dashboard must not show only:

```text
STAV: TRENINK
STAV: AKTIVNI
```

SAFE_MODE must override user-facing state.

Required display:

```text
STAV: SAFE_MODE_FIREBASE_DEGRADED
ENTRIES: BLOCKED
REASON: quota_429
NOTE: existing positions managed normally
LAST DECISIONS: ADVISORY/CACHED ONLY
```

Last decisions may remain visible, but must be marked advisory/cached. Do not show them as executable BUY/SELL commands while entries are blocked.

Required semantic change:

- `KUPUJ` / `PRODEJ` under SAFE_MODE must be visually/semantically advisory, e.g.:

```text
BTC  ADVISORY KUPUJ  ...  entries blocked by SAFE_MODE
```

or:

```text
BTC  CACHED/ADVISORY  KUPUJ ... not executable
```

Verification:

```bash
python -m py_compile bot2/main.py
grep -R "ADVISORY\|CACHED\|SAFE_MODE_FIREBASE_DEGRADED\|entries=blocked\|ENTRIES" -n bot2 src
```

---

# STEP 8 — Main loop observability

Target file likely:

```text
bot2/main.py
```

Required behavior:

When SAFE_MODE active, periodically log dashboard status:

```text
[SAFE_MODE] dashboard state=SAFE_MODE_FIREBASE_DEGRADED entries=blocked reason=quota_429
```

Use throttled helper from `runtime_flags.py`.

Do not spam every tick.

Verification:

```bash
grep -R "log_safe_mode_dashboard\|get_dashboard_status" -n bot2 src
python -m py_compile bot2/main.py
```

---

# STEP 9 — Full verification suite

Run from project root:

```bash
python -m py_compile bot2/main.py
python -m py_compile src/services/runtime_flags.py
python -m py_compile src/services/firebase_client.py
python -m py_compile src/services/trade_executor.py
python -m py_compile src/services/signal_generator.py
python -m py_compile src/core/anomaly.py
python -m py_compile src/core/self_heal.py
```

Search expected safe paths:

```bash
grep -R "SAFE_MODE_FIREBASE_DEGRADED\|TAKE_BLOCKED_SAFE_MODE\|FORCED_EXPLORE_SUPPRESSED_SAFE_MODE\|MICRO_TRADE_SUPPRESSED_SAFE_MODE\|ANTI_DEADLOCK_SUPPRESSED_SAFE_MODE\|watchdog escalation suppressed\|ADVISORY\|CACHED" -n bot2 src
```

Search unsafe patterns:

```bash
grep -R "reason=.*reason=" -n src bot2 || true
grep -R "last_trade_ts = 0\|completed_trades.clear\|learning.*clear\|reset.*learning" -n src bot2 || true
grep -R "return \[\]" -n src/services/signal_generator.py
```

Expected runtime logs during quota exhaustion:

```text
[FIREBASE_DEGRADED] load_history skipped: quota exhausted
[SAFE_MODE] DB_DEGRADED_SAFE_MODE = True reason=quota_429
[SAFE_MODE] dashboard state=SAFE_MODE_FIREBASE_DEGRADED entries=blocked reason=quota_429
[SAFE_MODE] forced explore suppressed reason=quota_429
[SAFE_MODE] micro-trade suppressed reason=quota_429
[SAFE_MODE] anti-deadlock suppressed reason=quota_429
[SAFE_MODE] watchdog escalation suppressed reason=quota_429
[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE reason=quota_429
[SAFE_MODE] decision=TAKE_BLOCKED_SAFE_MODE reason=quota_429
```

Expected dashboard during quota exhaustion:

```text
STAV: SAFE_MODE_FIREBASE_DEGRADED
ENTRIES: BLOCKED
REASON: quota_429
LAST DECISIONS: ADVISORY/CACHED ONLY
```

Expected not to see:

```text
reason=quota_429 reason=quota_429
SELF_HEAL ... boosting exploration
WATCHDOG ... boosting exploration
STAV: TRENINK
decision=TAKE  # as actionable executable entry during SAFE_MODE
```

---

## Final Acceptance Criteria

Patch is accepted only if all are true:

1. SAFE_MODE dashboard state appears instead of only `TRENINK` / `AKTIVNI`.
2. Existing positions still run through `on_price`.
3. New entries are blocked in `trade_executor.handle_signal`.
4. Forced explore is suppressed.
5. Micro-trades are suppressed.
6. Anti-deadlock generated entries are suppressed.
7. Watchdog/self-heal does not boost exploration during SAFE_MODE.
8. Non-critical Firebase writes are skipped when quota is exhausted.
9. Critical exit writes remain allowed.
10. Last decisions are marked `ADVISORY/CACHED` during SAFE_MODE.
11. No EV/RDE/score/strategy/TP/SL logic is changed.
12. No state reset is used to hide stall anomalies.
13. Logs are throttled and do not spam every tick.
14. Duplicate `reason=... reason=...` log bug is fixed.
15. `py_compile` passes for all touched files.

---

## Strictly Forbidden Changes

Do not change:

- EV formula
- RDE thresholds
- score thresholds
- coherence logic
- TP/SL values
- trailing/timeout/scratch logic
- strategy features
- position sizing logic except SAFE_MODE entry blocking
- learning calibration logic
- historical trade counters
- Firebase counters as a workaround
- dashboard by hiding SAFE_MODE behind TRENINK/AKTIVNI

Do not add broad refactors.

Do not reset runtime/learning state to hide bugs.

---

## Implementation Style

Preferred:

- small additive helpers in `runtime_flags.py`
- narrow guards at entry-generation and entry-execution boundaries
- existing-position exits remain active
- 60-second throttled logs
- backward-compatible Firebase write metadata
- minimal patches with clear comments

Comment to include near SAFE_MODE entry blocks:

```python
# SAFE_MODE blocks only new entries. Existing positions must still be managed
# by on_price so SL/TP/trailing/timeout exits can close risk normally.
```

---

## Suggested Commit Message

```text
fix: make firebase degraded safe mode fully observable and entry-safe
```

Commit body:

```text
- override dashboard state to SAFE_MODE_FIREBASE_DEGRADED
- mark last decisions advisory/cached while entries blocked
- suppress forced explore, micro-trades, anti-deadlock entries in SAFE_MODE
- make watchdog/self-heal observe-only during Firebase degraded mode
- preserve on_price and critical exit writes for existing positions
- fix duplicated degradation reason logging
- avoid unsafe stall timestamp fallback without resetting state
```
