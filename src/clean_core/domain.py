"""Core domain model for Clean Core RESET R1."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ExecutionTruthClass(Enum):
    """Classifies the trustworthiness of execution/fill/PnL measurements."""

    LEGACY_SPOT_EXECUTION_UNVERIFIED = "legacy_spot_execution_unverified"
    FUTURES_PUBLIC_BOOK_MEASURED = "futures_public_book_measured"
    FUTURES_RPI_AWARE_MEASURED = "futures_rpi_aware_measured"


class MarketObservationRole(Enum):
    """Classifies the role of a market data feed (execution vs telemetry)."""

    EXECUTION_BOOK = "execution_book"  # /public depth/bookTicker for fill prices
    MARK_FUNDING_TELEMETRY = "mark_funding_telemetry"  # /market markPrice for informational only
    TRADE_FLOW_TELEMETRY = "trade_flow_telemetry"  # /market aggTrade for informational only


@dataclass(frozen=True)
class MarketSourceIdentity:
    """
    Encapsulates the market source, instrument, price source, and execution truth.

    Used to tag all measurements so future cross-validation can prove source.
    """

    venue: str  # "binance_usdm"
    instrument: str  # "BTCUSDT"
    price_source: str  # "public_book", "mark_telemetry", or "trade_telemetry"
    execution_truth_class: Optional[ExecutionTruthClass]  # None for telemetry feeds
    rpi_visibility: bool  # True if RPI is visible to fill calculations
    route_version: str  # "R1" or version identifier
    observation_role: MarketObservationRole = MarketObservationRole.EXECUTION_BOOK

    def __post_init__(self):
        """Validate venue and execution_truth_class."""
        if self.venue != "binance_usdm":
            raise ValueError(f"Only binance_usdm supported, got {self.venue}")
        if self.execution_truth_class is not None and not isinstance(self.execution_truth_class, ExecutionTruthClass):
            raise TypeError("execution_truth_class must be ExecutionTruthClass enum or None")
