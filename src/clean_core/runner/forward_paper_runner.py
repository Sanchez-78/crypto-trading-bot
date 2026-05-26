"""Standalone forward PAPER runner for Futures public-feed lifecycle."""

import os
import json
import logging
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
    ):
        """
        Args:
            feed: PublicFuturesFeed implementation (Simulated or Live)
            symbol: Trading symbol (e.g., "BTCUSDT")
            output_dir: Directory for journal/report output (must exist, no defaults)
            strategy: Trading strategy (default: FixedStrategy with 1% TP, 0.5% SL)
            fee_schedule: Fee schedule (default: Binance USDM standard)
        """
        self.feed = feed
        self.symbol = symbol
        self.output_dir = output_dir
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

        logger.info(
            f"ForwardPaperRunner initialized: symbol={symbol}, "
            f"epoch={epoch_id}, output_dir={output_dir}"
        )

    def run(self) -> dict:
        """
        Execute complete PAPER lifecycle.

        Returns:
            Report dict with epoch stats and closed outcomes
        """
        # Initialize feed
        self.feed.initialize(self.symbol)

        # Get snapshot
        snapshot = self.feed.get_snapshot()
        if not snapshot:
            raise ValueError(f"Feed returned no snapshot for {self.symbol}")

        # Collect all trades from feed
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

        # Generate report
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
        }

        logger.info(f"ForwardPaperRunner completed: {self.epoch.closed_trades_count} closed trades")
        return report
