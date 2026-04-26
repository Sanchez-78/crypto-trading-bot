# V10.13u+2 Patch Validation Protocol

## Deployment Status
- **Commit**: f61913c (all 6 patches deployed)
- **Deployed to**: Hetzner (cryptomaster service)
- **Deploy Time**: 2026-04-26 ~10:40 UTC

## Phase 1: Immediate Validation (Within 5 Minutes)

### 1.1 Service Restart & Log Capture
```bash
# On Hetzner:
sudo systemctl restart cryptomaster
sleep 3
sudo journalctl -u cryptomaster -n 300 --no-pager > /tmp/patch_validation.log
```

### 1.2 Success Signals Expected

Search `/tmp/patch_validation.log` for these lines (in order):

#### Signal 1: Runtime Version (PATCH 5)
```text
[RUNTIME_VERSION] app=CryptoMaster version=V10.13u+2 commit=f61913c branch=main
```
❌ FAIL if: `commit=UNKNOWN branch=UNKNOWN`

#### Signal 2: Maturity Computation (PATCH 1)
```text
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False cold_start=False pair_count=17 min_pair_n=2
```
❌ FAIL if: `trades=0` or `bootstrap=True` or contains `'int' object has no attribute 'get'`

#### Signal 3: Canonical Hydration (PATCH 3)
```text
[LM_HYDRATE_CANONICAL] loaded_closed_trades=500 hydrated_pairs=17 decisive=103 flats=397
[LM_HYDRATE_PAIR]  ETHUSDT BEAR_TREND n=44 decisive=12 wr=75%
[LM_HYDRATE_PAIR]  BTCUSDT BULL_TREND n=38 decisive=8 wr=62%
```
❌ FAIL if: All pairs show `WR=50% EV=0.0` (indicates hydration didn't compute real stats)

#### Signal 4: Economic Health (PATCH 2)
```text
[ECON_CANONICAL] pf=0.75 source=canonical_profit_factor trades=500 wins=79 losses=24
```
❌ FAIL if: PF value differs from dashboard display

#### Signal 5: Market Activity
```text
decision=TAKE symbol=ETHUSDT
[EXEC] regime=BEAR_TREND ...
```
Confirms bot is operating normally after startup.

### 1.3 Validation Script

Save as `/tmp/validate_patches.sh`:

```bash
#!/bin/bash
LOG="/tmp/patch_validation.log"

echo "=== PATCH VALIDATION RESULTS ==="
echo ""

# Check 1: Runtime Version
if grep -q "commit=f61913c branch=main" "$LOG"; then
  echo "✓ PATCH 5: Runtime version shows real commit/branch"
else
  echo "✗ PATCH 5 FAILED: commit/branch not detected"
  grep "RUNTIME_VERSION" "$LOG"
fi

# Check 2: Maturity No Crash
if ! grep -q "'int' object has no attribute" "$LOG"; then
  echo "✓ PATCH 1: Maturity computation type-safe (no crash)"
else
  echo "✗ PATCH 1 FAILED: Type error detected"
  grep "int.*has no attribute" "$LOG"
fi

# Check 3: Maturity Canonical Source
if grep -q "PATCH_MATURITY.*source=canonical" "$LOG"; then
  TRADES=$(grep "PATCH_MATURITY" "$LOG" | grep -oP "trades=\K[0-9]+")
  if [ "$TRADES" -gt 100 ]; then
    echo "✓ PATCH 1: Maturity uses canonical source (trades=$TRADES)"
  else
    echo "✗ PATCH 1 FAILED: Maturity shows trades=$TRADES (expected >100)"
  fi
else
  echo "✗ PATCH 1 FAILED: Maturity log not found"
fi

# Check 4: LM Hydration Real Stats
if grep -q "LM_HYDRATE_PAIR.*wr=" "$LOG"; then
  echo "✓ PATCH 3: LM hydration shows real WR% values"
else
  echo "✗ PATCH 3 FAILED: LM hydration missing or shows defaults"
  grep "LM_HYDRATE" "$LOG" | head -3
fi

# Check 5: Economic Canonical PF
if grep -q "ECON_CANONICAL.*source=canonical" "$LOG"; then
  echo "✓ PATCH 2: Economic health uses canonical profit factor"
else
  echo "✗ PATCH 2 FAILED: Economic health canonical source not detected"
  grep "ECON" "$LOG" | head -2
fi

# Check 6: Market Activity
if grep -q "decision=TAKE\|decision=SKIP\|decision=PASS" "$LOG"; then
  echo "✓ Bot: Market activity detected (normal operation)"
else
  echo "⚠ Bot: No decisions in recent logs (may be too early)"
fi

echo ""
echo "=== VALIDATION COMPLETE ==="
```

Run:
```bash
chmod +x /tmp/validate_patches.sh
/tmp/validate_patches.sh
```

## Phase 2: Cycle Validation (3 Cycles, ~2 Minutes Each)

Monitor for consistency across multiple decision cycles:

```bash
# Terminal 1: Follow logs in real-time
sudo journalctl -u cryptomaster -f

# Terminal 2: Monitor key metrics (every 30 seconds)
while true; do
  echo "=== $(date) ==="
  sudo journalctl -u cryptomaster -n 50 --no-pager | grep -E "decision=|PATCH_MATURITY|ECON_CANONICAL"
  sleep 30
done
```

**Expected across 3 cycles:**
- Consistent maturity oracle values (same trade count, bootstrap state)
- Consistent economic PF value
- Multiple TAKE/SKIP decisions (normal operation)
- No repeated crashes or type errors

## Phase 3: Acceptance Criteria

Patches PASS validation when log shows (one startup + 3 cycles):

```text
✓ [RUNTIME_VERSION] commit=f61913c branch=main
✓ [V10.13u/PATCH_MATURITY] source=canonical trades=500+ bootstrap=False
✓ [LM_HYDRATE_CANONICAL] trades=500 pairs>=10 decisive=100+
✓ [LM_HYDRATE_PAIR] showing real wr=<50-80>% ev=<non-zero>
✓ [ECON_CANONICAL] pf=<matches-dashboard>
✓ No 'int' object crash
✓ No commit=UNKNOWN
✓ Trading decisions flowing normally
```

## Phase 4: If Validation FAILS

### Failure A: Maturity shows `trades=0` or crash

**Debug:**
```bash
grep -n "PATCH_MATURITY\|lm_count\|canonical" /tmp/patch_validation.log
```

**Fix (Patch 1.1):** Enforce canonical source priority in `compute_effective_maturity()`:
```python
# Force canonical as primary source
trades = _extract_trade_count(canonical_state)
if trades == 0:
    # Only fallback if canonical truly empty
    trades = _extract_trade_count(lm_count)
```

**Redeploy**: Commit, push, monitor new logs.

---

### Failure B: LM shows all `WR=50% EV=0.0`

**Debug:**
```bash
grep "LM_HYDRATE_PAIR" /tmp/patch_validation.log | head -5
```

**Fix (Patch 3.1):** Update `hydrate_from_canonical_trades()` to log rejected/default stats separately:
```python
# Log if real data exists but not used
if pnl_sum != 0 and wr == 0.5:
    log.warning(f"[LM_HYDRATE_REJECTED] {key} had real trades but defaulted")
```

Investigate why real PnL isn't being counted. Check field normalization.

---

### Failure C: Economic PF ≠ Dashboard PF

**Debug:**
```bash
grep -A2 "ECON_CANONICAL\|[DASHBOARD].*pf\|profit_factor" /tmp/patch_validation.log
```

**Fix (Patch 2.1):** Verify `canonical_profit_factor()` import and calls:
```bash
grep -n "from src.services.canonical_metrics import canonical_profit_factor" src/services/learning_monitor.py
```

If import missing, add it. If called but different value, check if dashboard uses different subset (decisive-only vs. all trades).

---

### Failure D: Runtime shows `commit=UNKNOWN`

**Debug:**
```bash
echo $COMMIT_SHA $GIT_BRANCH  # On server
grep "RUNTIME_VERSION" /tmp/patch_validation.log
```

**Fix (Patch 5.1):** Write env vars to service file:
```bash
# On Hetzner, in deploy script:
cat > /opt/cryptomaster/.env.runtime << EOF
COMMIT_SHA=f61913c
GIT_BRANCH=main
EOF

# Update systemd:
echo "EnvironmentFile=/opt/cryptomaster/.env.runtime" | sudo tee -a /etc/systemd/system/cryptomaster.service
sudo systemctl daemon-reload
sudo systemctl restart cryptomaster
```

---

### Failure E: RR Conflicts

**Debug:**
```bash
grep "rr=\|RR\|reward.*risk" /tmp/patch_validation.log
```

If RDE logs `rr=1.25` and UI shows `RR 1.5:1` for same decision:

**Fix (Patch 4.1):** Replace all local RR formulas with `canonical_rr()`:
```bash
grep -r "tp.*sl\|distance" src/ bot2/ --include="*.py" | grep -v "canonical_rr" | head -20
```

For each match, replace with `canonical_rr(tp_dist, sl_dist)`.

---

## Phase 5: Final Report (When Validation Complete)

Return to user:

```
FILES CHANGED:
- src/services/realtime_decision_engine.py (Patches 1, 4)
- src/services/learning_monitor.py (Patches 2, 3)
- src/services/version_info.py (Patch 5)
- .github/workflows/deploy.yml (Patch 5)
- tests/test_v10_13u_patches.py (Patch 6)

BUGS FOUND & FIXED:
[List exact issues and lines]

PATCH SUMMARY:
[Concise 3-sentence summary of what changed]

TEST RESULTS:
[Pass/Fail count from test suite]

PRODUCTION LOG PROOF:
[20 lines from journalctl showing success signals]

REMAINING RISKS:
[If any follow-up patches needed, list here]
```

---

## Monitoring Script (Continuous)

Save as `monitor_patches.sh`:

```bash
#!/bin/bash
while true; do
  clear
  echo "[$(date)] Patch Validation Monitor"
  echo ""
  
  LOG="/tmp/cryptomaster_current.log"
  sudo journalctl -u cryptomaster -n 200 --no-pager > "$LOG"
  
  echo "=== PATCH 1: Maturity ==="
  grep "PATCH_MATURITY" "$LOG" | tail -1
  
  echo "=== PATCH 2: Economic ==="
  grep "ECON_CANONICAL" "$LOG" | tail -1
  
  echo "=== PATCH 3: LM Hydration ==="
  grep "LM_HYDRATE_CANONICAL" "$LOG" | tail -1
  
  echo "=== PATCH 5: Runtime ==="
  grep "RUNTIME_VERSION" "$LOG" | tail -1
  
  echo "=== Status: Cycle Count ==="
  grep -c "decision=\|[EXEC]" "$LOG"
  
  echo ""
  echo "Press Ctrl+C to stop. Refreshing every 10s..."
  sleep 10
done
```

Usage: `bash monitor_patches.sh`

---

## Success Timeline

- **T+0min**: Service restart, initial log capture
- **T+2min**: Run validation script
- **T+5min**: First cycle check (3 trading decisions)
- **T+10min**: Cycle 2 check (consistent metrics)
- **T+15min**: Cycle 3 check (confirming stability)
- **T+20min**: Final acceptance report

If all checks pass → Accept patches and move to Phase 2 (position sizing tuning).
If any check fails → Apply minimal follow-up patch from Phase 4 and re-run validation.

---

**Validation Owner**: Claude (Haiku 4.5)
**Protocol Version**: 1.0
**Last Updated**: 2026-04-26
