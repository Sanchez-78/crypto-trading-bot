"""Binance USDⓈ-M Futures fee model."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FeeModel:
    """Binance USDⓈ-M taker/maker fee rates."""
    taker_rate: float = 0.0005  # 0.05% taker
    maker_rate: float = 0.0002  # 0.02% maker (default; rarely used in live execution)
    provenance: str = "PAPER_CONSERVATIVE"  # PAPER_CONSERVATIVE or ACCOUNT_VERIFIED_REAL
    source: str = "default"  # "default" or "account_tier"


class FeeCalculator:
    """Calculates trading fees for entries and exits."""

    def __init__(self, taker_rate: float = 0.0005, maker_rate: float = 0.0002,
                 provenance: str = "PAPER_CONSERVATIVE", source: str = "default"):
        self.model = FeeModel(
            taker_rate=taker_rate,
            maker_rate=maker_rate,
            provenance=provenance,
            source=source
        )

    def calc_entry_fee(self, notional_usd: float, is_taker: bool = True) -> float:
        """
        Calculate fee for entry fill.

        Args:
            notional_usd: USD value of fill (price * qty)
            is_taker: True if taker fee applies

        Returns:
            Fee in USD (positive)
        """
        rate = self.model.taker_rate if is_taker else self.model.maker_rate
        return notional_usd * rate

    def calc_exit_fee(self, notional_usd: float, is_taker: bool = True) -> float:
        """
        Calculate fee for exit fill.
        Same as entry: fee = notional * rate.
        """
        rate = self.model.taker_rate if is_taker else self.model.maker_rate
        return notional_usd * rate

    def calc_round_trip_fee_bps(self, entry_notional: float, exit_notional: float) -> float:
        """
        Calculate total round-trip fee in basis points relative to entry notional.

        Args:
            entry_notional: Entry fill value in USD
            exit_notional: Exit fill value in USD

        Returns:
            Fee as basis points of entry notional
        """
        entry_fee = self.calc_entry_fee(entry_notional, is_taker=True)
        exit_fee = self.calc_exit_fee(exit_notional, is_taker=True)
        total_fee = entry_fee + exit_fee

        if entry_notional == 0:
            return 0.0

        return (total_fee / entry_notional) * 10000

    def get_model(self) -> FeeModel:
        """Return current fee model."""
        return self.model
