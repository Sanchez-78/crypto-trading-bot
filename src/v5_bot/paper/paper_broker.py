"""PAPER trading broker — simulated entry/exit execution."""

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from ..market.local_book import LocalBookManager
from ..execution.accounting import TradeAccounting, FillRecord
from ..util.datetime_utils import utc_now


@dataclass
class PaperPosition:
    """Open PAPER position."""
    trade_id: str
    symbol: str
    side: str  # BUY or SELL
    qty: float
    entry_price: float
    entry_time: float  # epoch seconds
    target_price: float
    stop_loss_price: float
    tp_pct: float  # Target profit as % of entry
    sl_pct: float  # Stop loss as % of entry


class PaperBroker:
    """Simulates entry/exit execution for PAPER trading."""

    def __init__(self, book_manager: LocalBookManager):
        self.book_manager = book_manager
        self.open_positions: Dict[str, PaperPosition] = {}
        self.closed_trades: Dict[str, TradeAccounting] = {}
        self.failed_entries: List[dict] = []  # Entries that couldn't execute

    def request_entry(self, symbol: str, side: str, qty: float, expected_price: float,
                      tp_pct: float = 1.5, sl_pct: float = 1.0,
                      strategy_id: str = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Request entry execution.

        Args:
            symbol: Trading symbol
            side: BUY or SELL
            qty: Quantity to trade
            expected_price: Price we expected to get
            tp_pct: Target profit %
            sl_pct: Stop loss %
            strategy_id: Which strategy generated signal

        Returns:
            (trade_id, failure_reason)
            - trade_id: Generated ID if successful, None if failed
            - failure_reason: Error message if failed
        """
        # Get current market price
        fill_price = self.book_manager.get_price_for_order(symbol, side)
        if fill_price is None:
            return None, f"no_liquidity_{symbol}"

        # Check if entry is slippage-reasonable (within 1% of expected)
        slippage = abs(fill_price - expected_price) / expected_price * 100
        if slippage > 1.0:
            return None, f"excessive_slippage_{slippage:.2f}%"

        # Create position
        trade_id = f"trade_{uuid.uuid4().hex[:8]}"
        entry_time = utc_now().timestamp()

        # Calculate TP/SL prices
        if side.upper() == "BUY":
            target_price = fill_price * (1 + tp_pct / 100)
            stop_price = fill_price * (1 - sl_pct / 100)
        else:
            target_price = fill_price * (1 - tp_pct / 100)
            stop_price = fill_price * (1 + sl_pct / 100)

        position = PaperPosition(
            trade_id=trade_id,
            symbol=symbol,
            side=side.upper(),
            qty=qty,
            entry_price=fill_price,
            entry_time=entry_time,
            target_price=target_price,
            stop_loss_price=stop_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
        )

        self.open_positions[trade_id] = position

        return trade_id, None

    def check_and_exit_position(self, trade_id: str, current_price: float,
                                current_time: float) -> Tuple[Optional[dict], Optional[str]]:
        """
        Check if position should exit (TP/SL hit or timeout).

        Args:
            trade_id: Position to check
            current_price: Current market price
            current_time: Current epoch time (seconds)

        Returns:
            (exit_info, reason)
            - exit_info: Dict with exit details if exited, None otherwise
            - reason: "timeout", "tp_hit", "sl_hit", or None
        """
        if trade_id not in self.open_positions:
            return None, "not_found"

        position = self.open_positions[trade_id]

        # Check timeout first (takes priority over TP/SL)
        hold_seconds = current_time - position.entry_time
        if hold_seconds > 28800:  # 8 hours
            return self._close_position(trade_id, current_price, current_time), "timeout"

        # Check target/stop
        if position.side == "BUY":
            if current_price >= position.target_price:
                return self._close_position(trade_id, current_price, current_time), "tp_hit"
            elif current_price <= position.stop_loss_price:
                return self._close_position(trade_id, current_price, current_time), "sl_hit"
        else:  # SELL
            if current_price <= position.target_price:
                return self._close_position(trade_id, current_price, current_time), "tp_hit"
            elif current_price >= position.stop_loss_price:
                return self._close_position(trade_id, current_price, current_time), "sl_hit"

        return None, None

    def manual_close_position(self, trade_id: str, exit_price: float,
                              exit_time: float) -> Tuple[Optional[dict], Optional[str]]:
        """
        Explicitly close a position at a given price (manual/test close).

        Args:
            trade_id: Position to close
            exit_price: Price at which to close
            exit_time: Time of close (epoch seconds)

        Returns:
            (exit_info, reason) where reason="manual_close"
        """
        if trade_id not in self.open_positions:
            return None, "not_found"

        return self._close_position(trade_id, exit_price, exit_time), "manual_close"

    def _close_position(self, trade_id: str, exit_price: float,
                        exit_time: float) -> dict:
        """Close a position and calculate PnL."""
        position = self.open_positions.pop(trade_id)

        # Create fill records
        entry_fill = FillRecord(
            symbol=position.symbol,
            side=position.side,
            qty=position.qty,
            price=position.entry_price,
            timestamp=int(position.entry_time * 1000),
            received_time=position.entry_time,
        )

        exit_fill = FillRecord(
            symbol=position.symbol,
            side="SELL" if position.side == "BUY" else "BUY",
            qty=position.qty,
            price=exit_price,
            timestamp=int(exit_time * 1000),
            received_time=exit_time,
        )

        # Create trade accounting
        trade = TradeAccounting(
            trade_id=trade_id,
            symbol=position.symbol,
            entry_side=position.side,
        )
        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        self.closed_trades[trade_id] = trade

        return {
            "trade_id": trade_id,
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "qty": position.qty,
            "gross_pnl_usd": trade.gross_pnl_usd,
            "gross_pnl_pct": trade.gross_pnl_pct,
            "net_pnl_usd": trade.net_pnl_usd,
            "net_pnl_pct": trade.net_pnl_pct,
            "total_costs_usd": trade.total_costs_usd,
            "hold_seconds": int(exit_time - position.entry_time),
        }

    def get_open_positions(self) -> List[PaperPosition]:
        """Get all open positions."""
        return list(self.open_positions.values())

    def get_position_notional(self) -> float:
        """Get total notional value of open positions."""
        return sum(p.qty * p.entry_price for p in self.open_positions.values())

    def get_unrealized_pnl(self) -> Dict[str, float]:
        """Get unrealized PnL across all open positions."""
        book = self.book_manager
        total_pnl = 0.0
        position_count = len(self.open_positions)

        for position in self.open_positions.values():
            current_price = book.get_price_for_order(position.symbol, "SELL")
            if current_price is None:
                continue

            if position.side == "BUY":
                pnl = (current_price - position.entry_price) * position.qty
            else:
                pnl = (position.entry_price - current_price) * position.qty

            total_pnl += pnl

        return {
            "open_positions": position_count,
            "total_unrealized_pnl_usd": total_pnl,
            "avg_unrealized_per_position": total_pnl / position_count if position_count > 0 else 0.0,
        }

    def get_closed_trade(self, trade_id: str) -> Optional[TradeAccounting]:
        """Get closed trade accounting."""
        return self.closed_trades.get(trade_id)

    def get_daily_stats(self) -> dict:
        """Get daily trading statistics."""
        closed = list(self.closed_trades.values())
        wins = [t for t in closed if t.net_pnl_usd > 0]
        losses = [t for t in closed if t.net_pnl_usd < 0]
        flats = [t for t in closed if t.net_pnl_usd == 0]

        total_pnl = sum(t.net_pnl_usd for t in closed)
        total_fees = sum(t.total_costs_usd for t in closed)

        return {
            "trades_closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(flats),
            "win_rate": len(wins) / len(closed) if closed else None,
            "total_net_pnl_usd": total_pnl,
            "total_fees_usd": total_fees,
            "avg_pnl_per_trade": total_pnl / len(closed) if closed else None,
        }
