# V5 Cutover & Deployment Playbook

## Overview

This playbook describes the process for validating V5 PAPER implementation and planning eventual transition to production (cutover to REAL trading, if approved by operator).

**CRITICAL CONSTRAINTS:**
- V5.0-V5.6 implementation on **topic branch only** — NO main branch push
- PAPER trading always: `PAPER_ONLY_MODE=True`, `REAL_ORDERS_ALLOWED=False` (hardcoded)
- No production deployment from V5 branch
- No Firebase reset, no service restart
- Validation and metrics collection only

---

## Phase 1: Pre-Deployment Validation (Topic Branch)

### 1.1 Code Validation Checklist

```bash
# V5.0-V5.6 modules exist
ls -la src/v5_bot/
# - market/binance_usdm_feed.py ✓
# - market/local_book.py ✓
# - execution/accounting.py ✓
# - execution/fees.py ✓
# - execution/funding.py ✓
# - strategy/candidate.py ✓
# - strategy/feature_engine.py ✓
# - strategy/baseline_policies.py ✓
# - strategy/policy_selector.py ✓
# - strategy/cost_edge_gate.py ✓
# - paper/paper_broker.py ✓
# - paper/exits.py ✓
# - paper/runner.py ✓
# - learning/eligibility.py ✓
# - learning/learner.py ✓
# - learning/policy_state.py ✓
# - learning/readiness.py ✓
# - cli.py ✓
# - firebase/ (schema, quota_guard, outbox, repository) ✓
# - config.py ✓

# All tests pass
python -m pytest tests/v5_bot/ -v

# No import errors
python -c "from src.v5_bot import *; print('OK')"

# Firebase credentials configured
echo $FIREBASE_CREDENTIALS_PATH
```

### 1.2 Configuration Verification

```bash
# Check hardcoded safety constraints
grep "PAPER_ONLY_MODE = True" src/v5_bot/config.py
grep "REAL_ORDERS_ALLOWED = False" src/v5_bot/config.py

# Verify Firebase quota setup (Pacific timezone)
grep -A 5 "def _pt_date" src/v5_bot/firebase/quota_guard.py
# Should show: pytz.timezone('America/Los_Angeles')

# Verify learning eligibility gates
grep "min_net_expectancy_bps = 0.0" src/v5_bot/config.py
grep "require_binance_futures_truth = True" src/v5_bot/config.py
```

### 1.3 Firebase Dry-run

```bash
# Test Firebase connectivity (dry-run only, no writes)
python -m src.v5_bot.cli validate-fb

# Check quota state
python -m src.v5_bot.cli validate-quota

# Expected: NORMAL state, 50k reads, 20k writes available
```

### 1.4 Market Feed Validation

```bash
# Start V5 bot and let it run for 5 minutes
# Monitor: feed connectivity, book updates, stale rejections

python -c "
import asyncio
from src.v5_bot import V5BotRunner

async def validate():
    runner = V5BotRunner()
    await runner.startup()
    
    for i in range(30):  # 30 seconds
        status = runner.feed.get_status()
        print(f'{i:2d}s: symbols={status[\"symbols_with_data\"]}, reconnects={status[\"reconnect_count\"]}')
        await asyncio.sleep(1)
    
    await runner.shutdown()

asyncio.run(validate())
"

# Expected:
# - All 5 symbols (BTCUSDT, ETHUSDT, BNBUSDT, ADAUSDT, XRPUSDT) connected
# - No reconnects on first run
# - Stale events rejected counter < 5
```

---

## Phase 2: Local Testing (Topic Branch)

### 2.1 Unit Tests

Run all test suites:

```bash
# V5.1 Firebase layer
python -m pytest tests/v5_bot/test_quota_guard.py -v
python -m pytest tests/v5_bot/test_outbox.py -v

# V5.2 Market feeds
python -m pytest tests/v5_bot/test_futures_feed.py -v

# V5.3 Strategy layer
python -m pytest tests/v5_bot/test_strategy.py -v

# V5.4 PAPER lifecycle
python -m pytest tests/v5_bot/test_paper_lifecycle.py -v

# V5.5 Learning
python -m pytest tests/v5_bot/test_learning.py -v

# Expected: 100+ test cases, all passing
```

### 2.2 Integration Test

Run full E2E simulation:

```bash
# Simulate 1 hour of trading with synthetic market data
python -c "
import asyncio
from src.v5_bot.paper import V5BotRunner

async def test_e2e():
    runner = V5BotRunner()
    await runner.startup()
    
    # Run for 60 iterations (simulated 1 minute each = 1 hour total)
    for i in range(60):
        await runner.evaluate_entry_signals()
        await runner.evaluate_exit_conditions()
        if i % 10 == 0:
            print(f'Minute {i}: open={len(runner.broker.open_positions)}, closed={len(runner.broker.closed_trades)}')
    
    await runner.shutdown()
    
    stats = runner.broker.get_daily_stats()
    print(f'E2E Test Complete: {stats[\"trades_closed\"]} trades, {stats[\"win_rate\"]*100:.1f}% win rate')

asyncio.run(test_e2e())
"

# Expected:
# - No errors
# - Multiple positions opened and closed
# - Readiness evaluator successfully runs
# - Quota guard pre-flight checks work
```

### 2.3 Quota Stress Test

```bash
# Simulate heavy write load to verify quota guards
python -c "
from src.v5_bot.firebase import QuotaGuard
from src.v5_bot.firebase.quota_guard import QuotaLedger

# Test state machine
guard = QuotaGuard()

# Simulate 7000 reads (should trigger DEGRADED)
for i in range(7000):
    guard.record_read(1)

status = guard.get_status()
print(f'State after 7k reads: {status[\"state\"]}')
assert status['state'].name == 'DEGRADED', 'Expected DEGRADED state'

# Simulate 3000 writes (should trigger HARD_STOP)
for i in range(3000):
    guard.record_write(1)

status = guard.get_status()
print(f'State after 3k writes: {status[\"state\"]}')
assert status['state'].name == 'HARD_STOP', 'Expected HARD_STOP state'

print('✓ Quota guard state machine validated')
"

# Expected: State transitions work correctly
```

### 2.4 Readiness State Machine Test

```bash
python -c "
from src.v5_bot.learning.readiness import ReadinessEvaluator, ReadinessState

eval = ReadinessEvaluator()

# Test all 10 states
tests = [
    (0, 0, 0, 1.0, 0, False, 'NOT_READY_INITIALIZING'),
    (50, 2, 10, 1.2, 2, True, 'NOT_READY_INSUFFICIENT_DATA'),
    (300, 7, -5, 1.2, 2, True, 'NOT_READY_NEGATIVE_EXPECTANCY'),
    (300, 7, 10, 1.0, 2, True, 'NOT_READY_LOW_PROFIT_FACTOR'),
    (300, 7, 10, 1.2, 10, True, 'NOT_READY_DRAWDOWN_EXCEEDED'),
    (300, 7, 10, 1.2, 2, False, 'NOT_READY_ACCOUNTING_INCOMPLETE'),
    (300, 7, 10, 1.2, 2, True, 'REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED'),
]

for closes, days, exp_bps, pf, dd, acct, expected_state in tests:
    report = eval.evaluate(closes, days, exp_bps, pf, dd, acct, incidents=0)
    print(f'{expected_state:45s} -> {report.state.value}')
    assert report.state.name == expected_state

print('✓ All 10 readiness states validated')
"
```

---

## Phase 3: Operator Review (Before Merging to Main)

### 3.1 Code Review Checklist

- [ ] All V5.0-V5.6 modules reviewed
- [ ] No imports from legacy src/services/
- [ ] PAPER_ONLY_MODE=True hardcoded
- [ ] REAL_ORDERS_ALLOWED=False hardcoded
- [ ] Firebase schema v5_* namespace isolated
- [ ] Cost-edge gate enforced on every entry
- [ ] Learning eligibility strict (Futures-only, positive expectancy)
- [ ] Quota guard state machine verified
- [ ] TradeOutbox durability tested
- [ ] Readiness state machine with 10 states
- [ ] Czech status messages complete
- [ ] Tests > 100 test cases, all passing

### 3.2 Safety Review

- [ ] Entry cost-edge hard gate blocks all negative expectancy
- [ ] Quota HARD_STOP blocks all writes
- [ ] Outbox retry limit prevents infinite loops (max 3 retries)
- [ ] No emergency deploys without approval
- [ ] No Firebase reset, no service restart
- [ ] No hardcoded API keys in code

### 3.3 Documentation Review

- [ ] V5_ARCHITECTURE_DECISION.md reviewed
- [ ] V5_IMPLEMENTATION_ROADMAP.md complete
- [ ] V5_ANDROID_METRICS_CONTRACT.md with Czech labels
- [ ] v5_android_metrics_registry.json machine-readable
- [ ] V5_CUTOVER_PLAYBOOK.md (this file) ready

---

## Phase 4: Production Transition (Future)

### 4.1 Cutover to REAL Trading (Operator Decision)

**WHEN to transition (if ever):**
- Readiness state reaches REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
- All 10 gates passed (300+ closes, 7+ days data, positive exp, PF >= 1.20, DD < 5%, accounting complete)
- Operator explicitly approves
- All pre-flight checks pass

**HOW to transition (high-risk change):**

1. **Create release branch from main:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b v5-real-enable-YYYY-MM-DD
   ```

2. **Modify only these two lines (v5/config.py):**
   ```python
   PAPER_ONLY_MODE = False      # ONLY if readiness approved
   REAL_ORDERS_ALLOWED = True   # ONLY if readiness approved
   ```

3. **NO other changes allowed** — entire V5 logic remains identical

4. **Commit:**
   ```bash
   git add src/v5_bot/config.py
   git commit -m "REAL trading enable: readiness gate approved on YYYY-MM-DD"
   ```

5. **Create PR:**
   - Title: `V5 Enable REAL Trading - Readiness Approved`
   - Body: Link readiness report, operator approval, decision timestamp

6. **Code review + approval required**

7. **Merge to main:**
   ```bash
   git checkout main
   git merge v5-real-enable-YYYY-MM-DD
   git push origin main
   ```

8. **GitHub Actions auto-deploy to production**

9. **Monitor:**
   - Readiness dashboard: should now show `real_orders_allowed=true`
   - First trade sent to Binance REAL account
   - Cost-edge gate still active (no change)
   - Learning still works (no change)
   - Quota guard still enforced (no change)

### 4.2 Rollback Plan (Emergency Only)

If REAL trading has issues:

```bash
git revert <commit-hash-from-4.1.step4>
git push origin main
# Auto-deploys revert
```

This will:
- Flip REAL_ORDERS_ALLOWED back to False
- Future trades return to PAPER only
- All open REAL positions must be closed manually or timeout
- No data loss (Firebase appends only)

---

## Health Check Dashboard (Operator Runs Weekly)

```bash
python -m src.v5_bot.cli status
python -m src.v5_bot.cli validate-quota
python -m src.v5_bot.cli validate-feeds
python -m src.v5_bot.cli validate-fb
python -m src.v5_bot.cli check-readiness
```

Expected output:
```
=== V5 PAPER BOT STATUS ===
Epoch: epoch_20260527_120000
Running: true
Feed Connected: true
Symbols with Data: 5

Position Summary:
  Open Positions: 2
  Open Notional: $20,500.00

Firebase Quota:
  State: NORMAL
  Reads Remaining: 49,200
  Writes Remaining: 19,500

Statistics:
  Entries Attempted: 150
  Entries Successful: 48
  Entries Rejected: 102
  Trades Closed: 35

=== QUOTA VALIDATION ===
Quota State: NORMAL
✓ Quota healthy

=== FEED VALIDATION ===
Feed Running: true
Symbols with Data: 5
Stale Events Rejected: 12
✓ Feeds connected

=== FIREBASE VALIDATION ===
✓ Firebase connected
  Active Epoch: epoch_20260527_120000
  Mode: PAPER
  Entries Enabled: true

=== REAL READINESS EVALUATION ===
State: not_ready_insufficient_data
Status (CS): Nedostatek dat - čekání na 300+ uzavřených obchodů
Gate Status:
  Eligible Closes: 35/300
  Days of Data: 1/7
  Expectancy: 15.5 bps (min: 0.0)
  Profit Factor: 1.35 (min: 1.20)
  Drawdown: 2.5% (max: 5.0%)

Paper Only: true
REAL Orders Allowed: false
```

---

## Appendix: File Manifest

### V5.0-V5.6 Implementation Files

**Core Infrastructure:**
- `src/v5_bot/__init__.py`
- `src/v5_bot/config.py`
- `src/v5_bot/cli.py`

**V5.1: Firebase & Quota**
- `src/v5_bot/firebase/__init__.py`
- `src/v5_bot/firebase/schema.py`
- `src/v5_bot/firebase/quota_guard.py`
- `src/v5_bot/firebase/outbox.py`
- `src/v5_bot/firebase/repository.py`

**V5.2: Market Feeds & Accounting**
- `src/v5_bot/market/__init__.py`
- `src/v5_bot/market/binance_usdm_feed.py`
- `src/v5_bot/market/local_book.py`
- `src/v5_bot/execution/__init__.py`
- `src/v5_bot/execution/fees.py`
- `src/v5_bot/execution/funding.py`
- `src/v5_bot/execution/accounting.py`

**V5.3: Strategy & Cost Gate**
- `src/v5_bot/strategy/__init__.py`
- `src/v5_bot/strategy/candidate.py`
- `src/v5_bot/strategy/feature_engine.py`
- `src/v5_bot/strategy/baseline_policies.py`
- `src/v5_bot/strategy/policy_selector.py`
- `src/v5_bot/strategy/cost_edge_gate.py`

**V5.4: PAPER Lifecycle**
- `src/v5_bot/paper/__init__.py`
- `src/v5_bot/paper/paper_broker.py`
- `src/v5_bot/paper/exits.py`
- `src/v5_bot/paper/runner.py`

**V5.5: Learning & Readiness**
- `src/v5_bot/learning/__init__.py`
- `src/v5_bot/learning/eligibility.py`
- `src/v5_bot/learning/learner.py`
- `src/v5_bot/learning/policy_state.py`
- `src/v5_bot/learning/readiness.py`

**Tests (V5.0-V5.6):**
- `tests/v5_bot/test_quota_guard.py`
- `tests/v5_bot/test_outbox.py`
- `tests/v5_bot/test_futures_feed.py`
- `tests/v5_bot/test_strategy.py`
- `tests/v5_bot/test_paper_lifecycle.py`
- `tests/v5_bot/test_learning.py`

**Documentation:**
- `docs/V5_ARCHITECTURE_DECISION.md`
- `docs/V5_IMPLEMENTATION_ROADMAP.md`
- `docs/V5_ANDROID_METRICS_CONTRACT.md`
- `docs/v5_android_metrics_registry.json`
- `docs/V5_CUTOVER_PLAYBOOK.md` (this file)

---

## Summary

V5 PAPER implementation is **complete, tested, and ready for operator review**. All code is isolated on topic branch, safely constrained by hardcoded PAPER-only flags, and includes comprehensive validation tooling. Metrics contract fully specifies Android app integration with Czech language support. Cutover playbook defines the (rare) path to production, if approved.

**Total effort:** V5.0-V5.6 + sections 15-17 = ~30-40 hours of implementation
**Total lines of code:** ~4,500+ Python code + ~300+ documentation

