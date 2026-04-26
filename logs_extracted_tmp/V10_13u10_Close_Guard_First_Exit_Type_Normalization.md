# V10.13u+10 — Close Guard First + Exit Type Normalization

## Goal
Fix two production issues seen after V10.13u+9:

1. `CLOSE_LOGIC_START` can still spam before lock acquisition.
2. Exit attribution rejects `reason=replaced`:
   `Invalid final_exit_type: replaced`

This patch is **safety/consistency only**. Do not change PF, EV-only, sizing, entry thresholds, Firebase budget, or TP/SL logic.

---

## Production Evidence

```text
[CLOSE_LOGIC_START] SOLUSDT reason=replaced entering close logic  # repeated many times
[CLOSE_LOCK_ACQUIRED] XRPUSDT reason=replaced key=...
[V10.13u8 EXIT_INTEGRITY_ERROR] sym=? exit_type=replaced
- Invalid final_exit_type: replaced
```

Interpretation:
- Reentrant guard exists, but it is likely acquired **after** `CLOSE_LOGIC_START` logging or not applied to every replacement/close path early enough.
- `replaced` is a valid operational close reason, but not a valid attribution `final_exit_type`.

---

## Files to Modify

```text
src/services/trade_executor.py
src/services/exit_attribution.py
tests/test_v10_13u_patches.py
```

Optional only if already used there:
```text
src/services/smart_exit_engine.py
```

---

## Patch A — Acquire Close Lock Before Any Close Log

In `trade_executor.py`, find the close-position function/block that logs:

```python
log.warning(f"[CLOSE_LOGIC_START] {sym} reason={reason} entering close logic")
```

Move duplicate guard/lock acquisition **above this log**.

Required order:

```python
key = _close_key(sym, pos)

if _is_recently_closed(key):
    log.warning(f"[CLOSE_SKIP_DUPLICATE] {sym} reason={reason} key={key} status=recently_closed")
    return None

if key in _CLOSING_POSITIONS:
    log.warning(f"[CLOSE_SKIP_DUPLICATE] {sym} reason={reason} key={key} status=already_closing")
    return None

_CLOSING_POSITIONS.add(key)
log.warning(f"[CLOSE_LOCK_ACQUIRED] {sym} reason={reason} key={key}")

log.warning(f"[CLOSE_LOGIC_START] {sym} reason={reason} entering close logic")
```

Acceptance:
- Duplicate attempts must show `CLOSE_SKIP_DUPLICATE`, not repeated `CLOSE_LOGIC_START`.
- `CLOSE_LOGIC_START` must occur only after lock acquisition.

---

## Patch B — Release Lock Safely

Wrap close execution in `try/finally`.

Pseudo pattern:

```python
closed_ok = False
try:
    # existing close logic
    # only after position is actually removed/persisted:
    closed_ok = True
    _mark_recently_closed(key)
    return result
finally:
    _CLOSING_POSITIONS.discard(key)
    log.warning(
        f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={key} "
        f"status={'closed' if closed_ok else 'aborted'}"
    )
```

Important:
- If close aborts before persistence/removal, do **not** mark recently closed.
- Always release `_CLOSING_POSITIONS`.
- TTL cleanup for `_RECENTLY_CLOSED` stays unchanged.

---

## Patch C — Normalize `replaced` Exit Type

Create helper in `exit_attribution.py`:

```python
def normalize_exit_type(exit_type: str | None) -> str:
    raw = str(exit_type or "UNKNOWN").strip()
    mapping = {
        "replaced": "REPLACED_EXIT",
        "REPLACED": "REPLACED_EXIT",
        "replace": "REPLACED_EXIT",
        "replacement": "REPLACED_EXIT",
        "SCRATCH": "SCRATCH_EXIT",
        "STAGNATION": "STAGNATION_EXIT",
    }
    return mapping.get(raw, raw)
```

Use it before validation and persistence:

```python
ctx["final_exit_type"] = normalize_exit_type(ctx.get("final_exit_type"))
```

Add `REPLACED_EXIT` to the allowed final exit types.

Do **not** silently drop replacement exits. They are valid and must be tracked.

---

## Patch D — Keep Display Compatibility

In dashboard/summary grouping, either:
- show `REPLACED_EXIT`, or
- display alias `replaced` while storing canonical `REPLACED_EXIT`.

Preferred:
```text
REPLACED_EXIT
```

Do not mix `replaced` and `REPLACED_EXIT` as separate categories.

---

## Patch E — Tests

Append tests to `tests/test_v10_13u_patches.py`.

### 1. Replacement exit type is accepted

```python
def test_replaced_exit_type_normalized():
    from src.services.exit_attribution import normalize_exit_type
    assert normalize_exit_type("replaced") == "REPLACED_EXIT"
    assert normalize_exit_type("REPLACED") == "REPLACED_EXIT"
```

### 2. Validator accepts replaced exit

Build minimal valid ctx with:
```python
final_exit_type="replaced"
gross_pnl=0.001
fee_cost=0.0001
slippage_cost=0.0000
net_pnl=0.0009
```

Assert validation passes after normalization.

### 3. Close lock happens before start log

Unit-test the close guard helper if possible. Otherwise use monkeypatch/log capture:
- first call acquires lock
- second call returns duplicate before close start
- `CLOSE_LOGIC_START` appears max once

### 4. Aborted close releases lock

Simulate exception/abort after lock acquisition and assert key not in `_CLOSING_POSITIONS`.

### 5. Successful close marks recent

Simulate successful close and assert duplicate within TTL is skipped.

---

## Validation Commands

On Hetzner after deploy:

```bash
cd /opt/cryptomaster
git pull --ff-only
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 8
sudo journalctl -u cryptomaster -n 2000 --no-pager | grep -E "RUNTIME_VERSION|CLOSE_LOGIC_START|CLOSE_LOCK|CLOSE_SKIP_DUPLICATE|EXIT_INTEGRITY|REPLACED_EXIT|Traceback|ERROR" | tail -120
```

Live watch:

```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "CLOSE_LOGIC_START|CLOSE_LOCK|CLOSE_SKIP_DUPLICATE|EXIT_INTEGRITY|REPLACED_EXIT|Traceback|ERROR"
```

---

## Success Criteria

Required:

```text
[RUNTIME_VERSION] commit=<new_commit> branch=main
[CLOSE_LOCK_ACQUIRED] ... reason=replaced ...
[CLOSE_LOGIC_START] ... reason=replaced ...       # max once per actual close
[CLOSE_LOCK_RELEASED] ... status=closed|aborted
```

Allowed:

```text
[CLOSE_SKIP_DUPLICATE] ... status=already_closing
[CLOSE_SKIP_DUPLICATE] ... status=recently_closed
```

Forbidden:

```text
many repeated CLOSE_LOGIC_START for same symbol/reason within 1 second
EXIT_INTEGRITY_ERROR ... Invalid final_exit_type: replaced
Traceback
```

---

## Do Not Change

- `canonical_profit_factor`
- `canonical_profit_factor_with_meta`
- `lm_economic_health`
- EV-only enforcement
- economic BAD conservative mode
- position sizing
- TP/SL constants
- Firebase reads/writes
- partial TP realized PnL accumulation
- `canonical_close_pnl`
- PnL validator accounting formula

---

## Expected Outcome

After this patch:
- close storms are stopped at the very top of close flow,
- repeated close attempts are visible only as `CLOSE_SKIP_DUPLICATE`,
- `replaced` no longer triggers integrity errors,
- exit attribution remains strict for real PnL mismatches.
