"""
Disk retry mechanism - periodically attempt to save analysis results if initial save failed.

If disk is unavailable when bot runs at 08:00 UTC, this module will:
1. Keep analysis results in memory
2. Try to save to disk every 2 hours
3. Once saved, clear memory cache

Useful for temporary disk outages (unmounted, permission issues, full disk).
"""

import threading
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
import time

log = logging.getLogger(__name__)

_pending_save_queue = []  # List of (timestamp, metrics, issues, analysis_data) tuples
_retry_thread: Optional[threading.Thread] = None
_retry_running = False
_retry_lock = threading.Lock()

RETRY_INTERVAL_SECONDS = 7200  # 2 hours
MAX_RETRIES = 12  # 24 hours total (12 × 2h)


def queue_for_retry(
    report_dir: Path,
    metrics_dict: dict,
    issues: list,
    events: list,
    sanitized_logs: str,
) -> None:
    """Queue analysis results for retry save to disk."""
    global _retry_running
    with _retry_lock:
        item = {
            "queued_at": datetime.now().isoformat(),
            "report_dir": str(report_dir),
            "metrics": metrics_dict,
            "issues": [issue.to_dict() for issue in issues],
            "events_count": len(events),
            "logs_size": len(sanitized_logs),
            "retry_count": 0,
        }
        _pending_save_queue.append(item)
        log.warning(f"Queued analysis for retry save (queue size: {len(_pending_save_queue)})")

        if not _retry_running:
            _retry_running = True
            start_retry_thread()


def start_retry_thread() -> None:
    """Start background thread for periodic retry saves."""
    global _retry_thread
    _retry_thread = threading.Thread(target=_retry_loop, daemon=True, name="DiskRetryThread")
    _retry_thread.start()
    log.info("Started disk retry thread (2h interval)")


def _retry_loop() -> None:
    """Background thread that periodically tries to save queued items."""
    global _retry_running
    while _retry_running:
        time.sleep(RETRY_INTERVAL_SECONDS)  # Wait 2 hours before retry

        with _retry_lock:
            if not _pending_save_queue:
                _retry_running = False
                log.info("Disk retry queue empty, stopping retry thread")
                break

            # Try to save each queued item
            still_pending = []
            for item in _pending_save_queue:
                item["retry_count"] += 1
                if _try_save_item(item):
                    log.info(
                        f"✅ Successfully saved queued analysis "
                        f"(queued: {item['queued_at']}, retry: {item['retry_count']})"
                    )
                else:
                    if item["retry_count"] < MAX_RETRIES:
                        log.warning(
                            f"⚠️  Retry #{item['retry_count']}/{MAX_RETRIES} failed, "
                            f"will retry in 2h"
                        )
                        still_pending.append(item)
                    else:
                        log.error(
                            f"❌ Gave up saving queued analysis after {MAX_RETRIES} retries "
                            f"(24 hours). Disk may be permanently unavailable."
                        )

            _pending_save_queue[:] = still_pending


def _try_save_item(item: dict) -> bool:
    """Attempt to save a single queued analysis item. Returns True on success."""
    try:
        report_dir = Path(item["report_dir"])

        # Try to create directory
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError, IOError) as e:
            log.debug(f"Cannot create report dir {report_dir}: {e}")
            return False

        # Try to write summary JSON
        try:
            summary_path = report_dir / "analysis_retry.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump({
                    "original_queue_time": item["queued_at"],
                    "saved_at": datetime.now().isoformat(),
                    "retry_count": item["retry_count"],
                    "metrics": item["metrics"],
                    "issues_count": len(item["issues"]),
                    "events_analyzed": item["events_count"],
                }, f, indent=2)
            log.info(f"Saved retry analysis to {summary_path}")
            return True
        except (OSError, PermissionError, IOError) as e:
            log.debug(f"Cannot write to {report_dir}: {e}")
            return False

    except Exception as e:
        log.debug(f"Unexpected error in _try_save_item: {e}")
        return False


def get_pending_queue_stats() -> dict:
    """Get stats about pending saves."""
    with _retry_lock:
        if not _pending_save_queue:
            return {"pending": 0, "oldest": None}

        oldest = _pending_save_queue[0]["queued_at"]
        return {
            "pending": len(_pending_save_queue),
            "oldest": oldest,
            "hours_since_oldest": (datetime.now() - datetime.fromisoformat(oldest)).total_seconds() / 3600,
        }


def stop_retry_thread() -> None:
    """Gracefully stop retry thread."""
    global _retry_running
    _retry_running = False
    if _retry_thread:
        _retry_thread.join(timeout=5)
    log.info(f"Stopped disk retry thread ({len(_pending_save_queue)} items still pending)")
