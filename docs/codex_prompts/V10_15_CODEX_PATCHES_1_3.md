# V10.15 Mammon — Codex Task: Patches 1–3 (Core Helpers)

**Objective**: Implement 3 pure helper modules for observability (no trading behavior changes).

**Scope**: 100% CODEX_SAFE (dataclasses, enums, serialization, tests).

---

## HARD CONSTRAINTS

❌ **FORBIDDEN FILES** (do not touch):
```
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/learning_event.py
src/services/firebase_client.py
src/services/market_stream.py
src/services/signal_generator.py
bot2/main.py
start.py
start_fresh.py
src/core/event_bus.py
src/core/event_bus_v2.py
CLAUDE.md
```

❌ **FORBIDDEN CHANGES**:
- Do not add external dependencies
- Do not change Firestore schema
- Do not modify EV formula or gate logic
- Do not modify any existing imports
- Do not add async/await
- Do not touch any _config_, _constants_, or _thresholds_

✅ **ALLOWED ACTIONS**:
- Create new files only (no edits to existing files)
- Add type hints
- Add docstrings
- Add unit tests
- Import only stdlib + existing local modules

---

## PATCH 1: Core Helpers

**Files to create**:
- `src/core/decision_frame.py` (200–250 lines)
- `src/core/error_registry.py` (100–150 lines)

### src/core/decision_frame.py

```python
"""
Pure dataclass for wrapping decision signals and computations.
Backward compatible with plain dicts (can convert bidirectionally).
"""

from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, List
from enum import Enum

class DecisionState(Enum):
    """Decision state enum."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"

class GateType(Enum):
    """Gate types."""
    EV = "ev"
    COHERENCE = "coherence"
    SPREAD = "spread"
    FREQUENCY = "frequency"
    LOSS_STREAK = "loss_streak"
    DRAWDOWN = "drawdown"
    CALIBRATION = "calibration"

@dataclass
class GateResult:
    """Result of evaluating a single gate."""
    gate_type: GateType
    passed: bool
    reason: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None

@dataclass
class DecisionFrame:
    """
    Wraps signal + decision context.
    Converts from dict signal (backward compat) and back to dict.
    """
    symbol: str
    side: str  # "BUY" | "SELL"
    regime: str
    confidence: float
    ev: float
    ev_final: float
    score: float
    score_threshold: float
    prob: float  # win probability
    rr: float  # risk-reward ratio
    decision: DecisionState = DecisionState.PENDING
    gates: List[GateResult] = field(default_factory=list)
    reject_reason: Optional[str] = None
    timestamp: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_signal_dict(cls, signal: Dict[str, Any], ev: float, 
                         score: float, threshold: float) -> 'DecisionFrame':
        """Construct from RDE signal dict."""
        return cls(
            symbol=signal.get("symbol", "UNKNOWN"),
            side=signal.get("side", "BUY"),
            regime=signal.get("regime", "UNKNOWN"),
            confidence=signal.get("confidence", 0.5),
            ev=ev,
            ev_final=ev,
            score=score,
            score_threshold=threshold,
            prob=signal.get("prob", 0.5),
            rr=signal.get("rr", 1.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict."""
        d = asdict(self)
        d["gates"] = [asdict(g) for g in self.gates]
        d["decision"] = self.decision.value
        return d

    def add_gate(self, gate: GateResult) -> 'DecisionFrame':
        """Add gate result."""
        self.gates.append(gate)
        return self

    def approve(self, reason: str = "all gates passed") -> 'DecisionFrame':
        """Mark as approved."""
        self.decision = DecisionState.APPROVED
        return self

    def reject(self, reason: str) -> 'DecisionFrame':
        """Mark as rejected."""
        self.decision = DecisionState.REJECTED
        self.reject_reason = reason
        return self

    def block(self, reason: str) -> 'DecisionFrame':
        """Mark as blocked."""
        self.decision = DecisionState.BLOCKED
        self.reject_reason = reason
        return self
```

### src/core/error_registry.py

```python
"""
Pure error code registry.
Maps error codes to descriptions for canonical logging.
"""

from enum import Enum

class ErrorCode(Enum):
    """Canonical error/decision codes."""
    # Decision codes
    DECISION_APPROVED = "DECISION-APPROVED"
    DECISION_REJECTED = "DECISION-REJECTED"
    DECISION_BLOCKED = "DECISION-BLOCKED"
    
    # Gate rejections
    EV_TOO_LOW = "GATE-EV-LOW"
    SPREAD_WIDE = "GATE-SPREAD-WIDE"
    OVERTRADING = "GATE-OVERTRADING"
    LOSS_STREAK = "GATE-LOSS-STREAK"
    DRAWDOWN_HALT = "GATE-DD-HALT"
    COHERENCE_FAIL = "GATE-COHERENCE"
    CALIBRATION_INSUFFICIENT = "GATE-CALIB-INSUFF"
    
    # Execution codes
    ORDER_SENT = "EXEC-ORDER-SENT"
    ORDER_FILLED = "EXEC-ORDER-FILLED"
    ORDER_REJECTED = "EXEC-ORDER-REJECTED"
    
    # Exit codes
    EXIT_TP = "EXIT-TP"
    EXIT_SL = "EXIT-SL"
    EXIT_TRAIL = "EXIT-TRAIL"
    EXIT_TIMEOUT = "EXIT-TIMEOUT"
    EXIT_SCRATCH = "EXIT-SCRATCH"
    EXIT_STAGNATION = "EXIT-STAGNATION"
    EXIT_REGIME_CHANGE = "EXIT-REGIME-CHANGE"
    
    # Learning codes
    LEARN_TRADE_CLOSED = "LEARN-TRADE-CLOSED"
    LEARN_CALIBRATED = "LEARN-CALIBRATED"
    LEARN_FIREBASE_SAVED = "LEARN-FIREBASE-SAVED"

class ErrorRegistry:
    """Lookup descriptions for error codes."""
    
    _DESCRIPTIONS = {
        ErrorCode.DECISION_APPROVED: "Decision approved, executing trade",
        ErrorCode.DECISION_REJECTED: "Decision rejected, no trade",
        ErrorCode.DECISION_BLOCKED: "Decision blocked by auditor",
        
        ErrorCode.EV_TOO_LOW: "Expected value below threshold",
        ErrorCode.SPREAD_WIDE: "Bid-ask spread too wide",
        ErrorCode.OVERTRADING: "Too many trades in window",
        ErrorCode.LOSS_STREAK: "Loss streak detected",
        ErrorCode.DRAWDOWN_HALT: "Drawdown halt triggered",
        ErrorCode.COHERENCE_FAIL: "Regime-EV coherence failed",
        ErrorCode.CALIBRATION_INSUFFICIENT: "Calibration data insufficient",
        
        ErrorCode.ORDER_SENT: "Order sent to exchange",
        ErrorCode.ORDER_FILLED: "Order filled",
        ErrorCode.ORDER_REJECTED: "Order rejected by exchange",
        
        ErrorCode.EXIT_TP: "Exit: take-profit",
        ErrorCode.EXIT_SL: "Exit: stop-loss",
        ErrorCode.EXIT_TRAIL: "Exit: trailing stop",
        ErrorCode.EXIT_TIMEOUT: "Exit: timeout",
        ErrorCode.EXIT_SCRATCH: "Exit: scratch",
        ErrorCode.EXIT_STAGNATION: "Exit: stagnation",
        ErrorCode.EXIT_REGIME_CHANGE: "Exit: regime change",
        
        ErrorCode.LEARN_TRADE_CLOSED: "Trade closed, outcome recorded",
        ErrorCode.LEARN_CALIBRATED: "Calibrator updated",
        ErrorCode.LEARN_FIREBASE_SAVED: "Metrics saved to Firebase",
    }
    
    @classmethod
    def describe(cls, code: ErrorCode) -> str:
        """Get description for error code."""
        return cls._DESCRIPTIONS.get(code, code.value)
```

---

## PATCH 2: Canonical Logging

**Files to create**:
- `src/monitoring/canonical_decision_log.py` (100–150 lines)

### src/monitoring/canonical_decision_log.py

```python
"""
Canonical decision and lifecycle logging.
One-line stable format; resilient to missing fields.
"""

from typing import Dict, Any, Optional
import logging

def format_decision_log(decision: Dict[str, Any]) -> str:
    """
    Format decision dict as one-line canonical log.
    
    Example:
        CANON_DECISION id=abc123 sym=BTCUSDT reg=BULL_TREND 
        side=BUY decision=APPROVE ev=+0.123 gates=EV,COHERENCE status=OK
    """
    sym = decision.get("symbol", "?")
    reg = decision.get("regime", "?")
    side = decision.get("side", "?")
    dec = decision.get("decision", "?")
    ev = decision.get("ev_final", 0.0)
    score = decision.get("score", 0.0)
    gates = decision.get("gates", {})
    
    # Gates passed
    gates_passed = [k for k, v in gates.items() if v is True] if isinstance(gates, dict) else []
    gates_str = ",".join(gates_passed) if gates_passed else "NONE"
    
    # Status
    status = "OK" if dec in ["APPROVE", "BLOCK"] else ("REJECT" if dec == "REJECT" else "?")
    
    reason = decision.get("reject_reason", "")
    reason_str = f" reason={reason}" if reason else ""
    
    return (
        f"CANON_DECISION sym={sym} reg={reg} side={side} "
        f"decision={dec} ev={ev:+.3f} score={score:.2f} "
        f"gates=[{gates_str}] status={status}{reason_str}"
    )

def format_lifecycle_log(lifecycle: Dict[str, Any]) -> str:
    """
    Format order lifecycle milestone as one-line log.
    
    Example:
        CANON_LIFECYCLE sym=BTCUSDT state=ORDER_SENT pnl=? mfe=+0.5% mae=-0.2%
    """
    sym = lifecycle.get("symbol", "?")
    state = lifecycle.get("state", "?")
    pnl = lifecycle.get("pnl", "?")
    mfe = lifecycle.get("mfe", "?")
    mae = lifecycle.get("mae", "?")
    
    pnl_str = f"{pnl:+.6f}" if isinstance(pnl, (int, float)) and pnl != "?" else str(pnl)
    
    return (
        f"CANON_LIFECYCLE sym={sym} state={state} "
        f"pnl={pnl_str} mfe={mfe} mae={mae}"
    )

class CanonicalLogger:
    """Helper for emitting canonical logs safely."""
    
    def __init__(self, name: str = "canonical"):
        self.logger = logging.getLogger(name)
    
    def decision(self, decision: Dict[str, Any]):
        """Log decision."""
        try:
            line = format_decision_log(decision)
            self.logger.info(line)
        except Exception as e:
            self.logger.debug(f"failed to format decision log: {e}", exc_info=True)
    
    def lifecycle(self, lifecycle: Dict[str, Any]):
        """Log lifecycle."""
        try:
            line = format_lifecycle_log(lifecycle)
            self.logger.info(line)
        except Exception as e:
            self.logger.debug(f"failed to format lifecycle log: {e}", exc_info=True)
```

---

## PATCH 3: Order Lifecycle

**Files to create**:
- `src/execution/order_lifecycle.py` (150–200 lines)

### src/execution/order_lifecycle.py

```python
"""
Pure order lifecycle state machine.
Tracks milestones without side effects.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from enum import Enum
import time

class OrderState(Enum):
    """Order state milestones."""
    SIGNAL_CREATED = "signal_created"
    DECISION_STARTED = "decision_started"
    FEATURES_LOCKED = "features_locked"
    REGIME_LOCKED = "regime_locked"
    EV_COMPUTED = "ev_computed"
    GATES_EVALUATED = "gates_evaluated"
    DECISION_APPROVED = "decision_approved"
    DECISION_REJECTED = "decision_rejected"
    ORDER_ARMED = "order_armed"
    PREFIRE_VALIDATED = "prefire_validated"
    ORDER_SENT = "order_sent"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    EXIT_TRIGGERED = "exit_triggered"
    POSITION_CLOSED = "position_closed"
    PNL_ATTRIBUTED = "pnl_attributed"
    LEARNING_UPDATED = "learning_updated"
    FIREBASE_STATE_UPDATED = "firebase_state_updated"

@dataclass
class StateTransition:
    """Single state transition."""
    from_state: Optional[OrderState]
    to_state: OrderState
    timestamp: float
    detail: Optional[Dict[str, Any]] = None

@dataclass
class OrderLifecycle:
    """Track order lifecycle milestones."""
    symbol: str
    side: str
    entry_price: float
    current_state: OrderState = OrderState.SIGNAL_CREATED
    transitions: List[StateTransition] = field(default_factory=list)
    pnl: Optional[float] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    close_reason: Optional[str] = None
    
    @classmethod
    def from_signal(cls, symbol: str, side: str, entry_price: float) -> 'OrderLifecycle':
        """Construct from signal."""
        return cls(symbol=symbol, side=side, entry_price=entry_price)
    
    @classmethod
    def from_order(cls, order: Dict[str, Any], position: Dict[str, Any]) -> 'OrderLifecycle':
        """Construct from executor order dict."""
        return cls(
            symbol=order.get("symbol", "?"),
            side=order.get("side", "BUY"),
            entry_price=position.get("entry_price", 0.0),
        )
    
    @classmethod
    def from_closed_trade(cls, trade: Dict[str, Any]) -> 'OrderLifecycle':
        """Construct from closed trade dict."""
        return cls(
            symbol=trade.get("symbol", "?"),
            side=trade.get("side", "BUY"),
            entry_price=trade.get("entry_price", 0.0),
            pnl=trade.get("net_pnl"),
            mfe=trade.get("mfe"),
            mae=trade.get("mae"),
            close_reason=trade.get("close_reason"),
        )
    
    def mark_state(self, state: OrderState, detail: Optional[Dict[str, Any]] = None, 
                   timestamp: Optional[float] = None) -> 'OrderLifecycle':
        """Mark state transition."""
        if timestamp is None:
            timestamp = time.time()
        
        transition = StateTransition(
            from_state=self.current_state,
            to_state=state,
            timestamp=timestamp,
            detail=detail,
        )
        self.transitions.append(transition)
        self.current_state = state
        return self
    
    def set_pnl(self, pnl: float, mfe: Optional[float] = None, 
                mae: Optional[float] = None) -> 'OrderLifecycle':
        """Set PnL metrics."""
        self.pnl = pnl
        if mfe is not None:
            self.mfe = mfe
        if mae is not None:
            self.mae = mae
        return self
    
    def format_log(self) -> str:
        """Format as single-line log."""
        pnl_str = f"{self.pnl:+.6f}" if self.pnl is not None else "?"
        mfe_str = f"{self.mfe:+.1%}" if self.mfe is not None else "?"
        mae_str = f"{self.mae:+.1%}" if self.mae is not None else "?"
        
        return (
            f"CANON_LIFECYCLE sym={self.symbol} side={self.side} "
            f"state={self.current_state.value} pnl={pnl_str} "
            f"mfe={mfe_str} mae={mae_str}"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "current_state": self.current_state.value,
            "transitions": [
                {
                    "from": t.from_state.value if t.from_state else None,
                    "to": t.to_state.value,
                    "timestamp": t.timestamp,
                }
                for t in self.transitions
            ],
            "pnl": self.pnl,
            "mfe": self.mfe,
            "mae": self.mae,
            "close_reason": self.close_reason,
        }
```

---

## Unit Tests

Create `tests/test_mammon_core.py`:

```python
"""Tests for Mammon core helpers."""

import pytest
from src.core.decision_frame import DecisionFrame, DecisionState, GateResult, GateType, ErrorCode
from src.core.error_registry import ErrorRegistry
from src.monitoring.canonical_decision_log import format_decision_log, format_lifecycle_log
from src.execution.order_lifecycle import OrderLifecycle, OrderState

def test_decision_frame_construction():
    df = DecisionFrame(
        symbol="BTCUSDT",
        side="BUY",
        regime="BULL_TREND",
        confidence=0.8,
        ev=0.15,
        ev_final=0.12,
        score=0.9,
        score_threshold=0.10,
        prob=0.6,
        rr=1.5,
    )
    assert df.symbol == "BTCUSDT"
    assert df.decision == DecisionState.PENDING

def test_decision_frame_approve():
    df = DecisionFrame(symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
                       ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5)
    df.approve("all gates passed")
    assert df.decision == DecisionState.APPROVED

def test_decision_frame_to_dict():
    df = DecisionFrame(symbol="BTC", side="BUY", regime="BULL", confidence=0.8,
                       ev=0.1, ev_final=0.1, score=0.9, score_threshold=0.1, prob=0.6, rr=1.5)
    d = df.to_dict()
    assert d["symbol"] == "BTC"
    assert isinstance(d, dict)

def test_format_decision_log_basic():
    decision = {"symbol": "BTCUSDT", "regime": "BULL_TREND", "side": "BUY",
                "decision": "APPROVE", "ev_final": 0.123, "score": 0.9,
                "gates": {"ev": True, "coherence": True}}
    log = format_decision_log(decision)
    assert "CANON_DECISION" in log
    assert "BTCUSDT" in log
    assert "APPROVE" in log

def test_format_decision_log_missing_fields():
    decision = {"symbol": "BTCUSDT"}  # minimal
    log = format_decision_log(decision)
    assert "CANON_DECISION" in log
    assert "?" in log  # placeholders for missing fields

def test_error_registry_describe():
    desc = ErrorRegistry.describe(ErrorCode.EV_TOO_LOW)
    assert isinstance(desc, str)
    assert len(desc) > 0

def test_order_lifecycle_construction():
    lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
    assert lc.symbol == "BTCUSDT"
    assert lc.current_state == OrderState.SIGNAL_CREATED

def test_order_lifecycle_state_transitions():
    lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
    lc.mark_state(OrderState.ORDER_SENT)
    lc.mark_state(OrderState.ORDER_FILLED)
    assert lc.current_state == OrderState.ORDER_FILLED
    assert len(lc.transitions) == 2

def test_order_lifecycle_format_log():
    lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
    lc.set_pnl(100.5, mfe=0.002, mae=-0.001)
    log = lc.format_log()
    assert "CANON_LIFECYCLE" in log
    assert "BTCUSDT" in log

def test_order_lifecycle_to_dict():
    lc = OrderLifecycle.from_signal("BTCUSDT", "BUY", 50000.0)
    lc.mark_state(OrderState.ORDER_SENT)
    d = lc.to_dict()
    assert d["symbol"] == "BTCUSDT"
    assert d["current_state"] == "order_sent"
    assert len(d["transitions"]) == 1
```

---

## Acceptance Criteria

✅ All 3 modules compile without errors  
✅ All unit tests pass (15+ tests)  
✅ No imports of forbidden files  
✅ No external dependencies  
✅ JSON-safe serialization (all classes can be converted to dict)  
✅ Backward compatible (works with plain dicts)  
✅ No side effects (no I/O, no network, no state mutation outside the class)  
✅ Docstrings present for all classes/functions  

---

## Delivery

On completion:
1. `git diff --stat` (show files changed)
2. Run: `python -m compileall src/core src/monitoring src/execution tests/test_mammon_core.py`
3. Run: `python -m pytest tests/test_mammon_core.py -v`
4. Commit: `V10.15 Mammon: Patches 1–3 — core helpers (Codex)`

Do not commit other changes.
