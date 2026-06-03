# Paper Learning Monitoring — Daily Status Report

**Added**: 2026-06-03  
**Script**: `scripts/paper_learning_status.py`  
**Updates**: Daily at 18:00 UTC (after daily_trade_report.py)

---

## 📊 What This Shows

Detailed breakdown of paper trading learning progress:

```
✅ Total segments (symbol:regime:side combinations)
✅ Ready segments (n >= 20 samples)
✅ Learning segments (n < 20, collecting data)
✅ Samples collected (progress to 50 = READY)
✅ Win rate & Profit Factor per segment
✅ Rolling 20/50/100 metrics
✅ Expectancy per segment
✅ Learning feedback readiness
✅ READY status verdict
```

---

## 🚀 Usage

### **Daily Automated (18:00 UTC)**
```bash
python3 scripts/paper_learning_status.py
```

### **Manual (Anytime)**
```bash
ssh root@78.47.2.198
cd /opt/cryptomaster
python3 scripts/paper_learning_status.py
```

---

## 📈 Example Output (Once Data Available)

```
╔════════════════════════════════════════════════════════════════════════════════╗
║ PAPER LEARNING STATUS REPORT (2026-06-09 18:00 UTC)
╚════════════════════════════════════════════════════════════════════════════════╝

📊 OVERALL LEARNING STATUS
  Total segments:           22
  Ready (n >= 20):           3
  Learning (n < 20):        19
  Total samples collected:   65
  Progress to READY:        65 / 50 trades needed

  ✅ LEARNING READY — System can transition from PAPER to next phase

🎯 TOP SEGMENTS BY SAMPLES (Ready for feedback)

   READY SEGMENTS (n >= 20)
   BTCUSDT:BULL:LONG                   n= 24 WR= 100.0% PF= 1.45 ━━━━━━━━━━
   ETHUSDT:BULL:LONG                   n= 21 WR=  95.2% PF= 1.32 ━━━━━━━━━
   SOLUSDT:RANGE:SELL                  n= 20 WR=  85.0% PF= 1.18 ━━━━━━

   LEARNING SEGMENTS (n < 20, collecting data)
   ADAUSDT:BEAR:SHORT                 [████░░░░░░░░░░░░░░]  8/20
   BNBUSDT:BULL:LONG                  [███████░░░░░░░░░░░░] 11/20
   XRPUSDT:RANGE:BUY                  [██░░░░░░░░░░░░░░░░░]  3/20

💡 SEGMENT PERFORMANCE ANALYSIS

   Best performers (by PF):
   ✅ BTCUSDT:BULL:LONG                PF=1.45 n= 24
   ✅ ETHUSDT:BULL:LONG                PF=1.32 n= 21
   ✅ SOLUSDT:RANGE:SELL               PF=1.18 n= 20

   Struggling (by PF):
   ❌ ADAUSDT:BEAR:SHORT               PF=0.62 n=  8

📈 EXPECTANCY ANALYSIS

   Positive expectancy: 18 segments (good)
   Negative expectancy:  4 segments (need work)

   Highest EV: BTCUSDT:BULL:LONG (+0.000234)
   Lowest EV:  ADAUSDT:BEAR:SHORT (-0.000089)

🔄 ROLLING METRICS SUMMARY

   Rolling 20:   avg PF = 1.28
   Rolling 50:   avg PF = 1.25
   Rolling 100:  avg PF = 1.22

🎓 LEARNING FEEDBACK READINESS

   ✅ READY FOR FEEDBACK
      Promote-able segments (PF >= 1.15): 15
      Demote-able segments (PF < 0.75):    2
      → Could improve quality by prioritizing 15 profitable segments

📋 VERDICT

   ✅ LEARNING COMPLETE — Ready for next phase
      Recommended: Enable learning feedback & decision phase

╔════════════════════════════════════════════════════════════════════════════════╗
║ End of Paper Learning Status Report
╚════════════════════════════════════════════════════════════════════════════════╝
```

---

## 🎯 Key Metrics Explained

| Metric | Meaning | Target |
|--------|---------|--------|
| **Ready segments (n >= 20)** | Segments with reliable sample size | 3+ for feedback |
| **Rolling 20/50/100 PF** | Profit factor over last N trades | > 1.15 (profitable) |
| **Expectancy** | Average profit per trade | > +0.0001 (positive) |
| **Promote-able** | Segments good enough to prioritize | >= 3 to enable feedback |
| **READY status** | Total samples collected | 50 = can enable feedback |

---

## 📅 Timeline

### **Days 1-6** (Collecting Data)
```
Expected output: "NOT YET READY — < 30% progress"
Action: Keep paper trading, collect data
```

### **Days 6-7** (Getting Close)
```
Expected output: "ON TRACK — 60% progress"
Action: Continue, few more days to 50 samples
```

### **Day 7-9** (Ready or Close)
```
Expected output: "LEARNING COMPLETE" or "ON TRACK"
Action: Review Phase 5 reports, make decision on Day 9
```

---

## 🚨 What to Watch For

### **✅ Good Signs**
- Total segments growing (more data)
- Ready segments appearing (n >= 20)
- Win rates 70%+ across segments
- PF > 1.15 on multiple segments
- Positive expectancy majority

### **⚠️ Concerning Signs**
- Total samples stalled (no new trades)
- Ready segments with PF < 0.75 (unprofitable)
- Negative expectancy on 50%+ segments
- Huge variance in segment performance
- Rolling metrics declining

### **🔴 Critical Issues**
- Zero samples after 24 hours (trading stopped)
- All segments with PF < 0.5 (systemic problem)
- Learning file corrupted (error on script run)

---

## 📊 Decision on Day 9

When you see "LEARNING COMPLETE":

```
✅ IF: 3+ ready segments AND avg PF > 1.15
  → Enable learning feedback (Phase 5 rules apply)
  → Test 3 days, validate quality improvement

❌ IF: < 3 ready segments OR avg PF < 1.0
  → Extend freeze another 7 days
  → Need more data, metrics not reliable yet
```

---

## 📋 Integration with Phase 5

This script works alongside Phase 5 reports:

- **Phase 5B** (Shadow Feedback) — what feedback WOULD do
- **Paper Learning Status** — what's actually happened
- **Comparison** — Do shadow predictions match reality?

---

## 🔧 Manual Testing

```bash
# Test on Hetzner
ssh root@78.47.2.198
cd /opt/cryptomaster
python3 scripts/paper_learning_status.py

# Output: Will show segments once data is available
# Expected Day 6-7: Show ready segments & readiness verdict
```

---

**Status**: ✅ LIVE  
**Deploy Date**: 2026-06-03  
**First Output**: 2026-06-09 (end of freeze)
