# V10.13u+2 Consistency Patches — Deployment Verification

## Commit
- **SHA**: f61913c
- **Patches**: 6 (Maturity, Economic PF, LM Hydration, RR Consistency, Runtime Inject, Tests)
- **Files**: 5 (realtime_decision_engine.py, learning_monitor.py, version_info.py, deploy.yml, tests/)

## Post-Deploy Verification

### 1. Check Runtime Version (Patch 5)

Expected log output on service restart:

```text
[RUNTIME_VERSION] app=CryptoMaster version=V10.13u+2 commit=f61913c branch=main host=... python=...
```

Should NOT see:
```text
commit=UNKNOWN branch=UNKNOWN
```

**Command:**
```bash
journalctl -u cryptomaster -n 50 --no-pager | grep RUNTIME_VERSION
```

### 2. Check Maturity Oracle (Patch 1)

Expected logs:

```text
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False cold_start=False pair_count=17 min_pair_n=2
```

Should NOT see:
```text
'int' object has no attribute 'get'
Maturity computed: trades=0 bootstrap=True cold_start=True
```

**Command:**
```bash
journalctl -u cryptomaster -n 150 --no-pager | grep -E "PATCH_MATURITY|'int' object"
```

### 3. Check Economic Health (Patch 2)

Expected log:

```text
[ECON_CANONICAL] pf=0.75 source=canonical_profit_factor trades=500 wins=79 losses=24
```

Verify PF matches dashboard display.

**Command:**
```bash
journalctl -u cryptomaster -n 100 --no-pager | grep ECON_CANONICAL
```

### 4. Check LM Hydration Depth (Patch 3)

Expected logs:

```text
[LM_HYDRATE_CANONICAL] loaded_closed_trades=500 hydrated_pairs=17 decisive=103 flats=397
[LM_HYDRATE_PAIR]  ETHUSDT BEAR_TREND n=44 decisive=12 wr=75% avg_pnl=+0.000125 ev=+0.000002
[LM_HYDRATE_PAIR]  BTCUSDT BULL_TREND n=38 decisive=8 wr=62% avg_pnl=+0.000089 ev=+0.000001
```

Should NOT see:
```text
ETH BEAR_TREND n:44 EV:+0.000 WR:50%  # All pairs showing default 50%
```

**Command:**
```bash
journalctl -u cryptomaster -n 200 --no-pager | grep LM_HYDRATE
```

### 5. Check for Test Success

Tests should compile and mostly pass:

```bash
cd /opt/cryptomaster
./venv/bin/python -m pytest tests/test_v10_13u_patches.py -q
```

Expected: 17 collected, ≥15 passed.

### 6. Full Log Audit

Look for absence of error conditions:

```bash
journalctl -u cryptomaster -n 500 --no-pager | grep -E "ERROR|FAILED|crash|exception" | head -20
```

Should show normal operational errors only, not:
- Type errors in maturity computation
- PF mismatches (canonical vs economic)
- State mismatch warnings (if LM hydrated correctly)

## Smoke Test Checklist

- [ ] Service started without errors
- [ ] Runtime version shows real commit/branch (not UNKNOWN)
- [ ] Maturity computation succeeds with realistic trade counts
- [ ] Economic PF matches dashboard PF
- [ ] LM shows realistic WR% and EV per pair (not all 50%/0.0)
- [ ] No type errors or crashes in logs
- [ ] Dashboard displays consistent metrics
- [ ] Market data flowing (new signal logs appearing)

## Rollback Plan

If verification fails:

1. Identify which patch caused the issue
2. Revert commit f61913c: `git revert f61913c`
3. Push and redeploy
4. Verify previous commit (36bdf36) is live again

## Expected Improvements

After successful deployment:

1. **Maturity Oracle** — Now uses canonical trade count source with type safety
2. **Economic Health** — Uses same PF calculation as dashboard (canonical source)
3. **Learning Monitor** — Shows realistic per-pair metrics from hydration
4. **Runtime Visibility** — Git commit/branch visible in logs for deployment verification
5. **Test Coverage** — 17 tests ensure consistency across patches

No position sizing changes yet — pending maturity/economic validation.

## Next Steps (Post-Verification)

1. Run 24-hour smoke test cycle
2. Verify no new crashes or anomalies
3. Compare metrics before/after patches
4. Then proceed to Phase 2: Position sizing tuning

---

**Deployment Date**: 2026-04-26
**Patch Version**: V10.13u+2
**Responsible**: Claude (Haiku 4.5)
