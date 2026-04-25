# Daily Log Fix Prompt Bot

Automated daily analysis of CryptoMaster trading bot logs that detects regressions, bugs, and risks, then generates high-quality fix prompts for Claude Code / Codex.

## Features

- **Log Fetching**: Connects to Hetzner via SSH, pulls logs from journalctl or file glob
- **Sanitization**: Redacts API keys, tokens, passwords, IPs before analysis
- **Event Parsing**: Extracts signals, decisions, trades, rejections, exceptions from logs
- **Issue Detection**: Rule-based 8+ detectors for common trading bot problems
- **Report Generation**: Markdown summaries + Claude Code-ready fix prompts
- **Safe by Default**: No auto-deploy, no secret leaking, preserves existing code

## Installation

```bash
cd daily_log_fix_prompt_bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Hetzner details
```

## Usage

### Manual Run

```bash
python -m src.daily_log_fix_prompt_bot.main
```

Outputs to `reports/YYYY-MM-DD/` with:
- `raw_logs.txt` — fetched and sanitized logs
- `detected_issues.json` — machine-readable issues
- `log_summary.md` — human-readable summary
- `fix_prompt_final.md` — Claude Code/Codex prompt
- `run_metadata.json` — timestamps, stats

### Scheduled (systemd timer)

```bash
sudo cp systemd/daily-log-fix-prompt-bot.service /etc/systemd/system/
sudo cp systemd/daily-log-fix-prompt-bot.timer /etc/systemd/system/
sudo systemctl enable --now daily-log-fix-prompt-bot.timer
```

Runs daily at 06:00 UTC.

## Detectors

1. **NO_SIGNALS** — No signal generation for 24h → market feed stalled
2. **HIGH_REJECTION_RATE** — >80% decisions rejected → threshold/gate issue
3. **TIMEOUT_OVERLOAD** — >30% exits via timeout → hold window too long
4. **NEGATIVE_OR_ZERO_PNL** — All losses or excessive zeros → PnL bug
5. **VERSION_MISMATCH** — Multiple versions in logs → inconsistent deployment
6. **FIREBASE_QUOTA_RISK** — Heavy warnings → quota exhaustion
7. **REDIS_FAILURES** — Connection errors → Redis down or network issue
8. **UNCAUGHT_EXCEPTIONS** — Tracebacks → code bug needing fix

## Configuration

See `.env.example` for all options. Key settings:

- `HETZNER_HOST`, `HETZNER_USER`, `SSH_KEY_PATH` — SSH credentials
- `LOG_LOOKBACK_HOURS` — how far back to analyze (default 24)
- `SANITIZE_SECRETS` — redact API keys before processing (always True for safety)
- `ENABLE_AUTO_FIX` — **disabled by default** for safety

## Testing

```bash
pytest tests/ -v
```

## Architecture

```
main.py
  ├─ config.py              (settings from .env)
  ├─ log_fetcher.py         (SSH → journalctl/files)
  ├─ sanitizer.py           (regex redaction)
  ├─ parser.py              (extract events)
  ├─ issue_detector.py      (rule-based detection)
  ├─ report_writer.py       (markdown/JSON output)
  └─ models.py              (Issue, LogMetrics)
```

## Safety

- ✅ No credentials in logs (sanitized)
- ✅ No changes to live code (reports only)
- ✅ No Firestore writes (read-only analysis)
- ✅ No auto-deploy (manual review required)
- ✅ No feature deletion (conservative fixes only)

## Example Output

After running, check `reports/2026-04-25/log_summary.md`:

```markdown
# Daily CryptoMaster Log Analysis — 2026-04-25

## Executive Summary

**Status**: 🟠 HIGH

**Issues Detected**: 3 total
- Critical: 0
- High: 2
- Medium: 1

## Detected Issues

### 1. [HIGH] High rejection rate: 85% of decisions rejected

Evidence:
- Rejections: 68/80

Root Cause: EV threshold too high...
```

Then use `fix_prompt_final.md` in Claude Code for targeted fixes.

## License

Internal tool for CryptoMaster_srv.
