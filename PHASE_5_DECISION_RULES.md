# Phase 5 End-of-Freeze Decision Rules

**Date Established**: 2026-06-03  
**Effective**: 2026-06-09 (End of freeze period)  
**Authority**: User explicit instructions  
**Status**: LOCKED (no changes without explicit approval)

---

## 🎯 Decision Framework

After 7-day freeze period (June 2-9), evaluate Phase 5 reports using these rules:

---

## 1️⃣ **Learning Feedback Decision**

### **ENABLE** if ALL criteria met:
```
✅ Segment n >= 20 samples (reliable data)
✅ Shadow report shows PROMOTE/DEMOTE recommendations
✅ Promoted segments: PF >= 1.15 AND expectancy > 0
✅ Estimated quality improvement > 10%
✅ Cost-edge audit confirms no blocking issues
```

### **KEEP DISABLED** if ANY criterion missing:
```
❌ Segments still have n < 20 (insufficient data)
❌ No PROMOTE segments (learning not yet differentiating)
❌ PROMOTE segments only marginally better (PF 1.05 vs 1.15)
❌ Estimated improvement < 10%
❌ Phase 5C shows anomalies (investigate first)
```

### **Implementation** (if enabled):
```python
# In PolicySelector.evaluate_signal():
for policy in applicable_policies:
    segment_key = f"{symbol}:{regime}:{side}"
    segment_stats = learning_system.get_segment_stats(segment_key)
    
    # Shadow report recommended priority
    if shadow_priority == "PROMOTE":
        entry_multiplier = 1.5  # Encourage entry
    elif shadow_priority == "DEMOTE":
        entry_multiplier = 0.5  # Discourage entry
    else:
        entry_multiplier = 1.0  # Neutral
    
    # Apply multiplier to EV gate
    adjusted_required_ev = required_ev / entry_multiplier
```

### **Validation After Enable**:
```
Day 1-3: Monitor shadow vs actual impact
Target: Actual PF improvement > 5%
If success: Continue
If regression: Rollback immediately
```

---

## 2️⃣ **Exploration Decision**

### **ENABLE** if ALL criteria met:
```
✅ Segment coverage < 30% (room to expand)
✅ Shadow exploration shows >= 5 candidates
✅ Candidates are UNDEREXPLORED (n < 10) not UNPROFITABLE
✅ Safety caps are enforced:
     - max 1 per symbol
     - max 2 global
     - max 1 per 30min per segment
     - max 2-4 per hour
✅ Readiness isolated: PAPER_DETERMINISTIC_EXPLORATION=true
```

### **KEEP DISABLED** if ANY criterion missing:
```
❌ Coverage > 30% (already sufficient)
❌ < 5 candidates (not enough opportunities)
❌ Candidates are low-PF (unprofitable, not underexplored)
❌ Safety caps cannot be enforced (infrastructure issue)
❌ Readiness contamination risk exists
```

### **Implementation** (if enabled):
```python
# Add to paper_training_sampler.py
PAPER_DETERMINISTIC_EXPLORATION = True

# In admission logic:
if PAPER_DETERMINISTIC_EXPLORATION and is_exploration_candidate(symbol, regime, side):
    # Check caps
    if can_open_exploration_safely():
        admission_reason = "PAPER_DETERMINISTIC_EXPLORATION"
        learning_source = "paper_deterministic_exploration"
        readiness_eligible = False  # Isolated
        allow_entry = True
```

### **Validation After Enable**:
```
Day 1-3: Monitor exploration entries
Target: >= 1 entry per day (vs 0 without)
Safety: No readiness contamination
If contamination detected: Rollback immediately
```

---

## 3️⃣ **Cost-Edge Decision**

### **NO CHANGE** if:
```
✅ Phase 5C confirms gap = 475-500x (consistent)
✅ No unit anomalies detected
✅ No impossible gaps outside normal range (>2000x)
✅ Math audit passes (expected vs required move units correct)
```

### **INVESTIGATE** if:
```
⚠️ Gap suddenly drops < 100x (market volatility spike)
⚠️ Gap exceeds 1000x in tail (extreme market)
⚠️ Unit anomalies detected (e.g., consistent unit mismatch)
⚠️ Cost calculation mismatch found
```

### **REDUCE MARGIN ONLY IF**:
```
🚫 Do NOT reduce unless:
   - Clear unit bug proven (not just "gap seems wide")
   - Alternative cost structure identified
   - Backtest shows +profitability with new margin
   - User explicitly approves specific margin value
```

### **Safe Actions Instead**:
```
✅ Accept market-driven starvation (current approach)
✅ Extend TP target (e.g., 1.5% → 2.0%)
✅ Widen entry range (fewer % requirement)
✅ Enable learning feedback (better segment selection)
✅ Enable exploration (discover better opportunities)
```

---

## 4️⃣ **REAL Trading Decision**

### **DO NOT ENABLE** unless ALL criteria met:

```
✅ Net expectancy positive AFTER fees
   - Expected PF > 1.20 minimum (after 7-day backtest)
   - Expectancy in bps > +10 bps minimum
   - Stable across symbols/regimes (no outliers)

✅ Profit factor stable
   - rolling50_pf > 1.15 for all major segments
   - No segment showing downtrend
   - Max drawdown < 5% (if applicable)

✅ Infrastructure pristine
   - Outbox clean/empty
   - RECON status = OK
   - No crashes or tracebacks (0 for entire freeze)
   - Firebase quota healthy (< 50% usage)
   - V5 bridge working perfectly

✅ Learning system calibrated
   - Segment weights stable and predictive
   - Learning feedback (if enabled) showing +quality
   - Qualification system working reliably

✅ Explicit operator approval
   - User manually approves specific date/time
   - Approval includes: expected daily profit, capital at risk, exit plan
   - Approval in writing (git commit message or similar)

✅ Real trading parameters set
   - TRADING_MODE = "live_real"
   - ENABLE_REAL_ORDERS = true
   - POSITION_SIZE = specific amount (not automatic)
   - MAX_DAILY_LOSS = specified threshold
   - EMERGENCY_STOP = configured
```

### **NEVER ENABLE WITHOUT**:
```
🚫 Do NOT enable if:
   - Still in learning phase (< READY status)
   - Any critical infrastructure issue remains
   - Outbox has pending/failed events
   - Recent crashes or tracebacks
   - User approval is uncertain or "kinda maybe"
   - Expected profitability is theoretical (not proven)
```

### **Validation After Enable** (if approved):
```
Hour 1-2: Monitor live orders, fills, slippage
Target: Real fills match paper simulation within 5%
If slippage > 10%: Pause trading, investigate
If fill ratio < 90%: Investigate market conditions
If losses > exit plan: Execute emergency stop immediately
```

---

## 📋 End-of-Freeze Checklist (June 9)

### **Gather Data**
- [ ] 7-day Phase 5A reports (activity funnel history)
- [ ] 7-day Phase 5B reports (learning feedback recommendations)
- [ ] 7-day Phase 5C reports (cost-edge gap consistency)
- [ ] 7-day Phase 5D reports (exploration opportunities)
- [ ] Daily trade reports (profitability, segments)
- [ ] Service logs (RECON status, crashes, outbox health)

### **Evaluate Learning Feedback**
- [ ] Count segments with n >= 20
- [ ] Count PROMOTE segments (PF >= 1.15)
- [ ] Count DEMOTE segments (PF < 0.75)
- [ ] Calculate estimated quality improvement
- [ ] Decision: ENABLE or DISABLE?
- [ ] If ENABLE: Test for 3 days, validate +quality

### **Evaluate Exploration**
- [ ] Calculate segment coverage %
- [ ] Count exploration candidates
- [ ] Verify safety caps implementable
- [ ] Verify readiness isolation
- [ ] Decision: ENABLE or DISABLE?
- [ ] If ENABLE: Test for 3 days, validate safety

### **Evaluate Cost-Edge**
- [ ] Confirm gap remains 400-500x
- [ ] Check for unit anomalies
- [ ] Verify math is correct
- [ ] Decision: NO CHANGE (expected)

### **Evaluate REAL Trading**
- [ ] Net PF > 1.20 after fees?
- [ ] Outbox clean?
- [ ] RECON OK?
- [ ] Zero crashes for 7 days?
- [ ] Infrastructure stable?
- [ ] Decision: ENABLE or WAIT?
- [ ] If WAIT: Why? (specific blockers?)
- [ ] If ENABLE: What date/time? (explicit approval)

---

## 🚨 Escalation Rules

### **If Anomaly Detected During Freeze**

Any of these **triggers immediate response** (not waiting for Day 9):

```
Anomaly 1: Cost-edge gap drops below 100x
  → Action: Check market conditions manually
  → Decision: Is market shifting? Expected or anomaly?
  → If expected: Natural volatility, continue
  → If anomaly: Investigate underlying cause

Anomaly 2: Learning segments appear (n > 20) during freeze
  → Action: Run Phase 5B to see feedback recommendations
  → Decision: Preview whether feedback would help?
  → Note this in end-of-freeze analysis

Anomaly 3: Exploration candidates jump from 2 to 10+
  → Action: Coverage must have shifted
  → Decision: Any opportunity insights?
  → Note for exploration decision on Day 9

Anomaly 4: Activity funnel bottleneck shifts unexpectedly
  → Action: All checks pass (RECON OK, outbox OK)?
  → If YES: Natural variance, continue
  → If NO: Investigate infrastructure

Anomaly 5: RECON != OK or crashes detected
  → Action: STOP freeze immediately
  → Follow: Emergency procedures in emergency_health_monitor.py
  → Reset: 7-day freeze counter from crash date
```

---

## 📊 Decision Tree (June 9)

```
START: 7-day freeze complete, all Phase 5 data collected

├─ Q1: Should we enable learning feedback?
│  ├─ n >= 20 AND PROMOTE segments exist AND improvement > 10%
│  │  → YES: Enable feedback, test 3 days
│  │  → Implement: PolicySelector.evaluate_signal() multipliers
│  │
│  └─ ELSE: NO, keep disabled
│     → Reason: Insufficient/unclear data
│     → Action: Extend freeze another 7 days? (user decides)

├─ Q2: Should we enable exploration?
│  ├─ Coverage < 30% AND candidates >= 5 AND safety caps OK
│  │  → YES: Enable exploration, test 3 days
│  │  → Implement: PAPER_DETERMINISTIC_EXPLORATION=true
│  │
│  └─ ELSE: NO, keep disabled
│     → Reason: Sufficient coverage or no candidates
│     → Action: Continue current segment focus

├─ Q3: Cost-edge margin OK?
│  ├─ Gap 400-500x consistent AND no unit bugs
│  │  → YES: No change needed
│  │  → Verdict: System is correct
│  │
│  └─ ELSE: Investigate
│     → Action: Manual market/code review
│     → Decision point: Only reduce if bug proven

├─ Q4: Ready for REAL trading?
│  ├─ PF > 1.20 AND infrastructure perfect AND outbox clean AND user approves
│  │  → YES: Enable REAL trading with approval date
│  │  → Implement: TRADING_MODE=live_real, ENABLE_REAL_ORDERS=true
│  │  → Monitor: Hour-by-hour validation
│  │
│  └─ ELSE: NO, stay PAPER
│     → Reason: One or more criteria missing
│     → Action: Document what's blocking, when it will be ready

END: All decisions documented in git commit message
```

---

## ✅ Final Approval Gate

Before implementing ANY decision:

```
✓ User has reviewed Phase 5 reports for 7 days
✓ User explicitly approves specific action (not "maybe")
✓ Action is logged in git commit with approval timestamp
✓ Implementation is isolated, testable, reversible
✓ Validation plan is documented
✓ Rollback plan exists if validation fails
```

---

## 🔐 Locked Rules

These rules **DO NOT CHANGE** without explicit user approval:

- ✅ Learning feedback enabled only if n >= 20 AND better PF
- ✅ Exploration enabled only if coverage gaps + candidates exist
- ✅ Cost-edge unchanged unless unit bug proven
- ✅ REAL trading requires explicit approval (not automatic)
- ✅ All infrastructure must be perfect before REAL
- ✅ Outbox must be clean before REAL
- ✅ RECON must be OK for any new feature
- ✅ Crash-free period required before REAL

---

**Status**: LOCKED (Effective 2026-06-09)  
**Next Review**: 2026-06-10 (after freeze ends, before implementation)  
**Authority**: User explicit decision framework
