"""Daily log analysis bot entry point."""

import logging
import json
from pathlib import Path
from datetime import datetime
from .config import load_config, get_report_dir
from .log_fetcher import LogFetcher
from .sanitizer import Sanitizer
from .parser import LogParser
from .issue_detector import IssueDetector
from .models import AnalysisResult, LogMetrics
from .report_writer import ReportWriter
from .disk_retry import queue_for_retry, get_pending_queue_stats
from .health_reporter import build_hetzner_health, write_health_reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def run_daily_analysis() -> Path:
    """Run the complete daily log analysis."""
    config = load_config()

    # Try to create report directory; graceful fallback if disk unavailable
    try:
        report_dir = get_report_dir(config)
        log.info(f"Report directory: {report_dir}")
        disk_available = True
    except (OSError, IOError, PermissionError) as e:
        log.error(f"❌ Local disk unavailable or not writable: {e}")
        log.error("Continuing analysis in memory; reports will NOT be saved")
        report_dir = Path(config.local_report_dir) / "FAILED"  # Placeholder
        disk_available = False

    # Step 1: Fetch logs
    log.info("Fetching logs from server...")
    fetcher = LogFetcher(config)
    raw_logs = fetcher.fetch_logs()
    log_source = getattr(fetcher, "last_source", "unknown")
    if log_source == "none":
        log_source = "unknown"

    if not raw_logs:
        log.error("No logs fetched; writing UNKNOWN health report and aborting")
        health = build_hetzner_health(
            logs="",
            service_name=config.service_name,
            log_source=log_source or "empty",
            generated_at=datetime.now().isoformat(),
        )
        if disk_available:
            write_health_reports(report_dir, config.local_report_dir, health)
        return report_dir

    # Step 2: Sanitize logs BEFORE writing anything to disk.
    # P0 safety: raw server logs can contain secrets. Do not persist them by default.
    log.info("Sanitizing logs...")
    sanitizer = Sanitizer()
    sanitized_logs = sanitizer.sanitize(raw_logs) if config.sanitize_secrets else raw_logs

    if disk_available:
        try:
            sanitized_log_path = report_dir / "sanitized_logs.txt"
            _write_text(sanitized_log_path, sanitized_logs)
            log.info(f"Sanitized logs saved to {sanitized_log_path}")

            if config.save_unsanitized_raw_logs:
                raw_log_path = report_dir / "raw_logs.txt"
                _write_text(raw_log_path, raw_logs)
                log.warning(
                    "Unsanitized raw logs saved because SAVE_UNSANITIZED_RAW_LOGS=true: %s",
                    raw_log_path,
                )
        except (OSError, IOError, PermissionError) as e:
            log.error(f"⚠️  Failed to write logs to disk: {e}")
            disk_available = False
    else:
        log.warning("⚠️  Skipping log save (disk unavailable)")

    # Step 3: Parse logs
    log.info("Parsing logs...")
    parser = LogParser()
    parse_result = parser.parse(sanitized_logs)
    events = parse_result["events"]
    metrics_dict = parse_result["metrics"]

    # Step 3b: Build Hetzner health report from sanitized logs
    log.info("Building Hetzner health report...")
    health = build_hetzner_health(
        logs=sanitized_logs,
        service_name=config.service_name,
        log_source=log_source,
        generated_at=datetime.now().isoformat(),
    )
    log.info("Health status: %s", health["status"])

    # Step 4: Detect issues
    log.info("Detecting issues...")
    detector = IssueDetector()
    issues = detector.detect(events, metrics_dict, sanitized_logs)
    log.info(f"Detected {len(issues)} issues")

    # Build metrics object
    metrics = LogMetrics(
        log_lines_analyzed=len(sanitized_logs.split("\n")),
        period_start=datetime.now().isoformat(),
        period_end=datetime.now().isoformat(),
        trades_opened=metrics_dict.get("trades_opened", 0),
        trades_closed=metrics_dict.get("trades_closed", 0),
        rejection_count=metrics_dict.get("rejections", 0),
        timeout_count=metrics_dict.get("timeouts", 0),
        exception_count=metrics_dict.get("exceptions", 0),
        firebase_warnings=metrics_dict.get("firebase_warnings", 0),
        redis_warnings=metrics_dict.get("redis_warnings", 0),
    )

    # Step 5: Save analysis artifacts (skip if disk unavailable)
    if disk_available:
        log.info("Saving analysis artifacts...")
        try:
            # Save detected issues
            issues_path = report_dir / "detected_issues.json"
            with open(issues_path, "w", encoding="utf-8") as f:
                json.dump([issue.to_dict() for issue in issues], f, indent=2)
            log.info(f"Issues saved to {issues_path}")

            # Step 6: Generate summary and prompt
            log.info("Generating summary and fix prompt...")
            writer = ReportWriter()

            summary_path = report_dir / "log_summary.md"
            writer.write_summary(summary_path, metrics, issues)
            log.info(f"Summary written to {summary_path}")

            prompt_path = report_dir / "fix_prompt_final.md"
            writer.write_fix_prompt(prompt_path, metrics, issues)
            log.info(f"Fix prompt written to {prompt_path}")

            # Write Hetzner health reports
            write_health_reports(report_dir, config.local_report_dir, health)

            # Save metadata
            metadata_path = report_dir / "run_metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump({
                    "run_date": datetime.now().isoformat(),
                    "config": {
                        "service": config.service_name,
                        "lookback_hours": config.log_lookback_hours,
                        "sanitized_logs_saved": True,
                        "raw_logs_saved": bool(config.save_unsanitized_raw_logs),
                    },
                    "stats": {
                        "log_lines": len(sanitized_logs.split("\n")),
                        "events_detected": len(events),
                        "issues_detected": len(issues),
                    },
                    "health": {
                        "status": health["status"],
                        "log_source": health["log_source"],
                        "boot_version_seen": health["boot_version_seen"],
                        "trading_mode": health["trading_mode"],
                    },
                }, f, indent=2)
            log.info(f"Analysis complete. Report saved to {report_dir}")
        except (OSError, IOError, PermissionError) as e:
            log.error(f"⚠️  Failed to write analysis artifacts: {e}")
            log.warning("Queuing analysis for periodic retry save (every 2 hours)")
            queue_for_retry(report_dir, metrics_dict, issues, events, sanitized_logs)
    else:
        log.warning("⚠️  Skipping artifact save (disk unavailable)")
        log.warning(f"❌ CRITICAL: Local disk at '{config.local_report_dir}' is not accessible")
        log.warning("Queuing analysis for periodic retry save (every 2 hours)")
        log.warning("Bot will attempt to save every 2h; check disk status:")
        log.warning("  - df -h                    (check disk space)")
        log.warning("  - ls -la reports/          (check directory permissions)")
        log.warning("  - mount | grep reports     (check mount status)")
        queue_for_retry(report_dir, metrics_dict, issues, events, sanitized_logs)

    # Report retry queue status if items pending
    pending_stats = get_pending_queue_stats()
    if pending_stats["pending"] > 0:
        log.warning(
            f"⏳ {pending_stats['pending']} analysis result(s) pending save "
            f"(oldest: {pending_stats['hours_since_oldest']:.1f}h ago)"
        )

    return report_dir


if __name__ == "__main__":
    try:
        report_dir = run_daily_analysis()
        if report_dir.name == "FAILED":
            print(f"\n[WARNING] Daily analysis completed but disk unavailable - reports NOT saved\n")
        else:
            print(f"\n[OK] Daily analysis complete: {report_dir}\n")
    except Exception as e:
        log.error(f"FATAL: Daily analysis failed: {type(e).__name__}: {e}", exc_info=True)
        print(f"\n[ERROR] Daily analysis failed: {e}\n")
        exit(1)
