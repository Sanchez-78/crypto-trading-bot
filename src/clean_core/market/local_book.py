"""Local order book integrity model for Clean Core RESET R1."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import time


class BookIntegrityStatus(Enum):
    """State of local order book integrity."""

    UNINITIALIZED = "uninitialized"
    SYNCED = "synced"
    GAP_DETECTED = "gap_detected"
    STALE = "stale"


@dataclass
class DepthSnapshot:
    """Initial order book snapshot from REST API or stream."""

    last_update_id: int
    bids: List[List[float]]  # [[price, qty], ...]
    asks: List[List[float]]
    timestamp_ms: int
    source: str = "rest_api"  # "rest_api" or "stream_snapshot"


@dataclass
class DepthEvent:
    """Order book delta event from depth stream."""

    first_update_id: int
    last_update_id: int
    previous_final_id: Optional[int] = None
    bid_deltas: List[List[float]] = field(default_factory=list)
    ask_deltas: List[List[float]] = field(default_factory=list)
    timestamp_ms: int = 0
    event_time_ms: int = 0

    def __post_init__(self):
        """Validate sequence ordering."""
        if self.first_update_id > self.last_update_id:
            raise ValueError(
                f"Invalid sequence: first_update_id ({self.first_update_id}) "
                f"> last_update_id ({self.last_update_id})"
            )


@dataclass
class MarketTapeCheckpoint:
    """
    Encapsulates market state at a decision point.

    Enables future reproduction of execution/fill decisions.
    """

    symbol: str
    market_time_ms: int
    best_bid: float
    best_bid_qty: float
    best_ask: float
    best_ask_qty: float
    last_update_id: int
    integrity_status: BookIntegrityStatus
    gap_count: int = 0
    last_snapshot_update_id: Optional[int] = None
    eligible_for_execution_measurement: bool = False


class LocalOrderBook:
    """
    Maintains local order book with sequence integrity validation.

    Detects gaps in update stream (first_update_id != previous last_update_id + 1).
    Tracks sync state: UNINITIALIZED → SYNCED, or SYNCED → GAP_DETECTED.
    """

    def __init__(self, symbol: str, stale_threshold_ms: int = 1000):
        self.symbol = symbol
        self.stale_threshold_ms = stale_threshold_ms
        self.status = BookIntegrityStatus.UNINITIALIZED
        self.last_update_id: Optional[int] = None
        self.last_update_time_ms: Optional[int] = None
        self.gap_count = 0

        # Current order book state (simplified, only track best bid/ask)
        self.best_bid: Optional[float] = None
        self.best_bid_qty: Optional[float] = None
        self.best_ask: Optional[float] = None
        self.best_ask_qty: Optional[float] = None

    def apply_snapshot(self, snapshot: DepthSnapshot) -> None:
        """
        Initialize or reset order book with snapshot.

        Sets status to SYNCED and resets gap tracking.
        """
        if snapshot.last_update_id < 0:
            raise ValueError(f"Invalid snapshot update_id: {snapshot.last_update_id}")

        self.last_update_id = snapshot.last_update_id
        self.last_update_time_ms = snapshot.timestamp_ms
        self.status = BookIntegrityStatus.SYNCED
        self.gap_count = 0

        # Update best bid/ask from snapshot
        if snapshot.bids:
            self.best_bid = float(snapshot.bids[0][0])
            self.best_bid_qty = float(snapshot.bids[0][1])
        if snapshot.asks:
            self.best_ask = float(snapshot.asks[0][0])
            self.best_ask_qty = float(snapshot.asks[0][1])

    def apply_event(self, event: DepthEvent) -> None:
        """
        Apply depth delta event, validating sequence continuity.

        If first_update_id != (previous last_update_id + 1), marks GAP_DETECTED.
        """
        if self.status == BookIntegrityStatus.UNINITIALIZED:
            raise RuntimeError(
                "Cannot apply depth event before snapshot initialization"
            )

        # Check sequence continuity
        if event.previous_final_id is not None:
            if event.previous_final_id != self.last_update_id:
                self.status = BookIntegrityStatus.GAP_DETECTED
                self.gap_count += 1
                return

        # Check first_update_id continuity
        if event.first_update_id != (self.last_update_id + 1):
            self.status = BookIntegrityStatus.GAP_DETECTED
            self.gap_count += 1
            return

        # Update state
        self.last_update_id = event.last_update_id
        self.last_update_time_ms = event.timestamp_ms or event.event_time_ms

        # Apply deltas to order book
        for price, qty in event.bid_deltas:
            if qty == 0:
                # Deletion
                if price == self.best_bid:
                    self.best_bid = None
                    self.best_bid_qty = None
            else:
                # Update/insertion
                if self.best_bid is None or price >= self.best_bid:
                    self.best_bid = float(price)
                    self.best_bid_qty = float(qty)

        for price, qty in event.ask_deltas:
            if qty == 0:
                # Deletion
                if price == self.best_ask:
                    self.best_ask = None
                    self.best_ask_qty = None
            else:
                # Update/insertion
                if self.best_ask is None or price <= self.best_ask:
                    self.best_ask = float(price)
                    self.best_ask_qty = float(qty)

    def is_stale(self, current_time_ms: int) -> bool:
        """Check if last update exceeds stale threshold."""
        if self.last_update_time_ms is None:
            return True
        return (current_time_ms - self.last_update_time_ms) > self.stale_threshold_ms

    def checkpoint(self, current_time_ms: int) -> MarketTapeCheckpoint:
        """
        Generate a decision-point checkpoint.

        Returns checkpoint only if status is SYNCED and not stale.
        """
        if self.status != BookIntegrityStatus.SYNCED:
            return MarketTapeCheckpoint(
                symbol=self.symbol,
                market_time_ms=current_time_ms,
                best_bid=0.0,
                best_bid_qty=0.0,
                best_ask=0.0,
                best_ask_qty=0.0,
                last_update_id=self.last_update_id or 0,
                integrity_status=self.status,
                gap_count=self.gap_count,
                eligible_for_execution_measurement=False,
            )

        if self.is_stale(current_time_ms):
            return MarketTapeCheckpoint(
                symbol=self.symbol,
                market_time_ms=current_time_ms,
                best_bid=self.best_bid or 0.0,
                best_bid_qty=self.best_bid_qty or 0.0,
                best_ask=self.best_ask or 0.0,
                best_ask_qty=self.best_ask_qty or 0.0,
                last_update_id=self.last_update_id or 0,
                integrity_status=BookIntegrityStatus.STALE,
                gap_count=self.gap_count,
                eligible_for_execution_measurement=False,
            )

        return MarketTapeCheckpoint(
            symbol=self.symbol,
            market_time_ms=current_time_ms,
            best_bid=self.best_bid or 0.0,
            best_bid_qty=self.best_bid_qty or 0.0,
            best_ask=self.best_ask or 0.0,
            best_ask_qty=self.best_ask_qty or 0.0,
            last_update_id=self.last_update_id or 0,
            integrity_status=self.status,
            gap_count=self.gap_count,
            eligible_for_execution_measurement=True,
        )
