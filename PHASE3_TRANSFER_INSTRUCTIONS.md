# Phase 3 Hook Transfer to /opt/cryptomaster

**Status**: ✅ Ready for transfer  
**Scope**: Incremental transfer of Phase 3 hooks only (V5 bridge integration)  
**Bridge Components**: Already present in `/opt/cryptomaster`

---

## What to Transfer

### 1. src/services/paper_trade_executor.py

**Changes**: Lines 49-70 (lazy _get_v5_bridge helper) + Lines 971-994 (PAPER_ENTRY hook) + Lines 1702-1749 (close hook)

**Lines to add/update**:

**A) Lazy bridge helper (lines 49-70)**:
```python
# V5 Legacy Bridge integration (Phase 3)
_V5_BRIDGE = None
_V5_BRIDGE_LOCK = __import__("threading").RLock()


def _get_v5_bridge():
    """Lazy initialize V5 bridge singleton."""
    global _V5_BRIDGE
    if _V5_BRIDGE is None:
        with _V5_BRIDGE_LOCK:
            if _V5_BRIDGE is None:
                try:
                    from src.services.v5_legacy_bridge import V5LegacyBridge
                    _V5_BRIDGE = V5LegacyBridge()
                    log.info(
                        "[V5_BRIDGE_INIT] enabled=true real_orders_allowed=false service=cryptomaster.service"
                    )
                except Exception as e:
                    log.warning(f"[V5_BRIDGE_INIT_FAILED] {e}")
                    _V5_BRIDGE = None
    return _V5_BRIDGE
```

**B) PAPER_ENTRY hook (after position save, around line 971-994)**:
```python
    # V5 Legacy Bridge: Record paper entry (Phase 3 hook)
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperOpenEvent
            open_event = LegacyPaperOpenEvent(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                strategy_id=paper_source or "normal_rde_take",
                regime=position.get("regime", "NEUTRAL"),
                entry_ts=ts,
                entry_price=price,
                size=size_usd,
                bucket=bucket or training_bucket or "UNKNOWN",
                expected_move_bps=int((position.get("expected_move_pct", 0.0) or 0.0) * 10000),
                required_move_bps=int((position.get("required_move_pct", 0.23) or 0.23) * 10000),
                cost_edge_ok=position.get("cost_edge_ok", True),
                real_orders_allowed=False,
                metadata={"paper_source": paper_source or "normal_rde_take"},
            )
            v5_bridge.record_open(open_event)
    except Exception as e:
        log.error(f"[V5_BRIDGE] Paper entry hook failed: {e}")
```

**C) close_paper_position close hook (lines 1702-1749)**:
```python
    # V5 Legacy Bridge: Record paper close (Phase 3 hook) — BEFORE deduplication
    close_event = None  # Initialize to handle except block safely
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperCloseEvent
            size_usd = _safe_float(pos.get("size_usd") or pos.get("final_size_usd"), 10.0)
            net_pnl = (pnl_data["net_pnl_pct"] / 100.0) * size_usd
            close_event = LegacyPaperCloseEvent(
                trade_id=position_id,
                symbol=pos["symbol"],
                side=pos.get("side", "BUY"),
                exit_ts=ts,
                exit_price=price,
                exit_reason=reason,
                gross_pnl=(pnl_data.get("gross_pnl_pct", 0.0) / 100.0) * size_usd,
                fees=(pnl_data.get("fee_pct", 0.0) / 100.0) * size_usd,
                spread=(pnl_data.get("slippage_pct", 0.0) / 100.0) * size_usd,
                net_pnl=net_pnl,
                net_pnl_pct=pnl_data.get("net_pnl_pct", 0.0),
                duration_seconds=int(duration_s),
                learning_eligible=not pos.get("quarantined", False),
                readiness_eligible=False,  # Will be determined by learning bridge
                real_orders_allowed=False,
                metadata={"paper_source": pos.get("paper_source", "unknown")},
            )
            v5_bridge.record_close(close_event)
    except Exception as e:
        # P0 FIX #3: On V5 bridge failure, enqueue for retry instead of silently continuing
        log.error(f"[V5_BRIDGE_CLOSE_FAILED] trade_id={position_id} enqueuing to outbox: {e}")
        try:
            from src.services.v5_legacy_bridge.outbox import get_durable_outbox
            outbox = get_durable_outbox()
            if outbox and close_event:
                outbox.enqueue(
                    "paper_close",
                    close_event.to_dict() if hasattr(close_event, 'to_dict') else {
                        "trade_id": position_id,
                        "symbol": pos.get("symbol", "N/A"),
                        "exit_reason": reason,
                        "exit_price": price,
                        "exit_ts": ts,
                        "net_pnl_pct": pnl_data.get("net_pnl_pct", 0.0),
                    },
                    idempotency_key=position_id,
                )
                log.info(f"[V5_BRIDGE_CLOSE_ENQUEUED] trade_id={position_id} for retry")
        except Exception as outbox_e:
            log.error(f"[V5_BRIDGE_OUTBOX_ENQUEUE_FAILED] trade_id={position_id} error={outbox_e}")
```

### 2. bot2/main.py

**Changes**: Lines 1977-1978 (import helper) + Lines 1991-1992 (periodic flush)

**A) Add import (around line 1977)**:
```python
from src.services.paper_trade_executor import _get_v5_bridge, get_paper_open_positions
```

**B) Add periodic execution (around line 1991, in main loop)**:
```python
            v5_bridge = _get_v5_bridge()
            if v5_bridge:
                v5_bridge.publish_metrics(trading_stats=trading_stats)
                v5_bridge.flush_outbox(limit=20)
```

---

## Safety Checks

✅ **Preserved from Part 1 fixes**:
- Position pop-before-processing (safe position removal after all processing)
- Dedup TOCTOU prevention (fail-fast check before position modification)
- Bridge failure exception handling (enqueue to outbox for retry)

✅ **No modifications to**:
- Strategy logic, cost-edge thresholds, TP/SL, fee/funding
- Admission gates (P0 fixes #4-5)
- Dashboard diagnostics (P0 fix #6)
- REAL trading safeguards (ENABLE_REAL_ORDERS=false)

---

## Testing After Transfer

**Run on `/opt/cryptomaster`**:

```bash
cd /opt/cryptomaster
PY=/opt/cryptomaster/venv/bin/python

echo "=== Bridge Tests ==="
$PY -m pytest tests/test_v5_legacy_bridge*.py -q

echo "=== Admission Gates + Dashboard ==="
$PY -m pytest \
  tests/test_p11_admission_gates_part2.py \
  tests/test_p11_dashboard_diagnostics.py \
  tests/test_paper_mode.py::TestP1AE1BootstrapCostEdgeBypass::test_bootstrap_cost_edge_bypass_paper_train \
  -q

echo "=== Paper Mode Tests ==="
$PY -m pytest tests/test_paper_mode.py -q

echo "=== P11AP O2 Tests ==="
$PY -m pytest tests/test_p11ap_o2_*.py -q
```

**Expected**:
- All bridge tests passing
- All admission/dashboard tests passing
- All paper mode tests passing

---

## Critical Code Points

### paper_trade_executor.py locations:

1. **Lazy bridge helper**: Lines 49-70 (top of module with globals)
2. **PAPER_ENTRY hook**: After position save, after log `[PAPER_ENTRY]` (around line 971)
3. **close hook**: In `close_paper_position()`, after building pnl_data, before final position pop (around line 1702)

### bot2/main.py locations:

1. **Import**: Near other service imports (around line 1977)
2. **Periodic**: In main trading loop, same section as other periodic publishing (around line 1991)

---

## Verification

After transfer, verify:

```bash
# Check helper exists
grep -n "def _get_v5_bridge" src/services/paper_trade_executor.py

# Check PAPER_ENTRY hook
grep -n "\[V5_BRIDGE\] Paper entry hook" src/services/paper_trade_executor.py

# Check close hook
grep -n "V5_BRIDGE: Record paper close" src/services/paper_trade_executor.py

# Check periodic
grep -n "v5_bridge.publish_metrics\|v5_bridge.flush_outbox" bot2/main.py
```

---

## No Restart Until Tests Pass

✅ Transfer files  
✅ Verify signatures match bridge components  
✅ Run all test suites  
❌ Do NOT restart cryptomaster.service until all tests pass

---

## Rollback (if needed)

If tests fail, revert changed files:

```bash
cd /opt/cryptomaster
git checkout -- src/services/paper_trade_executor.py bot2/main.py
```

Then diagnose test failure.
