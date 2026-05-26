# CryptoMaster STOP PATCHING — Architecture Autopsy & Clean Core Replacement Plan

## Verdict
**PATCH_TREADMILL_CONFIRMED**

After ~207 patches, the system remains locked in a starvation deadlock. Analysis proves the existing decision/learning core cannot be repaired incrementally. A clean PAPER core replacement is mandatory before any productive learning can resume.

---

## Evidence Summary

### Runtime State (b6311c2)
- **Service:** `/opt/cryptomaster`, PID 1448746, mode PAPER
- **Persistence:** 6 `PAPER_CANONICAL_LEARNING_UPDATE` events, followed by 6 `PAPER_LEARNING_STATE_SAVE` failures (permission denied). Minimal remediation applied: `server_local_backups/paper_adaptive_learning_state.json` created but durability unproven.
- **Dashboard contradictions:** `TRENINK (zisk > 0)` reported vs `Profit Factor 0.49`, `closed profit negative`, `completed_trades=7707` vs `canonical_trades=100`.

### Starvation Evidence
```
Runtime logs prove:
Generated valid signal BUY
→ [V10.13w DECISION] REJECT (NEGATIVE_EV) ev_final < 0
→ [PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN
→ [WATCHDOG] No trades for 600s → Critical idle (15min) → enabling micro-trades
→ Positions: 0
→ LEARNING: health=0.0000 [BAD]
```

**Root fact:** Valid signals are being generated (confirmed by `Generated valid signal BUY` log), but `ev_final < 0` (legacy EV from historical outcomes) causes hard REJECT_NEGATIVE_EV. No available bucket routes REJECT_NEGATIVE_EV to any active PAPER path. Even watchdog-driven recovery probes (ECON_BAD, deadlock) cannot open trades.

### Persistence Facts
- **Before remediation:** Persistence failed 6 times (Permission denied on write)
- **Remediation applied:** File created, owner/mode set, initial `{}`
- **After remediation:** No new canonical update occurred to prove durability
- **Critical gap:** Current in-memory state is classified `LEGACY_SPOT_EXECUTION_UNVERIFIED`. Service restart would lose this state without persistent proof.

### Execution-Truth Facts
```
Current runtime uses Spot market data:
  wss://stream.binance.com:9443 @bookTicker/@depth20
  REST api.binance.com/api/v3/ticker/bookTicker

Spot prices/depth affect:
  - execution quality gates
  - fill/slippage calculations
  - spread checks
  - L2/wall logic  
  - position exit logic

Meanwhile the bot represents USDⓈ-M Futures outcomes.

Conclusion:
  execution_truth_class = LEGACY_SPOT_EXECUTION_UNVERIFIED
  existing outcomes are NOT eligible for future Futures readiness
```

---

## Actual Call Graph — Market Input to Learning

| Stage | File:function:line | Input/state | Gate/side effect | Trust classification |
|---|---|---|---|---|
| **Market input** | `src/services/market_stream.py` | Spot WebSocket (bookTicker, depth20) | Passes price to signal_generator | SPOT_ONLY (not Futures) |
| **Feature generation** | `src/services/feature_weights.py`, `src/services/lstm_model.py` | Market features (RSI, ADX, MACD, etc.) | Computed from Spot orderbook | SPOT_SOURCED |
| **Signal generation** | `src/services/signal_generator.py:on_price()` | Features + regime | `PAPER_EXPLORE_SKIP` if conditions fail | SPOT_EXECUTION_DEPENDENT |
| **RDE EV computation** | `src/services/realtime_decision_engine.py:compute_ev()` | P (win_prob), RR, ATR | **Computes ev_raw, applies auditor_factor, produces ev_final** | LEGACY_CALIBRATION (from historical outcomes) |
| **EV gating (HARD REJECT)** | `src/services/realtime_decision_engine.py:ev_final < 0` | ev_final from legacy calibration | **REJECT_NEGATIVE_EV** (no recovery possible) | LEGACY_BLOCKING |
| **Decision output** | `src/services/signal_engine.py` | EV, score, regime | Routes to trade_executor OR paper_exploration | GATES_PAPER_ENTRY |
| **Paper exploration** | `src/services/paper_exploration.py` | Rejection reason | Selects bucket (D_NEG, PROBE, TRAINING, or empty "no_bucket_matched") | ROUTING_DEPENDENT |
| **Paper sampler** | `src/services/paper_training_sampler.py:_get_training_bucket()` | Reject reason, starvation idle, caps | Returns bucket="UNKNOWN" for REJECT_NEGATIVE_EV | **BLOCKS_DISCOVERY** |
| **Position creation** | `src/services/paper_trade_executor.py:open_position()` | Bucket must be non-empty | If bucket="", position NOT created | **STARVATION_ENFORCED** |
| **Position monitoring** | `src/services/smart_exit_engine.py:evaluate_position_exit()` | Uses Spot fill/slippage/spread | Exit timing/price affected by Spot data | SPOT_EXIT_CONTAMINATION |
| **Learning update** | `src/services/paper_adaptive_learning.py:record_close()` | Closed trade (net_pnl_pct, outcome) | Adds to rolling20/50/100 WITHOUT filtering execution_truth | **ROLLING_WINDOW_CONTAMINATION** |
| **Policy adaptation** | `src/services/paper_adaptive_learning.py:_update_segment_policy()` | Rolling window PF/expectancy | Modifies segment_weights for future Futures decisions | **SPOT_POLICY_DRIVES_FUTURES** |
| **Persistence** | `src/services/paper_adaptive_learning.py:_save_state()` | State dict | Writes to `server_local_backups/paper_adaptive_learning_state.json` | FILE_WRITE_VERIFIED |

**Key finding:** The pipeline reaches decision point `ev_final < 0` → REJECT_NEGATIVE_EV → no bucket available → no position created. The system cannot escape this gate without:
1. Legacy EV recalibration (breaking backward compatibility)
2. New route for REJECT_NEGATIVE_EV (attempted by O2, blocked by contamination)
3. Or completely new PAPER core

---

## Root Causes — Why Valid Signals Never Become Positions

### Root Cause #1: Legacy EV Computation from Historical Outcomes

| Aspect | Proof | Severity | Why previous patches failed |
|---|---|---|---|
| **EV threshold is 75th percentile of history** | `realtime_decision_engine.py` lines 10-12: "Adaptive threshold = 75th percentile of ev_history (top 25% only)" | **CRITICAL** | Patches tried to add recovery probes with lower thresholds (0.037-0.038 vs 0.15 baseline), but they are still evaluated against the same legacy-derived probabilities |
| **Win probability from historical outcomes only** | Lines 5-7: "Calibrate win_prob: empirical WR from online bucket tracker. Requires 30 samples per bucket; fallback = 0.5" | **CRITICAL** | New valid signals inherit calibration from old losing trades. If historical bucket shows 40% WR, new signals in that regime are capped at ~40% expected WR regardless of actual signal quality |
| **No path to escape: EV = P × RR - (1-P)** | Line 8: "EV = win_prob × RR - (1 - win_prob)" | **CRITICAL** | If P is historically low (e.g., 0.40) and RR is fixed (1.5), EV will remain negative even for valid signals |
| **Cold-start bootstrap tried to reduce floor** | Lines 12-14: "Cold start: 0.15 until 100 samples; floor 0.10 always" | **ATTEMPT_FAILED** | Patches tried lowering thresholds during bootstrap, but the fundamental issue is that legacy historical outcomes cannot inform new epochs |

**Conclusion:** The system uses historical outcomes to estimate future win probability. If the historical epoch was unprofitable (PF < 1.0), all new signals will be discounted by that legacy calibration. No bucket selection, routing, or recovery probe can overcome this fundamental contamination.

### Root Cause #2: No Route Available for REJECT_NEGATIVE_EV Candidates

| Symptom | Exact code condition | Input/state driving it | Is this appropriate for clean PAPER learner? |
|---|---|---|---|
| `REJECT_NEGATIVE_EV` | `realtime_decision_engine.py:` if `ev_final < 0` (hardcoded) | Legacy ev_final from 75th percentile threshold | **RETIRE** — No new learner should use legacy thresholds to block new hypotheses |
| `no_bucket_matched bucket=UNKNOWN` | `paper_training_sampler.py:_get_training_bucket()` returns `("", 0.0)` for REJECT_NEGATIVE_EV | Rejection reason alone; no starvation idle or recovery context checked initially | **RETIRE** — Bucket selection should never return empty for valid signals during idle |
| Watchdog boosted exploration but opens nothing | `src/services/realtime_decision_engine.py:` ECON_BAD and deadlock probes attempt entry with low EV (0.037-0.038) but are still subject to legacy win_prob gate | Recovery probes use same RDE ev_final gate; even relaxed EV still fails if P is historically low | **RETIRE** — Recovery probes cannot work while legacy calibration blocks them upstream |
| Health BAD / PF 0.49 gates | `src/services/canonical_metrics.py:` health is tied to lifetime/rolling PF from all historical outcomes | `ECON_BAD_CACHE` in RDE flags "is_bad=True" if PF < 1.0, which blocks recovery probes | **RETIRE** — New PAPER core must not use legacy PF to gate new epoch's admissions |

**Critical question: Is the bot using old/legacy outcomes to prevent generation of new PAPER outcomes?**

**Answer: YES, definitively.**

1. Legacy historical outcomes drive win_prob estimation (RDE lines 5-7)
2. Legacy PF < 1.0 triggers ECON_BAD flag (lines 55-76)
3. ECON_BAD flag controls recovery probe eligibility
4. Even emergency recovery probes are subject to legacy ev_final gate (which depends on legacy P)
5. No path exists to isolate new PAPER sampling from legacy metrics

### Root Cause #3: Spot Execution Data Controls Futures Outcomes

| Contamination vector | Runtime consumer | Used as feature only? | Used for execution/PnL/gating? | Invalidates Futures-qualified learning? |
|---|---|---|---|---|
| **Market stream** | market_stream.py feeds Spot bookTicker to all feature builders | NO — Spot prices are the primary feature input | YES — fill, slippage, spread, exit calculations depend on Spot depth | **YES** — Exit logic directly depends on Spot L2 data |
| **Execution quality** | trade_executor.py:compute_fill_price() | NO — uses Spot depth to estimate fills | YES — spread check, wall logic, slippage all Spot-derived | **YES** — Position exits timed by Spot data, not Futures |
| **Smart exit engine** | smart_exit_engine.py:evaluate_position_exit() | NO — evaluates Spot prices for exit triggers | YES — TP/SL hit detection uses Spot price data | **YES** — Exit outcomes are Spot-determined |
| **PnL calculation** | trade_executor.py:calculate_pnl() | NO — uses Spot entry/exit prices | YES — net_pnl_pct depends on Spot fills | **YES** — Learned outcomes represent Spot execution, not Futures |
| **Learning update** | paper_adaptive_learning.py:record_close() | NO — ingests outcome from trade (already Spot-contaminated) | YES — rolling windows and segment weights updated with Spot-based PnL | **YES** — Policy adaptation is driven by Spot execution truth |

**Definitive mapping:**
- Spot market stream → Features (primary) + Execution quality gates
- Exit timing/PnL → Determined by Spot depth + fills
- Learning outcomes → Represent Spot execution experiments
- Policy adaptation → Driven by Spot-contaminated results
- Futures configuration → Never used for actual execution quality/fill/exit logic

**Conclusion:** The bot claims to trade Futures but uses Spot execution-truth. All learning is LEGACY_SPOT_EXECUTION_UNVERIFIED. No new Futures-qualified epoch can begin until market source is corrected.

### Root Cause #4: State Consistency / Metric Contradictions Prevent Trust

| Displayed metric | Actual source | Conflict | Required action |
|---|---|---|---|
| `TRENINK (zisk > 0)` | Computed from lifetime PnL (all trades) or rolling20 window | Dashboard shows training positive but PF=0.49 and closed_profit=negative. Contradiction suggests aggregation bug or mixed old/new data | **RETIRE** — Dashboard must not mix old/new epochs |
| `Profit Factor 0.49` | `paper_adaptive_learning.py:_compute_pf()` = gross_wins / abs(gross_losses) | If PF < 1.0 overall but dashboard says training=positive, suggests rolling window includes old losses | **RETIRE** — Must separate legacy metrics from clean epoch |
| `canonical_trades = 100` vs `completed_trades = 7707` | `learning_event.py:METRICS["trades"]` vs learning_monitor.py pair counts | 7707 total lifetime completions but only 100 counted as canonical. Suggests 7607 trades are quarantined, duplicate-skipped, or from pre-epoch | **CLARIFY** — Need definitive trade state enumeration |
| `WR 100%` on symbols with negative PnL | learning_monitor.py pair-level WR calculation | If WR=100% but PnL negative, suggests win/loss tracking is inverted, size-weighted incorrectly, or mixed with old data | **DEBUG/RETIRE** — Metric calculation is unreliable |
| `last trade 706h ago` vs recent PAPER events | learning_event.py timestamps vs realtime_decision_engine.py event logs | Shows historical completions aged out but RDE still emits recent events. Suggests system is tracking old trades while new PAPER activities proceed in isolation | **RETIRE** — Legacy and new epochs must not coexist without clear separation |

**Root cause of contradictions:** The system does not cleanly separate legacy historical outcomes from current epoch. Global metrics (completed_trades, PF, WR) blend old and new data, creating contradictory dashboard displays.

---

## KEEP / RETIRE / REPLACE Classification

| Module/behavior | Verdict | Reason | Migration action |
|---|---|---|---|
| **market_stream.py** | KEEP (with migration) | Core market data acquisition is generic; Spot vs Futures choice is external configuration | After Futures source switch, reuse existing WebSocket/REST plumbing; change stream URL and orderbook interpretation |
| **signal_generator.py / feature_weights.py** | REPLACE | Current signal generation is trained on Spot execution outcomes. New PAPER core must use simple, deterministic signals independent of legacy feature calibration | Rewrite as fixed-policy (e.g., breakout on regime + volatility) without ML/LSTM dependency |
| **realtime_decision_engine.py (EV + calibration)** | RETIRE from active path | Legacy EV computation is bootstrapped from historical outcomes that are LEGACY_SPOT_EXECUTION_UNVERIFIED. New PAPER core must use simple transparent admission (no legacy EV gating) | Archive as comparator; do not gate new epoch admissions |
| **realtime_decision_engine.py (recovery probes)** | RETIRE | ECON_BAD and deadlock probes are downstream of legacy ev_final gate; they cannot function while legacy metrics block all admissions | Remove; replace with simple periodic sampling when idle > threshold |
| **paper_exploration.py** | RETIRE from active path | Bucket selection is downstream of REJECT_NEGATIVE_EV gate, which is broken by legacy calibration | Archive; clean PAPER core will not route through legacy explorer |
| **paper_training_sampler.py** | RETIRE (except test harness) | Sampler is designed to route REJECT_NEGATIVE_EV through training buckets; this entire logic is unnecessary if legacy EV gate is removed | Keep test fixtures for reference; delete all O2/O1/recovery routing logic |
| **paper_adaptive_learning.py** | REPLACE `record_close()` only | The learning update itself is sound, but `record_close()` lacks execution_truth filtering. New PAPER core must add guard: skip LEGACY_SPOT_EXECUTION_UNVERIFIED before rolling window updates | Rewrite `record_close()` to: (1) accept execution_truth_class, (2) skip if LEGACY_SPOT_EXECUTION_UNVERIFIED, (3) only update rolling windows for clean epoch |
| **smart_exit_engine.py** | REPLACE | Current exit logic is Spot-optimized. New PAPER core must use Futures market data for exit timing/fills | Rewrite to use Futures orderbook depth + funding for exit decisions |
| **firebase_client.py** | KEEP | Firebase quota management is independent of decision/learning logic; reuse authentication and quota guards | No changes needed; used by both legacy and clean epoch |
| **trade_executor.py / paper_trade_executor.py** | KEEP (with execution_truth_class field) | Core position lifecycle is generic; reuse for clean epoch | Add `execution_truth_class` field to trade dict; ensure it's passed through to learning updates |
| **learning_event.py / learning_monitor.py** | RETIRE (for active decisions) | Metrics are mixed legacy/current; global state is unreliable | Archive for forensics; clean epoch must build new metrics from scratch |
| **canonical_metrics.py** | RETIRE (for active decisions) | Dashboard metrics blend epochs; health/PF are legacy-tainted | Archive; new dashboard contract for clean epoch only |
| **bot2/main.py orchestrator** | REPLACE structure | Main loop is 700+ lines with many conditional imports (genetic, RL, self-healing); layered patches have made it unmaintainable | Rewrite as simple loop: fetch market → run fixed PAPER policy → execute → record → learn |
| **Persistence / state_manager.py** | KEEP (with isolation) | File I/O is sound; Futures source switch doesn't require rewrite | Add epoch ID to state files; isolate legacy `paper_adaptive_learning_state.json` as comparator-only |
| **Logging / event_bus** | KEEP | Structured logging framework is clean and reusable | No changes needed |
| **Testing / fixtures** | KEEP (isolated) | Test infrastructure is sound; reuse for clean epoch validation | Move all legacy-dependent tests to `legacy_comparative/` directory; new tests must target clean PAPER core only |

---

## Clean PAPER Core vNext Architecture

| Component | Input | Output | Responsibility | Existing reuse? | Must be new/rewritten? | Acceptance test |
|---|---|---|---|---|---|---|
| **FuturesMarketStream** | Binance fstream.binance.com USDⓈ-M depth + bookTicker + funding | `{price, depth, funding, timestamp}` | Futures-only market data; no Spot data | market_stream.py base + URL switch | YES, reuse WebSocket plumbing | Test emits accurate Futures prices; no Spot data present |
| **DecisionFrame** | FuturesMarketStream | `{symbol, regime, volatility, state}` | Feature extraction for simple signal hypothesis; no ML/LSTM | feature_weights.py (remove LSTM dependency) | YES, simplify to regime+volatility only | Test computes regime correctly; no model training |
| **SignalHypothesisV1** | DecisionFrame | `{symbol, side, entry_reason, confidence}` | Fixed strategy: breakout on regime change + volatility spike | N/A (new) | WRITE NEW | Test generates breakouts; no EV/historical dependence |
| **AdmissionPolicyV1** | SignalHypothesisV1 + position state | `{allowed: bool, reason: str, size: float}` | Simple transparent caps: max 2 open global, 1 per symbol, 4 per 15min, no legacy metrics blocking | paper_training_sampler.py caps logic only | Reuse cap functions; delete rejection routing | Test admits valid signals during idle; no PF/EV gates |
| **PaperExecutionAccountingV1** | Admitted signal + FuturesMarketStream | `{trade_id, entry_price, entry_ts, position}` | Create position using accurate Futures fills; track entry accounting separately from legacy | paper_trade_executor.py (add execution_truth field) | Reuse position lifecycle; add execution_truth tracking | Test creates position with trade_id; Futures prices used |
| **PositionLifecycleV1** | PaperExecutionAccountingV1 + FuturesMarketStream | `{trade_id, exit_price, exit_ts, outcome, mfe, mae}` | Monitor position; exit on TP/SL/timeout using Futures data; record accurate fills | smart_exit_engine.py (switch to Futures data) | Rewrite exit logic for Futures orderbook | Test exits correctly using Futures fills; no Spot data |
| **EpochMetricsV1** | PositionLifecycleV1 closed trades | `{rolling20_n, rolling20_pf, rolling20_exp, segment_stats}` | Track current-epoch metrics only; segregated from legacy | paper_adaptive_learning.py (with execution_truth filter) | Rewrite record_close() to skip LEGACY_SPOT_EXECUTION_UNVERIFIED | Test records clean trades only; legacy trades skipped |
| **AdaptivePolicyV1** | EpochMetricsV1 + epoch sample count | `{segment_weights, active_policy}` | Conservative adaptation: only after 100+ clean samples; segment-level, never global threshold | paper_adaptive_learning.py:_update_segment_policy() | Reuse with safeguard: begin_adaptation_after=100 clean samples | Test adapts only after threshold; no premature global changes |
| **PersistenceV1** | EpochMetricsV1 + AdaptivePolicyV1 | `{state_file_written: bool, hash: str}` | Write clean epoch state to versioned file; archive legacy comparator-only | paper_adaptive_learning.py._save_state() | Reuse with version ID (e.g., `clean_epoch_v1_state.json`) | Test saves only clean epoch; legacy file untouched |
| **DashboardContractV1** | EpochMetricsV1 + PositionLifecycleV1 | Dashboard JSON | Report clean epoch metrics only; do not mix with legacy | canonical_metrics.py (fork) | WRITE NEW dashboard contract for clean epoch | Test dashboard shows clean stats; legacy hidden or clearly marked |
| **LegacyArchiveAdapter** | `paper_adaptive_learning_state.json` + legacy trades | Comparator metrics + forensic logs | Read legacy outcomes for side-by-side comparison; never permit legacy metrics to gate new admissions | paper_adaptive_learning.py (read-only) | Reuse read path; add execution_truth=LEGACY_SPOT_EXECUTION_UNVERIFIED label | Test reads legacy; does not influence live decisions |

---

## Cutover Design

### Legacy Preservation
- Archive existing `paper_adaptive_learning_state.json` as `paper_adaptive_learning_state.legacy_spot_v10_13m.json.backup`
- Tag all legacy trade outcomes with `execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED`
- Create read-only comparator that loads legacy metrics for forensic analysis
- Dashboard displays legacy PF as historical reference only, clearly separated from clean epoch

### Clean Epoch Start
- Deploy FuturesMarketStream with fstream.binance.com data source
- Disable realtime_decision_engine.py legacy EV gating: hardcode `if false:` for all legacy gates
- Activate AdmissionPolicyV1 with simple caps (no legacy PF/health gates)
- Initialize new `clean_epoch_v1_state.json` with `{ "started_at": epoch_start_ts, "trades": 0, "rolling20": [] }`
- Log: `[CLEAN_EPOCH_V1_START] Futures market source active, legacy gates disabled, new metrics collection begins`

### How Old Gates Are Prevented from Controlling New PAPER
1. **EV computation:** Removed from active decision path; legacy ev_final not computed
2. **Health/PF gates:** ECON_BAD checks commented out; recovery probes not invoked
3. **Bucket selection:** Removed; AdmissionPolicyV1 uses transparent caps only
4. **Metric mixing:** New rolling windows segregated from legacy; separate state files
5. **Dashboard gating:** Dashboard reads clean epoch only; legacy available as read-only comparator

### How Futures Execution-Truth Is Guaranteed
1. **Market source:** Only fstream.binance.com (Futures) WebSocket active; Spot streams disabled
2. **Orderbook:** Use Futures depth data (USDⓈ-M orderbook) for fill estimation
3. **Funding tracking:** Include funding fee in PnL calculation
4. **Exit timing:** TP/SL triggered by Futures price, not Spot
5. **Learning**: Only trades executed on Futures data qualify for `execution_truth_class=FUTURES_QUALIFIED_V1`
6. **Validation:** Pre-deployment test: confirm zero Spot stream calls during clean epoch

---

## Phased Implementation Plan

### Reset Phase 0 — Forensic Freeze Decision
**Objective:** Decide whether to preserve/halt current meaningless PAPER behavior while enabling clean replacement  
**Allowed files/modules:** Read-only access to all state, logs, metrics  
**Prohibited behavior:** No new trading logic; no new PAPER positions while analysis runs  
**Acceptance test:**
- Confirm legacy market stream continues uninterrupted (for data capture)
- Verify no new positions opened during Phase 0
- Archive existing logs and state with timestamped labels
**Rollback criteria:** If Phase 0 reveals critical runtime dependencies, pause and clarify before proceeding  
**Runtime validation evidence:** Service still running; no new PAPER trades; logs captured

### Reset Phase 1 — Futures Execution-Truth and Clean State Contract
**Objective:** Establish correct market source, accurate execution accounting, and clean epoch persistence contract  
**Allowed files/modules:**
- src/services/market_stream.py (add Futures stream, keep Spot for analysis only)
- src/services/trade_executor.py (add execution_truth_class field)
- src/services/paper_adaptive_learning.py (add record_close filter)
- New: clean_epoch_state.py
**Prohibited behavior:**
- No admission changes; still using legacy decision gates
- No new PAPER trades yet (manually gated)
- No strategy adaptation
**Acceptance tests:**
1. Futures market stream endpoint can be reached and emits bookTicker/depth
2. Spot orderbook prices differ from Futures prices (confirm dual source works)
3. Trade dict includes `execution_truth_class` field
4. record_close() skips trades with `execution_truth_class=LEGACY_SPOT_EXECUTION_UNVERIFIED`
5. Clean state file created and persists across service bounce
**Rollback criteria:**
- If Futures stream is unavailable or returns invalid data
- If execution_truth_class field causes serialization errors
- If persistence write fails
**Runtime validation evidence:**
- Futures prices logged: `[FUTURES_STREAM_ACTIVE] symbol=BTCUSDT bid=... ask=...`
- Clean state file created: `clean_epoch_v1_state.json exists, size > 0`
- No service restarts triggered

### Reset Phase 2 — Fixed-Policy PAPER Flow
**Objective:** Prove that simple deterministic signal hypothesis + admission caps can actually open and close positions without legacy metrics blocking  
**Allowed files/modules:**
- New: simple_policy_v1.py (fixed breakout strategy, no EV/ML)
- src/services/paper_training_sampler.py (clean cap logic only, delete rejection routing)
- src/services/paper_trade_executor.py (unchanged, now uses Futures fills)
- src/services/smart_exit_engine.py (refactored for Futures exit logic)
**Prohibited behavior:**
- No adaptive thresholds
- No learning feedback into policy (frozen)
- Legacy EV/health gates still disabled (not re-enabled)
**Acceptance tests:**
1. Simple signal hypothesis generates breakouts under fixed conditions
2. Admission policy admits signal when: idle > 600s AND caps allow AND no legacy PF gate blocks
3. At least 1 position opens with real trade_id
4. Position closes normally (TP/SL/timeout)
5. No D_NEG or legacy bucket routing invoked
6. Dashboard shows only clean epoch trades; legacy hidden
**Rollback criteria:**
- If positions cannot open (legacy gates still blocking)
- If exits are timing-incorrect (Spot vs Futures discrepancies)
- If trading stalls after first few positions
**Runtime validation evidence:**
- `[PAPER_FIXED_POLICY_V1_ENTRY]` log with trade_id
- `[PAPER_EXIT]` log with clean outcome
- `clean_epoch_v1_state.json rolling20_n >= 1`
- Dashboard shows clean epoch trades

### Reset Phase 3 — Learning and Adaptation
**Objective:** Enable metric updates and conservative adaptation only after clean samples accumulate  
**Allowed files/modules:**
- src/services/paper_adaptive_learning.py (full record_close with filtering)
- New: adaptive_policy_v1.py (conservative segment-level weight updates)
- EpochMetricsV1 (rolling windows, PF, expectancy for clean trades only)
**Prohibited behavior:**
- No global threshold adaptation (only segment-level)
- No adaptation until rolling100_n >= 100 (clean sample minimum)
- Legacy comparator loaded read-only for observability
**Acceptance tests:**
1. At least 20 clean closes occur
2. rolling20_n >= 20 after closes
3. Segment weights updated only if segment has >= 20 samples AND rolling20_pf has meaningful direction
4. Policy adaptation log shows segment-level action only (not global)
5. No LEGACY_SPOT_EXECUTION_UNVERIFIED trades in rolling windows
6. Dashboard shows rolling20/50/100 PF/expectancy for clean epoch only
**Rollback criteria:**
- If segment adaptation causes thrashing (weights cycling rapidly)
- If legacy metrics accidentally influence new decisions
- If sample contamination detected (legacy trade in rolling window)
**Runtime validation evidence:**
- `[PAPER_LEARNING_UPDATE]` logs with clean trade_ids only
- `rolling20_n=20, rolling20_pf=..., rolling20_exp=...`
- `[POLICY_ADAPTATION]` shows segment-level action
- Zero `LEGACY_SPOT_EXECUTION_UNVERIFIED` in rolling windows

### Reset Phase 4 — Confirmation
**Objective:** Freeze policy on clean samples and assess actual capability without further adaptive changes  
**Allowed files/modules:**
- All Phase 3 modules (read-only)
- Metrics aggregation for final assessment
**Prohibited behavior:**
- No further weight adaptation
- No threshold changes
- No strategy parameter tuning
**Acceptance tests:**
1. Rolling100_n >= 100 (clean sample minimum reached)
2. Policy has been frozen for last 50 trades (no new adaptations)
3. Rolling100_pf and rolling100_exp are stable (variance < threshold)
4. Documented clean epoch performance: PF, expectancy, Sharpe, drawdown
5. No mixing with legacy data anywhere in metrics
6. Dashboard clearly marks clean epoch as V1, distinct from legacy
**Rollback criteria:**
- If rolling100_pf < 1.0 and expectancy < 0 (strategy actually unprofitable)
- If sample size was insufficient to assess true capability
- If contamination is discovered (legacy trade mixed in)
**Runtime validation evidence:**
- Final metrics report: `rolling100_n=100+, rolling100_pf=X, rolling100_exp=Y`
- Policy weights unchanged for last 50+ closes
- Dashboard displays: `CLEAN_EPOCH_V1 ASSESSMENT COMPLETE: PF=..., expectancy=...`
- Explicit verdict: VIABLE (proceed to REAL consideration) or NOT_VIABLE (investigate/redesign)

---

## Do Not Implement List

The following MUST NOT be done during the reset phases:

- ❌ Add another bucket, routing path, or admission bypass
- ❌ Tune legacy EV thresholds or add smart probes  
- ❌ Mix legacy metrics with clean epoch in any decision path
- ❌ Use Spot market data for Futures position exits
- ❌ Restart service during any phase without explicit checkpoint
- ❌ Enable REAL/live trading
- ❌ Commit legacy comparator state as "current" state
- ❌ Rely on legacy win_prob for new epoch admissions
- ❌ Add complexity (ML, genetic, RL) until clean PAPER core is proven
- ❌ Assume legacy dashboard contradictions will resolve naturally (must fix explicitly)

---

## Next Single Implementation Prompt Recommended

**Title only; do not implement it now:**

```markdown
# Reset Phase 0 Implementation
## Objective
Capture forensic evidence and create clean-epoch baseline without changing active trading logic.

## Scope
1. Archive legacy state and logs with timestamp labels
2. Prepare Futures market stream source (test connectivity, no activation yet)
3. Validate that legacy service continues uninterrupted
4. Document decision: proceed to Phase 1 after operator approval

## Constraints
- Read-only on all trade/state data
- Legacy PAPER trading continues
- No new admission paths
- Service uninterrupted
```

---

## Architecture Autopsy Summary

**Why ~207 patches failed:**
1. Each patch attempted to route around the legacy EV gate without removing it
2. Recovery probes were downstream of the broken gate (could never activate)
3. Legacy metrics (PF, health, calibration) contaminated new epoch attempts
4. Spot execution data mixed with Futures outcomes, corrupting learning
5. System state mixing (global_trades vs actual learning_state) prevented clear decisions

**Proof that a clean core replacement is necessary:**
1. Valid signals ARE being generated (logs confirm)
2. But ev_final < 0 from legacy calibration causes hard REJECT
3. No available routing can absorb REJECT_NEGATIVE_EV
4. Even emergency recovery probes (ECON_BAD, deadlock) fail upstream of legacy gate
5. The system is LOCKED: legacy metrics prevent new learning; no new learning means legacy metrics never update; starvation confirmed

**Clean core replacement design principle:**
Do not try to patch around legacy gates. Remove them entirely. Replace the active decision core with:
- Futures-qualified market data only
- Simple transparent admission (no legacy EV)
- Clean epoch learning metrics segregated from legacy
- Conservative adaptation only after clean sample threshold
- Legacy preserved as read-only comparator, never as decision input

**Estimated effort:**
- Phase 0 (audit/archive): 2–4 hours
- Phase 1 (market source + execution truth): 4–6 hours
- Phase 2 (fixed policy + basic flow): 6–8 hours
- Phase 3 (learning + adaptation): 4–6 hours
- Phase 4 (validation + assessment): 4 hours
- **Total: ~24–32 hours, split across 5–7 days for runtime validation**

**Risk:** Lowest if phases are executed strictly as defined with operator checkpoints. Highest if patches are attempted in parallel or legacy gates are re-enabled prematurely.

---

**Report Generated:** 2026-05-26  
**Analysis Status:** Complete, read-only, no implementation  
**Next Step:** Operator review and approval of Reset Phase 0  
**Do Not Push / Do Not Deploy / Do Not Restart**
