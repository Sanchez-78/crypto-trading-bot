---
name: no-real-trading-gate
description: |
  Real trading safety enforcement. Audits code for exposed real order paths, 
  accidental live execution, unguarded TRADING_MODE changes. Blocks patches 
  touching order submission without explicit authorization.

---

# No Real Trading Gate Skill

## Audit Workflow

### 1. Find Real Order Code

```bash
grep -rn "submit_order\|place_order\|send_order\|create_order" src/
grep -rn "binance.*order\|exchange.*submit" src/
```

All matches must be guarded by `live_trading_allowed()`.

### 2. Check Guard Pattern

```bash
grep -B5 "submit_order" src/services/trade_executor.py
```

Expected:
```python
if live_trading_allowed():
    submit_order(...)  # ← Only way to execute real orders
```

### 3. Verify live_trading_allowed()

```python
def live_trading_allowed():
    mode = os.getenv("TRADING_MODE", "paper_live")
    return mode == "real_live"
```

**Requirements:**
- ✅ Default is "paper_live" (not "real_live")
- ✅ Explicit check required
- ✅ No fallback to real trading

### 4. Config Defaults

Check `.env`:
```
TRADING_MODE=paper_live  # ✅ Or missing (defaults to paper_live)
TRADING_MODE=real_live   # ❌ FAIL
```

## Authorization Levels

**PAPER-only (99% of patches):**
- ❌ REJECT if touching real order code without authorization

**REAL-LIVE authorized (rare, requires CEO sign-off):**
- ✅ ACCEPT with additional restrictions
- Separate instance (`/opt/cryptomaster-live/`)
- Separate `.env` with TRADING_MODE=real_live
- Manual approval before deploy
- Escalate to human authority

## Gates

- ✅ PASS: No real order code touched OR all real code properly guarded
- ❌ REJECT: Real order code exposed OR unguarded TRADING_MODE
