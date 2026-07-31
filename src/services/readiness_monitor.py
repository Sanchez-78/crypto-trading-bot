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
    """Collect readiness metrics from the authoritative dashboard read model.

    The executor used to expose an in-memory ``_closed_trades_today`` list.
    That private symbol was removed when closed trades became durable in
    ``cache.sqlite``.  Importing it here made the dashboard readiness loop fail
    once per minute and also made metrics process-local.  Reuse the same
    snapshot as the dashboard so both processes report one durable definition.
    """
    try:
        from src.services.dashboard_read_model import get_metrics

        snapshot = get_metrics()
        headline = snapshot.get("headline") or {}
        closed_count = int(
            headline.get("n")
            or snapshot.get("session_closed_trades")
            or 0
        )
        open_count = int(snapshot.get("open_positions") or 0)

        if closed_count == 0:
            return None

        return {
            "closed_trades": closed_count,
            "open_positions": open_count,
            "win_rate_pct": float(headline.get("win_rate_pct") or 0.0),
            "profit_factor": float(
                headline.get("profit_factor_pct_basis") or 0.0
            ),
            "net_pnl": float(headline.get("net_pnl_usd") or 0.0),
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
