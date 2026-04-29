# CryptoMaster — P1.1N Emergency Fix: make paper_train work without spam

## Objective
Stop the current duplicate paper-train spam and create a useful end-to-end learning loop:

`signal / reject / duplicate / blocked gate -> controlled paper_train sample -> paper position -> exit -> learning update -> bucket metrics -> adaptive tuning later`

Current production proves routing works, but it is broken by spam:
- many `[PAPER_TRAIN_ENTRY]` for the same symbol/side/source in the same second
- repeated `DUPLICATE_CANDIDATE(age=0.0s)` creates many duplicate trades
- some `C_WEAK_EV_TRAIN` entries open even with `cost_edge_ok=False`
- this pollutes learning and Firebase with low-quality duplicate samples

## Hard rules
- Do not enable real orders.
- Do not modify `live_real` behavior.
- Only affect `TRADING_MODE=paper_train`.
- Use real market prices only.
- No tick-level Firebase writes.
- No synthetic trades.
- Entry log must mean an actual paper position was opened.
- Bad/blocked samples must produce clear `[PAPER_TRAIN_SKIP]` logs.
- Do not start P1.2 until this is stable for at least 2 hours.

## Emergency safety first

Before code changes, archive current polluted open paper state on server:

```bash
cd /opt/cryptomaster
mkdir -p data/archive
cp -a data/paper_open_positions.json "data/archive/paper_open_positions.$(date +%Y%m%d_%H%M%S).json" 2>/dev/null || true
python - <<'PY'
import json, os
p="data/paper_open_positions.json"
if os.path.exists(p):
    json.dump({}, open(p, "w"), indent=2)
    print("paper_open_positions reset to {}")
else:
    print("no paper_open_positions file")
PY
```

Keep `.env`:

```env
TRADING_MODE=paper_train
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_TRAINING_ENABLED=true
PAPER_TRAINING_MIN_ENTRIES_PER_HOUR=6
PAPER_TRAIN_MAX_OPEN_PER_SYMBOL=1
PAPER_TRAIN_MAX_OPEN_PER_BUCKET=2
PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE=3
PAPER_TRAIN_MAX_ENTRIES_PER_HOUR=18
PAPER_TRAIN_DEDUPE_WINDOW_S=30
PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S=60
PAPER_EXPLORATION_ENABLED=false
```

Important: in `paper_train`, disable old `PAPER_EXPLORATION_ENABLED`; otherwise old exploration and new training can both sample the same rejected signal.

---

# Implementation patch

## Files
Likely files:
- `src/services/paper_training_sampler.py`
- `src/services/trade_executor.py`
- `src/services/paper_trade_executor.py`
- `src/services/runtime_mode.py`
- tests: add/update paper training tests

---

## 1. Add paper_train config helpers

In runtime/config helper area, add robust env readers:

```python
import os

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return default

def paper_train_enabled() -> bool:
    return os.getenv("TRADING_MODE", "").strip().lower() == "paper_train" and _env_bool("PAPER_TRAINING_ENABLED", True)

PAPER_TRAIN_MAX_OPEN_PER_SYMBOL = _env_int("PAPER_TRAIN_MAX_OPEN_PER_SYMBOL", 1)
PAPER_TRAIN_MAX_OPEN_PER_BUCKET = _env_int("PAPER_TRAIN_MAX_OPEN_PER_BUCKET", 2)
PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE = _env_int("PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE", 3)
PAPER_TRAIN_MAX_ENTRIES_PER_HOUR = _env_int("PAPER_TRAIN_MAX_ENTRIES_PER_HOUR", 18)
PAPER_TRAIN_DEDUPE_WINDOW_S = _env_int("PAPER_TRAIN_DEDUPE_WINDOW_S", 30)
PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S = _env_int("PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S", 60)
```

---

## 2. Sampler-level dedupe and rate caps

In `paper_training_sampler.py`, add module-level state:

```python
import time
from collections import defaultdict, deque

_recent_dedupe = {}
_recent_dup_candidate = {}
_entry_times_minute = deque()
_entry_times_hour = deque()
_health = defaultdict(int)

def _now() -> float:
    return time.time()

def _prune(now: float) -> None:
    while _entry_times_minute and now - _entry_times_minute[0] > 60:
        _entry_times_minute.popleft()
    while _entry_times_hour and now - _entry_times_hour[0] > 3600:
        _entry_times_hour.popleft()
    for k, ts in list(_recent_dedupe.items()):
        if now - ts > max(PAPER_TRAIN_DEDUPE_WINDOW_S * 2, 120):
            _recent_dedupe.pop(k, None)
    for k, ts in list(_recent_dup_candidate.items()):
        if now - ts > max(PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S * 2, 180):
            _recent_dup_candidate.pop(k, None)

def _skip(reason: str, **kw) -> dict:
    _health["skips"] += 1
    _health[f"skip_{reason}"] += 1
    return {"allowed": False, "reason": reason, **kw}

def _allow(**kw) -> dict:
    _health["entries"] += 1
    return {"allowed": True, **kw}
```

Before returning an allowed sample, enforce:

```python
def _training_quality_gate(symbol, side, bucket, source_reject, cost_edge_ok, open_positions=None):
    now = _now()
    _prune(now)

    symbol = str(symbol or "UNKNOWN").upper()
    side = str(side or "UNKNOWN").upper()
    bucket = str(bucket or "UNKNOWN")
    source_reject = str(source_reject or "UNKNOWN")

    # Cost-edge: do not open weak EV train if edge cannot cover costs.
    if bucket == "C_WEAK_EV_TRAIN" and cost_edge_ok is False:
        return _skip("cost_edge_too_low", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # Dedicated duplicate candidate cooldown.
    if "DUPLICATE_CANDIDATE" in source_reject:
        dk = f"{symbol}:{side}:DUPLICATE_CANDIDATE"
        last = _recent_dup_candidate.get(dk)
        if last is not None and now - last < PAPER_TRAIN_DUPLICATE_CANDIDATE_COOLDOWN_S:
            return _skip("duplicate_candidate_cooldown", symbol=symbol, bucket=bucket, source_reject=source_reject)
        _recent_dup_candidate[dk] = now

    # General dedupe per window.
    window = int(now // PAPER_TRAIN_DEDUPE_WINDOW_S)
    dedupe_key = f"{symbol}:{side}:{bucket}:{source_reject}:{window}"
    if dedupe_key in _recent_dedupe:
        return _skip("duplicate_training_sample", symbol=symbol, bucket=bucket, source_reject=source_reject)
    _recent_dedupe[dedupe_key] = now

    # Global rate caps.
    if len(_entry_times_minute) >= PAPER_TRAIN_MAX_ENTRIES_PER_MINUTE:
        return _skip("max_entries_per_minute", symbol=symbol, bucket=bucket, source_reject=source_reject)
    if len(_entry_times_hour) >= PAPER_TRAIN_MAX_ENTRIES_PER_HOUR:
        return _skip("max_entries_per_hour", symbol=symbol, bucket=bucket, source_reject=source_reject)

    # Open-position caps.
    open_positions = open_positions or []
    open_symbol = 0
    open_bucket = 0
    for p in open_positions:
        if (p.get("paper_source") == "training_sampler") or p.get("training_bucket"):
            if str(p.get("symbol", "")).upper() == symbol:
                open_symbol += 1
            if str(p.get("training_bucket", "")) == bucket:
                open_bucket += 1

    if open_symbol >= PAPER_TRAIN_MAX_OPEN_PER_SYMBOL:
        return _skip("max_open_per_symbol", symbol=symbol, bucket=bucket, open_symbol=open_symbol)
    if open_bucket >= PAPER_TRAIN_MAX_OPEN_PER_BUCKET:
        return _skip("max_open_per_bucket", symbol=symbol, bucket=bucket, open_bucket=open_bucket)

    _entry_times_minute.append(now)
    _entry_times_hour.append(now)
    return _allow(symbol=symbol, side=side, bucket=bucket, source_reject=source_reject)
```

Integrate this gate inside `maybe_open_training_sample()` after bucket/side/cost-edge are known but before open call is attempted.

---

## 3. Entry log only after actual open success

Where training router opens paper position:

Bad behavior:
```python
log.info("[PAPER_TRAIN_ENTRY] ...")
open_paper_position(...)
```

Correct behavior:
```python
opened = open_paper_position(...)
if opened:
    log.info(
        "[PAPER_TRAIN_ENTRY] bucket=%s symbol=%s side=%s price=%.8f size_mult=%.3f ev=%.4f "
        "cost_edge_ok=%s expected_move_pct=%.4f side_inferred=%s source_reject=%s",
        bucket, symbol, side, price, size_mult, ev, cost_edge_ok, expected_move_pct, side_inferred, source_reject
    )
else:
    log.info(
        "[PAPER_TRAIN_SKIP] reason=open_blocked symbol=%s bucket=%s source_reject=%s",
        symbol, bucket, source_reject
    )
```

If `open_paper_position()` returns a dict/ID instead of bool, treat non-empty as success.

---

## 4. Paper executor must enforce caps too

Even if sampler fails, `open_paper_position()` should protect state in paper_train:

Before appending position:
- if `paper_source == "training_sampler"`:
  - block if same symbol already open
  - block if too many same bucket
  - return `None` / `False`
  - log `[PAPER_ENTRY_BLOCKED] reason=max_open_per_symbol ...` or `max_open_per_bucket`

This is the second safety layer.

---

## 5. Health summary log

Every 10 minutes:

```python
_last_health_log = 0.0

def maybe_log_training_health(open_positions_count: int = 0):
    global _last_health_log
    now = _now()
    if now - _last_health_log < 600:
        return
    _last_health_log = now
    log.info(
        "[PAPER_TRAIN_HEALTH] router=%d entries=%d skips=%d duplicate_skips=%d "
        "duplicate_candidate_skips=%d cost_edge_skips=%d max_symbol_skips=%d "
        "max_bucket_skips=%d open_positions=%d minute_entries=%d hour_entries=%d",
        _health.get("router", 0),
        _health.get("entries", 0),
        _health.get("skips", 0),
        _health.get("skip_duplicate_training_sample", 0),
        _health.get("skip_duplicate_candidate_cooldown", 0),
        _health.get("skip_cost_edge_too_low", 0),
        _health.get("skip_max_open_per_symbol", 0),
        _health.get("skip_max_open_per_bucket", 0),
        open_positions_count,
        len(_entry_times_minute),
        len(_entry_times_hour),
    )
```

Call this from router/sampler path and/or periodic tick.

---

## 6. Tests

Add tests that must pass:

1. Repeated duplicate candidate spam opens exactly one sample:
```python
for _ in range(20):
    maybe_open_training_sample(symbol="ETHUSDT", side="BUY", source_reject="DUPLICATE_CANDIDATE(age=0.0s)", ...)
assert entries == 1
assert skips >= 19
```

2. `cost_edge_ok=False` blocks C_WEAK_EV_TRAIN:
```python
assert result["allowed"] is False
assert result["reason"] == "cost_edge_too_low"
```

3. max open per symbol blocks second open.

4. max open per bucket blocks after configured cap.

5. global minute cap blocks after configured cap.

6. `PAPER_TRAIN_ENTRY` is logged only after successful `open_paper_position`.

7. live executor is never called in paper_train.

8. closed training trade still emits learning update.

---

## Validation

```bash
python -m py_compile src/services/paper_training_sampler.py src/services/paper_trade_executor.py src/services/trade_executor.py src/services/realtime_decision_engine.py
python -m pytest tests/test_paper_mode.py tests/test_p1_paper_exploration.py tests/test_p0_3_paper_integration.py -v
git diff --check
```

Commit:

```bash
git add src tests .env.example
git commit -m "P1.1N: stabilize paper_train with anti-spam dedupe and quality caps"
git push origin main
```

---

## Production deploy

```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 60

sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_TRAIN_ROUTER|PAPER_TRAIN_ENTRY|PAPER_TRAIN_SKIP|PAPER_TRAIN_HEALTH|PAPER_ENTRY_BLOCKED|PAPER_EXIT|LEARNING_UPDATE|Traceback|ERROR"
```

Success criteria:
- `[TRADING_MODE] mode=paper_train`
- router > 0
- entries controlled, not dozens per second
- duplicate spam becomes `PAPER_TRAIN_SKIP reason=duplicate_candidate_cooldown` or `duplicate_training_sample`
- `PAPER_EXIT` appears
- `LEARNING_UPDATE` appears
- no Traceback
- no ERROR
- no real orders

Counting command:

```bash
sudo journalctl -u cryptomaster --since "60 minutes ago" --no-pager \
  | grep -E "PAPER_TRAIN_ROUTER|PAPER_TRAIN_ENTRY|PAPER_TRAIN_SKIP|PAPER_EXIT|LEARNING_UPDATE|Traceback|ERROR" \
  | awk '
/PAPER_TRAIN_ROUTER/ {r++}
/PAPER_TRAIN_ENTRY/ {e++}
/PAPER_TRAIN_SKIP/ {s++}
/PAPER_EXIT/ {x++}
/LEARNING_UPDATE/ {l++}
/Traceback|ERROR/ {err++}
END {print "router="r, "entries="e, "skips="s, "exits="x, "learning="l, "errors="err}'
```

Expected after 60 minutes:
```text
router > 0
entries between 3 and 18
skips > 0
exits > 0 after hold windows
learning > 0
errors = 0
```

## Do not continue to P1.2 until this is true
Minimum gate:
- 2 hours stable
- 20+ closed training trades
- no duplicate spam
- learning updates visible
- bucket metrics visible
- no real orders
- no Traceback/ERROR
