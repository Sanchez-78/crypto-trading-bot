"""Standalone forward PAPER runner for Futures public-feed lifecycle."""

import os
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List
from pathlib import Path

from src.clean_core.market.binance_usdm_routes import BinanceUsdmRoutes
from src.clean_core.strategy.fixed_strategy import FixedStrategy
from src.clean_core.strategy.offline_replay import OfflineReplayEngine
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.domain import ExecutionTruthClass, MarketSourceIdentity
from src.clean_core.provenance.journal import CleanCoreJournal
from src.clean_core.provenance.epoch import CleanPaperEpoch
from .public_futures_feed import PublicFuturesFeed

logger = logging.getLogger(__name__)


class ForwardPaperRunner:
    """
    Orchestrates complete PAPER lifecycle from Futures public feed to closed outcomes.

    Flow:
    1. Initialize feed (live or simulated)
    2. Consume market snapshot
    3. Stream trades through strategy
    4. Execute PAPER entry/exit logic
    5. Record closed outcomes to journal
    6. Generate epoch report
    """

    def __init__(
        self,
        feed: PublicFuturesFeed,
        symbol: str,
        output_dir: str,
        strategy: Optional[FixedStrategy] = None,
        fee_schedule: Optional[FeeSchedule] = None,
        duration_seconds: Optional[int] = None,
    ):
        """
        Args:
            feed: PublicFuturesFeed implementation (Simulated or Live)
            symbol: Trading symbol (e.g., "BTCUSDT")
            output_dir: Directory for journal/report output (must exist, no defaults)
            strategy: Trading strategy (default: FixedStrategy with 1% TP, 0.5% SL)
            fee_schedule: Fee schedule (default: Binance USDM standard)
            duration_seconds: For live mode, bounded session duration in seconds (None for simulated)
        """
        self.feed = feed
        self.symbol = symbol
        self.output_dir = output_dir
        self.duration_seconds = duration_seconds
        self.strategy = strategy or FixedStrategy(tp_pct=1.0, sl_pct=0.5, timeout_minutes=60)
        self.fee_schedule = fee_schedule or FeeSchedule.binance_usdm_standard()

        # Verify output_dir exists and is absolute (no defaults to legacy paths)
        output_path = Path(output_dir)
        if not output_path.exists():
            raise ValueError(f"output_dir must exist: {output_dir}")
        if not output_path.is_absolute():
            raise ValueError(f"output_dir must be absolute path: {output_dir}")

        # Create market source (FUTURES_PUBLIC_BOOK_MEASURED = R1 baseline)
        self.market_source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument=symbol,
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version="R1",
        )

        # Create epoch
        epoch_id = f"paper_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.epoch = CleanPaperEpoch(
            epoch_id=epoch_id,
            status="active",
            created_utc=datetime.now(timezone.utc).isoformat(),
            started_utc=datetime.now(timezone.utc).isoformat(),
        )

        # Create engine
        self.engine = OfflineReplayEngine(self.strategy, self.fee_schedule, self.market_source)

        # Create journal
        journal_path = os.path.join(output_dir, f"paper_run_{epoch_id}.jsonl")
        self.journal = CleanCoreJournal(journal_path)

        # Event tracking for live mode
        self.book_ticker_events_received = 0
        self.agg_trade_events_received = 0
        self.first_book_ticker_event_at = None
        self.first_agg_trade_event_at = None
        self.last_market_event_at = None
        self.feed_connected = False
        self.feed_reconnect_count = 0
        self.feed_timeout_count = 0
        self.hard_feed_failure = False

        logger.info(
            f"ForwardPaperRunner initialized: symbol={symbol}, "
            f"epoch={epoch_id}, output_dir={output_dir}, "
            f"duration_seconds={duration_seconds}"
        )

    def run(self) -> dict:
        """
        Execute complete PAPER lifecycle (simulated deterministic or bounded live streaming).

        Returns:
            Report dict with epoch stats and closed outcomes
        """
        if self.duration_seconds is None:
            # Simulated/recorded mode: deterministic finite replay
            return self._run_simulated()
        else:
            # Live mode: bounded streaming session
            return self._run_bounded_live()

    def _run_simulated(self) -> dict:
        """
        Simulated/recorded mode: consume fixture events until exhausted, replay, generate report.
        """
        # Initialize feed
        self.feed.initialize(self.symbol)

        # Get snapshot
        snapshot = self.feed.get_snapshot()
        if not snapshot:
            raise ValueError(f"Feed returned no snapshot for {self.symbol}")

        # Collect all trades from feed (deterministic: all available at once)
        trades = []
        while True:
            trade = self.feed.get_next_trade()
            if not trade:
                break
            trades.append({
                "time": trade.timestamp_utc,
                "price": trade.price,
            })

        self.feed.close()

        # Convert snapshot to dict
        snapshot_dict = {
            "time": snapshot.timestamp_utc,
            "price": snapshot.price,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
        }

        # Run replay
        closed_outcomes = self.engine.replay_snapshot_and_trades(
            symbol=self.symbol,
            initial_snapshot=snapshot_dict,
            trades=trades,
            epoch_id=self.epoch.epoch_id,
        )

        # Record outcomes to journal
        for outcome in closed_outcomes:
            self.journal.append_event(
                "paper_trade_closed",
                {
                    "position_id": outcome.position_id,
                    "symbol": outcome.symbol,
                    "entry_price": outcome.entry_fill.fill_price,
                    "exit_price": outcome.exit_fill.fill_price,
                    "gross_pnl_pct": outcome.gross_pnl_pct,
                    "fee_cost_pct": outcome.fee_cost_pct,
                    "net_pnl_pct": outcome.net_pnl_pct,
            },
                clean_core_version="R1",
                config_hash=f"strategy_{self.strategy.__class__.__name__}",
            )
            # Update epoch
            self.epoch.add_closed_trade(
                net_pnl_pct=outcome.net_pnl_pct,
                readiness_eligible=outcome.eligible_for_real_readiness,
                execution_truth_class=outcome.execution_truth_class.value,
            )

        return self._generate_report(closed_outcomes)

    def _run_bounded_live(self) -> dict:
        """
        Live mode: bounded streaming session with explicit duration.

        Runs until duration_seconds expires, collecting live events.
        Empty queue polls do not end the session.
        """
        try:
            self.feed.initialize(self.symbol)
            self.feed_connected = True
        except Exception as e:
            logger.error(f"Failed to initialize feed: {e}")
            self.hard_feed_failure = True
            return self._generate_report([])

        # Get initial snapshot
        snapshot = self.feed.get_snapshot()
        if not snapshot:
            logger.error(f"Feed returned no snapshot for {self.symbol}")
            self.hard_feed_failure = True
            self.feed.close()
            return self._generate_report([])

        # Start bounded session timer
        session_start = time.monotonic()
        trades = []
        closed_outcomes = []

        # Bounded streaming loop: collect trades until duration expires
        while True:
            elapsed = time.monotonic() - session_start
            if elapsed >= self.duration_seconds:
                break

            # Poll with short timeout (0.5s), but empty poll does NOT end session
            trade = self.feed.get_next_trade(timeout_seconds=0.5)
            if trade:
                # Track event
                self.agg_trade_events_received += 1
                if self.first_agg_trade_event_at is None:
                    self.first_agg_trade_event_at = time.monotonic() - session_start
                    logger.info(
                        f"AGG_TRADE_EVENT_RECEIVED symbol={self.symbol.upper()} "
                        f"price={trade.price} quantity={trade.qty} event_count=1"
                    )
                self.last_market_event_at = time.monotonic() - session_start
                trades.append({
                    "time": trade.timestamp_utc,
                    "price": trade.price,
                })

            # Get latest snapshot (tracking bookTicker events)
            latest_snapshot = self.feed.get_snapshot()
            if latest_snapshot:
                if self.book_ticker_events_received == 0:
                    self.book_ticker_events_received = 1
                    self.first_book_ticker_event_at = time.monotonic() - session_start
                    logger.info(
                        f"BOOK_TICKER_EVENT_RECEIVED symbol={self.symbol.upper()} "
                        f"bid={latest_snapshot.bid} ask={latest_snapshot.ask} event_count=1"
                    )
                else:
                    self.book_ticker_events_received += 1
                snapshot = latest_snapshot

            # Small sleep to avoid busy-loop (but allow responsiveness)
            time.sleep(0.01)

        self.feed.close()

        # Only evaluate strategy if both event types have been received
        if self.book_ticker_events_received > 0 and self.agg_trade_events_received > 0:
            snapshot_dict = {
                "time": snapshot.timestamp_utc,
                "price": snapshot.price,
                "bid": snapshot.bid,
                "ask": snapshot.ask,
            }

            try:
                closed_outcomes = self.engine.replay_snapshot_and_trades(
                    symbol=self.symbol,
                    initial_snapshot=snapshot_dict,
                    trades=trades,
                    epoch_id=self.epoch.epoch_id,
                )
            except Exception as e:
                logger.error(f"Strategy replay failed: {e}")

        # Record closed outcomes to journal
        for outcome in closed_outcomes:
            self.journal.append_event(
                "paper_trade_closed",
                {
                    "position_id": outcome.position_id,
                    "symbol": outcome.symbol,
                    "entry_price": outcome.entry_fill.fill_price,
                    "exit_price": outcome.exit_fill.fill_price,
                    "gross_pnl_pct": outcome.gross_pnl_pct,
                    "fee_cost_pct": outcome.fee_cost_pct,
                    "net_pnl_pct": outcome.net_pnl_pct,
            },
                clean_core_version="R1",
                config_hash=f"strategy_{self.strategy.__class__.__name__}",
            )
            # Update epoch
            self.epoch.add_closed_trade(
                net_pnl_pct=outcome.net_pnl_pct,
                readiness_eligible=outcome.eligible_for_real_readiness,
                execution_truth_class=outcome.execution_truth_class.value,
            )

        logger.info(
            f"Bounded live session completed: {elapsed:.2f}s elapsed, "
            f"{self.book_ticker_events_received} bookTicker, {self.agg_trade_events_received} aggTrade, "
            f"{self.epoch.closed_trades_count} closed trades"
        )

        return self._generate_report(closed_outcomes)

    def _generate_report(self, closed_outcomes: List) -> dict:
        """Generate standard report dict."""
        report = {
            "epoch_id": self.epoch.epoch_id,
            "symbol": self.symbol,
            "status": "complete",
            "closed_trades_count": self.epoch.closed_trades_count,
            "readiness_eligible_count": self.epoch.readiness_eligible_count,
            "average_net_pnl_pct": self.epoch.average_net_pnl_pct if self.epoch.closed_trades_count > 0 else 0.0,
            "closed_outcomes": [
                {
                    "position_id": o.position_id,
                    "entry_price": o.entry_fill.fill_price,
                    "exit_price": o.exit_fill.fill_price,
                    "gross_pnl_pct": o.gross_pnl_pct,
                    "fee_cost_pct": o.fee_cost_pct,
                    "net_pnl_pct": o.net_pnl_pct,
                    "eligible_for_clean_paper_metrics": o.eligible_for_clean_paper_metrics,
                    "eligible_for_real_readiness": o.eligible_for_real_readiness,
                    "execution_truth_class": o.execution_truth_class.value,
                }
                for o in closed_outcomes
            ],
            "journal_path": self.journal.file_path,
            "live_session_metadata": {
                "book_ticker_events": self.book_ticker_events_received,
                "agg_trade_events": self.agg_trade_events_received,
                "first_book_ticker_at": self.first_book_ticker_event_at,
                "first_agg_trade_at": self.first_agg_trade_event_at,
                "last_market_event_at": self.last_market_event_at,
                "feed_connected": self.feed_connected,
                "feed_reconnect_count": self.feed_reconnect_count,
                "feed_timeout_count": self.feed_timeout_count,
                "hard_feed_failure": self.hard_feed_failure,
            } if self.duration_seconds else {},
        }

        logger.info(f"ForwardPaperRunner completed: {self.epoch.closed_trades_count} closed trades")
        return report
