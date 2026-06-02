# 7-Day Freeze Period — Baseline Monitoring & Decision Criteria

**Start Date**: 2026-06-02 13:05 UTC  
**End Date**: 2026-06-09 13:05 UTC  
**Status**: 🔒 FROZEN — No patches unless critical conditions met

---

## Freeze Rules

### ✅ Patches ALLOWED if these occur:

| Condition | Threshold | Action |
|-----------|-----------|--------|
| **RECON != OK** | status=WARN or FAIL | Immediate patch |
| **Outbox failed** | Failed events detected | Immediate patch |
| **Dashboard zero** | All metrics = 0 (stale) | Immediate patch + restart |
| **Firebase quota critical** | >90% of daily writes | Immediate patch |
| **Runtime crash** | Traceback / Exception / FATAL | Immediate patch + restart |
| **Learning missing** | No update after PAPER_EXIT | Immediate patch |

### ❌ NOT patches (baseline metrics only):

| Condition | Reason | Response |
|-----------|--------|----------|
| **LEARNING_STALL** | Entry starvation is root cause | Monitor, don't patch |
| **ENTRY_STALL** | Market-driven, expected behavior | Monitor, don't patch |
| **Low entry rate** | 0-1 entries/hour is baseline | Collect 7-day data |
| **Low learning rate** | Follows entry rate | Collect 7-day data |
| **ECON_BAD rejects** | Conservative gate, expected | Monitor frequency |

---

## Daily Health Check

**Run every morning (9:00 UTC)**:
```bash
cd /opt/cryptomaster
bash scripts/daily_health_check.sh
```

**What it checks**:
1. ✅ RECON status
2. ✅ Outbox health
3. ✅ Dashboard metrics flowing
4. ✅ Firebase quota usage
5. ✅ Service crashes
6. ✅ Learning updates
7. 📊 Baseline metrics (entries, learning, blocks, cost-edge)

**Output**: Daily log in `/tmp/daily_health_YYYY-MM-DD_*.log`

---

## Baseline Metrics to Track

### Daily Counts

| Metric | Target | Baseline | Notes |
|--------|--------|----------|-------|
| **entries_24h** | 6-10 | ~1 | PAPER_ENTRY_ADMIT logs |
| **learning_updates_24h** | 3-5 | ~1 | V5_BRIDGE_LEARNING_UPDATE |
| **closed_trades_24h** | 5-8 | ~1 | PAPER_EXIT events |
| **firebase_writes_24h** | <8,000 | ~1,500 | quota tracking |

### Entry Blocking Breakdown (Percentage)

```
cost_edge_rejected: 40-60% (expected)
ECON_BAD_rejected: 20-40% (expected)
max_open_per_symbol: 5-15% (normal)
duplicate_rejected: 2-5% (normal)
regime_not_ready: 5-10% (normal)
Other: <5% (normal)
```

### Cost-Edge Diagnostics

Track per check cycle:
- `expected_move_pct`: ~0.02-0.05% (typical)
- `required_move_pct`: ~0.20-0.30% (typical)
- **Gap**: 4-15x mismatch = entry starvation root cause
- **Spreadsheet**: Track daily avg to see if volatility changes

### Learning Segment Performance

Watch for:
- Segments with >10 trades (reliable sample)
- Rolling profit factor (pf) trend
- Expectancy change over 7 days
- Which symbol/regime consistently profitable?

### Firebase Quota

Daily quota usage:
- **Reads**: Should be <500/day (mostly cached)
- **Writes**: ~1,500/day typical
- **Margin**: 80%+ unused (safety)
- **Risk**: Never > 15,000/day

### EMERGENCY_MONITOR Alert Frequency

Track:
- How many times per day alert fires?
- Which conditions most frequent?
- Are alerts spurious or early warnings?
- Are false positives >50%?

---

## Data Collection (Automated)

**Daily log file** stored in `/tmp/`:
- `daily_health_2026-06-02_*.log`
- `daily_health_2026-06-03_*.log`
- ... (7 files total)
- **Automatic cleanup**: Older than 7 days deleted

**Manual collection point (end of day 7)**:
```bash
cd /opt/cryptomaster
# Collect all 7 days of logs
tar -czf /tmp/baseline_2026-06-02_to_06-09.tar.gz /tmp/daily_health_*.log
# Download for analysis
scp root@78.47.2.198:/tmp/baseline_2026-06-02_to_06-09.tar.gz .
```

---

## End-of-Freeze Analysis (2026-06-09)

### Questions to Answer

#### Q1: Is entry starvation really market-driven?

**Data to check**:
- Total entries_24h across all 7 days
- Total EV candidate count across all 7 days
- Ratio: entries / candidates (should be <5% if market-driven)

**Decision**:
- **If ratio <1%**: Market is constraint (spreads too wide)
  - Action: Accept starvation, wait for volatility
- **If ratio >5%**: Gates are too strict
  - Action: Further optimize cost-edge/ECON_BAD

#### Q2: Which gate dominates rejections?

**Data to check**:
- cost_edge_rejected %
- ECON_BAD_rejected %
- max_open_per_symbol %
- Others %

**Decision**:
- **If cost_edge >60%**: Cost structure is primary limit
- **If ECON_BAD >40%**: Economic conditions are limiting
- **If max_open >20%**: Position capacity is bottleneck

#### Q3: How much learning data was collected?

**Data to check**:
- Total learning_updates_24h × 7 = Total updates
- Target READY status: 50 updates
- Progress: X / 50

**Decision**:
- **If <10 updates total**: Learning pace too slow (entry starvation is problem)
- **If 10-30 updates**: Moderate pace (2-3 weeks to READY)
- **If >30 updates**: Good pace (1-2 weeks to READY)

#### Q4: Is rolling expectancy improving?

**Data to check**:
- rolling20_pf on Day 1
- rolling20_pf on Day 7
- Trend direction (improving, stable, declining)?

**Decision**:
- **If improving**: Learning is working, strategy is calibrating
- **If stable**: Strategy at equilibrium, may need market change
- **If declining**: Overfitting or market regime shift

#### Q5: Is any symbol/side/regime consistently better?

**Data to check**:
- Segment profitability ranking by Day 7
- Which segments have >10 winning trades?
- Which segments have >10 total trades?

**Decision**:
- **If clear winners**: Implement focus (bias entries to profitable segments)
- **If mixed results**: No clear pattern (collect more data)
- **If all losers**: System still unprofitable (major issue)

#### Q6: Is infrastructure stable?

**Data to check**:
- EMERGENCY_MONITOR alert count (should be <2/day)
- Any service restarts needed? (should be 0)
- Firebase quota ever at risk? (should be <75%)
- Outbox ever stuck? (should be 0 times)

**Decision**:
- **If all nominal**: Infrastructure ready for prod monitoring
- **If any alerts >10/day**: Infrastructure needs tuning
- **If crash/restart needed**: Critical bug to patch

---

## Post-Freeze Decision Flowchart

```
START: 2026-06-09 13:05 UTC
├─ Q1: Entry starvation market-driven?
│  ├─ YES (ratio <1%) → Accept & continue baseline
│  └─ NO (ratio >5%) → Patch: Lower cost-edge further
│
├─ Q2: Which gate dominates?
│  ├─ cost_edge (>60%) → Patch: Reduce safety_margin
│  ├─ ECON_BAD (>40%) → Patch: Lower threshold
│  └─ Other (<40%) → Starvation is market-driven
│
├─ Q3: Learning progress?
│  ├─ <10 updates → Accept slow pace, continue
│  ├─ 10-30 updates → On track, 2-3 weeks to READY
│  └─ >30 updates → Fast, 1-2 weeks to READY
│
├─ Q4: Rolling expectancy improving?
│  ├─ YES → Learning working, continue
│  └─ NO → May indicate overfitting, investigate
│
├─ Q5: Symbol/side/regime clarity?
│  ├─ Clear winners → Future: segment prioritization
│  └─ Mixed → Continue broad sampling
│
└─ Q6: Infrastructure stable?
   ├─ YES → Ready for longer monitoring
   └─ NO → Fix critical issues before continuing
```

---

## Contingency: What If Critical Alert Fires?

**During freeze, if one of 6 critical conditions occurs**:

1. **IMMEDIATELY**: Run emergency remediation
2. **THEN**: Document what happened
3. **THEN**: Patch the issue
4. **THEN**: Reset 7-day clock (new freeze period starts)

**Example**:
- Day 3: Traceback detected
- Action: Patch, restart service
- Result: New 7-day freeze starts (Day 3 → Day 10)

---

## Resources

### Daily Check Script
```bash
/opt/cryptomaster/scripts/daily_health_check.sh
```

### Outbox Audit
```bash
cd /opt/cryptomaster
venv/bin/python scripts/audit_v5_outbox.py
```

### Manual Log Access
```bash
# See all logs from past 24 hours
journalctl -u cryptomaster.service --since "24 hours ago" -n 1000

# Search for specific metric
journalctl -u cryptomaster.service --since "24 hours ago" | grep "PAPER_ENTRY_ADMIT"

# Save 7-day snapshot
journalctl -u cryptomaster.service --since "7 days ago" > /tmp/7day_snapshot.log
```

### Baseline Spreadsheet Format
```csv
Date,entries_24h,learning_updates_24h,cost_edge_rejects_%,ECON_BAD_rejects_%,firebase_writes,alert_count,rolling20_pf
2026-06-02,1,1,65,25,1500,2,0.49
2026-06-03,2,2,62,28,1600,1,0.51
...
```

---

## Final Decision (2026-06-09)

**Freeze result** (to be completed):
- [ ] All critical systems stable
- [ ] Entry starvation root cause identified
- [ ] Learning rate acceptable
- [ ] No patches required during freeze
- [ ] Ready for next 7-day observation OR
- [ ] Ready for targeted patch + new freeze

**Next phase options**:
1. **Continue monitoring** (2 more weeks)
2. **Implement targeted patch** + reset freeze
3. **Transition to REAL trading** (if READY status achieved)
4. **Increase observation period** (if unclear trends)

---

**Status**: 🔒 **FROZEN UNTIL 2026-06-09**

No patches unless critical. Baseline metrics only. Daily checks enabled.

For questions during freeze period, contact: bob.sanchez78@gmail.com
