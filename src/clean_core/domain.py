"""Core domain model for Clean Core RESET R1."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ExecutionTruthClass(Enum):
    """Classifies the trustworthiness of execution/fill/PnL measurements."""

    LEGACY_SPOT_EXECUTION_UNVERIFIED = "legacy_spot_execution_unverified"
    FUTURES_PUBLIC_BOOK_MEASURED = "futures_public_book_measured"
    FUTURES_RPI_AWARE_MEASURED = "futures_rpi_aware_measured"


@dataclass(frozen=True)
class MarketSourceIdentity:
    """
    Encapsulates the market source, instrument, price source, and execution truth.

    Used to tag all measurements so future cross-validation can prove source.
    """

    venue: str  # "binance_usdm"
    instrument: str  # "BTCUSDT"
    price_source: str  # "public_book" or "rpi_marked"
    execution_truth_class: ExecutionTruthClass
    rpi_visibility: bool  # True if RPI is visible to fill calculations
    route_version: str  # "R1" or version identifier

    def __post_init__(self):
        """Validate venue and execution_truth_class."""
        if self.venue != "binance_usdm":
            raise ValueError(f"Only binance_usdm supported, got {self.venue}")
        if not isinstance(self.execution_truth_class, ExecutionTruthClass):
            raise TypeError("execution_truth_class must be ExecutionTruthClass enum")
