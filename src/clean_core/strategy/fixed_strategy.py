"""Simple fixed PAPER strategy for Clean Core MVP (no adaptation, no legacy EV gate)."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SignalHypothesis:
    """A market signal hypothesis with entry conditions."""

    signal_id: str
    symbol: str
    side: str  # "long" or "short"
    hypothesis: str  # description of the idea
    entry_reason: str


class FixedStrategy:
    """
    Deterministic PAPER strategy without adaptation or legacy gates.

    Entry: Simple breakout / momentum signal
    Exit: Fixed TP%, SL%, timeout rules
    """

    def __init__(
        self,
        tp_pct: float = 1.0,
        sl_pct: float = 0.5,
        timeout_minutes: int = 60,
    ):
        """
        Args:
            tp_pct: Take-profit in percent (e.g., 1.0 = +1%)
            sl_pct: Stop-loss in percent (e.g., 0.5 = -0.5%)
            timeout_minutes: Auto-close position after N minutes
        """
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.timeout_minutes = timeout_minutes
        self.next_signal_id = 0

    def generate_signal(
        self, symbol: str, current_price: float, recent_high: float, recent_low: float
    ) -> Optional[SignalHypothesis]:
        """
        Generate entry signal: simple breakout above recent high.

        Returns None if no signal, else SignalHypothesis with entry conditions.
        """
        # Threshold: breakout at or above recent high (tight signal, no noise buffer)
        breakout_threshold = recent_high

        if current_price >= breakout_threshold:
            self.next_signal_id += 1
            return SignalHypothesis(
                signal_id=f"sig_{self.next_signal_id}",
                symbol=symbol,
                side="long",
                hypothesis="breakout_above_recent_high",
                entry_reason=f"price {current_price:.2f} >= recent_high {recent_high:.2f}",
            )

        return None

    def entry_target_price(self, entry_price: float) -> float:
        """Entry target (assume market price = entry for this MVP)."""
        return entry_price

    def tp_target_price(self, entry_price: float) -> float:
        """Take-profit target price."""
        return entry_price * (1.0 + self.tp_pct / 100.0)

    def sl_target_price(self, entry_price: float) -> float:
        """Stop-loss target price."""
        return entry_price * (1.0 - self.sl_pct / 100.0)

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        minutes_held: float,
        exit_reason: str = "",
    ) -> tuple[bool, str]:
        """
        Determine if position should exit.

        Returns: (should_exit: bool, reason: str)
        """
        tp_price = self.tp_target_price(entry_price)
        sl_price = self.sl_target_price(entry_price)

        if current_price >= tp_price:
            return True, f"tp_hit (target {tp_price:.2f})"

        if current_price <= sl_price:
            return True, f"sl_hit (target {sl_price:.2f})"

        if minutes_held >= self.timeout_minutes:
            return True, f"timeout ({minutes_held}m >= {self.timeout_minutes}m)"

        return False, ""
