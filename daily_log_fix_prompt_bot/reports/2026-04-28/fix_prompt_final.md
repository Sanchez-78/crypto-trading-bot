# Claude Code / Codex: CryptoMaster Daily Fix Prompt

## Mission

Fix the highest-priority bugs and regressions detected from today's live trading bot logs.

## Hard Rules

- **Inspect real code first** before any edit.
- **No auto-deploy** or force-push; changes are local until human approval.
- **No secret printing** (keys, tokens, Firebase credentials).
- **Preserve architecture**: no refactors, no moving files.
- **Minimal safe diffs**: fix the bug, nothing extra.
- **Firebase quota safe**: no new heavy reads/writes.
- **Preserve metrics contracts**: no schema changes.

## Context

**System**: CryptoMaster_srv (Python crypto trading bot on Hetzner)
**Log Period**: Last 24 hours
**Branch**: main (commit 53acfef)

## Priority Issues


### Issue 1: No signals generated in analysis period

**Severity**: CRITICAL (Confidence: 100%)

**What We See**:
```
No signal_created events found in logs
```

**Why It Matters**: Signal generator stalled, WebSocket dead, or data feed frozen

**Files Likely Involved**:
```
src/services/market_stream.py
src/services/signal_generator.py
```

**What to Do**:
1. Inspect the actual code in the files listed above
2. Verify the bug matches the evidence
3. Implement minimal fix (1-5 line change if possible)
4. Add validation step: Check WebSocket connection status


### Issue 2: Uncaught exceptions detected: 11

**Severity**: CRITICAL (Confidence: 95%)

**What We See**:
```
⚠️  WebSocket error: Connection to remote host was lost.
⚠️  WebSocket error: Connection to remote host was lost.
```

**Why It Matters**: Code bug, missing error handling, or edge case not covered

**Files Likely Involved**:
```
src/services/realtime_decision_engine.py
src/services/trade_executor.py
```

**What to Do**:
1. Inspect the actual code in the files listed above
2. Verify the bug matches the evidence
3. Implement minimal fix (1-5 line change if possible)
4. Add validation step: Read full traceback


### Issue 3: High Firebase warnings count: 11

**Severity**: HIGH (Confidence: 80%)

**What We See**:
```
Firebase warnings in logs: 11
```

**Why It Matters**: Quota exhaustion, slow writes, or connection timeouts

**Files Likely Involved**:
```
src/services/firebase_client.py
```

**What to Do**:
1. Inspect the actual code in the files listed above
2. Verify the bug matches the evidence
3. Implement minimal fix (1-5 line change if possible)
4. Add validation step: Run quota monitor


## Testing & Validation

Run after any fix:
```bash
python -m compileall src/
python -m pytest tests/ -q
python start.py  # manual smoke test
```

## Safety Checklist

- [ ] Compiled without errors
- [ ] Tests pass (no new failures)
- [ ] No secrets printed to logs
- [ ] No Firestore schema changes
- [ ] No deleted files or features
- [ ] Diff is < 20 lines
- [ ] Commit message is clear

## Next Steps (After Fix)

1. Verify fix locally in trading loop
2. Create commit with clear message
3. Push to origin/main (CI will deploy)
4. Monitor logs for regression

---

**Note**: This prompt was auto-generated from daily log analysis.
Do not treat it as absolute truth. Use it as a starting point for investigation.

