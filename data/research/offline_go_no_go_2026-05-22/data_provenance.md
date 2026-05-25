# Data Provenance and Analysis Limitations

**Audit Date:** 2026-05-22  
**Code State:** 735ba35 (Revert P1.1AP-L shadow sampler experiment)  
**Environment:** Development machine (Windows 11) — no live Firebase access, no journalctl

## Available Data Sources

### 1. Snapshot Data (Provided in Audit Specification)

At 2026-05-22 13:01 UTC, dashboard/model reported:

**Canonical State:**
- Canonical trades: 100 (11 wins, 4 losses, 85 neutral/other)
- Win Rate (wins only): 73.3% = 11/(11+4)
- Net closed PnL: -0.00023955 BTC
- Profit Factor: 0.49x
- Learning health: 0.0000 (BAD status)
- LM trades in learning monitor: 200
- Last trade: 616h 29m ago
- Execution engine: Positions=0, Exposure=0, WR=0.00%, Edge=0.00000

**Exit Attribution (100 canonical trades):**
| Exit Type | Count | Net PnL | % of Total Loss |
|---|---:|---:|---:|
| PARTIAL_TP_25 | 8 | +0.00005131 | -2.2% |
| MICRO_TP | 4 | +0.00000556 | -2.4% |
| TIMEOUT_FLAT | 2 | -0.00000788 | 3.3% |
| REPLACED | 3 | -0.00003500 | 14.6% |
| TIMEOUT_LOSS | 2 | -0.00003975 | 16.6% |
| SCRATCH_EXIT | 47 | -0.00009236 | 38.5% |
| STAGNATION_EXIT | 34 | -0.00012143 | 50.7% |
| **Total** | **100** | **-0.00023955** | **100%** |

**Per-Symbol Results:**
| Symbol | Net PnL | Displayed WR | Status |
|---|---:|---|---|
| BTC | -0.00004517 | 100% | Inconsistent (shows win but negative PnL) |
| ETH | -0.00003778 | 100% | Inconsistent (shows win but negative PnL) |
| ADA | -0.00004278 | ? | Loss |
| BNB | -0.00004700 | 100% | Inconsistent (shows win but negative PnL) |
| DOT | -0.00007885 | ? | Largest per-symbol loss |
| SOL | -0.00000038 | 100% | Inconsistent (shows win but negative PnL) |
| XRP | +0.00001241 | ? | **Only positive symbol** |
| **Sum** | **-0.00023955** | | |

### 2. Code Analysis Sources

Examined files for metric calculation logic:

- **canonical_metrics.py** — PF, win rate, expectancy calculation logic
  - PF formula: gross_pnl / abs(gross_loss)
  - WIN/LOSS/FLAT classification per trade
  - Neutral outcome handling (TIMEOUT, SCRATCH_EXIT, STAGNATION_EXIT treated as FLAT)
  
- **exit_attribution.py** — Exit type definitions and tracking
  - 16 exit types defined (TP, SL, TRAIL, PARTIAL_TP, TIMEOUT, SCRATCH, STAGNATION, etc.)
  - Exit stats aggregation per type
  
- **learning_event.py** — Runtime metrics tracking
  - METRICS dict with trades, wins, losses, timeouts, profit tracking
  - _close_reasons dict to count each exit type
  - Recent results deque (maxlen=50) for trending

- **trade_executor.py** — Paper trade execution and learning flow
  - Paper entry/exit paths
  - Learning update integration points
  
- **firebase_client.py** — Firestore state persistence
  - Writes canonical trades, metrics, learning state to Firebase
  - Quota system (50k reads/day, 20k writes/day)

### 3. Unavailable Data

The following data required for complete analysis is not available on development machine:

**❌ Firebase Collections:**
- `canonical_closed_trades` — historical closed trades with full fields
- `learning_monitor` — learning state snapshots
- `paper_trades` — paper training trade history
- `metrics` — timestamped metric snapshots

**❌ Runtime Logs:**
- journalctl logs from production system (requires live Hetzner server access)
- Application event logs covering trade lifecycle
- LEARNING_UPDATE events with model state
- PAPER_EXIT events with exit attribution details

**❌ Offline Exports:**
- CSV/JSONL exports of closed trades for analysis
- Rejection pattern logs (RDE output, gates crossed, etc.)
- Signal history with entry/exit attribution

**Note:** Scripts `export_paper_training_dataset.py` and `paper_training_quality_report.py` exist but require pre-existing JSONL datasets (not present).

## Analysis Approach

Given the constraints:

1. **Mathematical Validation** — Use snapshot data to verify reported metrics against canonical calculation logic
2. **Code Path Analysis** — Trace exit attribution, canonical learning, shadow isolation in source
3. **Snapshot Inconsistencies** — Identify contradictions between displayed win rate and actual PnL
4. **Dashboard Reconciliation** — Document mismatch between dashboard WR 73.3% vs PF 0.49 vs net -0.00024
5. **Loss Attribution** — Analyze why SCRATCH+STAGNATION account for 81/100 trades and 89% of losses
6. **Economic Conclusion** — Determine if strategy can achieve positive edge given current state

## Minimum Data for Future Audit

To conduct a complete offline GO/NO-GO audit without production constraints:

1. **Export canonical_closed_trades from Firebase** (read-only)
   ```
   ~100 records with: symbol, side, entry_price, exit_price, entry_ev, 
   exit_reason, result, profit, entry_ts, exit_ts, regime
   ```

2. **Export paper_trades for each bucket** (C_WEAK_EV_TRAIN, B_RECOVERY_READY, D_NEG, etc.)
   ```
   Separate populations, clearly tagged by bucket
   ```

3. **Export rejection patterns** (last 7 days)
   ```
   Signal ID, rejection_reason, original_decision, gating level, symbol, regime
   ```

4. **Export LEARNING_UPDATE events** (last 100 events)
   ```
   Timestamp, trade_id, old_pf, new_pf, delta_in_lm, learning_rate
   ```

## Conclusion

This audit is constrained to **snapshot analysis + code inspection**. 
A complete GO/NO-GO determination would require live Firebase data export.
Current analysis bases verdict on snapshot inconsistencies and mathematical logic validation.
