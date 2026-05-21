"""
dashboard_snapshot_contract.py — Canonical mobile snapshot for Android.

Builds a single, comprehensive Firestore document for dashboard_snapshot/latest.
Pure builder, no Firebase/runtime imports.

Schema version: dashboard_snapshot_v1
Android reads: dashboard_snapshot/latest (one document)
"""

import math
import time as _time
from typing import Optional


def _safe_float(value, default: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default: str = "") -> str:
    try:
        return str(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _extract_profit(trade: dict) -> float:
    """Extract profit from trade dict (compatibility with app_metrics_contract)."""
    for field in ("profit", "pnl", "net_pnl"):
        if field in trade:
            try:
                v = float(trade[field] or 0.0)
                if not (math.isnan(v) or math.isinf(v)):
                    return v
            except (TypeError, ValueError):
                pass
    try:
        return float(trade.get("evaluation", {}).get("profit", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _extract_closed_at(trade: dict) -> float:
    """Extract closed_at timestamp. Prefer closed_at/exit_ts over created_at/timestamp."""
    for field in ("closed_at", "exit_ts"):
        if field in trade:
            v = _safe_float(trade.get(field), 0.0)
            if v > 0:
                return v
    # Fallback (should not happen)
    return _safe_float(trade.get("timestamp") or trade.get("created_at"), 0.0)


def _split_trades_by_mode(trades: list) -> tuple[list, list, list]:
    """Split closed trades into paper_train, paper_live, live_real, replay_train."""
    paper_train = []
    paper_live = []
    live_real = []
    replay_train = []

    for t in trades:
        mode = _safe_str(t.get("trading_mode") or t.get("mode"), "paper_live").lower()
        if mode == "paper_train":
            paper_train.append(t)
        elif mode == "replay_train":
            replay_train.append(t)
        elif mode == "live_real":
            live_real.append(t)
        else:
            paper_live.append(t)

    return paper_train, paper_live, live_real, replay_train


def _compute_mode_metrics(trades: list, mode_name: str) -> dict:
    """Compute KPIs for a mode-specific trade list."""
    if not trades:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "winrate": None,
            "net_pnl": 0.0,
            "last_closed_at": None,
        }

    profits = [_extract_profit(t) for t in trades]
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    flats = sum(1 for p in profits if abs(p) < 0.0001)
    decisive = wins + losses
    net_pnl = sum(profits)

    # Last closed trade
    last_closed_at = None
    for t in reversed(trades):
        ts = _extract_closed_at(t)
        if ts > 0:
            last_closed_at = ts
            break

    return {
        "count": len(trades),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "winrate": round(wins / decisive, 4) if decisive > 0 else None,
        "net_pnl": round(net_pnl, 6),
        "last_closed_at": last_closed_at,
    }


def build_dashboard_snapshot(
    *,
    closed_trades: list,
    all_time_stats: Optional[dict] = None,
    session_metrics: Optional[dict] = None,
    open_positions: Optional[list] = None,
    runtime: Optional[dict] = None,
    firebase_health: Optional[dict] = None,
    quota_status: Optional[dict] = None,
    market_health: Optional[dict] = None,
    learning_state: Optional[dict] = None,
    now: Optional[float] = None,
) -> dict:
    """
    Build canonical mobile dashboard snapshot.

    Args:
        closed_trades:    Recent closed trades
        all_time_stats:   All-time stats from system/stats
        session_metrics:  Current session metrics
        open_positions:   List of open positions (live)
        runtime:          Runtime state (trading_mode, safe_mode, etc)
        firebase_health:  Firebase health status
        quota_status:     Firestore quota usage
        market_health:    Market feed status
        learning_state:   LearningMonitor state
        now:              Current timestamp

    Returns:
        dict — snapshot ready for Firestore set()
    """
    if now is None:
        now = _time.time()

    closed_trades = closed_trades or []
    all_time_stats = all_time_stats or {}
    session_metrics = session_metrics or {}
    open_positions = open_positions or []
    runtime = runtime or {}
    firebase_health = firebase_health or {}
    quota_status = quota_status or {}
    market_health = market_health or {}
    learning_state = learning_state or {}

    # ── Runtime & Health ──────────────────────────────────────────────────────
    trading_mode = _safe_str(runtime.get("trading_mode"), "paper_live")
    paper_mode = bool(runtime.get("paper_mode", True))
    live_allowed = bool(runtime.get("live_allowed", False))
    paper_training_enabled = bool(runtime.get("paper_training_enabled", False))
    safe_mode = bool(runtime.get("safe_mode", False))
    safe_mode_reason = _safe_str(runtime.get("safe_mode_reason"))

    # Last heartbeat
    last_heartbeat_ts = _safe_float(runtime.get("last_heartbeat_ts"), 0.0)
    uptime_s = _safe_float(runtime.get("uptime_seconds"))

    # ── Market Data ───────────────────────────────────────────────────────────
    market_feed_status = _safe_str(market_health.get("feed_status"), "unknown")
    last_price_tick_ts = _safe_float(market_health.get("last_price_tick_ts"), 0.0)
    seconds_since_last_tick = None
    if last_price_tick_ts > 0:
        seconds_since_last_tick = round(now - last_price_tick_ts, 1)

    # ── Trading - All Time (from system/stats or session) ───────────────────────
    trades_total_all_time = _safe_int(all_time_stats.get("trades") or session_metrics.get("trades"))
    wins_all_time = _safe_int(all_time_stats.get("wins") or session_metrics.get("wins"))
    losses_all_time = _safe_int(all_time_stats.get("losses") or session_metrics.get("losses"))
    flats_all_time = _safe_int(all_time_stats.get("flats") or session_metrics.get("flats"))

    decisive_all_time = wins_all_time + losses_all_time
    winrate_all_time = round(wins_all_time / decisive_all_time, 4) if decisive_all_time > 0 else None

    # PnL (absolute values)
    net_pnl_abs = _safe_float(all_time_stats.get("net_pnl_abs") or session_metrics.get("net_pnl_abs"))
    unrealized_pnl_abs = _safe_float(session_metrics.get("unrealized_pnl_abs"))
    account_equity_abs = _safe_float(session_metrics.get("account_equity_abs"))

    # Drawdown
    drawdown_current_abs = _safe_float(session_metrics.get("drawdown_current_abs"))
    drawdown_current_pct = _safe_float(session_metrics.get("drawdown_current_pct"))
    drawdown_max_abs = _safe_float(all_time_stats.get("drawdown_max_abs"))
    drawdown_max_pct = _safe_float(all_time_stats.get("drawdown_max_pct"))

    # Risk metrics
    profit_factor = _safe_float(all_time_stats.get("profit_factor") or session_metrics.get("profit_factor"))
    expectancy_abs = _safe_float(all_time_stats.get("expectancy_abs") or session_metrics.get("expectancy_abs"))
    avg_win_abs = _safe_float(all_time_stats.get("avg_win_abs") or session_metrics.get("avg_win_abs"))
    avg_loss_abs = _safe_float(all_time_stats.get("avg_loss_abs") or session_metrics.get("avg_loss_abs"))
    best_trade_abs = _safe_float(all_time_stats.get("best_trade_abs") or session_metrics.get("best_trade_abs"))
    worst_trade_abs = _safe_float(all_time_stats.get("worst_trade_abs") or session_metrics.get("worst_trade_abs"))

    # Last trade (from closed trades)
    last_trade_ts = None
    last_trade_symbol = None
    for t in reversed(closed_trades):
        ts = _extract_closed_at(t)
        if ts > 0:
            last_trade_ts = ts
            last_trade_symbol = _safe_str(t.get("symbol"))
            break

    # ── Paper/Real/Replay Split ───────────────────────────────────────────────
    paper_train_trades, paper_live_trades, live_real_trades, replay_train_trades = _split_trades_by_mode(closed_trades)

    paper_train_metrics = _compute_mode_metrics(paper_train_trades, "paper_train")
    paper_live_metrics = _compute_mode_metrics(paper_live_trades, "paper_live")
    live_real_metrics = _compute_mode_metrics(live_real_trades, "live_real")
    replay_train_metrics = _compute_mode_metrics(replay_train_trades, "replay_train")

    # Open positions split
    paper_open_count = sum(1 for p in open_positions if _safe_str(p.get("mode"), "paper").lower() == "paper")
    real_open_count = sum(1 for p in open_positions if _safe_str(p.get("mode"), "paper").lower() == "live_real")
    total_open_count = len(open_positions)

    # ── Learning ──────────────────────────────────────────────────────────────
    lm_total_trades = _safe_int(learning_state.get("lm_total_trades"))
    lm_health_pct = _safe_float(learning_state.get("health_pct"))
    lm_confidence_momentum = _safe_str(learning_state.get("confidence_momentum"))
    cold_start_active = bool(learning_state.get("cold_start_active", False))
    learning_progress = _safe_float(learning_state.get("progress_to_ready"))

    # Paper training specific
    paper_train_entries_1h = _safe_int(session_metrics.get("paper_train_entries_1h"))
    paper_train_closed_1h = _safe_int(session_metrics.get("paper_train_closed_1h"))
    paper_train_learning_updates_1h = _safe_int(session_metrics.get("paper_train_learning_updates_1h"))

    # ── Signal Pipeline ───────────────────────────────────────────────────────
    signals_generated_count = _safe_int(session_metrics.get("signals_generated_count"))
    signals_filtered_count = _safe_int(session_metrics.get("signals_filtered_count"))
    signals_executed_count = _safe_int(session_metrics.get("signals_executed_count"))
    signals_blocked_count = _safe_int(session_metrics.get("signals_blocked_count"))
    last_signal_ts = _safe_float(session_metrics.get("last_signal_ts"))

    # ── Firebase / Quota ──────────────────────────────────────────────────────
    firebase_available = bool(firebase_health.get("available", True))
    firebase_read_degraded = bool(firebase_health.get("read_degraded", False))
    firebase_write_degraded = bool(firebase_health.get("write_degraded", False))
    reconciliation_verified = bool(firebase_health.get("reconciliation_verified", True))

    quota_reads = _safe_int(quota_status.get("reads_today"))
    quota_reads_limit = _safe_int(quota_status.get("reads_limit") or 50000)
    quota_writes = _safe_int(quota_status.get("writes_today"))
    quota_writes_limit = _safe_int(quota_status.get("writes_limit") or 20000)

    reads_pct = round(100 * quota_reads / max(quota_reads_limit, 1), 1) if quota_reads_limit > 0 else 0.0
    writes_pct = round(100 * quota_writes / max(quota_writes_limit, 1), 1) if quota_writes_limit > 0 else 0.0

    # ── Build Snapshot ────────────────────────────────────────────────────────
    snapshot = {
        "schema_version": "dashboard_snapshot_v1",
        "generated_at": now,
        "source": "cryptomaster_bot",

        # Bot runtime & health
        "runtime": {
            "trading_mode": trading_mode,
            "paper_mode": paper_mode,
            "live_allowed": live_allowed,
            "paper_training_enabled": paper_training_enabled,
            "safe_mode": safe_mode,
            "safe_mode_reason": safe_mode_reason,
            "last_heartbeat_ts": last_heartbeat_ts,
            "uptime_seconds": uptime_s,
        },

        # Market data
        "market": {
            "feed_status": market_feed_status,
            "last_price_tick_ts": last_price_tick_ts,
            "seconds_since_last_tick": seconds_since_last_tick,
        },

        # All-time trading metrics
        "trading": {
            "all_time": {
                "total_trades": trades_total_all_time,
                "wins": wins_all_time,
                "losses": losses_all_time,
                "flats": flats_all_time,
                "decisive_trades": decisive_all_time,
                "winrate": winrate_all_time,
                "net_pnl_abs": net_pnl_abs,
                "unrealized_pnl_abs": unrealized_pnl_abs,
                "account_equity_abs": account_equity_abs,
                "drawdown_current_abs": drawdown_current_abs,
                "drawdown_current_pct": drawdown_current_pct,
                "drawdown_max_abs": drawdown_max_abs,
                "drawdown_max_pct": drawdown_max_pct,
                "profit_factor": profit_factor,
                "expectancy_abs": expectancy_abs,
                "avg_win_abs": avg_win_abs,
                "avg_loss_abs": avg_loss_abs,
                "best_trade_abs": best_trade_abs,
                "worst_trade_abs": worst_trade_abs,
                "last_trade_ts": last_trade_ts,
                "last_trade_symbol": last_trade_symbol,
            },
            # Mode breakdown
            "paper_train": paper_train_metrics,
            "paper_live": paper_live_metrics,
            "live_real": live_real_metrics,
            "replay_train": replay_train_metrics,
            # Open positions
            "open": {
                "total_count": total_open_count,
                "paper_count": paper_open_count,
                "live_real_count": real_open_count,
            },
        },

        # Learning state
        "learning": {
            "lm_total_trades": lm_total_trades,
            "health_pct": lm_health_pct,
            "confidence_momentum": lm_confidence_momentum,
            "cold_start_active": cold_start_active,
            "progress_to_ready": learning_progress,
            "paper_train_entries_1h": paper_train_entries_1h,
            "paper_train_closed_1h": paper_train_closed_1h,
            "paper_train_learning_updates_1h": paper_train_learning_updates_1h,
        },

        # Signal pipeline
        "signals": {
            "generated_count": signals_generated_count,
            "filtered_count": signals_filtered_count,
            "executed_count": signals_executed_count,
            "blocked_count": signals_blocked_count,
            "last_signal_ts": last_signal_ts,
        },

        # Firebase health
        "firebase": {
            "available": firebase_available,
            "read_degraded": firebase_read_degraded,
            "write_degraded": firebase_write_degraded,
            "reconciliation_verified": reconciliation_verified,
            "quota": {
                "reads": quota_reads,
                "reads_limit": quota_reads_limit,
                "reads_pct": reads_pct,
                "writes": quota_writes,
                "writes_limit": quota_writes_limit,
                "writes_pct": writes_pct,
            },
        },

        # Metadata
        "metadata": {
            "window_trades_count": len(closed_trades),
            "note": "All timestamps are unix seconds. Use last_*_ts to detect freshness.",
        },
    }

    return snapshot
