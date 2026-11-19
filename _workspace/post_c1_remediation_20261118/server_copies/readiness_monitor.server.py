"""V10.28+: Readiness Monitoring Loop
Periodic monitoring that checks if bot is ready for real trading.
Integrates with dashboard for real-time readiness display.
"""
import os
import time
import logging
import threading
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

_last_readiness_check = 0
_check_interval_s = 300  # Check every 5 minutes

_monitoring_thread = None
_should_stop = False


def get_current_metrics():
    """Collect current trading metrics from available sources."""
    try:
        from src.services.paper_trade_executor import (
            _POSITIONS, _closed_trades_today, evaluate_paper_tp_sl_exits
        )

        # Count positions
        closed_count = len(_closed_trades_today) if hasattr(_closed_trades_today, '__len__') else 0
        open_count = len(_POSITIONS) if hasattr(_POSITIONS, '__len__') else 0

        if closed_count == 0:
            return None

        # Calculate WR and P&L from closed trades
        wins = 0
        total_pnl = 0.0

        for trade in _closed_trades_today:
            pnl = trade.get("pnl_usd", 0.0)
            total_pnl += pnl
            if pnl > 0:
                wins += 1

        wr_pct = (wins / closed_count * 100) if closed_count > 0 else 0.0

        # Calculate profit factor
        winning_trades_sum = 0.0
        losing_trades_sum = 0.0

        for trade in _closed_trades_today:
            pnl = trade.get("pnl_usd", 0.0)
            if pnl > 0:
                winning_trades_sum += pnl
            else:
                losing_trades_sum += abs(pnl)

        pf = winning_trades_sum / losing_trades_sum if losing_trades_sum > 0 else 0.0

        return {
            "closed_trades": closed_count,
            "open_positions": open_count,
            "win_rate_pct": wr_pct,
            "profit_factor": pf,
            "net_pnl": total_pnl,
        }
    except Exception as e:
        log.error(f"[METRICS_COLLECTION_ERROR] {e}")
        return None


def run_readiness_check():
    """Execute readiness check if interval elapsed."""
    global _last_readiness_check

    now = time.time()
    if now - _last_readiness_check < _check_interval_s:
        return  # Not time yet

    try:
        from src.services.trading_readiness_checker import check_readiness

        # Get current metrics
        metrics = get_current_metrics()
        if not metrics:
            return

        # Run readiness check
        result = check_readiness(metrics)

        # Log result
        if result.get("is_ready_for_trading"):
            log.info(
                "[READINESS_PASSED] score=%.1f ready_for_real_trading=true",
                result.get("readiness_score", 0)
            )
        else:
            blockers = result.get("blocker_reasons", [])
            log.warning(
                "[READINESS_CHECK] score=%.1f blockers=%d reasons=%s",
                result.get("readiness_score", 0),
                len(blockers),
                " | ".join(blockers[:3])  # Log first 3 blockers
            )

        _last_readiness_check = now

    except Exception as e:
        log.error(f"[READINESS_CHECK_ERROR] {e}", exc_info=True)


def start_monitoring_thread():
    """Start background monitoring thread."""
    global _monitoring_thread, _should_stop

    if _monitoring_thread and _monitoring_thread.is_alive():
        return  # Already running

    _should_stop = False

    def monitor_loop():
        while not _should_stop:
            try:
                run_readiness_check()
                time.sleep(60)  # Check every minute
            except Exception as e:
                log.error(f"[MONITOR_THREAD_ERROR] {e}")
                time.sleep(5)

    _monitoring_thread = threading.Thread(target=monitor_loop, daemon=True)
    _monitoring_thread.start()
    log.info("[READINESS_MONITOR_STARTED] Monitoring thread running")


def stop_monitoring_thread():
    """Stop background monitoring thread."""
    global _should_stop
    _should_stop = True


# Auto-start on module import if in paper trading mode
if os.getenv("TRADING_MODE") in ["paper_train", "paper_live"]:
    try:
        start_monitoring_thread()
    except Exception as e:
        log.warning(f"Could not start readiness monitoring: {e}")
