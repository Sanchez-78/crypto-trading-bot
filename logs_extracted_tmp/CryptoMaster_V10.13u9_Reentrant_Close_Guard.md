# CryptoMaster V10.13u+9 — Reentrant Close Guard / Idempotent Exit Patch

## Situation
Production logs show a critical close-loop reentrancy bug:

```text
[CLOSE_LOGIC_START] BTCUSDT reason=SCRATCH_EXIT entering close logic
... repeated dozens/hundreds of times within the same second
winners: SCRATCH_EXIT=25149 PARTIAL_TP_25=610
```

This is not normal exit behavior. It means the same open position can enter close logic repeatedly before it is removed/marked closed. This can spam logs, inflate exit audit counters, duplicate writes/notifier calls, and potentially corrupt learning/metrics.

## Immediate safety step on Hetzner

```bash
sudo systemctl stop cryptomaster
sudo journalctl -u cryptomaster -n 300 --no-pager | grep -E "CLOSE_LOGIC_START|CLOSE_LOGIC_DONE|CLOSE_SKIP|Traceback|ERROR" | tail -100
```

Do not tune exit thresholds until close idempotency is fixed.

---

## Task for Claude Code / Codex

You are a senior Python backend engineer. Implement a minimal, safe, idempotent close guard for CryptoMaster.

Goal: one logical position may execute close logic exactly once. Repeated exit checks for the same symbol/position while closing must be skipped.

## Files to inspect first

```text
src/services/trade_executor.py
src/services/smart_exit_engine.py
src/services/exit_attribution.py
tests/test_v10_13u_patches.py
```

Search:

```bash
grep -R "CLOSE_LOGIC_START\|close_position\|SCRATCH_EXIT\|STAGNATION_EXIT\|open_positions\|positions" -n src/services/trade_executor.py src/services/*.py
```

---

## Required patch

### 1. Add close lock state in `trade_executor.py`

Add module-level or executor-level structures:

```python
_CLOSING_POSITIONS: set[str] = set()
_RECENTLY_CLOSED: dict[str, float] = {}
_CLOSE_TTL_S = 30.0
```

Use a stable close key:

```python
def _close_key(sym: str, pos: dict) -> str:
    opened = pos.get("opened_at") or pos.get("entry_time") or pos.get("ts") or ""
    action = pos.get("action") or pos.get("side") or ""
    entry = pos.get("entry") or pos.get("entry_price") or ""
    return f"{sym}:{action}:{entry}:{opened}"
```

Also add cleanup:

```python
def _cleanup_recently_closed(now: float) -> None:
    for k, ts in list(_RECENTLY_CLOSED.items()):
        if now - ts > _CLOSE_TTL_S:
            _RECENTLY_CLOSED.pop(k, None)
```

### 2. Guard at the very start of close logic

Immediately before the current log:

```python
[CLOSE_LOGIC_START] ...
```

insert:

```python
now = time.time()
_cleanup_recently_closed(now)
ckey = _close_key(sym, pos)

if pos.get("_closing") or ckey in _CLOSING_POSITIONS or ckey in _RECENTLY_CLOSED:
    log.warning(
        f"[CLOSE_SKIP_DUPLICATE] {sym} reason={reason} key={ckey} "
        f"closing={pos.get('_closing')} recent={ckey in _RECENTLY_CLOSED}"
    )
    return None

pos["_closing"] = True
pos["_closing_reason"] = reason
pos["_closing_started_at"] = now
_CLOSING_POSITIONS.add(ckey)
log.warning(f"[CLOSE_LOCK_ACQUIRED] {sym} reason={reason} key={ckey}")
```

Do not allow any notifier, DB write, LM update, attribution update, or metrics update to run before the lock is acquired.

### 3. Release lock only after position is removed/closed

At the end of successful close, after the position is removed from active positions / portfolio:

```python
_RECENTLY_CLOSED[ckey] = time.time()
_CLOSING_POSITIONS.discard(ckey)
log.warning(f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={ckey} status=closed")
```

If the close fails with exception:

```python
_CLOSING_POSITIONS.discard(ckey)
pos["_closing"] = False
log.exception(f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={ckey} status=failed")
raise
```

Use `try/except/finally` carefully. On success, keep `_closing=True` irrelevant because position should no longer be active. On failure, restore it to allow retry.

### 4. Prevent exit audit counter inflation

Find where `winners: SCRATCH_EXIT=...` / exit audit counters increment.

Requirement:
- Exit audit counters may increment only when an actual close is accepted after `[CLOSE_LOCK_ACQUIRED]`.
- Do not increment repeatedly from passive exit recommendation/evaluation loops.
- Add a specific log if audit increment is skipped due to duplicate:

```python
[EXIT_AUDIT_SKIP_DUPLICATE] symbol=BTCUSDT reason=SCRATCH_EXIT key=...
```

### 5. Add defensive active-position removal ordering

If current flow removes position after notifier/DB writes, change order so active position is marked non-closeable immediately after PnL calculation and before slow external operations.

Safe order:

```text
1. acquire close lock
2. compute canonical PnL
3. mark position closing/non-closeable
4. remove from active positions or set status=CLOSING/CLOSED
5. write trade / metrics / learning
6. notifier
7. release lock into RECENTLY_CLOSED TTL
```

Never let the same position stay active and closeable while notifier/DB work is running.

### 6. Tests

Add tests to `tests/test_v10_13u_patches.py`:

```text
test_close_lock_blocks_duplicate_same_position
test_close_lock_allows_different_symbol
test_close_lock_releases_on_exception
test_recently_closed_ttl_blocks_immediate_reclose
test_exit_audit_not_incremented_on_duplicate
```

Mock minimal position dicts. Do not require Firebase or Binance.

### 7. Validation commands

Local:

```bash
python -m pytest tests/test_v10_13u_patches.py -k "close_lock or duplicate or recently_closed or exit_audit" -v
python -m pytest tests/test_v10_13u_patches.py -v
```

Hetzner after deploy:

```bash
sudo systemctl restart cryptomaster
sleep 10
sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "CLOSE_LOGIC_START|CLOSE_LOCK|CLOSE_SKIP_DUPLICATE|EXIT_AUDIT_SKIP_DUPLICATE|SCRATCH_EXIT|STAGNATION_EXIT|Traceback|ERROR" | tail -250
```

Success criteria:

```text
✅ CLOSE_LOGIC_START appears once per actual symbol close, not hundreds of times
✅ Duplicate attempts show CLOSE_SKIP_DUPLICATE
✅ No repeated BTCUSDT SCRATCH_EXIT storm
✅ winners: SCRATCH_EXIT no longer jumps to absurd values like 25149
✅ No EXIT_INTEGRITY_ERROR
✅ No Traceback
```

Rollback if needed:

```bash
sudo systemctl stop cryptomaster
git log --oneline -5
git reset --hard <previous_good_commit>
sudo systemctl start cryptomaster
```

## Do NOT change

```text
- canonical PF / economic health logic
- canonical_close_pnl formula
- EV-only enforcement
- TP/SL multipliers
- Firebase quota logic
- learning hydration logic
```

This patch is only for close idempotency and audit counter integrity.
