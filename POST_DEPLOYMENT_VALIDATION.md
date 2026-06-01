# Phase 4A Post-Deployment Validation Checklist

**Run on `/opt/cryptomaster` after service restart**

---

## Immediate Checks (0-5 minutes)

```bash
# Check service status
sudo systemctl status cryptomaster.service

# Expected: Active: active (running)
# If not: sudo systemctl restart cryptomaster.service
```

✅ Service running  
✅ No crash in logs  

---

## 30-Minute Checks

```bash
# Check if trades_closed > 0
grep "trades_closed" /opt/cryptomaster/logs/cryptomaster.log | tail -3

# Expected: trades_closed: 1, 2, 3... (incrementing)
# If still 0: Issue with close counting
```

✅ trades_closed incrementing  
✅ Closes being counted  

---

## 1-Hour Checks

```bash
# Check entry rate
grep "PAPER_ENTRY" /opt/cryptomaster/logs/cryptomaster.log | wc -l

# Expected: 5-20 entries
# If 0: Starvation issue
```

✅ Entries occurring  
✅ No starvation detected  

---

## Learning Feedback Check

```bash
# Check if learning_weight applied
grep "learning_weight" /opt/cryptomaster/logs/cryptomaster.log | tail -5

# Expected: learning_weight: 0.7, 0.85, 1.0, 1.15, 1.3
# If no output: Learning not wired
```

✅ Learning weights visible  
✅ Soft ranking applied  

---

## Segment Stats Check

```bash
# Check if losers are being tracked
grep "segment_key" /opt/cryptomaster/logs/cryptomaster.log | grep -E "wins|losses" | tail -5

# Expected: wins and losses both > 0
# If losses always 0: Gate 4 not removed
```

✅ Losers included  
✅ Segment stats updated  

---

## Safety Verification

```bash
# Check no REAL orders placed
grep "REAL_ORDER\|real_orders.*true" /opt/cryptomaster/logs/cryptomaster.log

# Expected: No output (empty)
# If found: SAFETY ISSUE - rollback immediately
```

✅ No REAL orders  
✅ PAPER only  

---

## Quick Summary Check

```bash
# Run all checks at once
echo "=== PHASE 4A VALIDATION ==="
echo ""
echo "1. Service status:"
sudo systemctl is-active cryptomaster.service
echo ""
echo "2. trades_closed (last 3):"
grep "trades_closed" /opt/cryptomaster/logs/cryptomaster.log | tail -3 || echo "   (no closes yet)"
echo ""
echo "3. Entry count (last hour):"
grep "PAPER_ENTRY" /opt/cryptomaster/logs/cryptomaster.log | tail -1 | wc -l || echo "   (monitoring)"
echo ""
echo "4. Learning weights:"
grep "learning_weight" /opt/cryptomaster/logs/cryptomaster.log | tail -1 || echo "   (not yet visible)"
echo ""
echo "5. REAL orders check:"
grep "REAL_ORDER\|real_orders.*true" /opt/cryptomaster/logs/cryptomaster.log && echo "   ❌ FOUND!" || echo "   ✅ None (safe)"
```

---

## Success = All Green ✅

- [x] Service running
- [x] trades_closed > 0
- [x] Entries occurring
- [x] Learning weight visible
- [x] Losers included
- [x] No REAL orders

---

## If Issues Found

### trades_closed Still 0
```bash
# Check if closes are happening
grep "CHECK_AND_EXIT\|position.*closed" /opt/cryptomaster/logs/cryptomaster.log | tail -20

# If no closes: Entry/exit logic issue
# If closes but trades_closed=0: Metric not counting (code issue)
```

### Entry Starvation
```bash
# Check cost-edge rejections
grep "cost_edge\|PAPER_ENTRY_BLOCKED" /opt/cryptomaster/logs/cryptomaster.log | tail -20

# If frequent rejections: Expected move too low relative to costs
```

### Learning Weight Not Applied
```bash
# Check if PolicyStateTracker initialized
grep "PolicyStateTracker\|set_policy_state_tracker" /opt/cryptomaster/logs/cryptomaster.log | head -5

# If not found: Integration missing
```

### Positions Lost on Exception
```bash
# Check for V5 bridge failures
grep "V5_BRIDGE\|OUTBOX_ENQUEUED" /opt/cryptomaster/logs/cryptomaster.log | tail -10

# OUTBOX_ENQUEUED is expected (safe retry)
# Repeated [V5_BRIDGE_CLOSE_FAILED] indicates exception handling working
```

---

## Rollback If Critical Issue

```bash
cd /opt/cryptomaster
git log --oneline -5
git revert <Phase4A-commit-hash>
git push origin main
sudo systemctl restart cryptomaster.service
sudo systemctl status cryptomaster.service
```

Estimated recovery: 5 minutes

---

## Expected Timeline

| Time | Event |
|------|-------|
| T+0 | Service restart |
| T+5min | Logs should show startup messages |
| T+15min | First entries should appear |
| T+30min | trades_closed should be > 0 |
| T+60min | Learning weight visible, entry rate stable |
| T+4h | Segment stats accumulated, soft ranking active |

---

**Status**: Ready for validation  
**Date**: 2026-06-01  
**Phase**: 4A Production Deployment
