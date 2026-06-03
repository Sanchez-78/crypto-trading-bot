"""Paper Learning Logger — Emit learning metrics to runtime logs

Periodically logs:
  - Segments with samples
  - Win rate & PF per segment (top 3)
  - Rolling metrics
  - Learning progress to READY
  - Feedback readiness verdict

Usage:
  from src.services.paper_learning_logger import PaperLearningLogger
  logger = PaperLearningLogger()
  logger.log_status()  # Call periodically (every 10min)
"""
import logging
import time
from pathlib import Path
from typing import Dict, Optional
import json

log = logging.getLogger(__name__)

class PaperLearningLogger:
    """Logs paper learning metrics to runtime logs."""

    def __init__(self, learning_state_file: Optional[str] = None):
        self.learning_state_file = learning_state_file or "server_local_backups/paper_adaptive_learning_state.json"
        self.last_log_time = 0.0
        self.log_interval_s = 600  # Log every 10 minutes

    def load_learning_state(self) -> Dict:
        """Load learning state from file."""
        try:
            path = Path(self.learning_state_file)
            if not path.exists():
                return {}

            with open(path) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"[PAPER_LEARNING_LOGGER] Failed to load state: {e}")
            return {}

    def should_log_now(self) -> bool:
        """Check if enough time has passed since last log."""
        now = time.time()
        if now - self.last_log_time >= self.log_interval_s:
            self.last_log_time = now
            return True
        return False

    def log_status(self) -> None:
        """Emit paper learning status to runtime logs."""
        if not self.should_log_now():
            return

        state = self.load_learning_state()
        if not state:
            return

        # Count segments
        segments = {}
        for key, data in state.items():
            if not isinstance(data, dict):
                continue
            n = data.get("n", 0)
            if n > 0:
                segments[key] = data

        if not segments:
            return

        # Calculate stats
        total_n = sum(s.get("n", 0) for s in segments.values())
        ready_count = sum(1 for s in segments.values() if s.get("n", 0) >= 20)

        # Top segments by PF
        top_segments = sorted(
            segments.items(),
            key=lambda x: x[1].get("rolling50_pf", 0),
            reverse=True
        )[:3]

        # Readiness
        if total_n >= 50:
            readiness = "READY"
        elif total_n >= 30:
            readiness = "ON_TRACK"
        else:
            readiness = "EARLY"

        # Average PF
        avg_pf = sum(s.get("rolling50_pf", 1.0) for s in segments.values()) / len(segments) if segments else 1.0

        # Log metrics
        segments_list = [f"{s[0]}(n={s[1].get('n',0)})" for s in top_segments]
        segments_str = " | ".join(segments_list) if segments_list else "none"

        log.info(
            f"[PAPER_LEARNING_METRICS] "
            f"segments={len(segments)} ready={ready_count} "
            f"total_samples={total_n}/50 "
            f"avg_pf={avg_pf:.2f} "
            f"readiness={readiness} "
            f"top_3=[{segments_str}]"
        )

        # Detailed breakdown (once per hour, separate log)
        if time.time() % 3600 < self.log_interval_s:
            self._log_detailed_status(segments, total_n, ready_count, avg_pf)

    def _log_detailed_status(self, segments: Dict, total_n: int, ready_count: int, avg_pf: float) -> None:
        """Log detailed paper learning status."""
        log.info("╔════════════════════════════════════════════════════════════════╗")
        log.info("║ PAPER LEARNING STATUS (Periodic Detailed Snapshot)")
        log.info("╚════════════════════════════════════════════════════════════════╝")

        # Overall
        log.info(f"Total segments: {len(segments)}")
        log.info(f"Ready (n>=20): {ready_count}")
        log.info(f"Samples collected: {total_n}/50")
        log.info(f"Avg profit factor: {avg_pf:.2f}")
        log.info("")

        # Top performers
        top_by_pf = sorted(
            segments.items(),
            key=lambda x: x[1].get("rolling50_pf", 0),
            reverse=True
        )[:3]

        log.info("Top performers (by PF):")
        for key, data in top_by_pf:
            pf = data.get("rolling50_pf", 0)
            n = data.get("n", 0)
            wr = (data.get("wins", 0) / n * 100) if n > 0 else 0
            log.info(f"  {key}: n={n} PF={pf:.2f} WR={wr:.0f}%")

        # Rolling metrics
        rolling20 = sum(s.get("rolling20_pf", 1.0) for s in segments.values()) / len(segments) if segments else 1.0
        rolling50 = avg_pf
        rolling100 = sum(s.get("rolling100_pf", 1.0) for s in segments.values()) / len(segments) if segments else 1.0

        log.info("")
        log.info("Rolling metrics:")
        log.info(f"  Rolling20: {rolling20:.2f}")
        log.info(f"  Rolling50: {rolling50:.2f}")
        log.info(f"  Rolling100: {rolling100:.2f}")

        # Readiness
        if total_n >= 50:
            log.info("")
            log.info("✅ LEARNING READY — Can enable feedback & make decisions")
        elif total_n >= 30:
            log.info("")
            log.info(f"🟡 ON TRACK — {total_n}/50 samples ({total_n*2:.0f}% progress)")
        else:
            log.info("")
            log.info(f"🔄 EARLY STAGE — {total_n}/50 samples ({total_n*2:.0f}% progress)")

        log.info("╚════════════════════════════════════════════════════════════════╝")

# Global singleton
_logger = None

def get_paper_learning_logger() -> PaperLearningLogger:
    """Get or create the global logger."""
    global _logger
    if _logger is None:
        _logger = PaperLearningLogger()
    return _logger

def log_paper_learning_status() -> None:
    """Convenience function to log paper learning status."""
    get_paper_learning_logger().log_status()
