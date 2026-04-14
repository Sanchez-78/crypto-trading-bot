# CRYPTOMASTER — FULL PATCH PROMPT (V10.x STABILITY + CLEAN EXECUTION FIX)

> Goal: Fix duplicated output, stabilize execution loop, repair learning monitor drift, remove UI corruption, enforce single-source-of-truth state, and ensure trading decisions are not blocked by logging/render bugs.

---

# 1. CRITICAL PROBLEMS FOUND (FROM LOG)

## 1.1 UI / LOG CORRUPTION (SEVERE)
### Symptoms:
- Repeated duplicated blocks of entire dashboard
- Mixed sections
- Broken stream rendering

### Root cause:
- Multiple render calls per tick
- No frame deduplication
- No atomic snapshot lock

---

## 1.2 EXECUTION ENGINE IS IDLE (BUG)
### Symptoms:
- Exposure 0
- No trades

### Root cause:
- EV threshold gating too strict
- Overfiltered signals

---

## 1.3 SIGNAL PIPELINE OVER-FILTERING
- 0 signals after filter
- 64 blocked / 1202 executed imbalance

---

## 1.4 LEARNING MONITOR STAGNATION
- weak edge
- no convergence

---

## 1.5 DUPLICATED STATE PRINTING
- multiple dashboard prints per cycle

---

# 2. REQUIRED ARCHITECTURE FIX

Single snapshot render per cycle:
market_tick → signals → risk → execution → learning → snapshot → render

---

# 3. PATCHES

## 3.1 Renderer lock
```python
import threading

_render_lock = threading.Lock()
_last_snapshot_hash = None

def render(snapshot):
    global _last_snapshot_hash
    with _render_lock:
        h = hash(str(snapshot))
        if h == _last_snapshot_hash:
            return
        _last_snapshot_hash = h
        print(snapshot)
```

---

## 3.2 Remove duplicate prints
```python
renderer.render(snapshot)
```

---

## 3.3 Soft filter
```python
def filter_signal(signal, state):
    if signal.score < state.ev_threshold:
        signal.confidence *= 0.8
    return signal
```

---

## 3.4 Watchdog fix
```python
def ensure_activity(state):
    if state.no_trades_seconds > 600:
        state.allow_micro_trade = True
```

---

## 3.5 Learning update
```python
def update_learning(self, trade):
    key = (trade.asset, trade.regime)
    stats = self.memory[key]
    stats.n += 1
    stats.ev = stats.ev + (trade.pnl - stats.ev) / stats.n
```

---

## 3.6 Snapshot
```python
def build_snapshot(state):
    return {
        "equity": state.equity,
        "dd": state.drawdown,
        "positions": len(state.positions)
    }
```

---

# END
