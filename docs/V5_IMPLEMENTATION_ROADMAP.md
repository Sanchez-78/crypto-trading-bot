# CryptoMaster V5 — Implementation Roadmap & Status Report

**Branch:** `v5/integrated-paper-firebase-quota-safe`  
**Session Started:** 2026-05-27  
**Current Status:** V5.1 COMPLETE, 4 phases remaining

---

## Executive Summary

V5 is a complete new PAPER trading bot isolated from legacy `src/services` architecture. It uses Firestore as durable source of truth, enforces hard quota guards (3,000 writes/day), and maintains PAPER-only mode permanently.

**Completed:**
- ✅ V5.0: Architecture decision + legacy boundary audit
- ✅ V5.1: Firebase schema + QuotaGuard + Outbox

**Remaining:**
- V5.2: Futures feed + accounting truth (market integration)
- V5.3: Strategy candidates + hard cost gate (signal generation)
- V5.4: PAPER lifecycle + Firebase persistence (entry/close/learning)
- V5.5: Clean learner + policy update (learning eligibility + readiness)
- V5.6: End-to-end validation + cutover plan (testing + deployment)
- 15-17: Metrics registry + REAL readiness + Android contract (visibility)

---

## Completed Work

### V5.0: Architecture Decision & Legacy Boundary (DONE)

**Deliverable:** `docs/V5_ARCHITECTURE_DECISION.md`

**What was done:**
- Declared V5 as new isolated PAPER runtime (NOT a patch)
- Audited codebase: confirmed `src/clean_core` has 0 imports from legacy services
- Mapped 8+ clean core components reusable (market feeds, execution, provenance)
- Identified 10+ forbidden legacy modules (paper_adaptive_learning, firebase_client, etc.)
- Defined v5_* Firebase namespace (separate from legacy collections)
- Established REAL trading disabled at architecture level: code guarantee
- Documented daily Firestore quota design (2,500 writes/3,000 hard cap target)
- Outlined 7-phase implementation structure

**Audit Results:**
- clean_core modules analyzed: 25 files
- Legacy imports from src.services: 0 ✓
- Isolated reusable components: 8+ ✓
- Official Binance routes: fstream.binance.com only ✓

---

### V5.1: Firebase Schema + QuotaGuard + Outbox (DONE)

**Deliverables:**
- `src/v5_bot/firebase/schema.py` — V5 dataclasses + validators
- `src/v5_bot/firebase/quota_guard.py` — QuotaGuard + state machine
- `src/v5_bot/firebase/outbox.py` — TradeOutbox durable WAL
- `src/v5_bot/firebase/repository.py` — QuotaAwareFirestoreRepository
- `src/v5_bot/firebase/__init__.py` — Module exports
- `src/v5_bot/config.py` — Runtime configuration + limits
- `src/v5_bot/__init__.py` — Package root

**What was done:**
- Designed v5_* Firebase schema with full dataclasses:
  - v5_control/active, v5_epochs, v5_trades, v5_learning/state
  - v5_runtime/open_positions, v5_metrics/daily_*, v5_dashboard
  - v5_readiness/current, v5_quota, v5_metrics_registry
  - No raw WebSocket events, no per-tick writes
- Implemented QuotaGuard with SQLite ledger (Pacific timezone):
  - State machine: NORMAL → WARNING → DEGRADED → CRITICAL → HARD_STOP
  - Internal caps: 4k reads soft, 8k hard; 1.5k writes soft, 3k hard
  - Pre-flight checks for operations before Firestore call
  - Entry write reserve check (enough writes to close all open trades)
- Implemented TradeOutbox for durability:
  - SQLite WAL for trade outcomes and learning updates
  - Durable persistence before Firebase write
  - Retry tracking (max 3 retries before discard)
  - FIFO ordering + status reporting
- Implemented QuotaAwareFirestoreRepository:
  - All Firebase operations go through quota guard
  - Outbox integration for failures
  - Read-only operations for startup recovery
- Configuration module:
  - PAPER_ONLY_MODE = True (hard-coded, never False)
  - REAL_ORDERS_ALLOWED = False (hard-coded, never True)
  - Position limits: 3 global, 1 per symbol, 300/day max
  - Firestore quota: 3,000 writes/day hard cap
  - Learning config: strict eligibility (positive cost edge required)

**Tests Created:**
- `tests/v5_bot/test_quota_guard.py` — 15+ unit tests
- `tests/v5_bot/test_outbox.py` — 20+ unit tests
- Manual execution tests: All modules functional ✓

**Commit:** `V5.1: Add quota-safe Firebase repository and durable PAPER outbox`

---

## Remaining Phases

### V5.2: Futures Feed + Accounting Truth (NEXT)

**Estimated Scope:** 4-6 hours

**Deliverables:**
- `src/v5_bot/market/binance_usdm_feed.py` — Official Futures WebSocket feed
- `src/v5_bot/market/local_book.py` — In-memory order book
- `src/v5_bot/execution/accounting.py` — Fill + PnL calculation
- `src/v5_bot/execution/fees.py` — Taker fee model
- `src/v5_bot/execution/funding.py` — Perpetual funding costs
- `tests/v5_bot/test_futures_feed.py` — Feed integration tests

**What needs to be done:**
1. Integrate Binance USDⓈ-M Futures WebSocket streams
   - `wss://fstream.binance.com/ws/<symbol>@bookTicker`
   - `wss://fstream.binance.com/market/ws/<symbol>@aggTrade`
   - Mark price + funding as REST telemetry (not fill truth)
   - Source identity validation (reject Spot, legacy sources)
2. Implement local order book with staleness checks
   - Book updates from bookTicker events
   - Bid/ask fill truth for entry/exit
   - Reject stale events (>5sec age)
3. Implement execution accounting
   - Taker fee: 0.05% default (verify Binance current rate)
   - Spread cost: (ask - bid) / midpoint * 10000 bps
   - Slippage: (actual_fill - best_available) / best_available
   - Funding: cumulative perpetual funding costs
4. Create no Firebase hot-path writes (all in-memory until close)
5. Full test coverage: feed integrity, staleness rejection, fill modeling

**Why V5.2 is critical:**
- **Execution truth** is the source of all learning. Wrong fills → wrong learning.
- Must be Binance Futures ONLY (no Spot, no legacy providers).
- No trade can enter without valid, recent, complete feed data.

---

### V5.3: Strategy Candidates + Hard Cost Gate (AFTER V5.2)

**Estimated Scope:** 5-7 hours

**Deliverables:**
- `src/v5_bot/strategy/candidate.py` — Signal candidate evaluation
- `src/v5_bot/strategy/feature_engine.py` — Feature + regime detection
- `src/v5_bot/strategy/baseline_policies.py` — Three base strategies
- `src/v5_bot/strategy/policy_selector.py` — Route signals to strategies
- `src/v5_bot/strategy/cost_edge_gate.py` — HARD cost-edge enforcement
- `tests/v5_bot/test_strategy_admission.py` — Candidate + cost gate tests
- Replay test dataset (limited public Futures stream, no Firebase writes)

**What needs to be done:**
1. Implement three baseline strategies (deterministic, no hyperparameter tuning):
   - `trend_pullback_v1` — Entry on pullback in trend
   - `range_reversion_v1` — Entry on reversion to range mean
   - `volatility_breakout_v1` — Entry on volatility breakout
2. Feature engine:
   - Regime detection (trending, mean-revert, quiet)
   - Features: momentum, volatility, regime, bid-ask dynamics
   - Regime per symbol, updated on each market event
3. Cost-edge gate (HARD requirement):
   - `expected_move_bps > round_trip_fee_bps + spread_bps + slippage_bps + safety_margin_bps`
   - No admission with `cost_edge_ok=False` (legacy anti-pattern)
   - Safety margin: 2 bps minimum buffer
4. Admission filters:
   - Feed freshness check
   - Max open limits (3 global, 1 per symbol)
   - Quota write reserve check (enough to close trade)
5. Offline replay test:
   - Load bounded Futures dataset (no Firebase writes)
   - Replay 3 strategies in parallel
   - Verify candidate generation realistic (5-50 per hour)
   - Verify cost gate rejection rate < 90% (edge exists)

**Why V5.3 is critical:**
- **Cost edge is the minimum viable gate** for entry. Without it, you're learning from random noise.
- Replay proves strategies generate realistic signals.
- Hard gate enforcement prevents legacy mistakes ("learn despite negative edge").

---

### V5.4: PAPER Lifecycle + Firebase Persistence (AFTER V5.3)

**Estimated Scope:** 6-8 hours

**Deliverables:**
- `src/v5_bot/execution/paper_broker.py` — PAPER position manager
- `src/v5_bot/execution/exits.py` — Exit logic (TP/SL/TIMEOUT/FEED_CLOSE)
- `src/v5_bot/runner.py` — Main event loop + lifecycle
- Integration tests for full entry → close → learning flow

**What needs to be done:**
1. PAPER broker (simulated fills):
   - Accept entry candidate → create v5_trades/{trade_id} document
   - Atomically update v5_runtime/open_positions
   - If Firebase fails: persist to outbox, mark as pending
2. Exit policy (deterministic):
   - TP: target profit reached
   - SL: stop loss hit
   - TRAIL: trailing stop (if enabled)
   - TIMEOUT: hold_limit_s exceeded
   - FEED_SAFETY_CLOSE: feed stale >30s
3. Close flow:
   - Write close outcome to outbox first (durability)
   - Update v5_trades/{trade_id} with CLOSED status + full accounting
   - Update v5_runtime/open_positions
   - If eligible: update v5_learning/state + v5_metrics/daily_*
   - Optional coalesce v5_dashboard/current
4. Restart recovery:
   - Read v5_runtime/open_positions
   - Reconcile with current market state
   - Identify stale positions (>4 hours without update) → force close
5. Full lifecycle tests:
   - Entry → hold → exit → learning update → metrics flush
   - Outbox recovery when Firebase fails
   - Position reconciliation on restart

**Why V5.4 is critical:**
- **Persistent trade state** ensures no loss of outcomes.
- Outbox recovery guarantees learning happens even if Firebase is temporarily unavailable.
- Full lifecycle proves bot can run autonomously.

---

### V5.5: Clean Learner + Policy Update (AFTER V5.4)

**Estimated Scope:** 4-6 hours

**Deliverables:**
- `src/v5_bot/learning/eligibility.py` — Strict learning eligibility rules
- `src/v5_bot/learning/learner.py` — Metrics aggregation by segment
- `src/v5_bot/learning/policy_state.py` — Segment cooldown/downweight
- `src/v5_bot/learning/readiness.py` — REAL readiness state machine

**What needs to be done:**
1. Learning eligibility (strict):
   - Only PAPER trades from V5 epoch
   - Valid Binance Futures execution truth
   - Complete entry/exit fills (no partial/stale)
   - Complete fee/slippage/funding accounting
   - No validation/manual overrides
   - Eligible check written to v5_trades.eligible_for_learning
2. Learner:
   - Group by: strategy_id : symbol : regime : side
   - Track: n, wins/losses/flats, net_expectancy_bps, profit_factor
   - Rolling: last20, last50, last100
   - Reject reason aggregates: cost_edge_too_low, feed_stale, etc.
3. Policy update:
   - After n >= 30: if net_expectancy < 0, set policy_action = "cooled"
   - Cooled segment gets 3600s cooldown (no new entries)
   - After n >= 100: segment is "mature", no more sample collection needed
   - No global block (other segments still active)
   - Downweight matrix: segment → allowed_for_paper (bool)
4. REAL readiness state machine:
   - NOT_READY_* states → PAPER_PERFORMANCE_PROMISING → REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
   - But ALWAYS: real_orders_allowed = False
   - Gates: 300 closes, 7 days, 3+ regimes, >0 expectancy, PF >= 1.20, no incidents
   - Dashboard shows all gates with current/required values
   - Czech status messages (e.g., "Sbírám 82/300 uzavřených obchodů")

**Why V5.5 is critical:**
- **Strict eligibility** prevents learning from contaminated data.
- **Policy update** tunes which segments are admissible without global kills.
- **Readiness report** tells operator exactly why bot is/isn't ready for REAL.

---

### V5.6: End-to-End Validation + Cutover Plan (AFTER V5.5)

**Estimated Scope:** 4-5 hours

**Deliverables:**
- `src/v5_bot/cli.py` — CLI for testing + running
- `tests/v5_bot/test_full_lifecycle.py` — Full E2E integration tests
- `tests/v5_bot/test_quota_stress.py` — Quota limits stress test
- `CUTOVER_PLAN.md` — Operator deployment playbook
- V5 acceptance trial results (live PAPER, <250 writes budget)

**What needs to be done:**
1. E2E validation:
   - Simulated Futures replay: 300 entry candidates → cost gate → 50 entries → closes → learning
   - Quota check: verify writes <= 2,500 expected, 3,000 hard
   - Restart test: kill/restart bot, verify position/learning recovery
   - Outbox recovery: simulate Firebase timeout, verify pending flushed
2. Quota stress:
   - Simulate 300 entries + 300 closes in one day
   - Dashboard writes, readiness updates, metrics flushes
   - Assert stays under 2,500 target and 3,000 hard cap
3. Live PAPER trial:
   - New V5 epoch on public Futures
   - Max 20 PAPER entries OR <250 writes total
   - Verify Firebase documents created correctly
   - Verify learning state updates correctly
   - NO deployment until PASS
4. Cutover playbook:
   - Pre-cutover: freeze legacy PAPER writer
   - Deploy V5 service + systemd unit
   - Validate first entries/closes/learning
   - Never run legacy and V5 as competing writers
   - Rollback procedure if needed

**Why V5.6 is critical:**
- **Validation proves** bot works end-to-end in all failure scenarios.
- **Stress test proves** quota enforcement doesn't fail in production.
- **Cutover playbook prevents** hand-off chaos.

---

## Metrics Registry & Android (Sections 15-17)

**Estimated Scope:** 3-4 hours (final integration)

**Deliverables:**
- `docs/V5_ANDROID_METRICS_CONTRACT.md` — Complete metric catalog
- `docs/v5_android_metrics_registry.json` — Machine-readable registry

**What needs to be done:**
1. Enumerate **all** V5 metrics (80+ total):
   - Runtime/identity (8): commit, version, epoch, mode, real_allowed, uptime, heartbeat, error
   - Quota (12): reads/writes/deletes attempted, remaining, state, retries, outbox age
   - Feed (14): source, symbols, events in 5m, staleness, reconnects, integrity failures
   - Signal (12): candidates total/by-strategy, rejected, acceptance rate, last candidate info
   - Positions (8): count, notional, unrealized PnL, oldest age, next exit
   - Performance (20): closes, wins/losses/flats, PnL, expectancy, PF, fees, slippage, funding, drawdown
   - Learning (12): eligible closes, rolling expectancy/PF, segments, cooldowns, policy version
   - Readiness (15): status, gates (7), blocking reasons, current/required values, quota safety days
   - Diagnostics (8): status, feed, Firebase, learning health, exceptions, incidents
   - Trade detail (15): for history cards (pnl, outcome, accounting, MFE/MAE, eligibility)
2. Android app design (5 tabs):
   - Tab 1: Dashboard (aggregate snapshot from v5_dashboard/current)
   - Tab 2: Trades (paginated history, 20 per request)
   - Tab 3: Learning & Segments (from v5_metrics/segments_current)
   - Tab 4: Readiness (all gates from v5_readiness/current)
   - Tab 5: System & Quota (health + quota from combined docs)
3. Dashboard constraints:
   - Auto-refresh: 1× per 5 min max
   - Manual refresh: allowed any time
   - Trades pagination: only on user request
   - No real-time listeners
4. Metrics registry structure:
   - metric_id, display_name_cs, category
   - Firebase doc/field path, update cadence
   - Android tab, visibility (summary/detail/diagnostics)
   - Unit, value_type, read_cost_note
   - Threshold interpretation

---

## Test Strategy

### Existing Test Infrastructure
- `tests/v5_bot/test_quota_guard.py` — 15+ unit tests (DONE)
- `tests/v5_bot/test_outbox.py` — 20+ unit tests (DONE)

### To Be Added
- `tests/v5_bot/test_futures_feed.py` — Feed integration (V5.2)
- `tests/v5_bot/test_strategy_admission.py` — Strategy + cost gate (V5.3)
- `tests/v5_bot/test_paper_lifecycle.py` — Entry/close/learning (V5.4)
- `tests/v5_bot/test_readiness_states.py` — Readiness state machine (V5.5)
- `tests/v5_bot/test_full_e2e.py` — Full integration (V5.6)
- `tests/v5_bot/test_quota_stress.py` — Quota limits (V5.6)

### Full Established Server-Safe Suite
```bash
python -m pytest tests/v5_bot/ -v
```
Expected: 100+ tests, all PASS, <10s runtime (no Firebase I/O)

---

## Safeguards in Place

1. **Legacy Isolation:** No imports from `src.services.*`
2. **PAPER-Only:** `PAPER_ONLY_MODE = True` (hard-coded, code review enforces)
3. **REAL Disabled:** `REAL_ORDERS_ALLOWED = False` (no order submission code)
4. **Quota Enforcement:** Circuit breaker at 3,000 writes/day hard cap
5. **Durability:** Outbox WAL for all trades before Firebase write
6. **Eligibility:** Learning only from valid Futures closes with complete accounting
7. **No Auto-REAL:** Readiness evaluator is read-only; no code path enables REAL trading

---

## Success Criteria

**V5 is COMPLETE when:**

✅ V5.0 — Architecture decision document with audit results  
✅ V5.1 — Firebase schema + QuotaGuard + Outbox, all tested  
✅ V5.2 — Official Futures feed, no Firebase in hot path  
✅ V5.3 — Three strategies, hard cost-edge gate, offline replay validation  
✅ V5.4 — Full PAPER lifecycle, Firestore persistence, restart recovery  
✅ V5.5 — Strict learner, policy state, REAL readiness state machine  
✅ V5.6 — E2E validation, quota stress test, live trial PASS, cutover plan  
✅ 15-17 — Metrics registry complete, Android contract defined  

**Release criteria:**
- Full test suite: 100+ tests, all PASS
- Quota: daily writes <= 2,500, hard cap 3,000 (verified)
- REAL: `real_orders_allowed=false` in all code paths (verified)
- Legacy: zero imports from `src.services.*` (verified)
- Firebase: v5_* collections only, no legacy writes (verified)

**Post-release:**
- Operator approval required for any REAL mode changes
- V5 becomes new canonical PAPER runtime
- Legacy services frozen (no patches, no new features)
- Cutover checklist signed off

---

## Next Session Recommendations

1. **Start with V5.2** (Futures feed) — execution truth is foundational
2. **Follow with V5.3** (strategies + cost gate) — validates feed + admission
3. **Then V5.4** (lifecycle) — brings trading online for the first time
4. **Parallel V5.5** (learning) — can start after V5.4 is stable
5. **Final V5.6** (E2E + cutover) — once everything integrated

**No production deploy until V5.6 PASS + operator approval**

---

## Files Changed

### Committed (V5.0 + V5.1)
- `docs/V5_ARCHITECTURE_DECISION.md` (new)
- `src/v5_bot/__init__.py` (new)
- `src/v5_bot/config.py` (new)
- `src/v5_bot/firebase/schema.py` (new)
- `src/v5_bot/firebase/quota_guard.py` (new)
- `src/v5_bot/firebase/outbox.py` (new)
- `src/v5_bot/firebase/repository.py` (new)
- `src/v5_bot/firebase/__init__.py` (new)
- `tests/v5_bot/__init__.py` (new)
- `tests/v5_bot/test_quota_guard.py` (new)
- `tests/v5_bot/test_outbox.py` (new)

### This Session (Planning)
- This file: `docs/V5_IMPLEMENTATION_ROADMAP.md` (new)

### Pending (Future Sessions)
- V5.2–V5.6 module files (6 sessions worth)
- Integration tests, CLI, cutover plan
- Metrics registry JSON + Android contract docs

---

## Session Wrap-Up

**Accomplished in this session:**
- ✅ Read and analyzed new V5 master specification
- ✅ Created V5 architecture decision document with legacy audit
- ✅ Implemented V5.1: Firebase schema + QuotaGuard + Outbox
- ✅ Verified all core modules functional (manual + test suite)
- ✅ Committed work to topic branch `v5/integrated-paper-firebase-quota-safe`
- ✅ Created comprehensive implementation roadmap

**Not in scope for this session (per user instructions):**
- No deploy to production
- No push to main
- No restart of existing legacy service
- No Firebase reset
- No additional O2/O2R patches

**Ready for next session:**
- Topic branch has foundation for V5.2–V5.6
- All tests passing
- No merge/deploy conflicts
- Clear roadmap for remaining work

---

**Status:** READY FOR OPERATOR REVIEW  
**Recommendation:** Proceed with V5.2 (Futures feed) in next session
