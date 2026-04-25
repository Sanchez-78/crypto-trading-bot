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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


def run_daily_analysis() -> Path:
    """Run the complete daily log analysis."""
    config = load_config()
    report_dir = get_report_dir(config)
    log.info(f"Report directory: {report_dir}")

    # Step 1: Fetch logs
    log.info("Fetching logs from server...")
    fetcher = LogFetcher(config)
    raw_logs = fetcher.fetch_logs()
    if not raw_logs:
        log.error("No logs fetched; aborting")
        return report_dir

    # Save raw logs
    raw_log_path = report_dir / "raw_logs.txt"
    with open(raw_log_path, "w", encoding="utf-8") as f:
        f.write(raw_logs)
    log.info(f"Raw logs saved to {raw_log_path}")

    # Step 2: Sanitize logs
    log.info("Sanitizing logs...")
    sanitizer = Sanitizer()
    sanitized_logs = sanitizer.sanitize(raw_logs)

    # Step 3: Parse logs
    log.info("Parsing logs...")
    parser = LogParser()
    parse_result = parser.parse(sanitized_logs)
    events = parse_result["events"]
    metrics_dict = parse_result["metrics"]

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

    # Step 5: Save analysis artifacts
    log.info("Saving analysis artifacts...")

    # Save detected issues
    issues_path = report_dir / "detected_issues.json"
    with open(issues_path, "w") as f:
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

    # Save metadata
    metadata_path = report_dir / "run_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump({
            "run_date": datetime.now().isoformat(),
            "config": {
                "service": config.service_name,
                "lookback_hours": config.log_lookback_hours,
            },
            "stats": {
                "log_lines": len(sanitized_logs.split("\n")),
                "events_detected": len(events),
                "issues_detected": len(issues),
            },
        }, f, indent=2)

    log.info(f"Analysis complete. Report saved to {report_dir}")
    return report_dir


if __name__ == "__main__":
    report_dir = run_daily_analysis()
    print(f"\n✅ Daily analysis complete: {report_dir}\n")
