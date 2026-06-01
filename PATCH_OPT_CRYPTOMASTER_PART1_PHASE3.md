# Surgical Patch: Add Part 1 Lifecycle + Phase 3 Hooks to /opt/cryptomaster

**Status**: Ready to apply  
**Target**: /opt/cryptomaster  
**Files**: 2  
**Scope**: NO full rewrites, NO git reset, NO strategy changes

---

## File 1: src/services/paper_trade_executor.py

### Check Current State

```bash
grep -n "def _get_v5_bridge" src/services/paper_trade_executor.py
# Expected: NOT FOUND
grep -n "V5 Legacy Bridge" src/services/paper_trade_executor.py
# Expected: NOT FOUND or very few
```

### Edit 1A: Add _get_v5_bridge() Helper (After line 47-48, before any function definitions)

**Location**: After `_QUALITY_ENTRY_LOCK = __import__("threading").RLock()` line

**Insert**:
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
                    log.error(f"[V5_BRIDGE_INIT_FAILED] {e}")
                    _V5_BRIDGE = False  # Mark as failed to avoid retry loop
    return _V5_BRIDGE if _V5_BRIDGE is not False else None
```

---

### Edit 1B: Add PAPER_ENTRY Hook (In `open_paper_position()`)

**Location**: After position saved to Firebase, after `[PAPER_ENTRY]` log line

**Find line like**:
```python
    log.warning(
        "[PAPER_ENTRY]
        ...
    )
```

**After that log block, add before next operation**:
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

---

### Edit 1C: Fix close_paper_position() — Move Dedup Check to START

**Location**: In `close_paper_position(position_id, price, ts, reason)` function

**Find**:
```python
def close_paper_position(position_id, price, ts, reason):
    """Close a paper position."""
    with _POSITION_LOCK:
        if position_id not in _POSITIONS:
            return None
        pos = _POSITIONS.pop(position_id)  # ← POP IS HERE (BAD)
```

**Change to** (DEDUP FIRST):
```python
def close_paper_position(position_id, price, ts, reason):
    """Close a paper position."""
    # P0 FIX #2: Dedup check FIRST (fail fast), before any position modifications
    with _CLOSED_TRADES_LOCK:
        if position_id in _CLOSED_TRADES_THIS_SESSION:
            log.debug(f"[PAPER_CLOSE_DEDUPE] trade_id={position_id} already processed, skipping")
            return None
        # Mark as being processed (added to set after position read succeeds)

    # P0 FIX #1: Do NOT pop position yet - read-only access first
    # Position removal must happen AFTER all processing succeeds to prevent loss on exception
    with _POSITION_LOCK:
        if position_id not in _POSITIONS:
            return None
        pos = _POSITIONS[position_id]  # Read-only, do not pop yet
```

---

### Edit 1D: Add V5 Close Hook + Outbox Fallback (In close_paper_position)

**Location**: After PnL calculation block, after the big `[PAPER_EXIT]` log

**Find** section that looks like:
```python
    log.warning(
        "[PAPER_EXIT] trade_id=%s ...
        ...
    )
```

**After that log, INSERT**:
```python

    # V5 Legacy Bridge: Record paper close (Phase 3 hook)
    close_event = None  # Initialize to prevent undefined variable in except
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
                readiness_eligible=False,
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

---

### Edit 1E: Move Position Removal to END of close_paper_position()

**Location**: At the VERY END of `close_paper_position()` function

**Find** the last lines of the function before `return closed_trade`

**Add BEFORE `return closed_trade`**:
```python

    # P0 FIX #1 (continued): NOW remove position from active, AFTER all processing succeeds
    with _POSITION_LOCK:
        _POSITIONS.pop(position_id, None)
```

**This ensures**:
- Position only removed after V5 bridge call completes
- Position only removed after learning update completes
- If any exception occurs above, position is still available for retry

---

## File 2: bot2/main.py

### Check Current State

```bash
grep -n "from src.services.paper_trade_executor import" bot2/main.py
# Expected: NOT including _get_v5_bridge
grep -n "v5_bridge.publish_metrics\|v5_bridge.flush_outbox" bot2/main.py
# Expected: NOT FOUND
```

### Edit 2A: Add Import

**Location**: Near other imports from paper_trade_executor

**Find line like**:
```python
from src.services.paper_trade_executor import get_paper_open_positions
```

**Change to**:
```python
from src.services.paper_trade_executor import _get_v5_bridge, get_paper_open_positions
```

---

### Edit 2B: Add Periodic Metrics Publishing

**Location**: In main trading loop, same section as other periodic publishing

**Find** section that looks like:
```python
        # Periodic publishing
        if <condition>:
            publish_something()
```

**Add this block** (somewhere in the periodic section, BEFORE CzechCycleReporter):
```python

            # V5 bridge metrics publishing (Phase 3)
            try:
                v5_bridge = _get_v5_bridge()
                if v5_bridge:
                    v5_bridge.publish_metrics(trading_stats=trading_stats)
                    v5_bridge.flush_outbox(limit=20)
            except Exception as _v5_publish_e:
                log.debug(f"[V5_BRIDGE_METRICS_PUBLISH_ERROR] {_v5_publish_e}")
```

---

## Verification Checklist

After applying patches, verify:

```bash
# Check helpers exist
grep -c "def _get_v5_bridge" src/services/paper_trade_executor.py
# Expected: 1

# Check PAPER_ENTRY hook
grep -c "V5 Legacy Bridge: Record paper entry" src/services/paper_trade_executor.py
# Expected: 1

# Check dedup at start
grep -n "P0 FIX #2: Dedup check FIRST" src/services/paper_trade_executor.py
# Expected: found, line number before position access

# Check no early pop
grep -n "pos = _POSITIONS\[position_id\]" src/services/paper_trade_executor.py
# Expected: found (read-only)
grep -n "pos = _POSITIONS\.pop" src/services/paper_trade_executor.py
# Expected: NOT FOUND (no early pop)

# Check late pop
grep -n "_POSITIONS\.pop(position_id, None)" src/services/paper_trade_executor.py
# Expected: found at end

# Check close hook
grep -c "V5 Legacy Bridge: Record paper close" src/services/paper_trade_executor.py
# Expected: 1

# Check outbox fallback
grep -c "get_durable_outbox" src/services/paper_trade_executor.py
# Expected: 1

# Check import
grep "from src.services.paper_trade_executor import _get_v5_bridge" bot2/main.py
# Expected: found

# Check metrics publishing
grep -c "v5_bridge.publish_metrics" bot2/main.py
# Expected: 1
```

---

## Test After Patching

```bash
PY=/opt/cryptomaster/venv/bin/python

echo "=== V5 Bridge Tests ==="
$PY -m pytest tests/test_v5_legacy_bridge*.py -q

echo "=== Admission Gates + Dashboard ==="
$PY -m pytest tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py -q

echo "=== Bootstrap Bypass Test ==="
$PY -m pytest tests/test_paper_mode.py::TestP1AE1BootstrapCostEdgeBypass::test_bootstrap_cost_edge_bypass_paper_train -q

echo "=== All Paper Mode Tests ==="
$PY -m pytest tests/test_paper_mode.py -q

echo "=== P11AP O2 Tests ==="
$PY -m pytest tests/test_p11ap_o2_*.py -q
```

**Expected**: All tests PASS

---

## Safety Guarantees

✅ No strategy changes (cost-edge thresholds, TP/SL untouched)  
✅ No Firebase reset  
✅ No full file rewrites  
✅ No standalone V5  
✅ Real trading still disabled  
✅ Position lifecycle safe (pop only after all processing)  
✅ Dedup prevents double-processing  
✅ Bridge failures recoverable (outbox fallback)  
✅ No CzechCycleReporter changes

---

## Rollback (if needed)

```bash
cd /opt/cryptomaster
git checkout -- src/services/paper_trade_executor.py bot2/main.py
```

Then diagnose test failure.

---

**Ready to patch /opt/cryptomaster manually using these exact edits.**
