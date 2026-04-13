from __future__ import annotations
from datetime import datetime
from typing import Optional
from src.optimized.bot_types import BotConfig, Trade, TradeResult, CloseReason, Direction


class PositionManager:
    """Tick-level position monitoring — TP/SL/timeout check.

    Critical bug fix: result is based on ACTUAL net_pnl_pct, NOT close_reason.
    TIMEOUT + negative PnL = LOSS (was incorrectly WIN before fix).
    """

    def __init__(self, cfg: BotConfig):
        self.cfg = cfg

    def check(
        self, trade: Trade, price: float
    ) -> tuple[bool, Optional[CloseReason], str]:
        if not trade.is_open:
            return False, None, "not_open"
        self._update(trade, price)
        if self._tp(trade, price):
            return True, CloseReason.TP, f"TP@{price}"
        if self._sl(trade, price):
            return True, CloseReason.SL, f"SL@{price}"
        elapsed = (datetime.now() - trade.opened_at).total_seconds()
        if elapsed >= self.cfg.max_duration_sec:
            return True, CloseReason.TIMEOUT, f"timeout_{elapsed:.0f}s"
        if elapsed < self.cfg.min_duration_sec:
            return False, None, f"min_guard_{elapsed:.0f}s"
        return False, None, "active"

    def _tp(self, t: Trade, p: float) -> bool:
        return p >= t.tp_price if t.direction == Direction.LONG else p <= t.tp_price

    def _sl(self, t: Trade, p: float) -> bool:
        return p <= t.sl_price if t.direction == Direction.LONG else p >= t.sl_price

    def _update(self, t: Trade, p: float) -> None:
        pnl = (
            (p - t.entry_price) / t.entry_price
            if t.direction == Direction.LONG
            else (t.entry_price - p) / t.entry_price
        ) * 100
        if pnl > t.max_profit_pct:
            t.max_profit_pct = pnl
        if pnl < -t.max_drawdown_pct:
            t.max_drawdown_pct = abs(pnl)


class TradeClassifier:
    """Classify closed trade by actual net PnL — never by close_reason."""

    def __init__(self, cfg: BotConfig):
        self.cfg = cfg

    def classify(self, trade: Trade) -> Trade:
        if not trade.entry_price or not trade.exit_price:
            return trade
        raw = (
            (trade.exit_price - trade.entry_price) / trade.entry_price
            if trade.direction == Direction.LONG
            else (trade.entry_price - trade.exit_price) / trade.entry_price
        )
        net = raw - (2 * self.cfg.taker_fee_pct)
        trade.raw_pnl_pct = round(raw * 100, self.cfg.pnl_decimals)
        trade.net_pnl_pct = round(net * 100, self.cfg.pnl_decimals)
        trade.result = (
            TradeResult.WIN if net > 0
            else TradeResult.LOSS if net < 0
            else TradeResult.BREAKEVEN
        )
        return trade
