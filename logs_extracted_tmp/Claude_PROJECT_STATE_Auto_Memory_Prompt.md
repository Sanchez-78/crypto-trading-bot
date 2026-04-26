# Claude Code Prompt — Auto Project State Memory for CryptoMaster

Use this prompt in the root of the existing project:

```text
Create and maintain a compact project memory file to reduce context loss and protect the workflow from conversation compacting.

Target file:
PROJECT_STATE.md

Goal:
PROJECT_STATE.md must become the single durable source of current workflow truth for this project. Use it at the start of every session, update it after every approved commit/patch/review, and keep it compact enough to fit into context quickly.

Rules:
1. Before doing any new work, read:
   - .maestro.md
   - PROJECT_STATE.md if it exists
   - only then inspect relevant code files
2. If PROJECT_STATE.md does not exist, create it.
3. After every meaningful step, update PROJECT_STATE.md.
4. Keep PROJECT_STATE.md under 150 lines.
5. Do not paste long logs, full diffs, or large code blocks into PROJECT_STATE.md.
6. Store only durable facts:
   - active phase
   - completed commits
   - current uncommitted work
   - approved files
   - forbidden actions
   - next exact step
   - validation status
   - rollback notes
   - roadmap status
7. PROJECT_STATE.md overrides old chat memory if there is any conflict.
8. If conversation context becomes compacted, continue from PROJECT_STATE.md, not from assumptions.
9. Never implement items from roadmap files unless PROJECT_STATE.md says that phase is active.
10. Always show a diff before staging/committing.
11. Never push without explicit approval.
12. One commit per hardening area.

Initial content to write now:

# CryptoMaster Project State

Last updated: 2026-04-25

## Active phase

Safety hardening before economics/integration rollout.

Current objective:
Make production safer and easier to verify without changing EV/RDE/execution behavior.

## Completed commits

- `b2bcca8` — Commit 1: runtime version marker for deployment verification.
  - Added `src/services/version_info.py`
  - Updated `bot2/main.py`
  - Updated `src/services/pre_live_audit.py`
  - Purpose: startup/audit runtime marker with git commit, branch, host, Python version, timestamp.
  - Status: accepted locally, not pushed.

## Current work

Commit 2: secret-safe logging.

Status:
Implemented but not staged and not committed. Awaiting diff review.

Approved files for Commit 2 only:
- `src/services/safe_logging.py`
- `src/services/firebase_client.py`
- `src/services/market_stream.py`

Expected Commit 2 scope:
- Add `sanitize(text)`
- Add `safe_log_exception(e)`
- Mask Firebase/Binance/tokens/password-like secrets
- Preserve normal trading logs: symbol, price, EV, TP, SL, timeout, pnl, score
- No trading behavior changes

## Forbidden now

Do not:
- push
- implement economics roadmap
- implement Firebase retry heartbeat yet
- implement quota circuit breaker yet
- implement market offline alert yet
- change EV/RDE/execution behavior
- change sizing, leverage, TP/SL, score, gates
- change Firebase schema
- change Android dashboard fields
- stage unrelated files
- commit `.claude/settings.local.json`
- do full rewrites

## Next exact step

Show and review Commit 2 diff:

```bash
git status --short
git diff --stat
git diff -- src/services/safe_logging.py src/services/firebase_client.py src/services/market_stream.py
```

Run validation:

```bash
python -m py_compile src/services/safe_logging.py
python -m py_compile src/services/firebase_client.py
python -m py_compile src/services/market_stream.py
python -c "from src.services.safe_logging import sanitize; print(sanitize('Authorization: Bearer abcdefghijklmnop')); print(sanitize('api_key: abcdefghijklmnop')); print(sanitize('password: abcdefghijklmnop')); print(sanitize('key=short')); print(sanitize('BTCUSDT price=42000 ev=0.035 TP=1.2 SL=0.6 pnl=0.01 score=0.22'))"
```

Expected validation:
- `Authorization: Bearer [REDACTED]`
- `api_key: [REDACTED]`
- `password: [REDACTED]`
- `key=short`
- trading metrics unchanged

Then stop for user review. Do not stage or commit yet.

## Pending hardening sequence

After Commit 2 is accepted:

1. Firebase retry queue heartbeat
   - must be thread-safe
   - lock around queue
   - no recursive unsafe `save_batch([])`
   - backoff, batch limit, log rate limit

2. Firebase quota degraded mode
   - OK/WARNING/DEGRADED/CRITICAL
   - never block emergency exits
   - may block new entries if audit persistence unsafe

3. Market offline alert
   - observational only
   - 120s without price update
   - emit `market_offline`
   - log recovery when prices resume

4. Rollback/deployment docs
   - include validation commands
   - include runtime version verification on server

## Post-hardening roadmap

File:
`CryptoMaster_Combined_Analysis_Integration_2026-04-25.md`

Status:
Remembered as roadmap only. Do not implement yet.

Use only after safety hardening is complete:
1. canonical metrics enforcement
2. audit enhancements/regression testing
3. bootstrap/cell quality governance
4. exit monetization shadow/live rollout
5. probability calibration and feature pruning last

## Workflow rules

- Read `.maestro.md` and `PROJECT_STATE.md` before new work.
- Analyze before editing.
- Patch plan before implementation.
- Diff before commit.
- Stage only approved files.
- Local commit only after approval.
- Push only after explicit approval.
- Update `PROJECT_STATE.md` after every accepted commit or major review.
- Keep changes incremental and reversible.

After creating/updating PROJECT_STATE.md:
1. show its final content
2. run `git status --short`
3. do not stage or commit PROJECT_STATE.md until I approve
```

## Follow-up instruction after Claude creates the file

```text
From now on, start every task by reading PROJECT_STATE.md and updating it after every accepted step. Treat it as durable memory and use it to recover from conversation compacting.
```
