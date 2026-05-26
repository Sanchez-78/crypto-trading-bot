"""Clean PAPER epoch definition for Clean Core RESET R1."""

from dataclasses import dataclass, field
from typing import Optional
import datetime


@dataclass
class CleanPaperEpoch:
    """
    Defines a single clean learning epoch with explicit versioning.

    All outcomes in this epoch are certified FUTURES_RPI_AWARE_MEASURED
    or explicitly marked as LEGACY_SPOT_EXECUTION_UNVERIFIED (discovery only).
    """

    epoch_id: str  # e.g., "clean_core_r1_epoch_001"
    status: str  # "active" or "completed"
    created_utc: str  # ISO 8601
    started_utc: str  # First trade entry
    completed_utc: Optional[str] = None  # Last trade exit
    min_observations: int = 30  # Minimum closed trades for validity
    closed_trades_count: int = 0
    total_net_pnl_pct: float = 0.0
    readiness_eligible_count: int = 0  # Trades eligible for future REAL
    legacy_spot_only_count: int = 0  # Discovery/test trades
    discovery_trades_count: int = 0
    commit_hash: str = ""  # Git commit of clean core version
    config_version: str = ""  # e.g., "R1"
    market_source_version: str = ""  # Route version used
    legacy_data_policy: str = "archive_comparator_only"  # How to treat legacy state
    notes: str = ""

    def is_ready_for_readiness_check(self) -> bool:
        """Can this epoch inform REAL readiness qualification?"""
        return (
            self.status == "completed"
            and self.closed_trades_count >= self.min_observations
            and self.readiness_eligible_count >= self.min_observations
        )

    def add_closed_trade(
        self,
        net_pnl_pct: float,
        readiness_eligible: bool,
        execution_truth_class: str,
    ) -> None:
        """Record a new closed trade in this epoch."""
        self.closed_trades_count += 1
        self.total_net_pnl_pct += net_pnl_pct

        if readiness_eligible:
            self.readiness_eligible_count += 1
        else:
            self.legacy_spot_only_count += 1

            if execution_truth_class == "legacy_spot_execution_unverified":
                self.discovery_trades_count += 1

    @property
    def average_net_pnl_pct(self) -> float:
        """Average PnL across all closed trades."""
        if self.closed_trades_count == 0:
            return 0.0
        return self.total_net_pnl_pct / self.closed_trades_count

    @property
    def readiness_coverage_pct(self) -> float:
        """Percentage of trades eligible for readiness."""
        if self.closed_trades_count == 0:
            return 0.0
        return (self.readiness_eligible_count / self.closed_trades_count) * 100.0
