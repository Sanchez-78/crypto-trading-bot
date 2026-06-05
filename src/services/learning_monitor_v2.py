"""
Learning Monitor V10.15m - Periodic learning cycle monitoring

Runs every 5 minutes:
1. Analyze trades in database
2. Print learning report
3. Adjust parameters if needed
4. Recommend config changes
"""

import threading
import time
import logging
from src.services.learning_optimizer import get_optimizer
from src.services.parameter_tuner import get_tuner

log = logging.getLogger(__name__)

class LearningMonitor:
    """Monitor learning progress and auto-tune parameters"""

    def __init__(self, check_interval_seconds: int = 300):  # Every 5 minutes
        self.check_interval = check_interval_seconds
        self.running = False
        self.thread = None

    def start(self):
        """Start monitor thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        log.info(f"[LEARNING_MONITOR] Started (check every {self.check_interval} seconds)")

    def stop(self):
        """Stop monitor thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        log.info("[LEARNING_MONITOR] Stopped")

    def _monitor_loop(self):
        """Continuous monitoring loop"""
        while self.running:
            try:
                self._run_learning_cycle()
            except Exception as e:
                log.error(f"[LEARNING_MONITOR_ERROR] Cycle failed: {e}")

            # Sleep and check if still running
            for _ in range(int(self.check_interval)):
                if not self.running:
                    break
                time.sleep(1)

    def _run_learning_cycle(self):
        """Run one learning cycle"""
        optimizer = get_optimizer()
        tuner = get_tuner()

        # 1. Print learning report
        report = optimizer.get_learning_report()
        log.info(report)

        # 2. Run parameter tuning
        changes = tuner.run_tuning_cycle()

        # 3. Notify if changes made
        if changes:
            log.warning(f"[LEARNING_CYCLE_COMPLETE] {len(changes)} parameter changes made (restart needed)")


# Global monitor
_monitor = None

def get_monitor() -> LearningMonitor:
    """Get global monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = LearningMonitor(check_interval_seconds=300)
    return _monitor


def start_learning_monitor():
    """Start the monitor"""
    monitor = get_monitor()
    monitor.start()


def stop_learning_monitor():
    """Stop the monitor"""
    monitor = get_monitor()
    monitor.stop()
