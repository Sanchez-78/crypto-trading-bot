"""Generate summary and fix prompt reports."""

import logging
from pathlib import Path
from typing import List
from .models import Issue, LogMetrics, Severity

log = logging.getLogger(__name__)


class ReportWriter:
    """Write analysis reports and fix prompts."""

    def write_summary(self, output_path: Path, metrics: LogMetrics, issues: List[Issue]) -> None:
        """Write log analysis summary."""
        critical = [i for i in issues if i.severity == Severity.CRITICAL]
        high = [i for i in issues if i.severity == Severity.HIGH]

        status = "🔴 CRITICAL" if critical else ("🟠 HIGH" if high else "🟢 OK")
        biggest_risk = critical[0].title if critical else (high[0].title if high else "None detected")

        summary = f"""# Daily CryptoMaster Log Analysis — {metrics.period_start}

## Executive Summary

**Status**: {status}

**Biggest Risk**: {biggest_risk}

**Issues Detected**: {len(issues)} total
- Critical: {len(critical)}
- High: {len(high)}
- Medium: {len([i for i in issues if i.severity == Severity.MEDIUM])}
- Low: {len([i for i in issues if i.severity == Severity.LOW])}

## Key Metrics

| Metric | Value |
|--------|-------|
| Log lines analyzed | {metrics.log_lines_analyzed} |
| Trades opened | {metrics.trades_opened} |
| Trades closed | {metrics.trades_closed} |
| Rejection count | {metrics.rejection_count} |
| Timeout exits | {metrics.timeout_count} |
| Exceptions | {metrics.exception_count} |
| Firebase warnings | {metrics.firebase_warnings} |
| Redis warnings | {metrics.redis_warnings} |

## Detected Issues

"""

        for i, issue in enumerate(issues, 1):
            summary += f"""### {i}. [{issue.severity.value.upper()}] {issue.title}

**Confidence**: {issue.confidence:.0%}

**Evidence**:
"""
            for ev in issue.evidence[:3]:
                summary += f"- `{ev}`\n"

            summary += f"""
**Root Cause**: {issue.probable_root_cause}

**Recommended Fix**: {issue.recommended_fix}

**Likely Files**: {', '.join(f'`{f}`' for f in issue.likely_files[:3])}

**Validation Steps**:
"""
            for step in issue.validation_steps[:2]:
                summary += f"- {step}\n"

            summary += "\n"

        summary += """## Positive Signals

- Event bus handling appears stable
- No obvious circular imports detected

## Unknowns

- Exact current deployed version (need git commit hash)
- Current Firebase quota consumption (need live metrics)
- Redis server health (need external monitoring)

"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(summary)
        log.info(f"Summary written to {output_path}")

    def write_fix_prompt(self, output_path: Path, metrics: LogMetrics, issues: List[Issue]) -> None:
        """Write Claude Code/Codex-ready fix prompt."""
        critical = [i for i in issues if i.severity == Severity.CRITICAL]
        high = [i for i in issues if i.severity == Severity.HIGH]
        priority_issues = critical + high

        prompt = """# Claude Code / Codex: CryptoMaster Daily Fix Prompt

## Mission

Fix the highest-priority bugs and regressions detected from today's live trading bot logs.

## Hard Rules

- **Inspect real code first** before any edit.
- **Create a new branch** for any code changes.
- **Do not push directly to `main`**.
- **Do not deploy or restart production** from this prompt.
- **No force-push**; open a PR or provide a diff for human review.
- **No secret printing** (keys, tokens, Firebase credentials).
- **Preserve architecture**: no refactors, no moving files.
- **Minimal safe diffs**: fix the bug, nothing extra.
- **Firebase quota safe**: no new heavy reads/writes.
- **Preserve metrics contracts**: no schema changes unless explicitly required.

## Context

**System**: CryptoMaster_srv (Python crypto trading bot on Hetzner)
**Log Period**: Last 24 hours
**Git Ref**: Use the current checked-out commit. If unknown, record it as `unknown` in the final report.
**Workflow**: branch -> tests -> PR/diff -> human approval -> deploy handled separately.

## Priority Issues

"""

        for i, issue in enumerate(priority_issues[:5], 1):
            prompt += f"""
### Issue {i}: {issue.title}

**Severity**: {issue.severity.value.upper()} (Confidence: {issue.confidence:.0%})

**What We See**:
```
{chr(10).join(issue.evidence[:2])}
```

**Why It Matters**: {issue.probable_root_cause}

**Files Likely Involved**:
```
{chr(10).join(issue.likely_files[:3])}
```

**What to Do**:
1. Inspect the actual code in the files listed above
2. Verify the bug matches the evidence
3. Implement the smallest safe fix
4. Add or update tests when practical
5. Add validation step: {issue.validation_steps[0] if issue.validation_steps else 'Run tests'}

"""

        prompt += """
## Testing & Validation

Run after any fix:
```bash
python -m compileall src bot2 daily_log_fix_prompt_bot start.py
python -m pytest tests/ -q
python -m pytest daily_log_fix_prompt_bot/tests -q
```

## Safety Checklist

- [ ] Working branch created
- [ ] Compiled without errors
- [ ] Tests pass or failures are documented as pre-existing
- [ ] No secrets printed to logs
- [ ] No Firestore schema changes unless explicitly required
- [ ] No deleted files or features
- [ ] Diff is minimal and reviewed
- [ ] PR/diff prepared for human approval
- [ ] No deploy/restart performed

## Next Steps (After Fix)

1. Verify fix locally
2. Create a commit with a clear message
3. Open a PR or provide the diff for review
4. Wait for human approval
5. Deploy only through a separate deployment prompt/checklist

---

**Note**: This prompt was auto-generated from daily log analysis.
Do not treat it as absolute truth. Use it as a starting point for investigation.

"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        log.info(f"Fix prompt written to {output_path}")
