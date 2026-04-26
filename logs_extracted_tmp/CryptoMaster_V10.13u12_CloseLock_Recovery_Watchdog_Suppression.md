# CryptoMaster V10.13u+12 — Close-Lock Recovery + Watchdog Suppression Patch

## Goal

Fix remaining production issue after V10.13u+11:

- `CLOSE_SKIP_DUPLICATE ... status=already_closing` still spams for the same keys.
- `SELF_HEAL: STALL` and `[WATCHDOG] Critical idle` fire while positions are stuck in close flow.
- Some positions remain `[OPEN]` even though close logic is repeatedly blocked.
- Prior `replaced` exits may still be invalid for exit attribution unless normalized.

This patch must be **safety-first** and **minimal**. Do not change PF, EV-only logic, sizing, TP/SL, Firebase quota, or learning formulas.

---

## Production Evidence

Example:

```text
SELF_HEAL: STALL (no trades 900s) → boosting exploration
[WATCHDOG] No trades for 600s → boosting exploration
[WATCHDOG] Critical idle (15min) → enabling micro-trades
[CLOSE_SKIP_DUPLICATE] BNBUSDT reason=SCRATCH_EXIT key=BNBUSDT:SELL:631.2774099999999: status=already_closing
[CLOSE_SKIP_DUPLICATE] DOTUSDT reason=replaced key=DOTUSDT:BUY:1.2609953999999999: status=already_closing
[RUNTIME_VERSION] commit=c11db06 branch=main
```

Interpretation:

1. Close lock exists, but duplicate attempts keep firing.
2. Lock cleanup either runs too late, does not run before duplicate check, or does not force recovery.
3. Watchdog sees no completed trades and boosts exploration while close locks are active, worsening churn.
4. Need close-lock health to be part of watchdog/self-heal suppression.

---

## Required Fixes

### 1. `trade_executor.py` — make close lock self-healing before duplicate skip

Find close-lock helpers from V10.13u+11.

Update `_try_acquire_close_lock(...)` so it always calls `_cleanup_close_locks()` **before** checking if key is already locked.

Required behavior:

```python
def _try_acquire_close_lock(key, symbol, reason, now=None):
    now = now or time.time()
    _cleanup_close_locks(now=now)

    existing = _CLOSING_POSITIONS.get(key)
    if existing:
        age = now - existing.get("ts", now)

        # Hard recovery: stale close lock must not block forever
        if age > CLOSE_LOCK_TTL_S:
            _release_stale_close_lock(key, existing, now=now)
            # Continue and acquire fresh lock below
        else:
            # duplicate log throttled by key, max once per 5s
            ...
            return False, key, "already_closing"

    _CLOSING_POSITIONS[key] = {
        "ts": now,
        "symbol": symbol,
        "reason": reason,
        "attempts": 1,
        "last_log": 0.0,
    }
    log.warning("[CLOSE_LOCK_ACQUIRED] ...")
    return True, key, "acquired"
```

Add helper:

```python
def _release_stale_close_lock(key, meta, now=None):
    now = now or time.time()
    age = now - meta.get("ts", now)
    _CLOSING_POSITIONS.pop(key, None)
    _STALE_CLOSE_COUNTS[key] = _STALE_CLOSE_COUNTS.get(key, 0) + 1
    log.error(
        "[CLOSE_LOCK_STALE_RELEASE] key=%s symbol=%s reason=%s age=%.1fs count=%s",
        key, meta.get("symbol"), meta.get("reason"), age, _STALE_CLOSE_COUNTS[key]
    )
```

Acceptance:

- No key can remain `already_closing` forever.
- A stale key must be released after `CLOSE_LOCK_TTL_S`.
- After stale release, the next close attempt must be allowed to proceed.

---

### 2. `trade_executor.py` — release lock in `finally`

Wrap the close logic after successful lock acquisition in `try/finally`.

Required invariant:

```python
lock_acquired = False
close_key = None

try:
    lock_acquired, close_key, close_lock_status = _try_acquire_close_lock(...)
    if not lock_acquired:
        return None

    # existing close logic unchanged

finally:
    if lock_acquired and close_key:
        # If close completed and position was removed, mark recently closed.
        # If close failed, release lock anyway but log failure.
        _release_close_lock(close_key, symbol=sym, reason=reason, status=...)
```

`finally` must run on:
- successful close
- notifier failure
- Firebase write failure
- exit attribution failure
- unexpected exception

Do not swallow exceptions unless current code already does. The key is: **lock release must not depend on perfect close completion**.

---

### 3. `trade_executor.py` — add close-lock health API

Expose lightweight function for watchdog/self-heal:

```python
def get_close_lock_health() -> dict:
    now = time.time()
    _cleanup_close_locks(now=now)
    oldest_age = 0.0
    if _CLOSING_POSITIONS:
        oldest_age = max(now - m.get("ts", now) for m in _CLOSING_POSITIONS.values())
    return {
        "active": len(_CLOSING_POSITIONS),
        "oldest_age": oldest_age,
        "keys": list(_CLOSING_POSITIONS.keys())[:5],
        "stale_releases": sum(_STALE_CLOSE_COUNTS.values()),
    }
```

Acceptance:
- No project imports inside this function except `time/log`.
- Safe to call frequently.
- It must cleanup stale locks before returning.

---

### 4. `self_heal.py` / watchdog code — suppress exploration during close-lock recovery

Find code emitting:

```text
SELF_HEAL: STALL (no trades 900s) → boosting exploration
[WATCHDOG] No trades for 600s → boosting exploration
[WATCHDOG] Critical idle (15min) → enabling micro-trades
```

Before boosting exploration or enabling micro-trades, check close-lock health:

```python
try:
    from src.services.trade_executor import get_close_lock_health
    close_health = get_close_lock_health()
except Exception:
    close_health = {"active": 0, "oldest_age": 0.0}

if close_health["active"] > 0:
    log.warning(
        "[WATCHDOG_SUPPRESSED_CLOSE_LOCK] active=%s oldest_age=%.1fs keys=%s",
        close_health["active"], close_health["oldest_age"], close_health.get("keys")
    )
    return  # or skip boost for this cycle
```

Acceptance:
- Watchdog must not enable micro-trades while closes are already stuck/active.
- Self-heal must prioritize close recovery over exploration.
- Does not disable normal trading if no active close locks.

---

### 5. `exit_attribution.py` — normalize `replaced`

If still present, normalize invalid close reasons:

```python
EXIT_TYPE_ALIASES = {
    "replaced": "REPLACED",
    "replace": "REPLACED",
    "replacement": "REPLACED",
}
```

Before validation:

```python
raw_exit_type = ctx.get("final_exit_type") or ctx.get("exit_type")
norm_exit_type = EXIT_TYPE_ALIASES.get(str(raw_exit_type).lower(), raw_exit_type)
ctx["final_exit_type"] = norm_exit_type
```

Add `REPLACED` to allowed exit types if missing.

Acceptance:
- No more `Invalid final_exit_type: replaced`.
- Historical lower-case `replaced` remains accepted.
- Do not change dashboard label unless already mapped elsewhere.

---

## Tests Required

Append to `tests/test_v10_13u_patches.py`.

### Close lock tests

1. `test_close_lock_cleanup_runs_before_duplicate_skip`
   - Insert fake stale lock.
   - Call `_try_acquire_close_lock`.
   - Assert it releases stale and acquires fresh.

2. `test_close_lock_finally_releases_on_exception`
   - Mock close flow to raise after acquisition.
   - Assert lock is not left in `_CLOSING_POSITIONS`.

3. `test_get_close_lock_health_cleans_stale`
   - Insert stale lock.
   - Call `get_close_lock_health`.
   - Assert active is 0 and stale release count increments.

4. `test_duplicate_log_throttled`
   - Repeated duplicate acquire attempts.
   - Assert log does not emit every call.

### Watchdog/self-heal tests

5. `test_watchdog_suppressed_when_close_lock_active`
   - Mock `get_close_lock_health` active > 0.
   - Assert exploration boost is not triggered.

6. `test_watchdog_runs_when_no_close_lock`
   - Mock active = 0.
   - Assert existing behavior preserved.

### Exit attribution test

7. `test_exit_type_replaced_alias_is_valid`
   - `final_exit_type="replaced"` validates as `REPLACED`.

---

## Verification Commands

On local/dev:

```bash
python -m pytest tests/test_v10_13u_patches.py -k "close_lock or watchdog or replaced_alias" -v
python -m pytest tests/test_v10_13u_patches.py -v
```

On Hetzner after deploy:

```bash
cd /opt/cryptomaster
git pull
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 20

sudo journalctl -u cryptomaster -n 3000 --no-pager | grep -E "RUNTIME_VERSION|CLOSE_LOCK|CLOSE_SKIP|STALE_RELEASE|WATCHDOG_SUPPRESSED|SELF_HEAL|WATCHDOG|EXIT_INTEGRITY|Invalid final_exit_type|Traceback|ERROR"
```

Live monitor:

```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "CLOSE_LOCK|CLOSE_SKIP|STALE_RELEASE|WATCHDOG_SUPPRESSED|SELF_HEAL|WATCHDOG|EXIT_INTEGRITY|Traceback"
```

---

## Acceptance Criteria

Success:

```text
[RUNTIME_VERSION] commit=<new_commit> branch=main
[CLOSE_LOCK_ACQUIRED] ...
[CLOSE_LOCK_RELEASED] ... status=closed
[CLOSE_LOCK_STALE_RELEASE] appears at most briefly during recovery
[WATCHDOG_SUPPRESSED_CLOSE_LOCK] appears instead of exploration boost while locks are active
```

Forbidden:

```text
CLOSE_SKIP_DUPLICATE spam every second for same key
SELF_HEAL: STALL → boosting exploration while close locks active
[WATCHDOG] Critical idle → enabling micro-trades while close locks active
EXIT_INTEGRITY_ERROR
Invalid final_exit_type: replaced
Traceback
```

Observation target after patch:

- No duplicate close storm.
- No audit counter explosion.
- No stuck `[OPEN]` positions caused by permanent close locks.
- Watchdog does not amplify exploration during close recovery.
- Existing EV-only/PF/economic safety behavior unchanged.

---

## Do Not Change

- `canonical_profit_factor`
- `canonical_profit_factor_with_meta`
- `lm_economic_health`
- EV-only rejection logic
- Position sizing tiers
- TP/SL constants
- Firebase read/write quota logic
- Partial TP accounting
- Canonical PnL helper math from V10.13u+8
- Dashboard rendering except log labels if needed
