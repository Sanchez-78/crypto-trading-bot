"""Funding rate forecast and realization for Clean Core RESET R1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FundingForecast:
    """
    Forecasted funding rate impact over position holding period.

    Used for entry admission (predict PnL cost).
    """

    symbol: str
    current_funding_rate_bps: float  # current rate in bps
    forecast_rate_bps: float  # expected average rate during holding
    holding_period_hours: float
    predicted_cashflow_bps: float  # signed; negative = cost, positive = rebate
    confidence: float  # 0.0-1.0

    def __post_init__(self):
        """Validate forecast."""
        if self.holding_period_hours < 0:
            raise ValueError(f"Invalid holding_period_hours: {self.holding_period_hours}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")


@dataclass(frozen=True)
class FundingRealization:
    """
    Actual funding payments received/paid during position lifecycle.

    Recorded at position close.
    """

    symbol: str
    position_id: str
    entry_time_utc: str
    exit_time_utc: str
    holding_hours: float
    funding_payments: list[dict]  # [{timestamp, rate_bps, cashflow_bps}, ...]
    total_cashflow_bps: float  # signed; negative = paid out, positive = earned
    reconciliation_status: str  # "complete" or "partial" (if missing data)

    def __post_init__(self):
        """Validate realization."""
        if self.holding_hours < 0:
            raise ValueError(f"Invalid holding_hours: {self.holding_hours}")
