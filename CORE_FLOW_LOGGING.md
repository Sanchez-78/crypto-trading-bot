# V10.13k: Dual Logging System — CORE FLOW vs DIAGNOSTICS

## Problem Solved

**Before:** Logs were so complex that actual trading/learning signals were buried in noise.
- Throttle logs (HBLOCK, EXPLORE_SKIP)
- State validation details
- Cap checks
- Rate limiting
- Technical plumbing

**Result:** Hard to see what the bot actually does—trades opening/closing, learning updates, errors.

---

## Solution: Dual Logging Streams

### CORE FLOW (What the Bot Does)
**Bright, colored, prominent**
- ✅ **ENTRY** — Signal accepted, trade opened (GREEN)
- ✅ **EXIT** — Trade closed, outcome (MAGENTA)
- 📚 **LEARNING** — LM state updated (CYAN)
- ⚠️ **ERROR** — Mismatches, failures (RED)
- 📊 **ATTRIBUTION** — Why trades lost (YELLOW)

### DIAGNOSTICS (Why/How It Works)
**Dim, collapsed, technical**
- Throttle suppression (HBLOCK, EXPLORE_SKIP)
- Rate cap checks (probe_cap_rate, probe_cap_total)
- State validation (mismatch detection)
- Internal counters and flags
- (Collapsed by default—visible only if explicitly enabled)

---

## Usage

### In Code: Use Core Flow Logger

```python
from src.services.core_flow_logging import (
    log_trade_entry,
    log_trade_exit,
    log_learning_update,
    log_error,
    log_attribution,
    log_diag,
)

# Log a trade entry (CORE FLOW, visible)
log_trade_entry(
    symbol="ETHUSDT",
    side="BUY",
    price=1800.0,
    bucket="C_WEAK_EV_TRAIN",
    source="PAPER_TRAIN",
    ev=0.05,
    confidence=0.85
)

# Log a trade exit (CORE FLOW, visible)
log_trade_exit(
    symbol="ETHUSDT",
    trade_id="trade_123",
    outcome="PROFIT",
    pnl_pct=0.8,
    bucket="C_WEAK_EV_TRAIN",
    reason="TARGET_HIT",
    mfe_pct=1.2
)

# Log learning update (CORE FLOW, visible)
log_learning_update(
    trades_in_lm=15,
    calibration_confidence=0.72,
    attribution_dominant="FEE_DOMINATED_MOVE",
    update_count=3
)

# Log error (CORE FLOW, RED, visible)
log_error(
    error_type="QUALITY_EXIT_MISSING",
    message="Trade closed but no quality exit log",
    trade_id="trade_123",
    symbol="ETHUSDT"
)

# Log attribution (CORE FLOW, YELLOW, visible)
log_attribution(
    trade_id="trade_123",
    symbol="ETHUSDT",
    attribution="FEE_DOMINATED_MOVE",
    loss_pct=-0.3,
    fee_pct=0.05
)

# Log technical detail (DIAGNOSTICS, DIM, hidden by default)
log_diag(
    "Throttle check passed",
    symbol="ETHUSDT",
    throttle_key=("HBLOCK", "ETHUSDT", "SOFT"),
    elapsed_s=15.2
)
```

### From Logs: View with Core Flow Viewer

**Simple usage:**
```bash
bash scripts/p11ak_core_flow_viewer.sh
```

**With time window:**
```bash
bash scripts/p11ak_core_flow_viewer.sh --since "60 min ago"
```

**Disable colors (for file export):**
```bash
bash scripts/p11ak_core_flow_viewer.sh --color off > core_flow_2026-05-18.txt
```

### Output Example

```
============================================================
CORE FLOW LOG VIEWER
============================================================
PID: 12345
Since: 1 hour ago

=== CORE FLOW: Trades & Learning ===

→ ENTRIES:
  ✓ ETHUSDT bucket=C_WEAK_EV_TRAIN ev=+0.0523
  ✓ LTCUSDT bucket=C_WEAK_EV_TRAIN ev=+0.0312
  ✓ ETHUSDT bucket=C_NEG_EV_PROBE ev=-0.0045

← EXITS:
  ✓ ETHUSDT outcome=PROFIT pnl=+0.80% reason=TARGET_HIT
  ✓ LTCUSDT outcome=LOSS pnl=-0.25% reason=TIMEOUT
  ✓ ETHUSDT outcome=LOSS pnl=-0.12% reason=STOPLOSS

📚 LEARNING UPDATES:
  ✓ LM trades=15
  ✓ LM trades=16
  ✓ LM trades=17

⚠️  ERRORS & MISMATCHES:
  None

=== DIAGNOSTICS: Technical Details ===

Counters (last 60 min):
  PAPER_TRAIN_ENTRY:       18
  PAPER_EXIT:              16
  PAPER_NEG_EV_PROBE:      2
  LM_STATE_AFTER_UPDATE:   16
  REJECT:                  142
  SKIP:                    89

Throttled/Diagnostic Logs (suppressed):
  Use 'journalctl' directly to see HBLOCK, EXPLORE_SKIP, etc.
============================================================
```

---

## Integration Guide

### Step 1: Add to Key Modules

Replace existing `log.info()` calls in critical paths with `log_trade_entry()`, `log_trade_exit()`, `log_learning_update()`:

**File:** `src/services/paper_trade_executor.py`
```python
from src.services.core_flow_logging import log_trade_entry, log_trade_exit

# In open_paper_position():
log_trade_entry(
    symbol=signal["symbol"],
    side=side,
    price=price,
    bucket=training_result.get("bucket", "UNKNOWN"),
    source=training_result.get("source", "UNKNOWN"),
    ev=signal.get("ev", 0.0),
)

# In close_paper_position():
log_trade_exit(
    symbol=trade.get("symbol"),
    trade_id=trade_id,
    outcome=outcome,
    pnl_pct=net_pnl_pct,
    bucket=trade.get("training_bucket", "UNKNOWN"),
    reason=exit_reason,
)
```

**File:** `src/services/learning_event.py`
```python
from src.services.core_flow_logging import log_learning_update, log_attribution

# In update_from_closed_trade():
log_learning_update(
    trades_in_lm=len(closed_trades),
    calibration_confidence=confidence_score,
    attribution_dominant=dominant_attribution,
)

# In log attribution:
log_attribution(
    trade_id=trade_id,
    symbol=trade.get("symbol"),
    attribution=attribution_reason,
    loss_pct=loss_pct,
)
```

### Step 2: Use Diagnostics for Technical Details

Replace noisy `log.debug()` or low-value `log.info()` with `log_diag()`:

```python
from src.services.core_flow_logging import log_diag

# Instead of:
# log.debug(f"Throttle check for {key}: {elapsed}s since last log")

# Use:
log_diag(
    "Throttle check passed",
    key=key,
    elapsed_s=elapsed,
    next_allowed_s=next_time - now,
)
```

---

## Color Codes

| Signal | Color | Code | Meaning |
|--------|-------|------|---------|
| ENTRY | 🟢 GREEN | `\033[92m` | Trade opened, signal accepted |
| EXIT | 🟣 MAGENTA | `\033[95m` | Trade closed, position resolved |
| LEARN | 🔵 CYAN | `\033[96m` | LM updated, calibration advanced |
| ERROR | 🔴 RED | `\033[91m` | Mismatch, failure, inconsistency |
| ATTR | 🟡 YELLOW | `\033[93m` | Attribution analysis, loss reason |
| INFO | 🔷 BLUE | `\033[94m` | Generic info |
| DIAG | ⚫ DIM | `\033[2m` | Diagnostic detail, collapsed |

---

## Monitoring Workflow

### During Development

```bash
# Watch CORE FLOW in real-time (skip noise)
bash scripts/p11ak_core_flow_viewer.sh --since "10 min ago"

# Compare before/after changes
bash scripts/p11ak_core_flow_viewer.sh --color off > before.txt
# [make changes]
bash scripts/p11ak_core_flow_viewer.sh --color off > after.txt
diff before.txt after.txt
```

### Post-Deploy Validation

```bash
# Check that trades are opening (CORE FLOW should be visible)
bash scripts/p11ak_core_flow_viewer.sh --since "30 min ago" | grep "ENTRIES"

# Verify learning is happening
bash scripts/p11ak_core_flow_viewer.sh --since "30 min ago" | grep "LEARNING"

# Check for errors
bash scripts/p11ak_core_flow_viewer.sh --since "30 min ago" | grep "ERROR"
```

### Diagnostics (When Needed)

```bash
# Full journalctl for technical debugging
journalctl -u cryptomaster --since "30 min ago" -n 500 | grep "HBLOCK\|EXPLORE_SKIP\|probe_cap"

# Parse for specific throttle reason
journalctl -u cryptomaster | grep "PAPER_EXPLORE_SKIP" | tail -20
```

---

## Design Principles

1. **CORE FLOW is primary** — What matters is what the bot does (trades, learning, errors)
2. **DIAGNOSTICS are secondary** — Why it works is technical, hidden by default
3. **Color is semantic** — Same signal type always same color
4. **Collapsed by design** — Noise is suppressed; run `journalctl` if you need details
5. **Easy transition** — Existing `log.info()` calls still work, but `log_trade_entry()` is clearer

---

## Future Enhancements

- [ ] Dashboard with real-time CORE FLOW chart (entries/exits/learning)
- [ ] Attribution pie chart (top reasons for losses)
- [ ] Trade timeline (opens → closes, color-coded by outcome)
- [ ] Email alerts when ERRORS appear
- [ ] Persistent log file with CORE FLOW only (smaller, faster to grep)
