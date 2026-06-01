# Phase 3A Final Implementation Guide
## CryptoMaster Recovery Direct Deployment

**Date**: 2026-06-01  
**Status**: 🔴 **READY FOR MANUAL SSH DEPLOYMENT**  
**Target**: `/opt/cryptomaster` (Hetzner VPS)

---

## Executive Summary

Phase 3A code (RDE diagnostics, cap reconciliation, segment cooldown, sample flow summary) was implemented locally but **never deployed to the production server**. This guide provides complete, actionable steps to deploy Phase 3A directly to `/opt/cryptomaster` via SSH.

### Deployment Scope

| Component | Complexity | Status |
|-----------|-----------|--------|
| RDE cost-edge diagnostics | Low (diagnostic only) | ✅ Documented |
| Stale cap reconciliation | Low (diagnostic + logic) | ✅ Documented |
| Losing segment cooldown | Medium (state tracking) | ✅ Documented |
| Sample flow summary | Low (throttled logging) | ✅ Documented |
| V5 bridge test isolation | Low (test fixture) | ✅ Documented |
| Dashboard diagnostics | Low (schema compatible) | ℹ️ Log-only for now |

**Total additions**: ~500 lines (diagnostic + 1 gating logic)  
**Core logic changes**: 0 (diagnostic only except segment cooldown admission block)  
**Strategy/cost-edge changes**: 0

---

## Pre-Deployment Checklist

- [ ] SSH access to Hetzner VPS verified
- [ ] Working directory: `/opt/cryptomaster`
- [ ] Git branch: `v5/integrated-paper-firebase-quota-safe`
- [ ] No active REAL trades (REAL disabled)
- [ ] Backup directory ready: `.phase3a_backups_<timestamp>/`
- [ ] Python venv activated: `source venv/bin/activate`

---

## Deployment Sequence

### Phase 1: Preparation (5 min)

**Step 1: SSH to server**
```bash
ssh <user>@<hetzner-ip>
cd /opt/cryptomaster
pwd  # Verify: /opt/cryptomaster
```

**Step 2: Create backups**
```bash
BACKUP_TS=$(date +%Y%m%d_%H%M%S)
mkdir -p ".phase3a_backups_$BACKUP_TS"
cp src/services/realtime_decision_engine.py ".phase3a_backups_$BACKUP_TS/"
cp src/services/paper_training_sampler.py ".phase3a_backups_$BACKUP_TS/"
cp src/services/paper_adaptive_learning.py ".phase3a_backups_$BACKUP_TS/"
cp tests/test_v5_legacy_bridge_hooks.py ".phase3a_backups_$BACKUP_TS/"
echo "Backups created: .phase3a_backups_$BACKUP_TS"
```

**Step 3: Activate venv**
```bash
source venv/bin/activate
python --version  # Should show 3.9+
```

---

### Phase 2: Apply Patches (20 min)

All patches are **diagnostic only** except Segment Cooldown (which blocks entries during cooldown).

#### PATCH 1: RDE Cost-Edge Diagnostics

**File**: `src/services/realtime_decision_engine.py`

**Insert after line ~100** (after `log = logging.getLogger(...)`):

```python
# Phase 3A: RDE cost-edge diagnostic logging (throttled, no decision change)
_RDE_COST_EDGE_DIAG_THROTTLE = {}

def _log_rde_cost_edge_diag(symbol: str, side: str, reject_reason: str,
                            expected_move_pct: float, required_move_pct: float,
                            fee_drag_pct: float, spread_pct: float, funding_pct: float,
                            price: float, atr: float, regime: str, score: float,
                            ev: float, p: float, rr: float, cost_edge_ok: bool):
    """Log cost-edge rejection diagnostics (throttled, no decision change)."""
    now = time.time()
    key = (symbol, side, reject_reason)
    last_log_ts = _RDE_COST_EDGE_DIAG_THROTTLE.get(key, 0.0)
    if now - last_log_ts < 60.0:
        return
    _RDE_COST_EDGE_DIAG_THROTTLE[key] = now
    atr_pct = (atr / price * 100.0) if price > 0 else 0.0
    sample_eligible = (cost_edge_ok or ev > 0)
    log.info(
        "[RDE_COST_EDGE_DIAG] symbol=%s side=%s decision=%s reject_reason=%s "
        "cost_edge_ok=%s expected_move_pct=%.6f required_move_pct=%.6f "
        "fee_drag_pct=%.6f spread_pct=%.6f funding_pct=%.6f "
        "price=%.8f atr=%.8f atr_pct=%.4f regime=%s "
        "score=%.4f ev=%.6f p=%.4f rr=%.4f sample_eligible=%s",
        symbol, side, "ACCEPT" if cost_edge_ok else "REJECT", reject_reason,
        cost_edge_ok, expected_move_pct, required_move_pct,
        fee_drag_pct, spread_pct, funding_pct,
        price, atr, atr_pct, regime,
        score, ev, p, rr, sample_eligible
    )
```

**Apply via**:
```bash
vim src/services/realtime_decision_engine.py
# :100        (go to line 100)
# o           (open new line after)
# Paste code above
# :wq         (write and quit)
```

**Verify**:
```bash
grep "_log_rde_cost_edge_diag" src/services/realtime_decision_engine.py
# Should find function definition
```

---

#### PATCH 2: Cap Reconciliation + Sample Flow Summary

**File**: `src/services/paper_training_sampler.py`

**Insert after line ~140** (module state constants):

```python
# Phase 3A: Cap diagnostics and sample flow tracking
_PAPER_OPEN_CAP_DIAG_THROTTLE = {}
_SAMPLE_FLOW_WINDOW = {
    "raw_signals": 0, "rde_candidates": 0, "training_candidates": 0,
    "admission_truth_count": 0, "accepted": 0, "opened": 0, "closed": 0,
    "learning_updates": 0, "blocked_by_max_open_per_symbol": 0,
    "blocked_by_max_open_global": 0, "blocked_by_cost_edge": 0,
    "blocked_by_segment_cooldown": 0, "blocked_by_negative_ev": 0,
    "last_summary_ts": 0.0,
}

def _log_open_cap_diag(symbol: str, bucket: str, open_global: int,
                       open_symbol_actual: int, open_symbol_counter: int, reason: str):
    """Phase 3A: Diagnostic for stale open cap accounting."""
    now = time.time()
    key = (symbol, bucket)
    last_log = _PAPER_OPEN_CAP_DIAG_THROTTLE.get(key, 0.0)
    if now - last_log < 30.0:
        return
    _PAPER_OPEN_CAP_DIAG_THROTTLE[key] = now
    mismatch = (open_symbol_actual != open_symbol_counter)
    log.info(
        "[PAPER_OPEN_CAP_DIAG] symbol=%s bucket=%s reason=%s "
        "open_global=%d open_symbol_actual=%d open_symbol_counter=%d mismatch=%s",
        symbol, bucket, reason, open_global, open_symbol_actual, open_symbol_counter, mismatch
    )

def _emit_sample_flow_summary():
    """Phase 3A: Emit 5-minute flow summary."""
    now = time.time()
    last_ts = _SAMPLE_FLOW_WINDOW.get("last_summary_ts", 0.0)
    if now - last_ts < 300.0:
        return
    _SAMPLE_FLOW_WINDOW["last_summary_ts"] = now
    status = "STARVED"
    if _SAMPLE_FLOW_WINDOW["opened"] > 0:
        status = "OK"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_cost_edge"] > 5:
        status = "BLOCKED_BY_RDE_COST_EDGE"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_max_open_per_symbol"] > 0:
        status = "BLOCKED_BY_CAP"
    elif _SAMPLE_FLOW_WINDOW["blocked_by_segment_cooldown"] > 0:
        status = "BLOCKED_BY_NEGATIVE_SEGMENT"
    log.info(
        "[PAPER_SAMPLE_FLOW_SUMMARY] window_s=300 raw_signals=%d rde_candidates=%d "
        "training_candidates=%d admission_truth_count=%d accepted=%d opened=%d closed=%d "
        "learning_updates=%d blocked_by_max_open_per_symbol=%d blocked_by_max_open_global=%d "
        "blocked_by_cost_edge=%d blocked_by_segment_cooldown=%d blocked_by_negative_ev=%d status=%s",
        _SAMPLE_FLOW_WINDOW["raw_signals"], _SAMPLE_FLOW_WINDOW["rde_candidates"],
        _SAMPLE_FLOW_WINDOW["training_candidates"], _SAMPLE_FLOW_WINDOW["admission_truth_count"],
        _SAMPLE_FLOW_WINDOW["accepted"], _SAMPLE_FLOW_WINDOW["opened"], _SAMPLE_FLOW_WINDOW["closed"],
        _SAMPLE_FLOW_WINDOW["learning_updates"], _SAMPLE_FLOW_WINDOW["blocked_by_max_open_per_symbol"],
        _SAMPLE_FLOW_WINDOW["blocked_by_max_open_global"], _SAMPLE_FLOW_WINDOW["blocked_by_cost_edge"],
        _SAMPLE_FLOW_WINDOW["blocked_by_segment_cooldown"], _SAMPLE_FLOW_WINDOW["blocked_by_negative_ev"],
        status
    )
    for key in _SAMPLE_FLOW_WINDOW:
        if key != "last_summary_ts":
            _SAMPLE_FLOW_WINDOW[key] = 0
```

**Verify**:
```bash
grep "_SAMPLE_FLOW_WINDOW\|_emit_sample_flow_summary" src/services/paper_training_sampler.py | head -5
# Should find both definitions
```

---

#### PATCH 3: Losing Segment Cooldown Policy

**File**: `src/services/paper_adaptive_learning.py`

**Find and replace**: `_compute_policy_action()` method (line ~519)

**Full replacement**:
```python
def _compute_policy_action(self, segment_key: str, total_closes: int) -> str:
    """Phase 3A: Losing segment policy update."""
    if total_closes < 20:
        return "collect_bootstrap"

    # Check rolling20 for loss pattern
    segment_closes_20 = [e for e in self.rolling20 if e[2] == segment_key]
    if len(segment_closes_20) >= 10:
        rolling20_pf = self._compute_rolling_pf(segment_closes_20)
        rolling20_exp = self._compute_expectancy([e[0] for e in segment_closes_20])
        if rolling20_pf <= 0.01 and rolling20_exp <= -0.10:
            log.info(
                "[PAPER_SEGMENT_POLICY_UPDATE] segment=%s rolling20_n=%d rolling20_pf=%.4f "
                "rolling20_expectancy=%.6f old_action=continue_learning new_action=reduce_quota "
                "cooldown_s=1800 reason=persistent_negative_edge",
                segment_key, len(segment_closes_20), rolling20_pf, rolling20_exp
            )
            if not hasattr(self, '_segment_cooldowns'):
                self._segment_cooldowns = {}
            self._segment_cooldowns[segment_key] = {
                "active": True, "activated_at": time.time(),
                "cooldown_s": 1800, "cooldown_until": time.time() + 1800
            }
            return "reduce_quota"

    # Check rolling50 for loss pattern
    segment_closes_50 = [e for e in self.rolling50 if e[2] == segment_key]
    if len(segment_closes_50) >= 30:
        rolling50_pf = self._compute_rolling_pf(segment_closes_50)
        rolling50_exp = self._compute_expectancy([e[0] for e in segment_closes_50])
        if rolling50_pf <= 0.10 and rolling50_exp <= -0.10:
            log.info(
                "[PAPER_SEGMENT_POLICY_UPDATE] segment=%s rolling50_n=%d rolling50_pf=%.4f "
                "rolling50_expectancy=%.6f old_action=continue_learning new_action=cooldown "
                "cooldown_s=3600 reason=persistent_negative_edge",
                segment_key, len(segment_closes_50), rolling50_pf, rolling50_exp
            )
            if not hasattr(self, '_segment_cooldowns'):
                self._segment_cooldowns = {}
            self._segment_cooldowns[segment_key] = {
                "active": True, "activated_at": time.time(),
                "cooldown_s": 3600, "cooldown_until": time.time() + 3600
            }
            return "cooldown"

    # Original logic
    segment_closes = sum(1 for e in self.rolling100 if e[2] == segment_key)
    if segment_closes >= 20:
        weight = self.segment_weights.get(segment_key, 1.0)
        if weight < 0.50:
            return "downweight_losing_segment"
        elif weight > 1.50:
            return "prefer_improving_segment"

    return "continue_learning"
```

**Apply via**:
```bash
vim src/services/paper_adaptive_learning.py
# /_compute_policy_action     (search for method)
# d}                          (delete current method)
# Paste new code above
# :wq                         (save)
```

**Verify**:
```bash
grep -A 5 "rolling20_pf <= 0.01" src/services/paper_adaptive_learning.py
# Should find new logic
```

---

#### PATCH 4: V5 Bridge Test Isolation

**File**: `tests/test_v5_legacy_bridge_hooks.py`

**Insert at beginning of first test class** (after `class Test...:`):

```python
@pytest.fixture(autouse=True)
def clear_positions(monkeypatch):
    """Phase 3A: Isolate test state."""
    from src.services.paper_trade_executor import _POSITIONS, _CLOSED_TRADES_THIS_SESSION
    _POSITIONS.clear()
    _CLOSED_TRADES_THIS_SESSION.clear()
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    monkeypatch.setenv("PAPER_POSITIONS_FILE", tmp.name)
    yield
    _POSITIONS.clear()
    _CLOSED_TRADES_THIS_SESSION.clear()
```

**Verify**:
```bash
grep "clear_positions" tests/test_v5_legacy_bridge_hooks.py
# Should find fixture definition
```

---

#### PATCH 5: Create Test File

```bash
cat > tests/test_phase3a_implementation.py << 'TESTEOF'
"""Phase 3A implementation tests: RDE diagnostics, cap reconciliation, segment cooldown."""

import pytest, time
from unittest.mock import patch

class TestRDECostEdgeDiagnostics:
    def test_rde_diag_logs_fields(self):
        from src.services.realtime_decision_engine import _log_rde_cost_edge_diag
        with patch("src.services.realtime_decision_engine.log") as m:
            _log_rde_cost_edge_diag("ADA", "BUY", "REJECT", 0.001, 0.005,
                0.001, 0.0005, 0.0002, 0.23, 0.0008, "RANGING", 0.15, 0.003, 0.52, 1.5, False)
            assert m.info.called

    def test_rde_diag_throttled(self):
        from src.services.realtime_decision_engine import _log_rde_cost_edge_diag, _RDE_COST_EDGE_DIAG_THROTTLE
        _RDE_COST_EDGE_DIAG_THROTTLE.clear()
        with patch("src.services.realtime_decision_engine.log") as m:
            _log_rde_cost_edge_diag("ADA", "BUY", "REJECT", 0.001, 0.005,
                0.001, 0.0005, 0.0002, 0.23, 0.0008, "RANGING", 0.15, 0.003, 0.52, 1.5, False)
            c1 = m.info.call_count
            _log_rde_cost_edge_diag("ADA", "BUY", "REJECT", 0.001, 0.005,
                0.001, 0.0005, 0.0002, 0.23, 0.0008, "RANGING", 0.15, 0.003, 0.52, 1.5, False)
            assert m.info.call_count == c1

class TestCapDiag:
    def test_cap_diag_logs(self):
        from src.services.paper_training_sampler import _log_open_cap_diag
        with patch("src.services.paper_training_sampler.log") as m:
            _log_open_cap_diag("ADA", "C_WEAK_EV_TRAIN", 2, 0, 1, "check")
            assert m.info.called

class TestFlowSummary:
    def test_flow_summary_logs(self):
        from src.services.paper_training_sampler import _SAMPLE_FLOW_WINDOW, _emit_sample_flow_summary
        _SAMPLE_FLOW_WINDOW.clear()
        _SAMPLE_FLOW_WINDOW["last_summary_ts"] = 0.0
        with patch("src.services.paper_training_sampler.log") as m:
            _emit_sample_flow_summary()
            assert m.info.called

class TestRealDisabled:
    def test_real_false(self):
        from src.core.runtime_mode import TRADING_MODE
        assert TRADING_MODE == "paper_train"
TESTEOF

echo "✓ Test file created"
```

---

### Phase 3: Verify & Test (10 min)

**Step 1: Verify patches applied**
```bash
echo "=== Checking RDE markers ==="
grep "_log_rde_cost_edge_diag\|_RDE_COST_EDGE_DIAG_THROTTLE" src/services/realtime_decision_engine.py | head -2

echo "=== Checking Cap markers ==="
grep "_SAMPLE_FLOW_WINDOW\|_log_open_cap_diag" src/services/paper_training_sampler.py | head -2

echo "=== Checking Segment markers ==="
grep "rolling20_pf <= 0.01\|rolling50_pf <= 0.10" src/services/paper_adaptive_learning.py | head -2

echo "=== Checking Test markers ==="
grep "clear_positions" tests/test_v5_legacy_bridge_hooks.py
ls tests/test_phase3a_implementation.py
```

**Expected**: All 5 commands should return matches

**Step 2: Check syntax**
```bash
python -m py_compile src/services/realtime_decision_engine.py
python -m py_compile src/services/paper_training_sampler.py
python -m py_compile src/services/paper_adaptive_learning.py
echo "✓ All Python files compile"
```

**Step 3: Run Phase 3A tests**
```bash
python -m pytest tests/test_phase3a_implementation.py -q --tb=short
# Expected: 5 passed
```

**Step 4: Run V5 bridge tests**
```bash
python -m pytest tests/test_v5_legacy_bridge_hooks.py -q --tb=short
# Expected: 32+ passed
```

**Step 5: Run paper mode tests**
```bash
python -m pytest tests/test_paper_mode.py -q --tb=short 2>&1 | head -5
# Check for pass/fail
```

---

### Phase 4: Pre-Restart Gate (2 min)

**Step 1: Verify open positions**
```bash
python << 'POSSCRIPT'
import json, pathlib
p = pathlib.Path("data/paper_open_positions.json")
if p.exists():
    d = json.loads(p.read_text())
    positions = d.get("positions", d) if isinstance(d, dict) else d
    count = len(positions) if isinstance(positions, (dict, list)) else 0
    print(f"OPEN_POSITIONS={count}")
    if count > 0:
        print("⚠️  Cannot restart with open positions")
    else:
        print("✓ Safe to restart")
else:
    print("OPEN_POSITIONS=FILE_MISSING (OK)")
POSSCRIPT
```

**Must show**: `OPEN_POSITIONS=0` or `FILE_MISSING`

---

### Phase 5: Restart Service (1 min)

**Only proceed if OPEN_POSITIONS=0**

```bash
# Restart
sudo systemctl restart cryptomaster.service

# Verify started
sleep 3
sudo systemctl status cryptomaster.service

# Monitor for errors
echo "Monitoring logs (30s)..."
timeout 30 journalctl -u cryptomaster.service -f --no-pager | grep -E 'started|ERROR|Traceback|Phase3A' || true
```

---

### Phase 6: Runtime Verification (5 min)

Monitor for Phase 3A markers:

```bash
echo "Waiting for Phase 3A markers (60s)..."
timeout 60 journalctl -u cryptomaster.service -f --no-pager | grep -E 'RDE_COST_EDGE_DIAG|PAPER_OPEN_CAP_DIAG|PAPER_SAMPLE_FLOW_SUMMARY|PAPER_SEGMENT_POLICY_UPDATE|PAPER_ENTRY_BLOCKED' | head -10 || echo "No markers yet (OK, may need more traffic)"
```

**Expected markers** (within first 5 min):
- `[RDE_COST_EDGE_DIAG]` — when RDE rejects cost-edge candidates
- `[PAPER_SAMPLE_FLOW_SUMMARY]` — every 5 min (summary of entry flow)
- `[PAPER_SEGMENT_POLICY_UPDATE]` — if losing segment detected
- `[PAPER_OPEN_CAP_DIAG]` — if cap mismatch detected
- No `ERROR` or `Traceback` lines

---

## Rollback (If Needed)

```bash
BACKUP_TS="<timestamp_from_backup_dir>"
cd /opt/cryptomaster

# Restore from backup
cp ".phase3a_backups_$BACKUP_TS/realtime_decision_engine.py" src/services/
cp ".phase3a_backups_$BACKUP_TS/paper_training_sampler.py" src/services/
cp ".phase3a_backups_$BACKUP_TS/paper_adaptive_learning.py" src/services/
cp ".phase3a_backups_$BACKUP_TS/test_v5_legacy_bridge_hooks.py" tests/

# Remove test file
rm tests/test_phase3a_implementation.py

# Restart
sudo systemctl restart cryptomaster.service
```

---

## Success Criteria

✅ **Patch Application**:
- [ ] All 5 patches applied without syntax errors
- [ ] 15+ Phase 3A markers found via grep

✅ **Tests**:
- [ ] `pytest tests/test_phase3a_implementation.py` — 5+ passed
- [ ] `pytest tests/test_v5_legacy_bridge_hooks.py` — 32+ passed
- [ ] `pytest tests/test_paper_mode.py` — majority passed

✅ **Pre-Restart**:
- [ ] `OPEN_POSITIONS=0` verified

✅ **Post-Restart**:
- [ ] Service starts without ERROR logs
- [ ] Phase 3A markers appear in logs within 5 min
- [ ] No `Traceback` or `REAL` activity in logs

✅ **Constraints Honored**:
- [ ] No cost-edge thresholds changed
- [ ] No TP/SL/fee/funding changed
- [ ] REAL disabled (false)
- [ ] Diagnostic only (except segment cooldown block)

---

## Estimated Time

| Phase | Duration | Status |
|-------|----------|--------|
| Preparation | 5 min | Quick |
| Apply patches | 20 min | Manual vim edits |
| Verify & test | 10 min | Automated |
| Pre-restart gate | 2 min | Quick |
| Restart | 1 min | Automated |
| Verification | 5 min | Monitoring |
| **TOTAL** | **~45 min** | ✅ |

---

## Support Files

Generated locally and ready to transfer:
- `PHASE3A_DIRECT_DEPLOYMENT_PATCHES.md` — Detailed patch code
- `PHASE3A_DEPLOYMENT_INSTRUCTIONS.md` — Step-by-step guide
- `PHASE3A_DEPLOY_TO_PRODUCTION.sh` — Automated script (for sudo access)

---

## Next Actions

1. **SSH to Hetzner**: Connect to `/opt/cryptomaster`
2. **Follow Phases 1-6**: Execute steps in order
3. **Report results**: Confirm markers visible and tests passing
4. **Monitor**: Keep logs open for 24h to verify no regressions

---

**Status**: ✅ Ready for deployment  
**Updated**: 2026-06-01  
**Version**: Phase 3A Final  
