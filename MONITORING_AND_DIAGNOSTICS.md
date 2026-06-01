# Phase 4A Monitoring & Issue Detection

**Purpose**: Detect and diagnose issues after Phase 4A deployment to `/opt/cryptomaster`

---

## Critical Metrics to Monitor

### 1. **trades_closed Metric** (Was always 0 before)
**What to watch**: Should increment with each closed position
```
Expected: trades_closed > 0 after 1 hour of trading
Before fix: trades_closed = 0 (broken)
After fix: trades_closed increases (every close counted)
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep -i "trades_closed"
```

**Issue**: If still 0 after 1 hour
- Root cause: Close lifecycle not being counted
- Action: Check `src/v5_bot/paper/runner.py` line 220-241
- Validate: `closed_count_before - closed_count_after` is being tracked

---

### 2. **Entry Rate** (Should NOT be starvation)
**What to watch**: Entries should occur regularly, not 0 for hours
```
Expected: 5-20 entries per hour during active trading
Before: Can see 12h+ starvation blocks
After: Consistent entry flow (losers now in learning)
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep "PAPER_ENTRY" | wc -l
```

**Issue**: If starvation (0 entries for >1 hour)
- Root cause: Cost-edge gate or learning gate blocking entries
- Action: Check PAPER_SAMPLE_FLOW_SUMMARY logs
- Validate: Expected move vs cost_edge margin
- Debug: Run cost-edge diagnostics (shadow margin check)

---

### 3. **Learning Feedback** (NEW - Was disconnected before)
**What to watch**: PolicySelector should rank strategies by segment performance
```
Expected: Profitable segments prioritized (soft ranking 0.7-1.3)
Before: Fixed strategy order (no feedback)
After: Adaptive ranking based on segment profit_factor
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep "POLICY_SELECTOR" | grep "learning_weight"
```

**Issue**: If no learning_weight in logs
- Root cause: PolicyStateTracker not wired to PolicySelector
- Action: Check `src/v5_bot/strategy/policy_selector.py` line 56-115
- Validate: `set_policy_state_tracker()` called
- Validate: `get_segment_learning_weight()` returns weights

---

### 4. **Segment Tracking** (Losers now included)
**What to watch**: Segment stats should include losers, not just winners
```
Expected: wins + losses tracked separately
Before: Only profitable trades (survivorship bias)
After: All eligible trades in learning
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep "segment_key" | grep -E "wins|losses|pf"
```

**Issue**: If all trades are winners (filtered)
- Root cause: Eligibility gate still filtering losers
- Action: Check `src/v5_bot/learning/eligibility.py`
- Validate: Gate 4 (net_pnl >= 0) is removed
- Validate: Segment stats include both wins AND losses

---

### 5. **Close Lifecycle** (Exception-safe now)
**What to watch**: Positions should not be lost on bridge exception
```
Expected: Position retried on exception (durable outbox)
Before: Position lost forever on V5 bridge failure
After: Position queued to outbox for retry
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep -E "V5_BRIDGE|OUTBOX|CLOSE_FAILED"
```

**Issue**: If OUTBOX_ENQUEUED appears
- Status: Expected on transient failures (Firebase timeout, etc.)
- Action: Monitor outbox flush on recovery
- Validate: Position ultimately closes and trades_closed increments

---

### 6. **Cost-Edge Diagnostics** (Shadow margin)
**What to watch**: Shadow margin should show what would pass with 2 bps margin
```
Expected: [shadow: required=X pass=Y] on rejection
Before: No shadow margin logged
After: Shadow margin visible for A/B analysis
```

**Check via logs**:
```bash
tail -f /opt/cryptomaster/logs/cryptomaster.log | grep "shadow:"
```

**Issue**: If no shadow margin in rejections
- Root cause: Diagnostics logging not active
- Action: Check `src/v5_bot/strategy/cost_edge_gate.py` line 96-121
- Validate: Shadow margin calculated and logged

---

## Daily Checks (After Deployment)

### Day 1: Immediate (0-1 hour)
- [ ] Service started successfully
- [ ] No crash in logs
- [ ] Entries occurring (not starvation)
- [ ] Closes happening (trades_closed > 0)

### Day 1: Extended (1-4 hours)
- [ ] trades_closed metric increasing
- [ ] Learning stats accumulating (wins/losses)
- [ ] PolicySelector applying learning weight
- [ ] No position loss on exceptions

### Day 2-3: Validation
- [ ] Entry rate consistent (5-20/hour)
- [ ] Close rate consistent
- [ ] Learning segments accumulating coverage
- [ ] Segment ranking changing (profitable first)

---

## Rollback Triggers

Rollback if ANY of these occur:
1. trades_closed never increments (metric broken)
2. Starvation detected (0 entries for 2+ hours)
3. Positions being lost (count mismatch)
4. Service crashes repeatedly
5. REAL orders placed (safety breach)

---

## Success Criteria (Phase 4A Live)

✅ **trades_closed** > 0 after 1 hour  
✅ **Entry rate** consistent (not starvation)  
✅ **Learning feedback** visible in logs (learning_weight)  
✅ **Segment stats** include wins AND losses  
✅ **Close lifecycle** exception-safe (outbox catches failures)  
✅ **No REAL orders** placed (safety confirmed)
