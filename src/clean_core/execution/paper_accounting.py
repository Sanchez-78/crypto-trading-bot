"""PAPER position accounting for Clean Core RESET R1."""

from dataclasses import dataclass
from src.clean_core.domain import MarketSourceIdentity, ExecutionTruthClass
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.execution.funding import FundingRealization


@dataclass(frozen=True)
class FillObservation:
    """
    Records actual fill at entry or exit with explicit impact.

    touch_price: best available (bid for sell, ask for buy)
    fill_price: actual fill including slippage
    midpoint: (bid + ask) / 2
    spread_bps: (ask - bid) / midpoint * 10000
    slippage_bps: (fill_price - touch_price) / touch_price * 10000
    """

    position_id: str
    symbol: str
    side: str  # "long" or "short"
    qty: float
    touch_price: float  # best bid/ask at decision time
    fill_price: float  # actual execution
    midpoint: float
    spread_bps: float
    slippage_bps: float
    execution_truth_class: ExecutionTruthClass
    market_source: MarketSourceIdentity
    timestamp_utc: str

    def __post_init__(self):
        """Validate fill."""
        if self.side not in ("long", "short"):
            raise ValueError(f"Invalid side: {self.side}")
        if self.qty <= 0:
            raise ValueError(f"qty must be positive: {self.qty}")
        if self.touch_price <= 0 or self.fill_price <= 0:
            raise ValueError("Prices must be positive")


@dataclass
class ClosedPaperOutcome:
    """
    Complete record of a closed PAPER position for learning/metrics.

    Includes entry, exit, fees, funding, realized PnL.
    """

    position_id: str
    symbol: str
    entry_fill: FillObservation
    exit_fill: FillObservation
    fee_schedule: FeeSchedule
    funding_realization: FundingRealization
    epoch_id: str
    entry_time_utc: str
    exit_time_utc: str
    holding_minutes: float
    gross_pnl_pct: float  # (exit_price - entry_price) / entry_price * 100
    fee_cost_pct: float  # (entry_fee + exit_fee) * (entry_qty) / (entry_price * qty)
    funding_cost_pct: float  # signed funding / entry_notional
    net_pnl_pct: float  # gross - fees - funding
    execution_truth_class: ExecutionTruthClass
    eligible_for_clean_paper_metrics: bool  # True if valid Futures (PUBLIC_BOOK or RPI_AWARE)
    eligible_for_real_readiness: bool  # False in MVP (never true)
    eligibility_reason: str  # Explanation of eligibility decision
    learning_source: str  # "canonical" or "discovery"
    notes: str = ""

    def __post_init__(self):
        """Validate outcome."""
        if self.holding_minutes < 0:
            raise ValueError(f"Invalid holding_minutes: {self.holding_minutes}")
        if self.entry_fill.symbol != self.exit_fill.symbol:
            raise ValueError("Entry and exit must be same symbol")
        if self.entry_fill.symbol != self.symbol:
            raise ValueError("Symbol mismatch between fills and outcome")

    @classmethod
    def calculate_from_fills(
        cls,
        position_id: str,
        epoch_id: str,
        entry_fill: FillObservation,
        exit_fill: FillObservation,
        fee_schedule: FeeSchedule,
        funding_realization: FundingRealization,
        entry_time_utc: str,
        exit_time_utc: str,
        holding_minutes: float,
        learning_source: str = "canonical",
    ) -> "ClosedPaperOutcome":
        """
        Factory method to calculate all PnL fields from fills.

        Assumes qty is same at entry and exit (no partial fills).
        """
        # Gross PnL (before fees/funding)
        entry_px = entry_fill.fill_price
        exit_px = exit_fill.fill_price
        gross_pnl_pct = ((exit_px - entry_px) / entry_px) * 100.0

        # Fee cost (in %) — MVP uses taker fees for touch fills
        entry_fee_bps = fee_schedule.entry_cost_bps(is_maker=False)  # Taker for touch fill
        exit_fee_bps = fee_schedule.exit_cost_bps(is_maker=False)  # Taker for touch fill
        fee_cost_pct = ((entry_fee_bps + exit_fee_bps) / 10000.0) * 100.0

        # Funding cost (in %) — telemetry only unless explicitly realized
        funding_cost_pct = (funding_realization.total_cashflow_bps / 10000.0) * 100.0

        # Net PnL
        net_pnl_pct = gross_pnl_pct - fee_cost_pct - funding_cost_pct

        # Determine clean PAPER metrics eligibility: accept valid Futures measurements (public book or RPI)
        futures_classes = (
            ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
        )
        eligible_for_clean_paper_metrics = (
            entry_fill.execution_truth_class in futures_classes
            and exit_fill.execution_truth_class in futures_classes
        )
        # MVP never sets REAL readiness to True
        eligible_for_real_readiness = False
        reason = "Clean PAPER Futures public book" if eligible_for_clean_paper_metrics else "Ineligible execution truth class"

        return cls(
            position_id=position_id,
            symbol=entry_fill.symbol,
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            fee_schedule=fee_schedule,
            funding_realization=funding_realization,
            epoch_id=epoch_id,
            entry_time_utc=entry_time_utc,
            exit_time_utc=exit_time_utc,
            holding_minutes=holding_minutes,
            gross_pnl_pct=gross_pnl_pct,
            fee_cost_pct=fee_cost_pct,
            funding_cost_pct=funding_cost_pct,
            net_pnl_pct=net_pnl_pct,
            execution_truth_class=entry_fill.execution_truth_class,
            eligible_for_clean_paper_metrics=eligible_for_clean_paper_metrics,
            eligible_for_real_readiness=eligible_for_real_readiness,
            eligibility_reason=reason,
            learning_source=learning_source,
        )
