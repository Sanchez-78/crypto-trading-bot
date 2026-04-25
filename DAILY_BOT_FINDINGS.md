# Daily Bot Findings & Fix Recommendations

**Date**: 2026-04-25  
**Bot Analysis**: Automated via daily_log_fix_prompt_bot  
**Priority**: CRITICAL + HIGH

---

## Executive Summary

Daily log analysis detected **5 critical/high issues**:
1. **CRITICAL**: 5 uncaught exceptions (WebSocket/Redis/Audit errors)
2. **HIGH**: 43 Firebase quota warnings (quota near limit)
3. **MEDIUM**: 650/650 trades with zero PnL (calculation bug)
4. **MEDIUM**: 40 Redis connection failures (Redis unavailable)
5. **MEDIUM**: 27 version tags in logs (mixed deployment)

---

## Root Causes

### Issue 1: Redis Unavailable (→ Data Loss)
**Evidence**: 40+ `[FLUSH_LM_REDIS_NONE] - Redis client is None` messages

**Impact**:
- Learning state not persisted to Redis
- Metrics lost on restart
- State manager falls back to in-memory only

**Fix**:
- Verify Redis server is running: `redis-cli ping`
- Check network connectivity from bot to Redis
- Add exponential backoff retry in state_manager.py

**Files**: `src/services/state_manager.py`, `src/services/learning_event.py`

---

### Issue 2: WebSocket Disconnects (→ Feed Loss)
**Evidence**: 4-5 `WebSocket closed` + `Connection to remote host was lost` messages

**Impact**:
- Market feed intermittent (74s → 175s → 286s uptime per connection)
- Signals delayed or missed during reconnect window
- Price updates stale

**Fix**:
- Add connection state monitoring with exponential backoff
- Increase ping/heartbeat interval
- Add WebSocket health check

**Files**: `src/services/market_stream.py`

---

### Issue 3: All Trades Have Zero PnL (→ Metrics Broken)
**Evidence**: Metrics show `profit=0.0`, all 650 trades with `net_pnl=0`

**Likely Causes**:
- PnL calculation missing or zeroed in trade close
- Firebase disabled (no FIREBASE_KEY_BASE64) → can't read/write history
- Rounding error: `profit < 0.0001` → rounds to zero
- Timeout exits not classified → treated as zero-PnL flats

**Fix**:
1. Check metrics_engine.py PnL calculation logic
2. Enable Firebase or implement local backup metrics storage
3. Inspect learning_event.py outcome classification (result field logic)

**Files**: `src/services/metrics_engine.py`, `src/services/learning_event.py`, `src/services/firebase_client.py`

---

### Issue 4: Firebase Disabled
**Evidence**: `⚠️  Firebase disabled (no FIREBASE_KEY_BASE64)`

**Impact**:
- No trade history persistence
- Metrics not backed up to Firestore
- Dashboard can't read historical stats
- Daily quota monitor can't connect

**Fix**:
- Set `FIREBASE_KEY_BASE64` env var on bot startup
- Or: fallback to local JSON file storage for metrics

**Files**: `src/services/firebase_client.py`, `start.py`

---

### Issue 5: 27 Version Tags in Logs
**Evidence**: V10.12c, 10.12d, 10.12e ... 10.13s, 5.1 all seen

**Likely Cause**: Bot restarted with different code between commits

**Fix**:
- Verify single bot instance running: `ps aux | grep start.py`
- Check git HEAD: `git log -1 --oneline` (should be 53acfef)
- Restart bot cleanly: `pkill -f start.py; sleep 2; python start.py`

**Files**: `start.py`, `bot2/main.py`

---

## Implementation Priority

### IMMEDIATE (Next 1 hour)
1. **Restart bot cleanly** — single instance, latest code
2. **Check Redis** — ensure server is running and accessible
3. **Add Firebase key** — or implement local fallback
4. **Monitor for improvements** — watch logs for 15 minutes

### FOLLOW-UP (Next 2 hours)
1. **PnL calculation audit** — trace where zero PnL originates
2. **WebSocket resilience** — add better reconnect logic
3. **Metrics persistence** — implement local JSON fallback if Firebase unavailable

### LONG-TERM (Next release)
1. **Redis auto-reconnect** with exponential backoff
2. **WebSocket health monitoring** with active ping/pong
3. **Graceful Firebase fallback** (local → Firebase → error)

---

## Testing Checklist

After each fix:
```bash
python -m compileall src/
python -m pytest tests/ -q
python start.py  # smoke test 5 minutes
tail -f bot.log  # watch for errors
```

Expected improvements:
- Zero Redis errors
- WebSocket healthy (300s+ uptime)
- PnL > 0 on winning trades
- Single version tag in logs (53acfef or latest)

---

## Monitoring

Daily bot output files:
```
reports/2026-04-25/
├── raw_logs.txt          (2.1MB sanitized logs)
├── detected_issues.json  (5 issues - machine readable)
├── log_summary.md        (detailed analysis)
├── fix_prompt_final.md   (Claude Code/Codex prompt)
└── run_metadata.json     (timestamps, stats)
```

Next run: ~06:00 UTC tomorrow

---

## References

- Mammon Patches 1–3: `commit 53acfef` (deployed)
- Daily Bot: `commit c199576` (deployed)
- Server: Hetzner, systemd
- Current Git HEAD: `53acfef` (V10.15 Mammon)
