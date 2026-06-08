---
name: paper-learning-validation
description: |
  Validates PAPER trading learning loop: entries admitted correctly, exits 
  recorded accurately, learned parameters affect future admission decisions. 
  Proves causality between learning updates and behavioral changes. Segments 
  metrics by bucket/regime/symbol. Never trust global WR—break down by segment.

---

# Paper Learning Validation Skill

## Validation Workflow

### 1. Collect Learning Artifacts

**From code:**
- `src/services/learning_tuner.py` — parameter updates
- `local_learning_storage/learning_database.sqlite` — trade records

**From logs:**
- `[LEARNING_UPDATE]` entries showing parameter changes
- Timestamps of tuner invocations

### 2. Pre/Post Comparison

**Pre-change (before parameter update T0):**
- Collect N_pre closed trades before T0
- Calculate: Entries, Admissions, PF, WR by segment

**Post-change (after T0):**
- Collect N_post closed trades after T0
- Same metrics

### 3. Causality Check

**Evidence of causality:**
- Parameter changed: Learning DB shows different value pre/post
- Behavior changed: Admissions pattern different post-change (e.g., fewer starvation bypasses)
- Direction correct: If gate stricter, should see fewer admits

**Example:**
```
BEFORE: 60 entries, 50 admits (83%), ECON_THRESHOLD=0.05
AFTER: 60 entries, 35 admits (58%), ECON_THRESHOLD=0.02

Causality: Stricter ECON gate → fewer admits ✓
```

### 4. Segment Health

For each segment (bucket/regime/symbol):

```
Segment: A_STRICT_TAKE / BEAR_TREND / BTCUSDT
- Closed trades (last 50): 45
- PF: 1.12x
- Net PnL: +0.00045 USD
- Confidence: HIGH (>30 samples)
- Health: POSITIVE_EDGE

Status: CONTINUE learning in this segment
```

### 5. Rolling Metrics

Don't use global WR. Track **last N closed trades**:

- Last 30 trades: WR 70%, PF 1.08x
- Last 100 trades: WR 65%, PF 1.02x
- Trend: Stable or improving?

## Key Commands

```bash
# Recent learning updates
grep "\[LEARNING_UPDATE\]" logs/*.log

# Trade breakdown by segment
sqlite3 learning.db "SELECT bucket, regime, COUNT(*) as n, \
  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)*100.0/COUNT(*) as wr_pct, \
  SUM(ABS(pnl_positive))/SUM(ABS(pnl_negative)) as pf \
  FROM trades GROUP BY bucket, regime;"
```

## Gates

- ✅ PASS: Parameter changed AND behavior changed in expected direction AND (PF > 1.0 OR net_pnl > 0)
- ⚠️ CAUTION: Parameter changed but behavior unchanged (learning not used)
- ❌ FAIL: Parameter changed but behavior worsened (negative learning signal)
