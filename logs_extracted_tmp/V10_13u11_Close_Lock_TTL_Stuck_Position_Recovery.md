# V10.13u+11 — Close Lock TTL + Stuck Position Recovery Patch

## Situation from production logs

Current state after V10.13u+9:

- `CLOSE_LOGIC_START` storm is mostly converted into `CLOSE_SKIP_DUPLICATE`, so the lock is active.
- But the close lock can stay stuck as `already_closing` for many seconds/minutes.
- Open positions remain visible even though close attempts keep repeating:
  - `ADAUSDT BUY`
  - `BNBUSDT SELL`
  - `DOTUSDT BUY`
- `CLOSE_SKIP_DUPLICATE` repeats heavily:
  - `ADAUSDT reason=replaced status=already_closing`
  - `DOTUSDT reason=replaced status=already_closing`
  - `BNBUSDT reason=TRAIL_PROFIT status=already_closing`
- `EXIT_AUDIT winners` counters explode unrealistically:
  - `TRAIL_PROFIT=119794`
  - `MICRO_TP=4098`
  - `EARLY_STOP=2680`
  - `SCRATCH_EXIT=1841`
- Stall detection fires incorrectly while close storm is happening:
  - `ANOMALY: STALL 13739s > 900s`
  - `SELF_HEAL: STALL → boosting exploration`
- Economic health is still correctly BAD:
  - `PF: 0.79`
  - `Economic: 0.340 [BAD]`

## Diagnosis

V10.13u+9 fixed duplicate close execution, but introduced/left a stuck-lock failure mode.

The bot now prevents repeated execution, but it does not reliably complete the close lifecycle:

1. Close lock is acquired.
2. Position is not removed or finalization fails/delays.
3. Lock remains in `_CLOSING_POSITIONS`.
4. Every loop sees the same close condition and logs `CLOSE_SKIP_DUPLICATE`.
5. Because the position is still open, the close engine keeps requesting close.
6. Exit audit counters count repeated candidate/winner events instead of actual finalized closes.
7. Watchdog sees no successful trade close and triggers false stall/self-heal.

This is now a liveness bug, not a PnL bug.

## Goal

Implement a minimal safety patch that makes close handling:

- idempotent,
- TTL-protected,
- observable,
- self-healing,
- and audit-safe.

Do not change trading strategy logic, EV formula, PF formula, TP/SL multipliers, or learning logic.

## Files likely to modify

| File | Purpose |
|---|---|
| `src/services/trade_executor.py` | close lock TTL, stale-lock recovery, guaranteed release/finalize |
| `src/services/exit_attribution.py` | normalize `replaced`, avoid invalid exit errors |
| `src/services/smart_exit_engine.py` | audit only actual exit decisions, not duplicate candidates |
| `src/core/anomaly.py` or watchdog module | ignore close-in-progress as idle stall |
| `tests/test_v10_13u_patches.py` | regression tests |

## Patch requirements

### 1. Add close lock metadata, not just a set

Current behavior likely has:

```python
_CLOSING_POSITIONS = set()
_RECENTLY_CLOSED = {}
```

Replace or extend with metadata:

```python
_CLOSING_POSITIONS = {}  # key -> {"ts": float, "symbol": str, "reason": str, "attempts": int}
_RECENTLY_CLOSED = {}    # key -> close timestamp

CLOSE_LOCK_TTL_S = 20
RECENTLY_CLOSED_TTL_S = 60
```

### 2. Add stale lock cleanup

Before acquiring or skipping a close lock, run cleanup:

```python
def _cleanup_close_locks(now=None):
    now = now or time.time()

    stale = [
        key for key, meta in _CLOSING_POSITIONS.items()
        if now - meta.get("ts", now) > CLOSE_LOCK_TTL_S
    ]
    for key in stale:
        meta = _CLOSING_POSITIONS.pop(key, {})
        log.error(
            "[CLOSE_LOCK_STALE_RELEASE] key=%s symbol=%s reason=%s age=%.1fs attempts=%s",
            key,
            meta.get("symbol"),
            meta.get("reason"),
            now - meta.get("ts", now),
            meta.get("attempts", 0),
        )

    old_closed = [
        key for key, ts in _RECENTLY_CLOSED.items()
        if now - ts > RECENTLY_CLOSED_TTL_S
    ]
    for key in old_closed:
        _RECENTLY_CLOSED.pop(key, None)
```

### 3. Make lock acquisition return explicit status

Implement:

```python
def _try_acquire_close_lock(symbol, pos, reason, now=None):
    now = now or time.time()
    _cleanup_close_locks(now)

    key = _close_key(symbol, pos)

    if key in _RECENTLY_CLOSED:
        return False, key, "recently_closed"

    meta = _CLOSING_POSITIONS.get(key)
    if meta:
        meta["attempts"] = meta.get("attempts", 0) + 1
        last_log = meta.get("last_log", 0)
        if now - last_log >= 5:
            meta["last_log"] = now
            log.warning(
                "[CLOSE_SKIP_DUPLICATE] %s reason=%s key=%s status=already_closing age=%.1fs attempts=%s",
                symbol,
                reason,
                key,
                now - meta.get("ts", now),
                meta.get("attempts", 0),
            )
        return False, key, "already_closing"

    _CLOSING_POSITIONS[key] = {
        "ts": now,
        "symbol": symbol,
        "reason": reason,
        "attempts": 1,
        "last_log": now,
    }
    log.warning("[CLOSE_LOCK_ACQUIRED] %s reason=%s key=%s", symbol, reason, key)
    return True, key, "acquired"
```

Important: `CLOSE_SKIP_DUPLICATE` must be throttled. It should not log every tick.

### 4. Guarantee lock release in `finally`

Close logic must be structured like:

```python
acquired, close_key, status = _try_acquire_close_lock(sym, pos, reason)
if not acquired:
    return None

closed_ok = False
try:
    log.info("[CLOSE_LOGIC_START] %s reason=%s entering close logic", sym, reason)

    # existing close logic:
    # - compute canonical PnL
    # - persist trade
    # - update metrics
    # - remove position from portfolio/open positions
    # - update learning monitor
    # - send notifier

    closed_ok = True

finally:
    if closed_ok:
        _RECENTLY_CLOSED[close_key] = time.time()
        _CLOSING_POSITIONS.pop(close_key, None)
        log.warning("[CLOSE_LOCK_RELEASED] %s reason=%s key=%s status=closed", sym, reason, close_key)
    else:
        _CLOSING_POSITIONS.pop(close_key, None)
        log.error("[CLOSE_LOCK_RELEASED] %s reason=%s key=%s status=failed", sym, reason, close_key)
```

Acceptance: no lock remains stuck unless close is actively executing for less than `CLOSE_LOCK_TTL_S`.

### 5. Add emergency position cleanup for stale closing positions

If a lock becomes stale, do not silently release it forever while the position remains in open positions. Add a safe recovery counter:

- first stale release: release lock only
- second stale release for same key within 5 minutes: force position state reconciliation
- third stale release: remove invalid open position only if an existing safe reconcile/remove function exists

Pseudo:

```python
_STALE_CLOSE_COUNTS = {}

if stale:
    _STALE_CLOSE_COUNTS[key] = _STALE_CLOSE_COUNTS.get(key, 0) + 1
    if _STALE_CLOSE_COUNTS[key] >= 2:
        log.error("[POSITION_CLOSE_STUCK] key=%s count=%s action=reconcile_required", key, _STALE_CLOSE_COUNTS[key])
```

Do not delete positions blindly unless existing code already has a safe remove/reconcile function. Prefer calling existing portfolio reconciliation.

### 6. Normalize exit type `replaced`

In `exit_attribution.py` or close context builder, normalize:

```python
EXIT_TYPE_ALIASES = {
    "replaced": "REPLACED_EXIT",
    "replace": "REPLACED_EXIT",
    "replacement": "REPLACED_EXIT",
    "TRAIL_PROFIT": "TRAIL_PROFIT",
    "SCRATCH_EXIT": "SCRATCH_EXIT",
    "STAGNATION_EXIT": "STAGNATION_EXIT",
}
```

Before validation:

```python
final_exit_type = normalize_exit_type(final_exit_type)
```

Acceptance: no more:

```text
Invalid final_exit_type: replaced
```

### 7. Fix exit audit counter explosion

The log below is not plausible:

```text
winners: TRAIL_PROFIT=119794 MICRO_TP=4098 EARLY_STOP=2680 ...
```

Rule:

- audit `winners` must increment only after a close is accepted/finalized, not while already closing.
- if `_try_acquire_close_lock()` returns `already_closing`, do not update exit audit winner counters.
- near-miss counters can increment, but must be throttled or windowed.

Add a guard:

```python
if close_lock_status != "acquired":
    return None  # no audit winner increment
```

Or move audit winner increment after successful close.

### 8. Fix watchdog false stall during close-in-progress

Stall logic should not boost exploration while positions are open or close locks are active.

Add condition:

```python
if open_positions_count > 0 or close_locks_active > 0:
    log.info("[WATCHDOG_SKIP] reason=positions_or_close_in_progress positions=%s locks=%s", open_positions_count, close_locks_active)
    return
```

Acceptance: no `SELF_HEAL: STALL → boosting exploration` while positions are open and close locks are active.

### 9. Add compact diagnostics

Once per 60s:

```text
[CLOSE_LOCK_HEALTH] active=3 stale=0 recently_closed=1 top=ADAUSDT:BUY age=7.2s attempts=12
```

Do not spam every tick.

## Tests to add

Add tests to `tests/test_v10_13u_patches.py`.

1. `test_close_lock_acquire_once`
2. `test_close_lock_ttl_releases_stale`
3. `test_close_skip_duplicate_is_throttled`
4. `test_recently_closed_blocks_reclose`
5. `test_recently_closed_expires`
6. `test_replaced_exit_type_normalizes`
7. `test_exit_audit_not_incremented_on_duplicate_close`
8. `test_watchdog_does_not_stall_when_close_locks_active`
9. `test_lock_released_on_exception`

## Validation commands on Hetzner

After deploy:

```bash
sudo systemctl restart cryptomaster
sleep 10
sudo journalctl -u cryptomaster -n 2000 --no-pager | grep -E "RUNTIME_VERSION|CLOSE_LOCK|CLOSE_SKIP|CLOSE_LOCK_STALE|POSITION_CLOSE_STUCK|POSITION_FORCE_RECONCILE|EXIT_INTEGRITY|Invalid final_exit_type|WATCHDOG|SELF_HEAL|Traceback"
```

Live watch:

```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "CLOSE_LOCK|CLOSE_SKIP|CLOSE_LOCK_HEALTH|EXIT_INTEGRITY|WATCHDOG|SELF_HEAL|Traceback"
```

## Success criteria

Must see:

```text
[CLOSE_LOCK_ACQUIRED]
[CLOSE_LOCK_RELEASED] ... status=closed
```

May see occasionally:

```text
[CLOSE_SKIP_DUPLICATE] ... status=already_closing
```

Should not see:

```text
CLOSE_SKIP_DUPLICATE spam every tick
EXIT_INTEGRITY_ERROR
Invalid final_exit_type: replaced
winners: TRAIL_PROFIT=119794
SELF_HEAL: STALL while positions/locks active
```

## Current production interpretation

Do not continue tuning entries/exits yet.

Priority order:

1. Fix close lifecycle liveness.
2. Fix audit counter explosion.
3. Fix false stall/self-heal.
4. Observe 30–60 minutes.
5. Only then tune scratch/stagnation/harvest.

## Non-goals

Do not change:

- EV-only enforcement
- canonical PF
- canonical WR
- Firebase quota logic
- TP/SL ATR ratios
- position sizing model
- learning hydration
- signal generation logic

This patch is operational safety only.
