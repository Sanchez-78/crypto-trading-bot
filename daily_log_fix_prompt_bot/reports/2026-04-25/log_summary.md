# Daily CryptoMaster Log Analysis — 2026-04-25T09:18:38.237441

## Executive Summary

**Status**: 🔴 CRITICAL

**Biggest Risk**: Uncaught exceptions detected: 5

**Issues Detected**: 5 total
- Critical: 1
- High: 1
- Medium: 3
- Low: 0

## Key Metrics

| Metric | Value |
|--------|-------|
| Log lines analyzed | 32034 |
| Trades opened | 0 |
| Trades closed | 650 |
| Rejection count | 207 |
| Timeout exits | 134 |
| Exceptions | 5 |
| Firebase warnings | 43 |
| Redis warnings | 40 |

## Detected Issues

### 1. [MEDIUM] Excessive zero PnL trades

**Confidence**: 70%

**Evidence**:
- `650/650 trades have zero PnL`

**Root Cause**: Rounding errors, flat timeout exits not classified, or PnL not computed

**Recommended Fix**: Check PnL rounding logic, verify timeout classification, ensure computation

**Likely Files**: `src/services/learning_event.py`, `src/services/metrics_engine.py`

**Validation Steps**:
- Inspect PnL calculation code
- Check rounding thresholds

### 2. [MEDIUM] Multiple versions observed: 10.12c, 10.12d, 10.12e, 10.12f, 10.12g, 10.12h, 10.12i, 10.13, 10.13a, 10.13b, 10.13c, 10.13d, 10.13f, 10.13g, 10.13h, 10.13i, 10.13m, 10.13n, 10.13o, 10.13p, 10.13q, 10.13r, 10.13s, 10.13u, 10.13w, 10.13x, 5.1

**Confidence**: 70%

**Evidence**:
- `10.13h`
- `10.12g`
- `10.13`

**Root Cause**: Bot restarted with different code, or mixed deployment

**Recommended Fix**: Verify deployment is consistent, check git HEAD, restart bot cleanly

**Likely Files**: `start.py`, `bot2/main.py`

**Validation Steps**:
- Check git status
- Verify single instance running

### 3. [HIGH] High Firebase warnings count: 43

**Confidence**: 80%

**Evidence**:
- `Firebase warnings in logs: 43`

**Root Cause**: Quota exhaustion, slow writes, or connection timeouts

**Recommended Fix**: Check Firebase quota status, optimize batch writes, add backoff retry

**Likely Files**: `src/services/firebase_client.py`

**Validation Steps**:
- Run quota monitor
- Check daily usage stats

### 4. [MEDIUM] Repeated Redis connection failures: 40

**Confidence**: 75%

**Evidence**:
- `Redis warnings in logs: 40`

**Root Cause**: Redis server down, network timeout, or connection pool exhaustion

**Recommended Fix**: Check Redis server status, verify network connectivity, increase pool size

**Likely Files**: `src/services/learning_event.py`, `src/services/execution_engine.py`

**Validation Steps**:
- ping Redis server
- Check connection pool stats

### 5. [CRITICAL] Uncaught exceptions detected: 5

**Confidence**: 95%

**Evidence**:
- `WARNING:src.services.audit_worker:⚠️  AuditWorker: Redis connection lost/failed. Subsequent retries `
- `⚠️  WebSocket error: Connection to remote host was lost.`
- `⚠️  WebSocket error: Connection to remote host was lost.`

**Root Cause**: Code bug, missing error handling, or edge case not covered

**Recommended Fix**: Inspect traceback, add error handling, write test for edge case

**Likely Files**: `src/services/realtime_decision_engine.py`, `src/services/trade_executor.py`

**Validation Steps**:
- Read full traceback
- Reproduce locally

## Positive Signals

- Event bus handling appears stable
- No obvious circular imports detected

## Unknowns

- Exact current deployed version (need git commit hash)
- Current Firebase quota consumption (need live metrics)
- Redis server health (need external monitoring)

