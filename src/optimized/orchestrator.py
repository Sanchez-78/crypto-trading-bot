from __future__ import annotations
from datetime import datetime
from typing import Optional
import logging

from src.optimized.bot_types import BotConfig, Trade, TradeSignal, Direction, CloseReason
from src.optimized.filter_pipeline import SignalFilterPipeline
from src.optimized.position_manager import PositionManager, TradeClassifier

logger = logging.getLogger(__name__)


class TradeOrchestrator:
    """Main entry point for the optimized signal pipeline.

    Usage:
        bot = TradeOrchestrator()
        decision, meta = bot.on_signal(signal, market)
        closed_trade = bot.on_price_tick(price)
        closed_trade = bot.on_candle(df, regime, tf, funding_rate, market)
    """

    def __init__(self, cfg: BotConfig = None, candle_seconds: int = 3600, capital: float = 10_000):
        self.cfg = cfg or BotConfig()
        self.pipeline = SignalFilterPipeline(self.cfg, candle_seconds)
        self.manager = PositionManager(self.cfg)
        self.classifier = TradeClassifier(self.cfg)
        self.active: Optional[Trade] = None
        self.history: list[Trade] = []
        # Strategy router — lazy import to avoid hard dependency on talib at import time
        self._capital = capital
        self._router = None

    def _get_router(self):
        if self._router is None:
            from src.optimized.strategies import StrategyRouter
            self._router = StrategyRouter(capital=self._capital)
        return self._router

    # ── Signal entry ──────────────────────────────────────────────────────────

    def on_signal(
        self, signal: TradeSignal, market: dict
    ) -> tuple[str, dict]:
        if self.active:
            return "BLOCKED", {"reason": "position_open"}

        decision, meta = self.pipeline.evaluate(signal, market)

        if decision not in ("ENTER", "ENTER_REDUCED"):
            t = Trade(
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                sl_price=signal.sl_price,
                tp_price=signal.tp_price,
                close_reason=CloseReason.VALIDATION,
                rejection_reason=f"{decision}:{meta}",
            )
            self.history.append(t)
            logger.info("[%s] REJECT %s:%s", t.id, decision, meta)
            return decision, meta

        t = Trade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            sl_price=meta.get("sl", signal.sl_price),
            tp_price=meta.get("tp", signal.tp_price),
            probability=signal.probability,
            obi=signal.obi,
            atr=signal.atr,
            opened_at=datetime.now(),
            entry_size=meta.get("size", 1.0),
        )
        self.active = t
        logger.info(
            "[%s] OPEN %s %s@%.8f SL=%.8f TP=%.8f sz=%.2f rr=%s",
            t.id, t.direction.value, t.symbol, t.entry_price,
            t.sl_price, t.tp_price, t.entry_size, meta.get("rr_ratio"),
        )
        return decision, meta

    # ── Tick monitoring ───────────────────────────────────────────────────────

    def on_price_tick(self, price: float) -> Optional[Trade]:
        if not self.active:
            return None
        sc, reason, msg = self.manager.check(self.active, price)
        return self._close(price, reason) if sc else None

    # ── Manual close ──────────────────────────────────────────────────────────

    def force_close(self, price: float) -> Optional[Trade]:
        return self._close(price, CloseReason.MANUAL) if self.active else None

    # ── Candle handler (B14) — regime-aware strategy routing ─────────────────

    def on_candle(
        self,
        df,
        regime: str,
        tf: str = "1h",
        funding_rate: float = 0.0,
        market: dict = None,
    ) -> Optional[tuple]:
        if self.active:
            return None

        router = self._get_router()
        sigs = router.route(df, regime, tf, funding_rate)
        if not sigs:
            return None

        top = sigs[0]
        if top.signal == "NEUTRAL" or top.strength < 0.4:
            return None

        from src.optimized.sl_tp_calculator import calculate_sl_tp
        atr = df["close"].diff().abs().rolling(14).mean().iloc[-1]
        entry = df["close"].iloc[-1]
        stops = calculate_sl_tp(top.signal, entry, atr, 1.0, df.attrs.get("symbol", ""))

        sig = TradeSignal(
            symbol=df.attrs.get("symbol", "UNK"),
            direction=Direction[top.signal],
            entry_price=entry,
            sl_price=stops["sl"],
            tp_price=stops["tp"],
            probability=min(0.95, 0.5 + top.strength * 0.4),
            expected_value=top.strength,
            obi=market.get("obi", 0.0) if market else 0.0,
            atr=atr,
        )
        return self.on_signal(sig, market) if market else None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _close(self, exit_price: float, reason: CloseReason) -> Trade:
        t = self.active
        t.exit_price = exit_price
        t.closed_at = datetime.now()
        t.close_reason = reason
        t = self.classifier.classify(t)
        self.pipeline.on_trade_closed(t.symbol, "RANGING", t.net_pnl_pct, reason)
        self.active = None
        self.history.append(t)
        logger.info(
            "[%s] CLOSE %s PnL=%+.4f%% %s %ss",
            t.id, t.result.value, t.net_pnl_pct, reason.value, t.duration_seconds,
        )
        return t

    # ── Statistics ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        import collections
        closed = [t for t in self.history if t.close_reason != CloseReason.VALIDATION]
        if not closed:
            return {"msg": "no_trades"}

        from src.optimized.bot_types import TradeResult
        wins    = [t for t in closed if t.result == TradeResult.WIN]
        losses  = [t for t in closed if t.result == TradeResult.LOSS]
        to_loss = [t for t in closed
                   if t.close_reason == CloseReason.TIMEOUT and t.result == TradeResult.LOSS]
        return {
            "total":         len(closed),
            "wins":          len(wins),
            "losses":        len(losses),
            "winrate_pct":   round(len(wins) / len(closed) * 100, 1),
            "total_pnl_pct": round(sum(t.net_pnl_pct for t in closed), 4),
            "avg_win_pct":   round(sum(t.net_pnl_pct for t in wins) / len(wins), 4) if wins else 0,
            "avg_loss_pct":  round(sum(t.net_pnl_pct for t in losses) / len(losses), 4) if losses else 0,
            "avg_dur_s":     round(sum(t.duration_seconds or 0 for t in closed) / len(closed)),
            "timeout_losses": len(to_loss),
            "rejected":      len([t for t in self.history if t.close_reason == CloseReason.VALIDATION]),
            "rejections":    dict(collections.Counter(
                t.rejection_reason.split(":")[0]
                for t in self.history
                if t.close_reason == CloseReason.VALIDATION
            )),
        }
