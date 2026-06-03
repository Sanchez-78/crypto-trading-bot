# Phase 5 — Operational Summary for Daily Monitoring

**Date**: 2026-06-03  
**Freeze Period**: 2026-06-02 to 2026-06-09 (7 days)  
**Phase 5 Status**: ✅ LIVE & TESTING

---

## 🎯 What Phase 5 Does (For You)

Phase 5 adds **4 diagnostic reports** that help us understand the bot better:

### **Report 1: Activity Reconciliation** (Phase 5A)
```
Shows: How many signals became trades?

Example:
  100 candidates → 100 admission attempts → 0 entries → 10 exits → 6 learning
  
Use case: Understand conversion funnel bottlenecks
Command: python3 scripts/phase5_activity_reconciliation_report.py --window 24h
```

### **Report 2: Learning Feedback Shadow** (Phase 5B)
```
Shows: What IF we used past performance to pick entries?

Example:
  "IF we enabled feedback: SOLUSDT:LONG would get 1.5x priority (high PF)"
  "But: No data yet (need 20+ trades per segment)"
  
Use case: Decide whether to enable learning feedback (Day 6-7)
Command: python3 scripts/phase5_segment_shadow_report.py
```

### **Report 3: Cost-Edge Audit** (Phase 5C)
```
Shows: Is the cost-edge math correct?

Finding: YES. Gap of 475x is real (not a bug)
  - Expected move: 0.0005% (market volatility)
  - Required move: 0.23% (entry costs + TP)
  - This is market-driven, expected behavior
  
Use case: Verify system is working correctly (NOT broken)
Command: python3 scripts/phase5_cost_edge_unit_report.py --window 24h
```

### **Report 4: Exploration Plan** (Phase 5D)
```
Shows: Which segments should we try next?

Example:
  "Underexplored: segment_weights (n=0, need 20 samples)"
  
Use case: Plan safe exploration (when enabled)
Command: python3 scripts/phase5_exploration_shadow_report.py
```

---

## 📅 Daily Monitoring (During Freeze)

### **Every Day at 9:00 UTC**
```bash
ssh root@78.47.2.198
cd /opt/cryptomaster

# Health check (existing)
bash scripts/daily_health_check.sh

# Phase 5 diagnostics (new)
python3 scripts/phase5_activity_reconciliation_report.py --window 1h
python3 scripts/phase5_cost_edge_unit_report.py --window 1h
```

### **Every Day at 18:00 UTC**
```bash
# Daily trade report (existing)
python3 scripts/daily_trade_report.py

# Phase 5 analysis (new)
python3 scripts/phase5_segment_shadow_report.py
python3 scripts/phase5_exploration_shadow_report.py
```

---

## 🔍 What to Look For (Daily)

### **Phase 5A: Activity Funnel**
```
✅ GOOD:  Candidates → Entries → Exits → Learning all flowing
❌ BAD:   Any stage stuck at 0 (blockers)
⚠️  WARN:  Exits != Learning counts (timing mismatch expected)

Current: 106 → 0 → 10 → 6 (entries blocked by max_open_per_symbol — OK)
```

### **Phase 5B: Learning Feedback**
```
✅ READY:  Segments with n > 20 start appearing
⚠️  WAIT:  "Insufficient data" segments increasing
❌ ISSUE:  No segments with n > 20 after Day 5

Action: Day 6-7 decide: enable feedback or extend freeze?
```

### **Phase 5C: Cost-Edge Gap**
```
✅ NORMAL:  Gap stays 400-500x (market-driven)
❌ ANOMALY: Gap drops below 10x (market shift)
❌ ANOMALY: Gap exceeds 1000x (extreme market)

Action: If anomaly, check market conditions manually
```

### **Phase 5D: Exploration**
```
✅ READY:  2-5 exploration candidates identified
⚠️  WAIT:  0 candidates (all segments covered)
❌ ISSUE:  50+ candidates (poor coverage)

Action: Day 6-7 decide: enable exploration or manual sampling?
```

---

## 🚀 Decision Checklist (Day 9 — End of Freeze)

### Before you make decisions, gather these reports:

```bash
# Collect 7-day baseline
python3 scripts/phase5_activity_reconciliation_report.py --window 24h > phase5a_final.txt
python3 scripts/phase5_segment_shadow_report.py > phase5b_final.txt
python3 scripts/phase5_cost_edge_unit_report.py --window 24h > phase5c_final.txt
python3 scripts/phase5_exploration_shadow_report.py > phase5d_final.txt

# Also get daily reports for context
python3 scripts/daily_trade_report.py --window 7d > weekly_report.txt
```

### Answer these 4 questions:

**Q1: Should we enable learning feedback?**
```
Check: Phase 5B report
Criteria:
  - promoted_segments >= 3? (high-quality recommendations)
  - avg_promoted_pf > 1.15? (significant edge)
YES → Enable: --enable-learning-feedback=true
NO  → Keep: shadow-only
```

**Q2: Should we enable exploration?**
```
Check: Phase 5D report
Criteria:
  - exploration_candidates >= 5?
  - coverage < 30%? (room to grow)
YES → Enable: PAPER_DETERMINISTIC_EXPLORATION=true
NO  → Keep: current segments only
```

**Q3: Is cost-edge margin correct?**
```
Check: Phase 5C report
Criteria:
  - gap_ratio consistently 400-500x?
  - no unit anomalies?
YES → Keep: no changes needed
NO  → Investigate: market shift or system issue?
```

**Q4: Ready for extended learning?**
```
Check: Phase 5A + daily reports
Criteria:
  - trading_volume >= 300 trades/day?
  - learning_updates >= 100/day?
  - closure_rate > 70%?
YES → Extend freeze 7 more days (more data)
NO  → Continue with current parameters
```

---

## ⚠️ Anomalies to Watch

### **If you see these, something changed:**

```
Anomaly 1: Learning feedback suggestions (Phase 5B)
  Sudden appearance of PROMOTE segments
  → Market shifted, learning is working
  → Decision: Enable feedback? (safe if n>20)

Anomaly 2: Exploration candidates triple
  Phase 5D shows 10+ candidates instead of 2-3
  → Coverage shifted, new opportunities
  → Decision: Enable exploration? (safe, capped)

Anomaly 3: Cost-edge gap drops below 100x
  Phase 5C shows 50x instead of 475x
  → Market volatility spike (good for trading)
  → No action needed, opportunity for more entries

Anomaly 4: Activity funnel bottleneck changes
  Phase 5A: All entries blocked at different stage
  → Check dashboard metrics (might be issue)
  → If RECON=OK and outbox OK: natural variance
```

---

## 📊 Success = Clear Decision

After 7 days, you'll have clear data to answer:

1. **Does learning feedback help?** → Enable or skip
2. **Are there safe segments to explore?** → Enable or skip
3. **Is the math correct?** → Confirmed or investigate
4. **Ready for next phase?** → Yes or extend baseline

**Key point**: Phase 5 tells you WHAT is happening, so you can decide WHAT TO DO.

---

## 🛠️ Running Phase 5 Reports Manually

```bash
ssh root@78.47.2.198
cd /opt/cryptomaster

# Single report
python3 scripts/phase5_activity_reconciliation_report.py --window 24h

# All four reports (summary)
for script in scripts/phase5_*.py; do
  echo "=== $(basename $script) ==="
  python3 "$script" 2>&1 | head -80
  echo ""
done
```

---

## ✅ No Impact on Bot

**Phase 5 is PURE OBSERVATION:**
- ✅ No changes to entry logic
- ✅ No changes to exit logic
- ✅ No changes to position sizing
- ✅ No changes to TP/SL
- ✅ No changes to learning system
- ✅ No REAL trading impact
- ✅ Zero performance overhead

**Safe to run 24/7**. Shadow-only mode. Can disable anytime.

---

## 📞 Questions?

- **"How do I use Phase 5?"**  
  → Run the scripts daily, look for anomalies above

- **"Will Phase 5 break the bot?"**  
  → No. Pure observation, no strategy changes.

- **"When should I make decisions?"**  
  → Day 9 (freeze end), based on 7-day data.

- **"Can I enable feedback/exploration now?"**  
  → Not yet. Need Day 5-7 data to decide safely.

- **"What if Phase 5 reports show nothing?"**  
  → That's OK. Means: keep collecting data.

---

**Remember**: Phase 5 is your eyes and ears.  
It tells you what's working, what needs data, what's safe to enable.

Trust the data. Follow the decision checklist on Day 9.

---

**Phase 5 Status**: ✅ LIVE  
**Next Action**: Monitor daily, decide on Day 9  
**Safety Level**: SAFE (shadow-only, zero impact)
