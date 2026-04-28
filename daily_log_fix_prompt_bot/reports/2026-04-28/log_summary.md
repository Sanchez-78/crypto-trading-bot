# Daily CryptoMaster Log Analysis — 2026-04-28T12:30:45.427956

## Executive Summary

**Status**: 🔴 CRITICAL

**Biggest Risk**: No signals generated in analysis period

**Issues Detected**: 6 total
- Critical: 2
- High: 1
- Medium: 3
- Low: 0

## Key Metrics

| Metric | Value |
|--------|-------|
| Log lines analyzed | 50000 |
| Trades opened | 0 |
| Trades closed | 1086 |
| Rejection count | 370 |
| Timeout exits | 279 |
| Exceptions | 11 |
| Firebase warnings | 11 |
| Redis warnings | 11 |

## Detected Issues

### 1. [CRITICAL] No signals generated in analysis period

**Confidence**: 100%

**Evidence**:
- `No signal_created events found in logs`

**Root Cause**: Signal generator stalled, WebSocket dead, or data feed frozen

**Recommended Fix**: Check market_stream WebSocket, verify Binance connectivity, restart if hung

**Likely Files**: `src/services/market_stream.py`, `src/services/signal_generator.py`

**Validation Steps**:
- Check WebSocket connection status
- Verify Binance API is accessible

### 2. [MEDIUM] Excessive zero PnL trades

**Confidence**: 70%

**Evidence**:
- `1086/1086 trades have zero PnL`

**Root Cause**: Rounding errors, flat timeout exits not classified, or PnL not computed

**Recommended Fix**: Check PnL rounding logic, verify timeout classification, ensure computation

**Likely Files**: `src/services/learning_event.py`, `src/services/metrics_engine.py`

**Validation Steps**:
- Inspect PnL calculation code
- Check rounding thresholds

### 3. [MEDIUM] Multiple versions observed: 10.12c, 10.13g, 10.13m, 10.13r, 10.13u, 10.13w, 10.13x

**Confidence**: 70%

**Evidence**:
- `10.13u`
- `10.13w`
- `10.13g`

**Root Cause**: Bot restarted with different code, or mixed deployment

**Recommended Fix**: Verify deployment is consistent, check git HEAD, restart bot cleanly

**Likely Files**: `start.py`, `bot2/main.py`

**Validation Steps**:
- Check git status
- Verify single instance running

### 4. [HIGH] High Firebase warnings count: 11

**Confidence**: 80%

**Evidence**:
- `Firebase warnings in logs: 11`

**Root Cause**: Quota exhaustion, slow writes, or connection timeouts

**Recommended Fix**: Check Firebase quota status, optimize batch writes, add backoff retry

**Likely Files**: `src/services/firebase_client.py`

**Validation Steps**:
- Run quota monitor
- Check daily usage stats

### 5. [MEDIUM] Repeated Redis connection failures: 11

**Confidence**: 75%

**Evidence**:
- `Redis warnings in logs: 11`

**Root Cause**: Redis server down, network timeout, or connection pool exhaustion

**Recommended Fix**: Check Redis server status, verify network connectivity, increase pool size

**Likely Files**: `src/services/learning_event.py`, `src/services/execution_engine.py`

**Validation Steps**:
- ping Redis server
- Check connection pool stats

### 6. [CRITICAL] Uncaught exceptions detected: 11

**Confidence**: 95%

**Evidence**:
- `⚠️  WebSocket error: Connection to remote host was lost.`
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

