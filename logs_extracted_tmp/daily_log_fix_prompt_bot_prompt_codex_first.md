# DAILY LOG ANALYZER BOT → FIX PROMPT GENERATOR FOR CODEX / CLAUDE CODE

## ROLE
You are a senior backend/DevOps/quant trading systems engineer. Build a production-safe Python bot that runs once per day, connects to a Hetzner Linux server, analyzes CryptoMaster trade-bot logs, detects regressions/bugs/risk issues, and generates a high-quality compressed fix prompt for Codex/Claude Code. After generating the prompt, the bot must self-review it, optimize it, and append concrete implementation suggestions.

## PROJECT CONTEXT
Existing project: `CryptoMaster_srv`, Python crypto trading bot, event-driven architecture, running live on Hetzner/systemd. Logs may come from:
- `journalctl -u cryptomaster`
- `/var/log/cryptomaster/*.log`
- app-specific stdout logs
- optional exported log files copied locally

Important known system concepts:
- RDE / realtime_decision_engine
- signal_generator
- trade_executor
- portfolio/risk engine
- learning_monitor
- Firebase/Firestore metrics
- EV, WR, score, regime, streak penalties, velocity guard, pair block, fast fail
- open positions, exits, TP/SL/trailing/timeout
- canonical decision logs
- rejection reasons
- version tags such as `RDE[v10.x]`, `coherence[v10.x]`, `V10.13...`
- production safety: no direct live code mutation, no auto-deploy without explicit human approval

## OBJECTIVE
Create a standalone helper bot named:

`daily_log_fix_prompt_bot`

It must:
1. Run once daily.
2. Fetch last 24h logs from Hetzner.
3. Parse and summarize important trading/system events.
4. Detect anomalies, regressions, contradictions, and high-impact improvement opportunities.
5. Produce a Claude Code/Codex-ready fix prompt as a Markdown file.
6. Run a second-pass self-review over that generated prompt.
7. Create an optimized final prompt with:
   - root-cause hypotheses
   - exact files/functions likely involved
   - implementation tasks
   - tests/validation commands
   - rollback/safety rules
   - acceptance criteria
8. Save artifacts locally and optionally on the server.
9. Never change trading bot code automatically unless explicitly enabled by config and confirmed manually.

## OUTPUT FILES
Every daily run must create a dated folder:

`reports/YYYY-MM-DD/`

Inside:
- `raw_logs.txt` — fetched logs, sanitized if needed
- `log_summary.md` — structured analysis summary
- `detected_issues.json` — machine-readable issues
- `fix_prompt_draft.md` — first generated prompt
- `fix_prompt_final.md` — reviewed/optimized prompt for Claude Code/Codex
- `run_metadata.json` — timestamps, server, command used, line counts, errors

## RECOMMENDED TECH STACK
- Python 3.11+
- `paramiko` for SSH, or subprocess `ssh` fallback
- `pydantic` or dataclasses for config/schema
- `python-dotenv` for local secrets
- `rich` for terminal output
- `pytest` for parser tests
- optional: OpenAI/Anthropic API adapter, but must work without API by using deterministic rule-based prompt generation
- scheduling: systemd timer preferred; cron fallback

## CONFIG
Create `.env.example`:

```env
HETZNER_HOST=1.2.3.4
HETZNER_PORT=22
HETZNER_USER=root
SSH_KEY_PATH=~/.ssh/id_ed25519
SERVICE_NAME=cryptomaster
LOG_LOOKBACK_HOURS=24
LOCAL_REPORT_DIR=reports
PROJECT_ROOT=/opt/CryptoMaster_srv
REMOTE_LOG_GLOB=/var/log/cryptomaster/*.log
USE_JOURNALCTL=true
MAX_LOG_LINES=50000
SANITIZE_SECRETS=true
ENABLE_REMOTE_WRITE=false
ENABLE_AUTO_FIX=false
LLM_PROVIDER=none
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

Rules:
- Never commit `.env`.
- Never print private keys, Firebase credentials, API keys, passwords, Binance keys, or tokens.
- Redact secrets using regex before saving logs.

## ARCHITECTURE
Create this structure:

```text
daily_log_fix_prompt_bot/
  README.md
  .env.example
  requirements.txt
  pyproject.toml
  src/
    daily_log_fix_prompt_bot/
      __init__.py
      main.py
      config.py
      ssh_client.py
      log_fetcher.py
      sanitizer.py
      parser.py
      issue_detector.py
      summarizer.py
      prompt_builder.py
      prompt_reviewer.py
      report_writer.py
      models.py
      utils.py
  tests/
    test_parser.py
    test_issue_detector.py
    fixtures/
      sample_logs.txt
  systemd/
    daily-log-fix-prompt-bot.service
    daily-log-fix-prompt-bot.timer
```

## CORE FLOW
Implement:

```text
main.py
  load config
  create dated report dir
  fetch logs
  sanitize logs
  parse events
  detect issues
  create summary
  build fix prompt draft
  review/optimize prompt
  save all artifacts
  print final path
```

## LOG FETCHING
Support at least two modes:

### Mode A: journalctl
Command:

```bash
journalctl -u cryptomaster --since "24 hours ago" --no-pager -o short-iso
```

Configurable:
- service name
- lookback hours
- max lines

### Mode B: file logs
Command example:

```bash
tail -n 50000 /var/log/cryptomaster/*.log
```

If both modes enabled, combine and deduplicate.

## PARSER REQUIREMENTS
Parse and extract:
- timestamps
- app version tags
- signal creation events
- RDE decisions
- accepted/rejected signals
- rejection reasons
- EV / WR / score / thresholds
- regime
- symbol
- action BUY/SELL/HOLD
- spread/slippage warnings
- open/close trades
- exit type: TP, SL, TRAIL, TIMEOUT, MANUAL, ERROR
- net PnL if present
- drawdown
- profit factor
- Firebase read/write warnings
- Redis errors
- websocket reconnects/errors
- Binance API errors
- uncaught exceptions/tracebacks
- stalled pipeline / no signals for N cycles
- contradictions, e.g. accepted then blocked, timeout counted as win despite negative PnL, `SL == TP`, stale version running

Use robust regex, tolerate missing fields, never crash on malformed lines.

## ISSUE DETECTION
Implement rule-based detectors.

Minimum detectors:
1. `NO_SIGNALS_STALL`
   - Trigger when logs show no signals for too many cycles, idle > threshold, WS stale, or pipeline deadlock.

2. `HIGH_REJECTION_RATE`
   - Aggregate rejection reasons.
   - Flag if one reason dominates, e.g. TIMING, PAIR_BLOCK, FAST_FAIL, LOW_SCORE, SPREAD.

3. `TIMEOUT_OVERLOAD`
   - Flag if too many exits are TIMEOUT or hold windows look too long.

4. `NEGATIVE_OR_ZERO_PNL_BUG`
   - Detect suspicious PnL formatting, rounded zero, timeout classified as win, fees missing.

5. `VERSION_MISMATCH`
   - Detect if production logs show older RDE/version than expected from recent project state.

6. `FIREBASE_BUDGET_RISK`
   - Flag high read/write warnings or repeated DB calls.

7. `REDIS_OPTIONAL_MODE_FAILURE`
   - Flag repeated Redis connection spam or missing cooldown.

8. `EXECUTION_RISK`
   - Detect spread/slippage/ATR/correlation/heat warnings.

9. `OPEN_POSITION_STUCK`
   - Detect positions held too long or no exit evaluation.

10. `TRACEBACK_OR_EXCEPTION`
   - Extract stack traces and rank criticality high.

11. `CONTRADICTORY_DECISION_LOGS`
   - Detect inconsistent log statements for the same symbol/timestamp.

12. `LEARNING_NOT_UPDATING`
   - Detect constant EV/WR/weights or missing model_state persistence.

Each issue must include:
- `id`
- `severity`: critical/high/medium/low
- `confidence`: 0.0-1.0
- `evidence`: exact short log snippets
- `probable_root_cause`
- `recommended_fix`
- `likely_files`
- `validation_steps`

## SUMMARY FORMAT
Create `log_summary.md`:

```md
# Daily CryptoMaster Log Analysis — YYYY-MM-DD

## Executive Summary
- Overall status:
- Biggest risk:
- Most likely bug:
- Recommended next action:

## Key Metrics
- log lines analyzed:
- period:
- symbols seen:
- trades opened:
- trades closed:
- rejection count:
- top rejection reasons:
- timeout count:
- exceptions:
- Firebase warnings:
- Redis warnings:
- version tags observed:

## Detected Issues
### 1. [SEVERITY] ISSUE_ID
Evidence:
Root cause hypothesis:
Recommended fix:
Likely files:
Validation:

## Positive Signals
What seems to work.

## Unknowns / Missing Data
What could not be determined from logs.
```

## FIX PROMPT DRAFT REQUIREMENTS
Create `fix_prompt_draft.md` with a compressed but complete implementation prompt for Claude Code/Codex.

Must include:
- role
- project context
- observed evidence
- prioritized issues
- implementation tasks
- exact files likely affected
- constraints
- test commands
- production safety
- acceptance criteria
- no destructive actions
- ask Codex/Claude to inspect actual code before editing

## SELF-REVIEW / OPTIMIZATION
Create `prompt_reviewer.py`.

It must evaluate `fix_prompt_draft.md` using this checklist:
- Is the task scoped and actionable?
- Does it avoid vague “improve everything” instructions?
- Does it tell Codex/Claude to inspect real files first?
- Does it include exact symptoms and evidence?
- Does it separate critical fixes from optional improvements?
- Does it include tests/validation?
- Does it include rollback/safety?
- Does it avoid secrets?
- Is it token-efficient?
- Does it avoid changing live production automatically?
- Does it preserve existing architecture and metrics?
- Does it avoid deleting features?
- Does it explicitly require minimal diffs?

Then write `fix_prompt_final.md`.

Final prompt structure:

```md
# Claude Code / Codex Prompt — Fix CryptoMaster Issues From Daily Logs

## Mission
...

## Hard Rules
- Inspect files before editing.
- Do not remove existing features.
- Make minimal safe diffs.
- No auto-deploy.
- No secret printing.
- Preserve Firebase budgets.
- Preserve Android metrics contracts.
- Add/adjust tests where possible.

## Evidence From Logs
...

## Priority 1 — Critical Fixes
...

## Priority 2 — Stability / Risk Fixes
...

## Priority 3 — Observability / Diagnostics
...

## Files To Inspect First
...

## Implementation Plan
...

## Validation Commands
...

## Acceptance Criteria
...

## Output Required From Codex/Claude
- changed files
- explanation
- tests run
- remaining risks
- exact deploy checklist
```

## PROMPT QUALITY RULES
The final prompt must be:
- compressed but not ambiguous
- written for direct paste into Claude Code or Codex
- implementation-grade
- no filler
- no duplicate sections
- no huge raw logs; only relevant snippets
- evidence-driven
- safe for live trading code
- preserves all existing metrics and learning features

## SAFETY RULES
The bot must:
- not execute trade-bot code changes
- not restart production service
- not deploy
- not delete logs
- not wipe Firebase
- not expose secrets
- not include private keys or tokens in prompts
- not store excessive raw logs forever unless configured
- clearly mark hypotheses vs confirmed bugs



## TOKEN-EFFICIENT AI EVALUATION MODE
Add an optional AI-assisted evaluation layer. The bot should primarily use deterministic local parsing/rules, but when configured, it may call an AI model to improve root-cause analysis, prioritize fixes, and optimize the final Claude Code/Codex prompt.

Hard requirement: maximum token savings.

### AI usage rules
- Default must be `LLM_PROVIDER=none`.
- AI must be optional, never required for the bot to work.
- Never send full raw logs to AI.
- Never send secrets, API keys, Firebase credentials, Binance credentials, SSH data, private paths containing secrets, or full environment dumps.
- Always sanitize before any AI call.
- Always compress evidence before any AI call.
- Prefer local rule-based detection first, then ask AI only about already-detected issue summaries.
- AI call must be skipped if there are no high/critical issues.
- AI call must be skipped if token budget would be exceeded.
- AI call must be skipped if `ALLOW_EXTERNAL_LLM=false`.

### Token budget config
Extend `.env.example`:

```env
ALLOW_EXTERNAL_LLM=false
LLM_PROVIDER=none
LLM_MODEL=
AI_MAX_INPUT_TOKENS=6000
AI_MAX_OUTPUT_TOKENS=1800
AI_ONLY_FOR_SEVERITY=high,critical
AI_INCLUDE_RAW_SNIPPETS=false
AI_MAX_EVIDENCE_SNIPPETS_PER_ISSUE=3
AI_MAX_SNIPPET_CHARS=500
AI_SUMMARY_ONLY=true
```

### AI input format
The AI must receive only compact structured data like:

```json
{
  "period": "last_24h",
  "service": "cryptomaster",
  "version_tags": ["RDE[v10.10b]", "coherence[v10.12]", "V10.13r"],
  "metrics": {
    "lines_analyzed": 42000,
    "trades_opened": 12,
    "trades_closed": 10,
    "timeouts": 7,
    "rejections": 180,
    "exceptions": 1
  },
  "top_rejection_reasons": [
    {"reason": "TIMING", "count": 83},
    {"reason": "PAIR_BLOCK", "count": 51}
  ],
  "issues": [
    {
      "id": "TIMEOUT_OVERLOAD",
      "severity": "high",
      "confidence": 0.82,
      "evidence_short": [
        "TIMEOUT exit count 7/10 closed trades",
        "hold window appears too long vs ATR movement"
      ],
      "likely_files": [
        "src/services/trade_executor.py",
        "src/services/realtime_decision_engine.py"
      ]
    }
  ]
}
```

Do not send:
- `raw_logs.txt`
- entire tracebacks longer than necessary
- repeated duplicate lines
- more than 3 short snippets per issue
- any line matching secret patterns

### AI task
When AI is enabled, ask it only to return:

```json
{
  "root_cause_review": [],
  "priority_adjustments": [],
  "missing_checks": [],
  "prompt_improvements": [],
  "safe_fix_strategy": [],
  "validation_plan": []
}
```

Then merge the AI suggestions into `fix_prompt_final.md`.

### AI prompt template
Use a minimal prompt:

```text
You are reviewing a compact daily production log analysis for a live Python crypto trading bot.
Do not ask for raw logs.
Do not suggest auto-deploy.
Do not remove existing features.
Prioritize production-safe minimal diffs.
Return only JSON with:
root_cause_review, priority_adjustments, missing_checks, prompt_improvements, safe_fix_strategy, validation_plan.

Input:
{COMPACT_ISSUE_SUMMARY_JSON}
```

### Local compression before AI
Implement `ai_compactor.py` or equivalent function that:
- deduplicates repeated log events
- keeps only top N issues by severity and confidence
- keeps only top N rejection reasons
- truncates snippets
- removes low-confidence noise
- groups equivalent exceptions
- estimates approximate token count
- refuses to call AI if estimated input exceeds `AI_MAX_INPUT_TOKENS`

### AI cost/token guard
Before calling AI, print and save in `run_metadata.json`:
- whether AI was used
- provider/model
- estimated input tokens
- estimated output token cap
- reason if AI was skipped
- number of issues sent
- number of evidence snippets sent

Example:

```json
{
  "ai_used": true,
  "ai_provider": "openai",
  "ai_model": "gpt-5-mini",
  "estimated_input_tokens": 3120,
  "max_output_tokens": 1800,
  "issues_sent": 4,
  "snippets_sent": 9
}
```

### AI fallback
If AI fails:
- continue with deterministic `fix_prompt_final.md`
- add note: `AI review skipped/failed; deterministic prompt generated`
- do not crash the daily run

### Acceptance criteria for AI mode
- With `LLM_PROVIDER=none`, bot works fully offline.
- With AI enabled, only compact sanitized summaries are sent.
- No raw logs or secrets are sent.
- AI suggestions improve prioritization and validation only.
- Final prompt remains concise.
- Token budget is respected.

## OPTIONAL LLM ADAPTER
If `LLM_PROVIDER=none`, generate prompt with deterministic templates.

If LLM enabled, implement provider interface:

```python
class LLMProvider:
    def complete(self, system: str, user: str) -> str:
        ...
```

But never send unsanitized logs to external APIs.

Before LLM call:
- redact secrets
- truncate logs
- include only issue evidence, not full raw logs
- allow config `ALLOW_EXTERNAL_LLM=false` by default

## CLI
Implement:

```bash
python -m daily_log_fix_prompt_bot
python -m daily_log_fix_prompt_bot --lookback-hours 48
python -m daily_log_fix_prompt_bot --local-log ./sample.log
python -m daily_log_fix_prompt_bot --no-ssh
python -m daily_log_fix_prompt_bot --dry-run
```

## SYSTEMD TIMER
Create:

`systemd/daily-log-fix-prompt-bot.service`

```ini
[Unit]
Description=Daily CryptoMaster log analyzer and fix prompt generator
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/daily_log_fix_prompt_bot
EnvironmentFile=/opt/daily_log_fix_prompt_bot/.env
ExecStart=/opt/daily_log_fix_prompt_bot/.venv/bin/python -m daily_log_fix_prompt_bot
User=cryptomaster
Group=cryptomaster
Nice=5
```

`systemd/daily-log-fix-prompt-bot.timer`

```ini
[Unit]
Description=Run Daily CryptoMaster log analyzer once per day

[Timer]
OnCalendar=*-*-* 06:15:00
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
```

Install commands:

```bash
sudo cp systemd/daily-log-fix-prompt-bot.service /etc/systemd/system/
sudo cp systemd/daily-log-fix-prompt-bot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now daily-log-fix-prompt-bot.timer
systemctl list-timers | grep daily-log
```

## TESTING
Create tests for:
- parser extracts EV/score/reason/symbol/regime
- issue detector catches timeout overload
- issue detector catches version mismatch
- sanitizer redacts secrets
- prompt reviewer removes duplicate/weak sections
- report writer creates all expected files

Commands:

```bash
python -m pytest -q
python -m daily_log_fix_prompt_bot --local-log tests/fixtures/sample_logs.txt --dry-run
```

## ACCEPTANCE CRITERIA
Implementation is done when:
- bot runs locally with sample logs
- bot can fetch Hetzner logs through SSH or journalctl
- generated `fix_prompt_final.md` is directly usable in Claude Code/Codex
- raw logs are sanitized
- issues are ranked by severity
- final prompt includes exact evidence and validation steps
- systemd timer runs daily
- failures are logged but do not crash silently
- no production mutation occurs
- tests pass



## CODEX-FIRST CODING WORKFLOW
Optimize the generated daily fix prompt so that Codex is used as the primary coding agent whenever possible. Claude Code can remain optional for second-opinion review, prompt refinement, or architecture critique, but actual repository inspection, patching, command execution, test running, and diff preparation should be Codex-first.

### Codex-first principle
Every generated `fix_prompt_final.md` and `fix_prompt_final_compact.md` must clearly say:

```text
Primary coding agent: Codex.
Use Claude Code only as optional reviewer if needed.
Codex should inspect the repo, make minimal safe diffs, run validation commands, and report changed files.
```

### Why Codex-first
The generated prompt should assume Codex is best used when:
- it can run directly inside the target repository
- it can inspect real files before editing
- it can make code changes in-place
- it can run tests/commands
- it can produce reviewable diffs
- it can iterate on failures locally

### Codex launch instructions
Generated reports must include a short section:

````md
## Run With Codex

```bash
cd /opt/CryptoMaster_srv
git status
codex
```

Paste this prompt into Codex.

Recommended first instruction to Codex:
"Inspect the repository first. Do not edit until you identify the exact files/functions involved. Make the smallest safe patch. Run validation commands. Do not deploy or restart production."
````

If using a specific Codex model is supported in the local environment, include optional examples:

```bash
codex -m gpt-5.5
```

Do not hard-require a specific model. If model selection is unavailable, use default Codex.

### Codex execution mode
The prompt should tell Codex:
1. Read relevant files first.
2. Summarize likely root cause.
3. Propose minimal patch plan.
4. Apply changes only to necessary files.
5. Run tests or syntax checks.
6. Show `git diff`.
7. Provide manual deploy checklist.
8. Stop before production restart/deploy.

### Codex permissions / safety
Every generated Codex prompt must include:

```text
Do not run destructive commands.
Do not delete Firebase data.
Do not rotate secrets.
Do not restart systemd services.
Do not deploy automatically.
Do not edit unrelated files.
Do not remove existing metrics, learning logic, risk guards, Android contracts, or Firestore schema.
Ask before any command that changes production state.
```

Allowed commands by default:

```bash
git status
git diff
python -m pytest -q
python -m compileall .
python -m py_compile <changed_file.py>
grep / rg searches
```

Disallowed unless explicitly approved:

```bash
sudo systemctl restart cryptomaster
firebase delete / wipe commands
rm -rf
git reset --hard
git push --force
production deploy scripts
secret/key modification
```

### Codex output contract
Every generated prompt must require Codex to return:

```md
## Codex Result Required
- Files inspected
- Files changed
- Summary of root cause
- Minimal patch explanation
- Tests/commands run
- `git diff` summary
- Remaining risks
- Manual deploy checklist
- What was intentionally not changed
```

### Codex task decomposition
If many issues are found, the bot should split the generated prompt into Codex-sized tasks:

```text
Task A: critical runtime exceptions
Task B: trading decision contradiction / RDE gates
Task C: timeout/exit attribution
Task D: observability / log cleanup
Task E: optional improvements
```

Rules:
- One Codex task should focus on one coherent fix group.
- Critical runtime failures go first.
- Optional improvements must not be mixed with critical fixes.
- If prompt is too large, generate separate files:
  - `codex_task_01_critical.md`
  - `codex_task_02_trading_logic.md`
  - `codex_task_03_observability.md`

### Generated files update
In addition to existing output files, create when useful:

```text
codex_task_01_critical.md
codex_task_02_trading_logic.md
codex_task_03_observability.md
```

Only generate multiple Codex task files if:
- more than 5 high/critical issues exist
- or final prompt exceeds configured word budget
- or issues affect unrelated parts of the codebase

### Claude Code role
Claude Code is optional and should be described as:

```text
Optional reviewer, not primary patcher.
Use Claude Code to critique the Codex plan, improve the prompt, or review a diff.
Do not use Claude Code to duplicate the same patching work unless Codex fails or the change is architectural.
```

### Codex-first final prompt structure
Generated `fix_prompt_final.md` should prefer this structure:

```md
# Codex Prompt — CryptoMaster Daily Fix YYYY-MM-DD

## Primary Agent
Use Codex as the main coding agent inside the real repository.

## Mission
Fix only evidenced production issues from last 24h logs.

## Hard Rules
Minimal diffs. Inspect files first. No deploy. No restart. Preserve existing features.

## Run With Codex
cd /opt/CryptoMaster_srv
git status
codex

## Evidence Summary
Compact table of top issues.

## Codex Task
Step-by-step implementation instructions.

## Files To Inspect First
...

## Validation Commands
...

## Codex Result Required
...
```

### Prompt builder update
Update `prompt_builder.py` so the generated prompt uses wording like:
- "Codex: inspect these files first"
- "Codex: patch only these issue groups"
- "Codex: run these validation commands"
- "Codex: stop before deploy"
- "Claude Code optional reviewer"

Avoid equal wording like:
- "Claude/Codex"
- "Claude Code or Codex"
- "use either tool"

Preferred wording:

```text
Use Codex for coding. Use Claude Code only as optional reviewer.
```

### Deploy guide alignment
Update the deployment guide or generated report instructions to say:
1. Open the real project directory.
2. Run Codex there.
3. Paste `fix_prompt_final_compact.md` first.
4. Use full `fix_prompt_final.md` only if Codex needs more context.
5. Use Claude Code only for second review or if Codex gets stuck.

### Acceptance criteria update
Add:
- Generated prompts are Codex-first.
- `fix_prompt_final_compact.md` is directly pasteable into Codex.
- Prompt avoids ambiguous "Claude/Codex" wording.
- Prompt includes Codex run commands.
- Prompt includes Codex output contract.
- Prompt tells Codex to stop before deploy/restart.
- Optional Claude Code usage is clearly secondary.

## FINAL DELIVERABLE
Return:
1. Full file tree.
2. Complete code for every new file.
3. Setup commands.
4. Example `.env`.
5. Example generated `fix_prompt_final.md`.
6. Test commands and expected output.
7. Safety/deploy checklist.

## IMPORTANT IMPLEMENTATION STYLE
- Prefer simple readable Python.
- Avoid overengineering.
- Keep modules small.
- Add comments only where useful.
- Strong error handling.
- No broad bare `except`.
- Use type hints.
- Treat missing logs as a recoverable error.
- Preserve raw evidence snippets.
- Keep final prompt under practical token budget.
- Never remove existing CryptoMaster features.
- The helper bot is an external observer, not a trading component.

## EXTRA OPTIMIZATION IDEAS TO INCLUDE
After the first working version, propose:
- GitHub issue creation from `fix_prompt_final.md`
- Slack/Telegram notification with report path
- trend comparison vs previous daily reports
- issue recurrence tracking
- severity score over time
- automatic attachment of last 3 reports to next prompt
- optional local-only vector search over historical reports
- dashboard page listing daily issues
- command to compare before/after deploy logs
- production version fingerprint check
