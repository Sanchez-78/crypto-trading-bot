"""Fee schedule model for Clean Core RESET R1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    """
    Encapsulates maker/taker/RPI fees for a Binance USDⓈ-M position.

    All values in basis points (bps). 1 bps = 0.01% = 1/10000.
    """

    maker_fee_bps: float
    taker_fee_bps: float
    rpi_fee_bps: float
    source: str  # "api_snapshot" or "test_fixture"

    def __post_init__(self):
        """Validate fee values are reasonable."""
        if not (0 <= self.maker_fee_bps <= 100):
            raise ValueError(f"maker_fee_bps out of range: {self.maker_fee_bps}")
        if not (0 <= self.taker_fee_bps <= 100):
            raise ValueError(f"taker_fee_bps out of range: {self.taker_fee_bps}")
        if not (-100 <= self.rpi_fee_bps <= 100):
            raise ValueError(f"rpi_fee_bps out of range: {self.rpi_fee_bps}")

    @classmethod
    def binance_usdm_standard(cls) -> "FeeSchedule":
        """Standard Binance USDⓈ-M fee structure (VIP0)."""
        return cls(
            maker_fee_bps=2.0,
            taker_fee_bps=4.0,
            rpi_fee_bps=0.0,
            source="test_fixture",
        )

    def entry_cost_bps(self, is_maker: bool) -> float:
        """Cost of opening a position (entry fee in bps)."""
        return self.maker_fee_bps if is_maker else self.taker_fee_bps

    def exit_cost_bps(self, is_maker: bool) -> float:
        """Cost of closing a position (exit fee in bps)."""
        return self.maker_fee_bps if is_maker else self.taker_fee_bps

    def total_round_trip_bps(self, entry_is_maker: bool, exit_is_maker: bool) -> float:
        """Total round-trip cost (entry + exit + RPI) in bps."""
        entry = self.entry_cost_bps(entry_is_maker)
        exit = self.exit_cost_bps(exit_is_maker)
        rpi = max(0, self.rpi_fee_bps)  # Only count if positive cost
        return entry + exit + rpi
