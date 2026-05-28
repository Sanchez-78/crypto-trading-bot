"""REAL readiness state machine (10 states) with Czech status reporting."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from datetime import datetime
from ..util.datetime_utils import utc_timestamp_iso


class ReadinessState(Enum):
    """10-state readiness progression for REAL trading."""
    NOT_READY_INITIALIZING = "not_ready_initializing"
    NOT_READY_INSUFFICIENT_DATA = "not_ready_insufficient_data"
    NOT_READY_NEGATIVE_EXPECTANCY = "not_ready_negative_expectancy"
    NOT_READY_LOW_PROFIT_FACTOR = "not_ready_low_profit_factor"
    NOT_READY_DRAWDOWN_EXCEEDED = "not_ready_drawdown_exceeded"
    NOT_READY_ACCOUNTING_INCOMPLETE = "not_ready_accounting_incomplete"
    PAPER_PERFORMING = "paper_performing"
    PAPER_READY_FOR_REVIEW = "paper_ready_for_review"
    REAL_REVIEW_READY = "real_review_ready"
    REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED = "real_review_ready_operator_approval_required"


# Czech status messages
READINESS_MESSAGES_CS = {
    ReadinessState.NOT_READY_INITIALIZING: "Inicializace - žádná data",
    ReadinessState.NOT_READY_INSUFFICIENT_DATA: "Nedostatek dat — čekám na alespoň 300 validních uzavřených PAPER obchodů.",
    ReadinessState.NOT_READY_NEGATIVE_EXPECTANCY: "Negativní očekávání - čistá hodnota < 0",
    ReadinessState.NOT_READY_LOW_PROFIT_FACTOR: "Nízký profit faktor - je třeba >= 1.20",
    ReadinessState.NOT_READY_DRAWDOWN_EXCEEDED: "Překročeno max. snížení - limit 5%",
    ReadinessState.NOT_READY_ACCOUNTING_INCOMPLETE: "Neúplné účetnictví - chybí fee/funding",
    ReadinessState.PAPER_PERFORMING: "PAPER pracuje - sbírání dat pro validaci",
    ReadinessState.PAPER_READY_FOR_REVIEW: "PAPER připraven - splňuje brány, čekání na přezkum",
    ReadinessState.REAL_REVIEW_READY: "Připraven na REAL přezkum - všechny brány splněny",
    ReadinessState.REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED: "Čekání na schválení operátora - NE AUTOMATICKÉ",
}


@dataclass
class ReadinessGate:
    """Single gate in readiness evaluation."""
    gate_name: str
    gate_name_cs: str
    required_value: float
    current_value: float
    is_passed: bool
    reason: str = ""


@dataclass
class ReadinessReport:
    """Complete readiness evaluation report."""
    state: ReadinessState
    state_label_cs: str
    paper_only: bool = True
    real_orders_allowed: bool = False  # Always False (hardcoded in config.py)
    readiness_evidence_generated: bool = False  # Separate from real_orders_allowed flag

    # Gate evaluations
    eligible_closes_required: int = 300
    eligible_closes_current: int = 0

    days_of_data_required: int = 7
    days_of_data_current: int = 0

    min_expectancy_bps_required: float = 0.0
    expectancy_bps_current: float = 0.0

    min_profit_factor_required: float = 1.20
    profit_factor_current: float = 1.0

    max_drawdown_pct_required: float = 5.0
    drawdown_pct_current: float = 0.0

    # Blocking reasons
    blocking_reasons_cs: List[str] = field(default_factory=list)
    gates: List[ReadinessGate] = field(default_factory=list)

    # Provenance
    unresolved_incidents: int = 0
    accounting_missing_count: int = 0
    quota_safe_days: int = 0

    timestamp: str = ""

    def to_dict(self) -> Dict:
        """Export as dict."""
        return {
            "state": self.state.value,
            "state_label_cs": self.state_label_cs,
            "paper_only": self.paper_only,
            "real_orders_allowed": self.real_orders_allowed,
            "eligible_closes": f"{self.eligible_closes_current}/{self.eligible_closes_required}",
            "days_of_data": f"{self.days_of_data_current}/{self.days_of_data_required}",
            "expectancy_bps": self.expectancy_bps_current,
            "profit_factor": self.profit_factor_current,
            "drawdown_pct": self.drawdown_pct_current,
            "blocking_reasons_cs": self.blocking_reasons_cs,
            "timestamp": self.timestamp,
        }


class ReadinessEvaluator:
    """Evaluates REAL readiness using 10-state machine."""

    def __init__(self, gates_config=None):
        from ..config import REAL_READINESS_GATES
        self.gates_config = gates_config or REAL_READINESS_GATES

    def evaluate(self, eligible_closes: int, days_of_data: int, expectancy_bps: float,
                 profit_factor: float, drawdown_pct: float,
                 accounting_complete: bool, incidents: int = 0) -> ReadinessReport:
        """
        Evaluate readiness and determine state.

        Args:
            eligible_closes: Number of eligible closed trades
            days_of_data: Days of trading data
            expectancy_bps: Net expectancy in basis points
            profit_factor: Profit factor (wins/losses)
            drawdown_pct: Maximum drawdown percentage
            accounting_complete: Whether all trades have complete accounting
            incidents: Number of unresolved incidents

        Returns:
            ReadinessReport with state and details
        """
        report = ReadinessReport(
            state=ReadinessState.NOT_READY_INITIALIZING,
            state_label_cs=READINESS_MESSAGES_CS[ReadinessState.NOT_READY_INITIALIZING],
            eligible_closes_current=eligible_closes,
            days_of_data_current=days_of_data,
            expectancy_bps_current=expectancy_bps,
            profit_factor_current=profit_factor,
            drawdown_pct_current=drawdown_pct,
            unresolved_incidents=incidents,
            timestamp=utc_timestamp_iso(),
        )

        blocking_reasons = []

        # Early exit: True initialization (no data at all)
        if eligible_closes == 0 and days_of_data == 0:
            return report  # Return with default NOT_READY_INITIALIZING state

        # Gate 1: Sufficient eligible closes
        if eligible_closes < self.gates_config.min_eligible_closes:
            blocking_reasons.append(
                f"Nedostatek uzavřených obchodů: {eligible_closes}/{self.gates_config.min_eligible_closes}"
            )
            report.state = ReadinessState.NOT_READY_INSUFFICIENT_DATA
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_INSUFFICIENT_DATA]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # Gate 2: Sufficient days of data
        if days_of_data < self.gates_config.min_days_of_data:
            blocking_reasons.append(
                f"Nedostatek dní dat: {days_of_data}/{self.gates_config.min_days_of_data}"
            )
            report.state = ReadinessState.NOT_READY_INSUFFICIENT_DATA
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_INSUFFICIENT_DATA]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # Gate 3: Positive expectancy
        if expectancy_bps < self.gates_config.min_expectancy_bps:
            blocking_reasons.append(
                f"Negativní očekávání: {expectancy_bps:.1f} bps < {self.gates_config.min_expectancy_bps:.1f}"
            )
            report.state = ReadinessState.NOT_READY_NEGATIVE_EXPECTANCY
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_NEGATIVE_EXPECTANCY]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # Gate 4: Profit factor
        if profit_factor < self.gates_config.min_profit_factor_overall:
            blocking_reasons.append(
                f"Nízký profit faktor: {profit_factor:.2f} < {self.gates_config.min_profit_factor_overall:.2f}"
            )
            report.state = ReadinessState.NOT_READY_LOW_PROFIT_FACTOR
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_LOW_PROFIT_FACTOR]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # Gate 5: Drawdown limit
        if drawdown_pct > self.gates_config.max_drawdown_pct:
            blocking_reasons.append(
                f"Překročeno max snížení: {drawdown_pct:.1f}% > {self.gates_config.max_drawdown_pct:.1f}%"
            )
            report.state = ReadinessState.NOT_READY_DRAWDOWN_EXCEEDED
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_DRAWDOWN_EXCEEDED]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # Gate 6: Accounting completeness
        if not accounting_complete:
            blocking_reasons.append("Neúplné účetnictví - chybí fee nebo funding")
            report.state = ReadinessState.NOT_READY_ACCOUNTING_INCOMPLETE
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.NOT_READY_ACCOUNTING_INCOMPLETE]
            report.blocking_reasons_cs = blocking_reasons
            return report

        # All gates passed: transition to paper performing
        report.state = ReadinessState.PAPER_PERFORMING
        report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.PAPER_PERFORMING]
        report.readiness_evidence_generated = True

        # If no incidents, ready for review
        if incidents == 0:
            report.state = ReadinessState.PAPER_READY_FOR_REVIEW
            report.state_label_cs = READINESS_MESSAGES_CS[ReadinessState.PAPER_READY_FOR_REVIEW]

            # Finally, real review ready (but operator approval required)
            # NOTE: readiness_evidence_generated=True is SEPARATE from real_orders_allowed=False
            # The readiness state indicates PAPER has proven profitable and stable.
            # The real_orders_allowed flag is hardcoded False in config.py and cannot auto-enable.
            report.state = ReadinessState.REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
            report.state_label_cs = READINESS_MESSAGES_CS[
                ReadinessState.REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
            ]

        return report
