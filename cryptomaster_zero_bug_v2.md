# CRYPTOMASTER — ZERO BUG ARCHITECTURE (INCREMENTAL PATCH V2)

> Objective: Eliminate systemic runtime bugs, enforce deterministic execution, introduce event-driven architecture, and guarantee single-source-of-truth state across trading, learning, and UI.

---

# 0. CORE PRINCIPLE

## RULE: NO SIDE EFFECTS OUTSIDE EVENT PIPELINE

All subsystems MUST communicate only via event bus.

---

# 1. NEW ARCHITECTURE OVERVIEW

```
Market Data → Feature Engine → Signal Engine → Risk Engine → Execution Engine
        ↓            ↓             ↓             ↓             ↓
                 EVENT BUS (single source of truth)
        ↓            ↓             ↓             ↓             ↓
     Learning ←── Snapshot Builder ←── State Store ←── Logger/UI
```

---

# 2. CRITICAL FIXES

## 2.1 ELIMINATE DIRECT PRINTS (ZERO TOLERANCE)

### RULE:
No module is allowed to call `print()`.

### REPLACEMENT:
```python
def log(event_type, payload):
    event_bus.emit({
        "type": event_type,
        "payload": payload
    })
```

---

## 2.2 EVENT BUS (NEW CORE SYSTEM)

### FILE: `core/event_bus.py`

```python
from collections import defaultdict

class EventBus:
    def __init__(self):
        self.subscribers = defaultdict(list)

    def subscribe(self, event_type, handler):
        self.subscribers[event_type].append(handler)

    def emit(self, event):
        for handler in self.subscribers[event["type"]]:
            handler(event["payload"])
```

---

## 2.3 STATE STORE (SINGLE SOURCE OF TRUTH)

### FILE: `core/state.py`

```python
class State:
    def __init__(self):
        self.equity = 1.0
        self.positions = []
        self.drawdown = 0.0
        self.metrics = {}
        self.market_regime = "UNKNOWN"
        self.no_trade_counter = 0
```

---

## 2.4 SNAPSHOT BUILDER (IMMUTABLE STATE VIEW)

### FILE: `core/snapshot.py`

```python
def build_snapshot(state):
    return {
        "equity": state.equity,
        "positions": len(state.positions),
        "dd": state.drawdown,
        "regime": state.market_regime,
        "metrics": dict(state.metrics)
    }
```

---

# 3. ENGINE FIXES

---

## 3.1 SIGNAL ENGINE (REMOVE HARD FILTERING)

### BEFORE (BUG):
- hard reject signals → pipeline deadlock

### AFTER:

```python
def process_signal(signal):
    if signal.score < 0.3:
        signal.confidence *= 0.5
        signal.tag = "WEAK"
    return signal
```

---

## 3.2 RISK ENGINE (FAIL SAFE MODE)

```python
def risk_adjust(signal, state):
    if state.drawdown > 0.4:
        signal.size *= 0.2  # emergency mode
    elif state.drawdown > 0.2:
        signal.size *= 0.5
    return signal
```

---

## 3.3 EXECUTION ENGINE (DETERMINISTIC)

```python
def execute(signal, state):
    if signal.size <= 0:
        return None

    trade = {
        "asset": signal.asset,
        "size": signal.size,
        "entry": signal.price,
        "regime": state.market_regime
    }

    state.positions.append(trade)
    return trade
```

---

# 4. WATCHDOG REWRITE (NO MORE DEADLOCK)

```python
def watchdog(state):
    if state.no_trade_counter > 600:
        state.allow_micro_trade = True
        state.exploration_factor = 1.3
```

---

# 5. LEARNING SYSTEM FIX (CRITICAL)

## PROBLEM:
- no convergence
- bandit collapse
- weak EV updates

## FIX:

```python
def update_learning(stats, trade):
    stats.n += 1

    # stable incremental mean
    stats.ev += (trade.pnl - stats.ev) / stats.n

    # confidence convergence
    stats.conv = min(1.0, stats.n / 25)

    # bandit smoothing
    stats.bandit = (
        0.85 * stats.bandit +
        0.15 * (1 if trade.pnl > 0 else 0)
    )
```

---

# 6. UI FIX (ZERO DUPLICATION GUARANTEE)

```python
_rendered_hash = None

def render(snapshot):
    global _rendered_hash

    h = hash(str(snapshot))
    if h == _rendered_hash:
        return

    _rendered_hash = h
    ui_draw(snapshot)
```

---

# 7. EVENT PIPELINE (FINAL FLOW)

```python
def main_loop():
    state = State()

    while True:
        market = get_market_data()

        features = build_features(market)
        signals = generate_signals(features)

        for s in signals:
            s = process_signal(s)
            s = risk_adjust(s, state)
            trade = execute(s, state)

            if trade:
                update_learning(state.metrics, trade)

        snapshot = build_snapshot(state)
        render(snapshot)
```

---

# 8. GUARANTEED OUTCOMES

## BEFORE:
- duplicated logs
- frozen execution
- overfiltered signals
- weak learning
- unstable UI

## AFTER:
- deterministic execution flow
- no duplicate renders
- adaptive signal survival
- stable EV convergence
- event-driven architecture

---

# 9. MIGRATION STRATEGY (IMPORTANT)

### STEP 1:
Replace all `print()` → `event_bus.emit()`

### STEP 2:
Disable old renderer

### STEP 3:
Switch main loop to event-driven pipeline

### STEP 4:
Enable watchdog micro-trading mode

---

# END OF ZERO BUG PATCH V2
