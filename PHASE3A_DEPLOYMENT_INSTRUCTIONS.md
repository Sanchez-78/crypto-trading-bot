# Phase 3A Direct Deployment Instructions
## For /opt/cryptomaster on Hetzner VPS

**Status**: Patches documented and ready for deployment

---

## Quick Start (Copy-Paste SSH Commands)

### 1. SSH to Server
```bash
ssh <user>@<hetzner-vps-ip>
cd /opt/cryptomaster
```

### 2. Backup Original Files
```bash
mkdir -p .phase3a_backups_$(date +%Y%m%d_%H%M%S)
cp src/services/{realtime_decision_engine,paper_training_sampler,paper_adaptive_learning}.py .phase3a_backups_*/
cp tests/test_v5_legacy_bridge_hooks.py .phase3a_backups_*/
```

### 3. Apply PATCH 1: RDE Cost-Edge Diagnostics

**File**: `src/services/realtime_decision_engine.py`

**Location**: After module imports (line ~100), add:

```python
# Phase 3A: RDE cost-edge diagnostic logging (throttled, no decision change)
_RDE_COST_EDGE_DIAG_THROTTLE = {}  # (symbol, side, reject_reason) -> timestamp

def _log_rde_cost_edge_diag(symbol: str, side: str, reject_reason: str,
                            expected_move_pct: float, required_move_pct: float,
                            fee_drag_pct: float, spread_pct: float, funding_pct: float,
                            price: float, atr: float, regime: str, score: float,
                            ev: float, p: float, rr: float, cost_edge_ok: bool):
    """Log cost-edge rejection diagnostics (throttled, no decision change)."""
    now = time.time()
    key = (symbol, side, reject_reason)
    last_log_ts = _RDE_COST_EDGE_DIAG_THROTTLE.get(key, 0.0)
    if now - last_log_ts < 60.0:  # Throttle: once per 60s per key
        return

    _RDE_COST_EDGE_DIAG_THROTTLE[key] = now
    atr_pct = (atr / price * 100.0) if price > 0 else 0.0
    sample_eligible = (cost_edge_ok or ev > 0)

    log.info(
        "[RDE_COST_EDGE_DIAG] "
        "symbol=%s side=%s decision=%s reject_reason=%s "
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

**Apply via vim/nano**:
```bash
vim +100 src/services/realtime_decision_engine.py
# :100 (go to line 100)
# o (open new line)
# Paste the code above
# :wq (save)
```

### 4. Apply PATCH 2: Cap Reconciliation + Sample Flow

**File**: `src/services/paper_training_sampler.py`

**Location**: After module state constants (line ~140), add:

```python
# Phase 3A: Cap diagnostics and sample flow tracking
_PAPER_OPEN_CAP_DIAG_THROTTLE = {}  # (symbol, bucket) -> timestamp
_SAMPLE_FLOW_WINDOW = {
    "raw_signals": 0,
    "rde_candidates": 0,
    "training_candidates": 0,
    "admission_truth_count": 0,
    "accepted": 0,
    "opened": 0,
    "closed": 0,
    "learning_updates": 0,
    "blocked_by_max_open_per_symbol": 0,
    "blocked_by_max_open_global": 0,
    "blocked_by_cost_edge": 0,
    "blocked_by_segment_cooldown": 0,
    "blocked_by_negative_ev": 0,
    "last_summary_ts": 0.0,
}

def _log_open_cap_diag(symbol: str, bucket: str, open_global: int,
                       open_symbol_actual: int, open_symbol_counter: int,
                       reason: str):
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
        "blocked_by_cost_edge=%d blocked_by_segment_cooldown=%d blocked_by_negative_ev=%d "
        "status=%s",
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

### 5. Apply PATCH 3: Segment Cooldown Policy

**File**: `src/services/paper_adaptive_learning.py`

**Location**: Update `_compute_policy_action()` method (line ~519)

**Replace the entire method with**:

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
                "active": True,
                "activated_at": time.time(),
                "cooldown_s": 1800,
                "cooldown_until": time.time() + 1800
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
                "active": True,
                "activated_at": time.time(),
                "cooldown_s": 3600,
                "cooldown_until": time.time() + 3600
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

### 6. Apply PATCH 4: V5 Bridge Test Isolation

**File**: `tests/test_v5_legacy_bridge_hooks.py`

**Location**: Add fixture at the start of first test class

```python
@pytest.fixture(autouse=True)
def clear_positions(monkeypatch):
    """Phase 3A: Isolate test state."""
    from src.services.paper_trade_executor import _POSITIONS, _CLOSED_TRADES_THIS_SESSION
    _POSITIONS.clear()
    _CLOSED_TRADES_THIS_SESSION.clear()

    # Monkeypatch data file to use temp location
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    monkeypatch.setenv("PAPER_POSITIONS_FILE", tmp.name)

    yield

    _POSITIONS.clear()
    _CLOSED_TRADES_THIS_SESSION.clear()
```

### 7. Create Test File

```bash
cat > tests/test_phase3a_implementation.py << 'EOF'
"""Phase 3A implementation tests."""

import pytest
import time
from unittest.mock import patch


class TestRDECostEdgeDiagnostics:
    def test_rde_cost_edge_diag_logs(self):
        from src.services.realtime_decision_engine import _log_rde_cost_edge_diag
        with patch("src.services.realtime_decision_engine.log") as mock_log:
            _log_rde_cost_edge_diag(
                symbol="ADAUSDT", side="BUY", reject_reason="REJECT_ECON_BAD_ENTRY",
                expected_move_pct=0.001, required_move_pct=0.005, fee_drag_pct=0.001,
                spread_pct=0.0005, funding_pct=0.0002, price=0.2321, atr=0.0008,
                regime="RANGING", score=0.15, ev=0.003, p=0.52, rr=1.5, cost_edge_ok=False
            )
            assert mock_log.info.called


class TestSampleFlowSummary:
    def test_sample_flow_emits(self):
        from src.services.paper_training_sampler import _SAMPLE_FLOW_WINDOW, _emit_sample_flow_summary
        _SAMPLE_FLOW_WINDOW.clear()
        _SAMPLE_FLOW_WINDOW["last_summary_ts"] = 0.0
        with patch("src.services.paper_training_sampler.log") as mock_log:
            _emit_sample_flow_summary()
            assert mock_log.info.called


class TestRealDisabled:
    def test_real_trading_disabled(self):
        from src.core.runtime_mode import TRADING_MODE
        assert TRADING_MODE == "paper_train"
EOF
```

### 8. Run Tests

```bash
cd /opt/cryptomaster

# Run Phase 3A tests
./venv/bin/python -m pytest tests/test_phase3a_implementation.py -q

# Run V5 bridge tests
./venv/bin/python -m pytest tests/test_v5_legacy_bridge_hooks.py -q

# Run paper mode tests
./venv/bin/python -m pytest tests/test_paper_mode.py -q
```

### 9. Verify OPEN_POSITIONS

```bash
./venv/bin/python << 'PYSCRIPT'
import json, pathlib
p = pathlib.Path("data/paper_open_positions.json")
if p.exists():
    d = json.loads(p.read_text())
    positions = d.get("positions", d) if isinstance(d, dict) else d
    print(f"OPEN_POSITIONS={len(positions) if isinstance(positions, dict) else len(positions) if isinstance(positions, list) else 0}")
else:
    print("OPEN_POSITIONS=FILE_MISSING (OK if starting fresh)")
PYSCRIPT
```

**Must show**: `OPEN_POSITIONS=0` before restart

### 10. Verify Markers

```bash
grep -r "RDE_COST_EDGE_DIAG\|PAPER_OPEN_CAP_DIAG\|PAPER_SAMPLE_FLOW_SUMMARY\|PAPER_SEGMENT_POLICY_UPDATE" src/services/ | wc -l
```

**Should show**: 15+ matches (indicates patches applied)

### 11. Restart Service (When Ready)

```bash
# Only after OPEN_POSITIONS=0
sudo systemctl restart cryptomaster.service

# Monitor logs
journalctl -u cryptomaster.service -f --no-pager | grep -E 'RDE_COST_EDGE_DIAG|PAPER_SAMPLE_FLOW_SUMMARY|PAPER_SEGMENT_POLICY_UPDATE|ERROR|Traceback'
```

---

## Troubleshooting

### "No such file or directory"
- Verify you're in `/opt/cryptomaster` directory
- Check file paths match your actual file names

### Tests failing with import errors
- Patches may not be applied correctly
- Check for syntax errors with: `python -m py_compile src/services/realtime_decision_engine.py`

### Positions won't close before restart
- Check: `journalctl -u cryptomaster.service -n 100`
- Verify no trades currently open
- Force close via: `python -c "from src.services.paper_trade_executor import _POSITIONS; print(f'Open: {len(_POSITIONS)}')"`

---

## File Checksum (Post-Deployment)

After applying patches, verify via:
```bash
# Should find Phase 3A markers
grep "_RDE_COST_EDGE_DIAG_THROTTLE\|_SAMPLE_FLOW_WINDOW" src/services/*.py

# Expected output: 2 files matched
```

---

**Status**: Ready for manual SSH deployment

**Next**: Follow steps 1-11 above, then report results.
