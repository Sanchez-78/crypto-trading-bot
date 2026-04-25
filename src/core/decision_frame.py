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
        d["gates"] = [
            {
                "gate_type": g.gate_type.value if isinstance(g.gate_type, GateType) else g.gate_type,
                "passed": g.passed,
                "reason": g.reason,
                "value": g.value,
                "threshold": g.threshold,
            }
            for g in self.gates
        ]
        d["decision"] = self.decision.value
        return d

    def add_gate(self, gate: GateResult) -> 'DecisionFrame':
        """Add gate result."""
        self.gates.append(gate)
        return self

    def approve(self, reason: str = "all gates passed") -> 'DecisionFrame':
        """Mark as approved."""
        self.decision = DecisionState.APPROVED
        self.reject_reason = None
        return self

    def reject(self, reason: str = "gate failed") -> 'DecisionFrame':
        """Mark as rejected."""
        self.decision = DecisionState.REJECTED
        self.reject_reason = reason
        return self

    def block(self, reason: str = "blocked") -> 'DecisionFrame':
        """Mark as blocked."""
        self.decision = DecisionState.BLOCKED
        self.reject_reason = reason
        return self
