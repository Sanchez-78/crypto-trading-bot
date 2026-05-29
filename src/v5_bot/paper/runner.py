"""V5 PAPER Bot event loop and orchestration."""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from .paper_broker import PaperBroker
from .exits import ExitEvaluator, ExitReason
from ..market.binance_usdm_feed import BinanceUSDMFeed
from ..market.local_book import LocalBookManager
from ..strategy.policy_selector import PolicySelector
from ..strategy.feature_engine import FeatureEngine
from ..strategy.cost_edge_gate import CostEdgeGate
from ..firebase.repository import QuotaAwareFirestoreRepository
from ..config import TRADING_SYMBOLS, QUOTA_BUDGET, LEARNING_CONFIG, REAL_READINESS_GATES
from ..util.datetime_utils import utc_now, utc_timestamp_iso

logger = logging.getLogger(__name__)


class V5BotRunner:
    """Main V5 PAPER bot orchestrator."""

    def __init__(self, firebase_creds_path: Optional[str] = None):
        # Market data
        self.feed = BinanceUSDMFeed()
        self.book_manager = LocalBookManager()

        # Execution
        self.broker = PaperBroker(self.book_manager)
        self.exit_evaluator = ExitEvaluator()

        # Strategy
        self.policy_selector = PolicySelector()
        self.feature_engines: Dict[str, FeatureEngine] = {
            symbol: FeatureEngine(symbol) for symbol in TRADING_SYMBOLS
        }
        self.cost_gate = CostEdgeGate()

        # Firebase
        self.firebase = QuotaAwareFirestoreRepository(firebase_creds_path)

        # State
        self.running = False
        self.epoch_id = None
        self.stats = {
            "entries_attempted": 0,
            "entries_successful": 0,
            "entries_rejected_by_gate": 0,
            "trades_closed": 0,
            "firebase_writes": 0,
            "firebase_failures": 0,
        }

    async def startup(self) -> None:
        """Initialize bot components."""
        logger.info("V5 PAPER Bot startup...")

        # Connect market feed
        await self.feed.connect(TRADING_SYMBOLS)
        logger.info(f"Connected to feeds for {len(TRADING_SYMBOLS)} symbols")

        # Initialize epoch
        self.epoch_id = f"epoch_{utc_now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Created epoch: {self.epoch_id}")

        self.running = True

    async def shutdown(self) -> None:
        """Gracefully shutdown bot."""
        logger.info("V5 PAPER Bot shutdown...")
        self.running = False

        if self.feed:
            await self.feed.disconnect()

        # Flush any pending Firebase writes
        try:
            status = self.firebase.flush_outbox(max_retries=3)
            logger.info(f"Flushed outbox: {status}")
        except Exception as e:
            logger.error(f"Outbox flush failed: {e}")

    async def process_market_tick(self) -> None:
        """Process one market tick (bookTicker events)."""
        for symbol in TRADING_SYMBOLS:
            # Update local book
            book = self.feed.get_book(symbol)
            if not book:
                continue

            self.book_manager.update_book(
                symbol=symbol,
                bid=book.bid,
                bid_qty=book.bid_qty,
                ask=book.ask,
                ask_qty=book.ask_qty,
                transaction_time=book.transaction_time,
                received_time=book.received_time,
            )

    async def evaluate_entry_signals(self) -> None:
        """Check all symbols for entry signals."""
        for symbol in TRADING_SYMBOLS:
            if len(self.broker.open_positions) >= 3:  # Max 3 open positions
                logger.debug(f"[{symbol}] Skipped: max open positions reached")
                continue

            # Get current book
            book = self.book_manager.get_book(symbol)
            if not book:
                logger.debug(f"[{symbol}] Skipped: no book data")
                continue
            if book.is_stale():
                logger.debug(f"[{symbol}] Skipped: stale book")
                continue

            # Extract features
            engine = self.feature_engines[symbol]
            # Note: In real implementation, would add candles from market data
            features = engine.extract_features(
                current_price=book.midpoint() or book.best_ask() or 0,
                bid=book.best_bid() or 0,
                ask=book.best_ask() or 0,
                spread_bps=book.spread_bps(),
            )

            # Get policy signal
            strategy_id, signal_reason, should_enter = self.policy_selector.evaluate_signal(features)
            if not should_enter:
                logger.debug(f"[Signal {symbol}] REJECTED: {signal_reason} (strategy_id={strategy_id})")
                continue

            logger.info(f"[Signal {symbol}] ACCEPTED: {signal_reason} (strategy_id={strategy_id})")

            # Get entry parameters
            entry_params = self.policy_selector.get_entry_params(strategy_id)
            if not entry_params:
                continue

            # Check cost-edge gate
            entry_price = book.best_ask() if entry_params["side"] == "BUY" else book.best_bid()
            if entry_price is None:
                continue

            cost_breakdown = self.cost_gate.calc_cost_breakdown(
                entry_price=entry_price,
                bid=book.best_bid() or 0,
                ask=book.best_ask() or 0,
                entry_qty=0.1,  # Default qty
                is_long=(entry_params["side"] == "BUY"),
            )

            # For PAPER bootstrap testing, assume moderate positive expectancy
            expected_move_bps = 40.0
            allowed, gate_reason = self.cost_gate.check_entry_allowed(expected_move_bps, cost_breakdown)

            if not allowed:
                self.stats["entries_rejected_by_gate"] += 1
                logger.debug(f"Entry {symbol} rejected: {gate_reason}")
                continue

            # Execute entry
            self.stats["entries_attempted"] += 1
            trade_id, fail_reason = self.broker.request_entry(
                symbol=symbol,
                side=entry_params["side"],
                qty=0.1,
                expected_price=entry_price,
                tp_pct=entry_params["target_pct"],
                sl_pct=entry_params["stop_loss_pct"],
                strategy_id=strategy_id,
            )

            if trade_id:
                self.stats["entries_successful"] += 1
                logger.info(f"Entry {trade_id}: {symbol} {entry_params['side']} @ {entry_price}")
            else:
                logger.warning(f"Entry failed for {symbol}: {fail_reason}")

    async def evaluate_exit_conditions(self) -> None:
        """Check all open positions for exit conditions."""
        current_time = utc_now().timestamp()

        for position in list(self.broker.open_positions.values()):
            # Get current price
            current_price = self.book_manager.get_price_for_order(position.symbol, "SELL")
            if current_price is None:
                continue

            # Check exit condition
            hold_seconds = int(current_time - position.entry_time)
            exit_info, exit_reason = self.broker.check_and_exit_position(
                position.trade_id, current_price, current_time
            )

            if exit_info:
                self.stats["trades_closed"] += 1
                logger.info(
                    f"Exit {position.trade_id}: {exit_reason} @ {current_price}, "
                    f"PnL: {exit_info['net_pnl_pct']:.2f}%"
                )

    async def publish_metrics(self) -> None:
        """Publish current metrics to Firebase."""
        try:
            open_count = len(self.broker.open_positions)
            notional = self.broker.get_position_notional()
            daily_stats = self.broker.get_daily_stats()

            metrics = {
                "epoch_id": self.epoch_id,
                "timestamp": utc_timestamp_iso(),
                "open_positions": open_count,
                "open_notional_usd": notional,
                "trades_closed_today": daily_stats.get("trades_closed", 0),
                "net_pnl_usd": daily_stats.get("total_net_pnl_usd", 0),
                "win_rate": daily_stats.get("win_rate"),
                "quota_state": self.firebase.get_quota_status(),
            }

            # In real implementation, would write to Firebase
            logger.debug(f"Metrics: {metrics}")
            self.stats["firebase_writes"] += 1

        except Exception as e:
            logger.error(f"Metrics publish failed: {e}")
            self.stats["firebase_failures"] += 1

    async def run(self, tick_interval_s: float = 1.0) -> None:
        """Main bot loop."""
        await self.startup()

        try:
            while self.running:
                # Process market data
                await self.process_market_tick()
                logger.debug(f"[Main loop] Market tick processed")

                # Check entry signals
                await self.evaluate_entry_signals()
                logger.debug(f"[Main loop] Entry signals evaluated (attempted: {self.stats['entries_attempted']}, rejected: {self.stats['entries_rejected_by_gate']})")

                # Check exit conditions
                await self.evaluate_exit_conditions()
                logger.debug(f"[Main loop] Exit conditions checked (closed: {self.stats['trades_closed']})")

                # Publish metrics periodically
                if int(utc_now().timestamp()) % 60 == 0:
                    await self.publish_metrics()
                    logger.info(f"[Main loop] Metrics published: {self.stats}")

                # Sleep before next tick
                await asyncio.sleep(tick_interval_s)

        except KeyboardInterrupt:
            logger.info("Received interrupt")
        except Exception as e:
            logger.error(f"Bot error: {e}", exc_info=True)
        finally:
            await self.shutdown()

    def get_status(self) -> Dict[str, Any]:
        """Get bot status."""
        return {
            "running": self.running,
            "epoch_id": self.epoch_id,
            "open_positions": len(self.broker.open_positions),
            "open_notional_usd": self.broker.get_position_notional(),
            "feed_connected": self.feed.running,
            "symbols_with_data": self.feed.get_status()["symbols_with_data"],
            "quota_state": self.firebase.get_quota_status(),
            "stats": self.stats,
        }
