"""V5 Bot Metrics API - Android App Integration"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime
from ..util.datetime_utils import utc_now, utc_timestamp_iso


@dataclass
class MetricsSnapshot:
    """Complete metrics snapshot for Android app."""

    # Status
    running: bool
    epoch_id: Optional[str]
    timestamp: str  # ISO8601
    feed_connected: bool
    symbols_with_data: int

    # Positions
    open_positions: int
    open_notional_usd: float
    max_open_global: int

    # Trading
    entries_attempted: int
    entries_successful: int
    entries_rejected_by_gate: int
    trades_closed: int

    # Performance
    total_net_pnl_usd: float
    net_pnl_pct: Optional[float]
    win_rate: Optional[float]
    profit_factor: Optional[float]
    average_cost_bps: float

    # Signals (per symbol)
    signals: Dict[str, str]  # {BTCUSDT: "ACCEPTED: ...", ETHUSDT: "REJECTED: ...", ...}
    current_regime: Optional[str]

    # Firebase
    firebase_writes: int
    firebase_failures: int
    quota_reads_used: int
    quota_reads_limit: int
    quota_writes_used: int
    quota_writes_limit: int
    quota_state: str  # "NORMAL", "WARNING", "EXHAUSTED"

    # Market data
    reconnect_count: int
    stale_events_rejected: int
    book_spreads: Dict[str, float]  # {BTCUSDT: 0.01, ETHUSDT: 0.05, ...}
    mid_prices: Dict[str, float]    # {BTCUSDT: 73258.55, ...}

    # Learning
    learning_updates: int
    strategies_being_evaluated: int
    eligible_closes_today: int
    min_closes_for_eligibility: int

    # Operations
    uptime_seconds: int
    logs_per_second: float
    cpu_percent: float
    memory_mb: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class TradeRecord:
    """Single closed trade with full details and timestamps."""
    trade_id: str
    symbol: str
    entry_side: str
    entry_price: float
    exit_price: float
    qty: float
    entry_timestamp: str  # ISO8601
    exit_timestamp: str   # ISO8601
    hold_seconds: int
    gross_pnl_usd: float
    gross_pnl_pct: float
    net_pnl_usd: float
    net_pnl_pct: float
    total_costs_usd: float
    entry_fee_usd: float
    exit_fee_usd: float
    funding_cost_usd: float
    entry_notional_usd: float
    outcome: str  # "WIN", "LOSS", or "FLAT"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class PerSymbolLearning:
    """Learning metrics per symbol."""
    symbol: str
    trades_closed: int
    wins: int
    losses: int
    flats: int
    win_rate: Optional[float]
    total_pnl_usd: float
    avg_pnl_per_trade: Optional[float]
    total_fees_usd: float
    best_trade_pnl_usd: Optional[float]
    worst_trade_pnl_usd: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class LearningHistory:
    """Complete learning and success history."""
    total_trades_closed: int
    total_wins: int
    total_losses: int
    total_flats: int
    win_rate: Optional[float]
    total_net_pnl_usd: float
    total_fees_usd: float
    avg_pnl_per_trade: Optional[float]
    per_symbol_summary: Dict[str, PerSymbolLearning]
    closed_trades: List[TradeRecord]  # Detailed history of each trade
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_trades_closed": self.total_trades_closed,
            "total_wins": self.total_wins,
            "total_losses": self.total_losses,
            "total_flats": self.total_flats,
            "win_rate": self.win_rate,
            "total_net_pnl_usd": self.total_net_pnl_usd,
            "total_fees_usd": self.total_fees_usd,
            "avg_pnl_per_trade": self.avg_pnl_per_trade,
            "per_symbol_summary": {
                symbol: summary.to_dict()
                for symbol, summary in self.per_symbol_summary.items()
            },
            "closed_trades": [trade.to_dict() for trade in self.closed_trades],
            "timestamp": self.timestamp,
        }


class MetricsCollector:
    """Collects metrics from V5 bot components."""

    def __init__(self, runner=None, firebase_repo=None, feed=None):
        """Initialize collector with bot components."""
        self.runner = runner
        self.firebase_repo = firebase_repo
        self.feed = feed
        self.start_time = utc_now().timestamp()
        self.log_count = 0

    def collect(self) -> MetricsSnapshot:
        """Collect all metrics from bot state."""
        if not self.runner:
            return self._empty_snapshot()

        # Status
        running = self.runner.running
        epoch_id = self.runner.epoch_id
        feed_connected = self.runner.feed.running if self.runner.feed else False
        symbols_with_data = self.runner.feed.get_status()["symbols_with_data"] if self.runner.feed else 0

        # Positions
        open_positions = len(self.runner.broker.open_positions)
        open_notional = self.runner.broker.get_position_notional()
        max_open = 3  # From config

        # Trading stats
        stats = self.runner.stats
        entries_attempted = stats.get("entries_attempted", 0)
        entries_successful = stats.get("entries_successful", 0)
        entries_rejected = stats.get("entries_rejected_by_gate", 0)
        trades_closed = stats.get("trades_closed", 0)

        # Performance
        daily_stats = self.runner.broker.get_daily_stats()
        total_pnl = daily_stats.get("total_net_pnl_usd", 0.0)
        net_pnl_pct = daily_stats.get("net_pnl_pct", None)
        win_rate = daily_stats.get("win_rate", None)
        profit_factor = daily_stats.get("profit_factor", None)
        avg_cost = daily_stats.get("average_cost_bps", 0.0)

        # Signals (last evaluated signals)
        signals = getattr(self.runner, "last_signals", {})
        current_regime = getattr(self.runner, "last_regime", None)

        # Firebase
        firebase_writes = stats.get("firebase_writes", 0)
        firebase_failures = stats.get("firebase_failures", 0)
        quota_status = self.firebase_repo.get_quota_status() if self.firebase_repo else {}
        quota_reads_used = quota_status.get("reads_used", 0)
        quota_reads_limit = quota_status.get("reads_limit", 20000)
        quota_writes_used = quota_status.get("writes_used", 0)
        quota_writes_limit = quota_status.get("writes_limit", 10000)
        quota_state = quota_status.get("state", "NORMAL")

        # Market data
        feed_status = self.feed.get_status() if self.feed else {}
        reconnect_count = feed_status.get("reconnect_count", 0)
        stale_rejected = feed_status.get("stale_events_rejected", 0)

        # Book spreads and prices
        spreads = {}
        prices = {}
        if self.feed:
            for symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT"]:
                book = self.feed.get_book(symbol)
                if book:
                    spreads[symbol] = book.spread_bps()
                    prices[symbol] = book.midpoint()

        # Learning
        learning_updates = stats.get("learning_updates", 0)
        strategies_eval = len(self.runner.feature_engines)
        eligible_closes = stats.get("eligible_closes_today", 0)
        min_closes = 30

        # Operations
        now = utc_now().timestamp()
        uptime = int(now - self.start_time)
        logs_per_sec = self.log_count / max(uptime, 1)
        cpu_pct = 0.0  # TODO: get from psutil
        mem_mb = 0  # TODO: get from psutil

        return MetricsSnapshot(
            running=running,
            epoch_id=epoch_id,
            timestamp=utc_timestamp_iso(),
            feed_connected=feed_connected,
            symbols_with_data=symbols_with_data,
            open_positions=open_positions,
            open_notional_usd=open_notional,
            max_open_global=max_open,
            entries_attempted=entries_attempted,
            entries_successful=entries_successful,
            entries_rejected_by_gate=entries_rejected,
            trades_closed=trades_closed,
            total_net_pnl_usd=total_pnl,
            net_pnl_pct=net_pnl_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_cost_bps=avg_cost,
            signals=signals,
            current_regime=current_regime,
            firebase_writes=firebase_writes,
            firebase_failures=firebase_failures,
            quota_reads_used=quota_reads_used,
            quota_reads_limit=quota_reads_limit,
            quota_writes_used=quota_writes_used,
            quota_writes_limit=quota_writes_limit,
            quota_state=quota_state,
            reconnect_count=reconnect_count,
            stale_events_rejected=stale_rejected,
            book_spreads=spreads,
            mid_prices=prices,
            learning_updates=learning_updates,
            strategies_being_evaluated=strategies_eval,
            eligible_closes_today=eligible_closes,
            min_closes_for_eligibility=min_closes,
            uptime_seconds=uptime,
            logs_per_second=logs_per_sec,
            cpu_percent=cpu_pct,
            memory_mb=mem_mb,
        )

    def collect_learning_history(self) -> LearningHistory:
        """Collect learning history from closed trades."""
        if not self.runner or not self.runner.broker:
            return self._empty_learning_history()

        closed_trades = self.runner.broker.closed_trades
        per_symbol = {}
        all_trade_records = []

        # Process each closed trade
        for trade_id, trade in closed_trades.items():
            if not trade.is_complete or not trade.accounting_valid:
                continue

            # Determine outcome
            if trade.net_pnl_usd > 0:
                outcome = "WIN"
            elif trade.net_pnl_usd < 0:
                outcome = "LOSS"
            else:
                outcome = "FLAT"

            # Convert timestamps from FillRecord
            entry_timestamp = ""
            exit_timestamp = ""
            hold_seconds = 0

            if trade.entry_fill and trade.exit_fill:
                entry_timestamp = utc_timestamp_iso() if not trade.entry_fill.received_time else trade.entry_fill.received_time
                exit_timestamp = utc_timestamp_iso() if not trade.exit_fill.received_time else trade.exit_fill.received_time
                hold_seconds = int(trade.exit_fill.received_time - trade.entry_fill.received_time)

                # Create ISO timestamp strings from epoch seconds
                from datetime import datetime, timezone
                entry_dt = datetime.fromtimestamp(trade.entry_fill.received_time, tz=timezone.utc)
                exit_dt = datetime.fromtimestamp(trade.exit_fill.received_time, tz=timezone.utc)
                entry_timestamp = entry_dt.isoformat()
                exit_timestamp = exit_dt.isoformat()

            # Create trade record
            record = TradeRecord(
                trade_id=trade_id,
                symbol=trade.symbol,
                entry_side=trade.entry_side,
                entry_price=trade.entry_fill.price if trade.entry_fill else 0.0,
                exit_price=trade.exit_fill.price if trade.exit_fill else 0.0,
                qty=trade.entry_fill.qty if trade.entry_fill else 0.0,
                entry_timestamp=entry_timestamp,
                exit_timestamp=exit_timestamp,
                hold_seconds=hold_seconds,
                gross_pnl_usd=trade.gross_pnl_usd,
                gross_pnl_pct=trade.gross_pnl_pct,
                net_pnl_usd=trade.net_pnl_usd,
                net_pnl_pct=trade.net_pnl_pct,
                total_costs_usd=trade.total_costs_usd,
                entry_fee_usd=trade.entry_fee_usd,
                exit_fee_usd=trade.exit_fee_usd,
                funding_cost_usd=trade.funding_cost_usd,
                entry_notional_usd=trade.entry_fill.notional_usd if trade.entry_fill else 0.0,
                outcome=outcome,
            )
            all_trade_records.append(record)

            # Accumulate per-symbol stats
            symbol = trade.symbol
            if symbol not in per_symbol:
                per_symbol[symbol] = {
                    "trades": [],
                    "wins": 0,
                    "losses": 0,
                    "flats": 0,
                    "total_pnl": 0.0,
                    "total_fees": 0.0,
                    "best_pnl": None,
                    "worst_pnl": None,
                }

            per_symbol[symbol]["trades"].append(trade)
            per_symbol[symbol]["total_pnl"] += trade.net_pnl_usd
            per_symbol[symbol]["total_fees"] += trade.total_costs_usd

            if outcome == "WIN":
                per_symbol[symbol]["wins"] += 1
            elif outcome == "LOSS":
                per_symbol[symbol]["losses"] += 1
            else:
                per_symbol[symbol]["flats"] += 1

            # Track best/worst
            if per_symbol[symbol]["best_pnl"] is None or trade.net_pnl_usd > per_symbol[symbol]["best_pnl"]:
                per_symbol[symbol]["best_pnl"] = trade.net_pnl_usd
            if per_symbol[symbol]["worst_pnl"] is None or trade.net_pnl_usd < per_symbol[symbol]["worst_pnl"]:
                per_symbol[symbol]["worst_pnl"] = trade.net_pnl_usd

        # Build per-symbol summary
        per_symbol_summary = {}
        total_wins = 0
        total_losses = 0
        total_flats = 0
        total_pnl = 0.0
        total_fees = 0.0

        for symbol, data in per_symbol.items():
            trades_count = len(data["trades"])
            summary = PerSymbolLearning(
                symbol=symbol,
                trades_closed=trades_count,
                wins=data["wins"],
                losses=data["losses"],
                flats=data["flats"],
                win_rate=data["wins"] / trades_count if trades_count > 0 else None,
                total_pnl_usd=data["total_pnl"],
                avg_pnl_per_trade=data["total_pnl"] / trades_count if trades_count > 0 else None,
                total_fees_usd=data["total_fees"],
                best_trade_pnl_usd=data["best_pnl"],
                worst_trade_pnl_usd=data["worst_pnl"],
            )
            per_symbol_summary[symbol] = summary

            total_wins += data["wins"]
            total_losses += data["losses"]
            total_flats += data["flats"]
            total_pnl += data["total_pnl"]
            total_fees += data["total_fees"]

        total_trades = len(all_trade_records)

        return LearningHistory(
            total_trades_closed=total_trades,
            total_wins=total_wins,
            total_losses=total_losses,
            total_flats=total_flats,
            win_rate=total_wins / total_trades if total_trades > 0 else None,
            total_net_pnl_usd=total_pnl,
            total_fees_usd=total_fees,
            avg_pnl_per_trade=total_pnl / total_trades if total_trades > 0 else None,
            per_symbol_summary=per_symbol_summary,
            closed_trades=all_trade_records,
            timestamp=utc_timestamp_iso(),
        )

    def _empty_learning_history(self) -> LearningHistory:
        """Return empty learning history."""
        return LearningHistory(
            total_trades_closed=0,
            total_wins=0,
            total_losses=0,
            total_flats=0,
            win_rate=None,
            total_net_pnl_usd=0.0,
            total_fees_usd=0.0,
            avg_pnl_per_trade=None,
            per_symbol_summary={},
            closed_trades=[],
            timestamp=utc_timestamp_iso(),
        )

    def _empty_snapshot(self) -> MetricsSnapshot:
        """Return empty snapshot when bot not initialized."""
        return MetricsSnapshot(
            running=False,
            epoch_id=None,
            timestamp=utc_timestamp_iso(),
            feed_connected=False,
            symbols_with_data=0,
            open_positions=0,
            open_notional_usd=0.0,
            max_open_global=3,
            entries_attempted=0,
            entries_successful=0,
            entries_rejected_by_gate=0,
            trades_closed=0,
            total_net_pnl_usd=0.0,
            net_pnl_pct=None,
            win_rate=None,
            profit_factor=None,
            average_cost_bps=0.0,
            signals={},
            current_regime=None,
            firebase_writes=0,
            firebase_failures=0,
            quota_reads_used=0,
            quota_reads_limit=20000,
            quota_writes_used=0,
            quota_writes_limit=10000,
            quota_state="NORMAL",
            reconnect_count=0,
            stale_events_rejected=0,
            book_spreads={},
            mid_prices={},
            learning_updates=0,
            strategies_being_evaluated=0,
            eligible_closes_today=0,
            min_closes_for_eligibility=30,
            uptime_seconds=0,
            logs_per_second=0.0,
            cpu_percent=0.0,
            memory_mb=0,
        )
