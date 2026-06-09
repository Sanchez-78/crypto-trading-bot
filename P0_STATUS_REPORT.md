# P0 EVIDENCE-BASED RECOVERY — STATUS REPORT
**Date:** 2026-06-09 09:45 UTC  
**Status:** FROZEN | ANALYZED | READY FOR P0.3

---

## EXECUTIVE SUMMARY

✅ **P0.1 Complete**: Service stopped, forensic snapshot locked  
✅ **P0.2 Complete**: Segment analysis shows data too fragmented for strict gates  
🛑 **P0.3 Pending**: Fix EV model + restart PAPER with validated segments only

**Critical Finding:** 
- Total 25 closed trades across 4 symbols
- NO segment meets n ≥ 30 threshold
- Only **ETHUSDT** shows positive PF (8 trades, 100% WR, +$0.01260)
- BTCUSDT/SOLUSDT/ADAUSDT all negative (0% WR, PF ≈ 0)
- Cannot validate strict EV gate with current dataset

**Decision:**
- ❌ DO NOT restart PAPER until EV gate is fixed
- ❌ DO NOT add more symbols/entry logic without validation
- ✅ DO fix EV model to use realized post-cost payoff
- ✅ DO rebuild dataset with corrected EV gate
- ✅ DO validate 100+ trades per segment before strict approval

---

## P0.1: FORENSIC FREEZE (COMPLETE)

**Action:** Stop service, preserve evidence

**Snapshot Location:** `forensic_snapshots/p0_20260609_094213/`

**Contents:**
- `cache.sqlite.live` — SQLite database (closed trades)
- `paper_open_positions.json` — Open positions state (none remaining)
- `service_env.txt` — Environment variables
- `service_unit.txt` — Systemd unit configuration
- `journal_last_200.log` — Service logs

**Service Status:** 
```
○ cryptomaster.service - INACTIVE (stopped)
```

---

## P0.2: SEGMENT ANALYSIS (COMPLETE)

### Overall Metrics
| Metric | Value |
|--------|-------|
| Total closed trades | 25 |
| Win Rate | 36.0% |
| Profit Factor | 0.28x |
| Net PnL | -$0.03589 |
| Status | **LOSING** |

### Segment Breakdown

| Symbol | Regime | Exit | n | WR | PF | Net PnL | Eligible? |
|--------|--------|------|---|----|----|---------|-----------|
| **BTCUSDT** | BEAR_TREND | TIMEOUT | 11 | 0% | 0.00x | -$0.02799 | ❌ |
| **SOLUSDT** | BEAR_TREND | TIMEOUT | 3 | 0% | 0.00x | -$0.01290 | ❌ |
| **SOLUSDT** | BULL_TREND | TIMEOUT | 1 | 0% | 0.00x | -$0.00415 | ❌ |
| **ADAUSDT** | RANGING | SL | 1 | 0% | 0.00x | -$0.00500 | ❌ |
| **ETHUSDT** | BEAR_TREND | TIMEOUT | 8 | 100% | ∞* | +$0.01260 | ❌ (n too small) |
| **ETHUSDT** | BULL_TREND | TIMEOUT | 1 | 100% | ∞* | +$0.00153 | ❌ (n too small) |

**\* High PF due to small n; not statistically valid**

### Eligibility Gate Assessment
```
Required: n ≥ 30, avg_pnl > 0, PF ≥ 1.2

Current state:
  ✅ ETHUSDT has positive edge (only 9 trades though)
  ❌ BTCUSDT 0% WR across 11 trades (systemic failure)
  ❌ SOLUSDT 0% WR across 4 trades (systemic failure)
  ❌ ADAUSDT 1 trade (insufficient sample)
  
  Result: ZERO segments eligible
```

---

## ROOT CAUSE ANALYSIS

### Why Dataset is Fragmented

1. **EV Gate Broken**: Accepting trades with negative realized payoff
2. **Poor Entry Signals**: BEAR_TREND/BTCUSDT trading against trend
3. **Wrong TP/SL Targets**: Too aggressive for 300s timeframe (0% TP hits)
4. **No Market Filtering**: Trading in RANGING/QUIET regimes (low edge)

### Why ETHUSDT Wins (Brief Success)

- Only 9 trades total
- All timeout exits (not TP/SL)
- Positive by luck (favorable market window or random entry alignment)
- NOT statistically significant (n < 30)
- Cannot validate as "strategy success"

---

## CONSTRAINTS FOR P0.3+

**Cannot proceed to P0.3 (EV model fix) until:**

1. **EV Gate Redesign:** Use realized segment payoff, not fixed RR=1.25
2. **Market Filtering:** Block entry in QUIET_RANGE, RANGING (no edge)
3. **Symbol Filtering:** Block BTCUSDT/SOLUSDT (0% WR proven), test ETHUSDT only
4. **Minimum Sample Size:** Require n ≥ 100 per segment before strict gate

**After EV Fix, PAPER Restart will require:**

- n ≥ 30 per segment
- avg_pnl_per_trade > 0 (post-cost)
- PF ≥ 1.2
- timeout_rate ≤ 60%
- All 4 gates must PASS

---

## NEXT STEPS (P0.3+)

### P0.3: EV Model Repair (RECOMMENDED)

**Current EV Formula (BROKEN):**
```python
ev = (win_prob × 1.25) - (1 - win_prob)
```

**Problems:**
- Uses fixed RR=1.25, ignores realized payoff
- Ignores TP/SL/TIMEOUT distribution
- Ignores exit_reason in evaluation

**Proposed EV Formula (CORRECT):**
```python
def calc_segment_ev(segment_trades):
    """Segment = symbol + side + regime + exit_reason."""
    
    if len(segment_trades) < 30:
        return None  # insufficient data
    
    p_tp = count(exit_reason="TP") / len(segment_trades)
    p_sl = count(exit_reason="SL") / len(segment_trades)
    p_timeout = count(exit_reason="TIMEOUT") / len(segment_trades)
    
    avg_tp = mean(pnl_usd for trade if exit_reason="TP")
    avg_sl = mean(pnl_usd for trade if exit_reason="SL")
    avg_timeout = mean(pnl_usd for trade if exit_reason="TIMEOUT")
    
    realized_ev = (p_tp × avg_tp) + (p_sl × avg_sl) + (p_timeout × avg_timeout)
    
    if realized_ev <= 0:
        return None
    
    return realized_ev
```

### P0.4: PAPER Restart (Conditional)

**Only if:**
- EV fix deployed
- First 30 ETHUSDT trades collected
- ETHUSDT segment shows avg_pnl > 0
- BTCUSDT/SOLUSDT remain blocked

**Scope:**
- ETHUSDT only
- BULL_TREND + BEAR_TREND only
- TP/SL targets: 0.5-0.8% / 1.5-2.0% (realistic for 300s)
- Entry gate: Realized EV > 0 per segment

### P0.5: Scale Up

**Only after:**
- 100 ETHUSDT trades with PF ≥ 1.2
- BEAR_TREND root cause understood (why BTCUSDT fails)
- Other symbols tested individually

---

## REAL TRADING READINESS

**Current Status:** ❌ **BLOCKED**

**Unblock Criteria:**
1. Segment profitability proven (100+ trades, PF ≥ 1.2)
2. EV model validated against realized payoff
3. Dashboard metrics match SQLite (no discrepancies)
4. Zero crashes in 48h continuous run
5. CEO approval (final gate)

**Estimated Timeline:**
- P0.3 (EV fix): 1-2 days
- P0.4 (restart): Day 3
- P0.5 (validation): Days 4-7
- Real trading: Week 2+ (if metrics hold)

---

## FILES & REFERENCES

| File | Purpose |
|------|---------|
| `forensic_snapshots/p0_20260609_094213/` | Evidence lock (immutable) |
| `TRADING_LOGIC_AUDIT.md` | Pre-fix audit (now INVALIDATED by P0.2) |
| `P0_STATUS_REPORT.md` | This document (current truth) |

---

**Report Author:** Claude (Evidence-Based Patch Orchestrator)  
**Approval Status:** Ready for P0.3 review
