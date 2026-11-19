"""V10.28+: Readiness Monitoring Loop
Periodic monitoring that checks if bot is ready for real trading.
Integrates with dashboard for real-time readiness display.
"""
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
    """REAL-trading readiness metrics are not collected (2026-11-18).

    This module is only imported by the dashboard process. Importing
    paper_trade_executor there read the bot's in-memory state of a *different*
    process (always empty) and executed its module-level load_dotenv(), which
    the dashboard sandbox denies (InaccessiblePaths=/opt/cryptomaster/.env) --
    the source of the recurring [METRICS_COLLECTION_ERROR] Permission denied.
    The operating policy is PAPER only, so there is nothing to evaluate here;
    trade metrics come from the dashboard read model (/api/dashboard/metrics).
    """
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


# No auto-start on import (2026-11-18): get_current_metrics() never yields
# metrics in the dashboard process, so the thread could only spin. Importing this
# module has no side effects; start_monitoring_thread() stays for explicit callers.
