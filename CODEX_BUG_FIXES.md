# Codex Implementation Prompt — CryptoMaster Bug Fixes

## Context

This is a Python high-frequency trading bot. The codebase uses a synchronous
event-bus (`src/core/event_bus.py`) where WebSocket price ticks arrive on one
thread and fire subscribed handlers synchronously. Two handlers share global
mutable state: `trade_executor.on_price` (subscribed to `price_tick`) and
`trade_executor.handle_signal` (subscribed to `signal_created`). There is no
asyncio involved in the execution path — everything is threading.

## Instructions

Implement all five fixes below **in the order listed**. Each fix is independent.
After all fixes, add or update tests in `tests/test_v5_core.py`. Run
`python -m py_compile` on every changed file and `python -m pytest tests/ -q`
before finishing. Do not touch any file not listed in a fix.

---

## Fix 1 — DATA_RACE: `_positions` dict unprotected across threads

**Files:** `src/services/trade_executor.py`

**Problem:**  
`_positions` (line 63) is a plain `dict` accessed by two handlers that fire from
different threads:
- `handle_signal()` (line 1167) — subscribed to `signal_created`
- `on_price()` (line 1941) — subscribed to `price_tick`

Both read and write `_positions` without any lock. Concurrent access causes
`KeyError`, corrupted position data, or lost closes under load.

**Fix:**

1. Add at line 63 (next to `_positions = {}`):
   ```python
   _positions_lock = threading.RLock()
   ```

2. Wrap every block that reads OR writes `_positions` in both `handle_signal`
   and `on_price` (and any helper they call that touches `_positions` directly:
   `_allow_trade`, `_replace_if_better`, `_close_position`, `get_open_positions`,
   `force_close_symbol`) with:
   ```python
   with _positions_lock:
       ...
   ```

3. `get_open_positions()` (line 947) already returns `dict(_positions)` — keep
   that shallow copy; it's fine as long as the copy is taken under the lock.

4. Do NOT lock across I/O calls (Firebase writes, notifier threads). Lock only
   the dict read/write itself; release before any blocking call.

---

## Fix 2 — STALE_STATE: `_processed_events` set evicts random entries, not oldest

**File:** `src/core/event_bus.py`

**Problem:**  
`_processed_events` is a `set` (line 18). When it overflows `_MAX_PROCESSED_EVENTS`
(2000), line 46–48 evicts by slicing `list(_processed_events)`. Sets have no
insertion-order guarantee in Python, so this evicts a random half — recent
event IDs may be dropped, allowing duplicates through; old IDs may be kept,
wasting memory.

**Fix:**

Replace the set with a `collections.deque` with a fixed `maxlen`. The deque
auto-evicts the oldest entry on overflow — no manual eviction needed.

```python
# Remove:
_processed_events: set = set()
_MAX_PROCESSED_EVENTS = 2000

# Add (at top of file, after imports):
from collections import deque
_processed_events: deque = deque(maxlen=2000)
```

Update `publish()` to use the deque API:

```python
# Remove lines 42–48 (the old eid check block) and replace with:
if isinstance(data, dict):
    eid = data.get("_event_id")
    if eid is not None:
        if eid in _processed_events:
            return
        _processed_events.append(eid)   # deque drops oldest automatically
```

Remove the now-unused `_MAX_PROCESSED_EVENTS` constant and the `keep`/`clear`/
`update` eviction block entirely.

---

## Fix 3 — DATA_RACE: `lm_pnl_hist` list mutated and iterated without a copy

**File:** `src/services/learning_monitor.py`

**Problem:**  
`lm_update()` appends to `lm_pnl_hist[key]` (line 346) and then, in the same
function a few lines later, iterates the same list to compute win-rate (line 371:
`wins = sum(1 for x in pnl_lst if x > 0)`). Because `lm_update` can be called
from the trade-close path (WebSocket thread) while `lm_pnl_hist` is also read
by dashboard/stats functions on other threads, the iteration can see a
mid-append list state.

**Fix:**

Wherever `lm_pnl_hist` values are iterated (not just appended), take a local
snapshot first:

```python
# In lm_update(), before the win-rate computation (around line 369):
pnl_snap = list(pnl_lst)   # snapshot under no lock needed — list.copy() is atomic in CPython
wins  = sum(1 for x in pnl_snap if x > 0)
total = len(pnl_snap)
```

Apply the same `list(...)` snapshot pattern everywhere `lm_pnl_hist.get(key, [])`
is iterated in a loop or passed to `sum()`/`np.mean()`/`np.std()`. Specifically:
- `lm_update()` — lines ~369–375
- `true_ev()` — wherever `pnl` list is passed to `np.mean` / `np.std`
- `ev_stability()` — wherever `pnl_list` is iterated
- `check_learning_integrity()` — wherever per-pair lists are iterated

Do **not** add a module-level lock — a snapshot is sufficient and avoids
contention on the hot path.

---

## Fix 4 — SILENT_FAIL: Notifier daemon thread swallows all exceptions

**File:** `src/services/trade_executor.py`

**Problem:**  
Lines 2232–2233:
```python
from src.services.notifier import send_trade_notification as _notify
threading.Thread(target=_notify, args=(...), daemon=True).start()
```
Any exception inside `_notify` (network error, Firebase error, encoding error)
is silently discarded because daemon threads have no exception propagation.
Operators never know trade notifications have stopped.

**Fix:**

Replace the two lines above with:
```python
try:
    from src.services.notifier import send_trade_notification as _notify
    def _notify_safe(*a):
        try:
            _notify(*a)
        except Exception as _ne:
            log.warning("[NOTIFY_FAIL] send_trade_notification: %s", _ne)
    threading.Thread(
        target=_notify_safe,
        args=(sym, pos["action"], move - fee_used, reason),
        daemon=True,
    ).start()
except Exception as e:
    log.info("    [Warn: Notifikace error] %s", e)
```

---

## Fix 5 — LOGIC_ERROR: `_regime_exposure` increment/decrement use different defaults

**File:** `src/services/trade_executor.py`

**Problem:**  
Open (line 1920):
```python
_regime_exposure[regime] = _regime_exposure.get(regime, 0) + 1
```
Close (line 2458–2459):
```python
_regime_exposure[closed_regime] = max(
    0, _regime_exposure.get(closed_regime, 0) - 1)
```
Both use `default=0`, which is consistent now. But if the bot restarts mid-trade
(position loaded from Firebase but `_regime_exposure` starts empty), the close
path gets `get(regime, 0)` → 0, then `max(0, -1)` → 0, leaving the counter at
0. The next open increments to 1 rather than resuming from the true live count,
causing the regime concentration gate (`_allow_trade` line 1154) to under-count
open positions and allow excess concentration.

**Fix:**

Populate `_regime_exposure` when positions are re-hydrated from Firebase at
startup. In the function that loads existing open positions from Firestore
(search for `bootstrap_from_history` or `load_history` in `trade_executor.py`
or `bot2/main.py`) add, after each position is loaded into `_positions`:

```python
# Recount exposure from loaded positions rather than trusting the counter
_regime_exposure.clear()
for pos in _positions.values():
    r = pos.get("regime", "RANGING")
    _regime_exposure[r] = _regime_exposure.get(r, 0) + 1
```

This ensures the counter always matches actual open positions after restart.
Run the recount once, immediately after all positions are loaded.

---

## Tests to add in `tests/test_v5_core.py`

Add a new test class `TestBugFixes` at the bottom of the file:

```python
class TestBugFixes:
    """Regression tests for the five-fix batch (V10.15x)."""

    def test_positions_lock_exists(self):
        """trade_executor must expose a _positions_lock RLock."""
        import src.services.trade_executor as te
        import threading
        assert hasattr(te, "_positions_lock"), "_positions_lock missing"
        assert isinstance(te._positions_lock, type(threading.RLock())), \
            "_positions_lock must be an RLock"

    def test_processed_events_is_deque(self):
        """event_bus._processed_events must be a deque, not a set."""
        from collections import deque
        import src.core.event_bus as eb
        assert isinstance(eb._processed_events, deque), \
            "_processed_events must be a deque for ordered eviction"

    def test_processed_events_evicts_oldest(self):
        """Oldest event IDs must be evicted first when deque overflows."""
        from collections import deque
        import src.core.event_bus as eb
        # Reset to a tiny deque for test isolation
        original = eb._processed_events
        eb._processed_events = deque(maxlen=3)
        try:
            eb._processed_events.append("A")
            eb._processed_events.append("B")
            eb._processed_events.append("C")
            eb._processed_events.append("D")   # should evict "A"
            assert "A" not in eb._processed_events
            assert "D" in eb._processed_events
        finally:
            eb._processed_events = original

    def test_lm_pnl_hist_snapshot_does_not_raise_on_concurrent_append(self):
        """Iterating a snapshot of lm_pnl_hist must not raise even if the source
        list is modified concurrently."""
        import threading
        from src.services.learning_monitor import lm_pnl_hist

        key = ("TEST_SNAP", "RANGING")
        lm_pnl_hist[key] = [0.01, -0.005, 0.02]
        errors = []

        def _reader():
            try:
                snap = list(lm_pnl_hist.get(key, []))
                _ = sum(1 for x in snap if x > 0)
            except Exception as e:
                errors.append(e)

        def _writer():
            for _ in range(50):
                lm_pnl_hist[key].append(0.001)

        t_r = threading.Thread(target=_reader)
        t_w = threading.Thread(target=_writer)
        t_r.start(); t_w.start()
        t_r.join();  t_w.join()

        assert not errors, f"Reader raised during concurrent write: {errors}"
        del lm_pnl_hist[key]

    def test_regime_exposure_recount_matches_positions(self):
        """After recount, _regime_exposure must equal the tally of open positions."""
        import src.services.trade_executor as te
        original_positions = dict(te._positions)
        original_exposure  = dict(te._regime_exposure)
        try:
            te._positions = {
                "BTCUSDT": {"regime": "RANGING",    "action": "BUY",  "size": 1},
                "ETHUSDT": {"regime": "RANGING",    "action": "SELL", "size": 1},
                "SOLUSDT": {"regime": "BULL_TREND", "action": "BUY",  "size": 1},
            }
            te._regime_exposure.clear()
            for pos in te._positions.values():
                r = pos.get("regime", "RANGING")
                te._regime_exposure[r] = te._regime_exposure.get(r, 0) + 1
            assert te._regime_exposure.get("RANGING",    0) == 2
            assert te._regime_exposure.get("BULL_TREND", 0) == 1
        finally:
            te._positions       = original_positions
            te._regime_exposure = original_exposure
```

---

## Acceptance criteria

- `python -m py_compile src/services/trade_executor.py` — exit 0
- `python -m py_compile src/core/event_bus.py` — exit 0
- `python -m py_compile src/services/learning_monitor.py` — exit 0
- `python -m pytest tests/ -q` — all tests pass, no new failures
- No new `bare except:` or `except Exception: pass` introduced
