# CryptoMaster V10.13u+20 — P0.3 Deployment Checklist

**Date**: 2026-04-28  
**Status**: ✅ READY FOR PRODUCTION

---

## Pre-Deployment Verification

### Code Changes Summary
- ✅ `src/services/trade_executor.py`: +65 lines (imports, paper routing, learning integration)
- ✅ `src/core/runtime_mode.py`: Unchanged (already complete from P0.1)
- ✅ `src/services/paper_trade_executor.py`: Unchanged (already complete from P0.2)
- ✅ `bot2/main.py`: +7 lines (startup logging for runtime mode)
- ✅ `tests/test_p0_3_paper_integration.py`: New file (163 lines, 8 tests)
- ✅ `tests/test_paper_mode.py`: 1 test fix (realistic FLAT outcome)

### Compilation Check
```bash
python -m py_compile src/core/runtime_mode.py src/services/paper_trade_executor.py src/services/trade_executor.py bot2/main.py
# ✅ All files compile successfully
```

### Test Coverage
```bash
python -m pytest tests/test_paper_mode.py tests/test_p0_3_paper_integration.py -v
# ✅ 23/23 tests passing
#    - 14 P0.2 unit tests (paper executor)
#    - 8 P0.3 integration tests (routing + learning)
#    - 1 deprecated defaults test
```

---

## Deployment Steps

### 1. Commit Changes
```bash
git add src/services/trade_executor.py \
        src/core/runtime_mode.py \
        src/services/paper_trade_executor.py \
        bot2/main.py \
        tests/test_p0_3_paper_integration.py \
        tests/test_paper_mode.py \
        .env.example

git commit -m "P0.3: Integrate paper executor into production TAKE path with Firebase learning"

git push origin main
```

**Expected commit message**:
```
P0.3: Integrate paper executor into production TAKE path with Firebase learning

- Route TAKE signals to paper_trade_executor when is_paper_mode()=true
- Integrate update_paper_positions() into on_price() loop for exit detection
- Implement _save_paper_trade_closed() for Firebase trades_paper collection
- Add startup logging via log_runtime_config() for production validation
- Add 8 integration tests for complete end-to-end flow
- All 23 tests passing (P0.2 unit + P0.3 integration)
```

### 2. Deploy to Production
```bash
sudo systemctl restart cryptomaster
sleep 60
```

### 3. Verify Startup Logs
```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager | grep -E "TRADING_MODE|PAPER_ROUTED|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|LIVE_ORDER_DISABLED"
```

**Expected Output**:
```
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true
```

**Within 30 minutes, expect**:
```
[PAPER_ENTRY] symbol=XRPUSDT side=BUY price=2.5432 size_usd=100 ev=0.050 score=0.25 reason=RDE_TAKE
[PAPER_EXIT] symbol=XRPUSDT reason=TP entry=2.5432 exit=2.5543 net_pnl_pct=0.82 outcome=WIN
[LEARNING_UPDATE] source=paper_closed_trade symbol=XRPUSDT outcome=WIN net_pnl_pct=0.82
```

---

## Production Validation Checklist

### Minimum Success Criteria
- [ ] `[RUNTIME_VERSION]` log appears at startup
- [ ] `[TRADING_MODE] mode=paper_live` appears
- [ ] `is_paper_mode()` reads true from runtime_mode.py
- [ ] No Traceback or ERROR in logs
- [ ] No real orders attempted (safe defaults enforced)

### Full P0.3 Success Criteria
- [ ] `[PAPER_ENTRY]` log appears with real price and signal metadata
- [ ] `[PAPER_EXIT]` log appears with TP/SL/TIMEOUT reason and net_pnl_pct
- [ ] `[LEARNING_UPDATE]` appears with outcome classification (WIN/LOSS/FLAT)
- [ ] Closed trades appear in Firebase `trades_paper` collection
- [ ] Learning metrics updated (trades counter incremented)
- [ ] Multiple paper trades opened and closed (confirms loop integration)
- [ ] Real orders remain blocked (no Binance calls in logs)

### Debug Commands (if issues found)

**Check runtime mode configuration**:
```bash
cd /opt/cryptomaster
source venv/bin/activate
python -c "
from src.core.runtime_mode import is_paper_mode, live_trading_allowed, get_trading_mode
print('mode:', get_trading_mode())
print('is_paper:', is_paper_mode())
print('live_allowed:', live_trading_allowed())
"
```

**Check .env file**:
```bash
grep -E "TRADING_MODE|ENABLE_REAL_ORDERS|LIVE_TRADING_CONFIRMED|PAPER_EXPLORATION" /opt/cryptomaster/.env
```

**Expected values**:
```
TRADING_MODE=paper_live
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_EXPLORATION_ENABLED=true
```

**Check production code includes P0.3**:
```bash
grep -n "PAPER_ROUTED\|_save_paper_trade_closed\|update_paper_positions\|is_paper_mode" /opt/cryptomaster/src/services/trade_executor.py | head -10
```

**Monitor logs in real-time**:
```bash
sudo journalctl -f -u cryptomaster | grep -E "PAPER|TRADING_MODE|LEARNING_UPDATE|LIVE_ORDER"
```

---

## Rollback Plan

If production validation fails:

1. **Identify issue** from logs
2. **Revert commit** (if code bug):
   ```bash
   git revert HEAD
   git push origin main
   sudo systemctl restart cryptomaster
   ```
3. **Or fix locally** (if env/config issue):
   ```bash
   # Edit .env, restart
   sudo systemctl restart cryptomaster
   ```

---

## Success Indicators Timeline

| Time | Expected Event |
|------|---|
| 0 min | Systemd starts cryptomaster |
| +30 sec | `[RUNTIME_VERSION]` and `[TRADING_MODE]` logs |
| +1-2 min | `[PAPER_ENTRY]` (first signal from RDE) |
| +2-5 min | `[PAPER_EXIT]` (first position closes) |
| +5 min | `[LEARNING_UPDATE]` |
| +30 min | 5-20 `[PAPER_ENTRY]` + `[PAPER_EXIT]` cycles |

---

## Post-Deployment Verification

After 30 minutes of successful operation:

```bash
# Count paper entries
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager | grep -c "PAPER_ENTRY"
# Expected: > 0 (5+ typical)

# Count learning updates
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager | grep -c "LEARNING_UPDATE.*paper_closed_trade"
# Expected: > 0 (2-10 typical)

# Verify no real orders attempted
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager | grep -c "Binance.*market.*order"
# Expected: 0 (must remain 0)
```

---

## Next Steps

### If P0.3 Validates Successfully
1. ✅ Confirm 30-minute logs show all required entries
2. ✅ Verify Firebase trades_paper collection has closed trades
3. ✅ Check learning metrics incremented correctly
4. ⏭️ **Proceed to P1 — Paper Exploration + Replay Training**

### If Issues Found
1. ❌ Read debug logs
2. ❌ Fix code or config
3. ❌ Redeploy and revalidate
4. ❌ Do **not** start P1 until P0.3 fully validated

---

## P1 Readiness

P0.3 is the prerequisite for P1. Do not start P1 implementation until:

```
✅ [TRADING_MODE] appears in production logs
✅ [PAPER_ROUTED] appears (paper executor reached)
✅ [PAPER_ENTRY] appears (positions opened via paper executor)
✅ [PAPER_EXIT] appears (positions closed by paper executor)
✅ [LEARNING_UPDATE] source=paper_closed_trade appears
✅ No Traceback or ERROR in logs
✅ Real orders remain blocked by default
```

---

**Status**: ✅ Ready for deployment  
**Last Updated**: 2026-04-28  
**Test Results**: 23/23 passing  
**Deployment Date**: [To be filled]  
**Validation Complete**: [To be filled]
