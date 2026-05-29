# CryptoMaster V5 — Architecture Decision & Legacy Boundary

**Date:** 2026-05-27  
**Status:** Design & Boundary Audit COMPLETE  
**V5 Commit Target:** Branch `v5/integrated-paper-firebase-quota-safe`

---

## 1. Decision: New Integrated PAPER Runtime, NOT a Patch

### What V5 Is

V5 is a **complete new PAPER trading bot** with:
- Single integrated lifecycle (market → signal → entry/close → learning → Firebase → metrics)
- Firebase as durable source of truth (not legacy local state)
- Hard Firestore quota guard (2,500 writes/3,000 hard cap per day)
- Complete metrics visibility for operator review and Android dashboard
- Deterministic REAL readiness evaluator (but REAL stays disabled)
- Strict learning eligibility (no "learn despite negative post-cost edge")

### What V5 Is NOT

V5 is NOT:
- A patch to legacy `src/services` pipeline
- An import of legacy learning state, rolling metrics, ECON_BAD/PF status, or bucket outcomes
- Another discovery/probe/shadow route layered onto legacy architecture
- A Spot WebSocket feed adapter
- A recovery path using legacy Firebase collections

### Explicit Statement

```
legacy_learning_imported = False
legacy_firebase_collections_read = False
legacy_firebase_collections_written_to = False
```

---

## 2. Legacy Dependency Audit — What V5 Will NOT Import

### Forbidden Legacy Services Modules

V5 runtime **must not** import from:

| Module | Reason |
|--------|--------|
| `src.services.paper_adaptive_learning` | Proved to have idle-gate violation; rolling100 metrics stale; admission controls not activated |
| `src.services.paper_training_sampler` | Discovery bootstrap failed idle gate enforcement; C segment cooldowns never persisted |
| `src.services.realtime_decision_engine` | Legacy Bayesian calibration tied to old cost_edge_ok=False logic |
| `src.services.firebase_client` | Legacy client; V5 uses new QuotaAwareFirestoreRepository |
| `src.services.trade_executor` | Legacy REAL/PAPER unified module; V5 has separate paper_broker |
| `src.services.risk_engine` | Legacy calibration; V5 uses hard cost-edge gate |
| `src.services.adaptive_recovery` | Tied to legacy learning; V5 learning is new |
| `src.services.adaptive_block_telemetry` | Legacy control state schema; V5 uses new v5_admission_controls |
| `src.services.event_bus` | Legacy pipeline signaling; V5 uses simple in-memory queues |
| Any module with `PAPER_STARVATION_DISCOVERY`, `legacy_pre_scoped_discovery_guard`, or `c_weak_segment_cooldowns` | Previous failed architecture |

### Confirmed Audit Results

Grep confirmed:
```bash
$ rg "from src.services\|import.*services" src/clean_core
# Result: NO MATCHES — clean_core is isolated ✓
```

### Import Boundary

**V5 source tree layout:**
```
src/v5_bot/
  __init__.py
  config.py
  domain.py  (V5 domain models, separate from clean_core.domain if needed)
  runner.py  (main service entry point)
  
  market/
  strategy/
  execution/
  learning/
  firebase/
  monitoring/

tests/v5_bot/
```

**Imports allowed:**
- `src.clean_core.*` (market feeds, accounting, provenance, epoch, journal)
- `src.v5_bot.*` (internal V5 modules)
- External: `firebase_admin`, `binance`, `pydantic`, `pytest`, `numpy`, etc.

**Imports forbidden:**
- `src.services.*` (entire legacy module)
- `src.clean_core.runner.forward_paper_runner` only if it imports `src.services` (audit individually)

---

## 3. Clean Core Reuse Audit — What V5 CAN Port

### Reusable Components (CONFIRMED ISOLATED)

| Component | Location | V5 Use | Audit |
|-----------|----------|--------|-------|
| **Futures routes** | `clean_core.market.binance_usdm_routes.py` | WebSocket URL generation | ✓ Uses only `fstream.binance.com`; no Spot; no legacy imports |
| **Local book** | `clean_core.market.local_book.py` | In-memory order book | ✓ Isolated; no legacy deps |
| **Fee model** | `clean_core.execution.fees.py` | Taker/maker fee accounting | ✓ Isolated; no service deps |
| **Funding** | `clean_core.execution.funding.py` | Perpetual funding cost | ✓ Isolated |
| **Paper accounting** | `clean_core.execution.paper_accounting.py` | Fill + PnL calculation | ✓ Isolated; core math |
| **Provenance/epoch** | `clean_core.provenance.epoch.py` | Epoch tracking | ✓ Isolated; can be extended |
| **Eligibility** | `clean_core.provenance.eligibility.py` | Learning eligibility rules | ⚠ Review for legacy state references |
| **Domain** | `clean_core.domain.py` | MarketSourceIdentity, ExecutionTruthClass | ✓ Pure dataclasses |
| **Recorded feed** | `clean_core.runner.recorded_futures_feed.py` | Replay for testing | ✓ No legacy deps |
| **Simulated feed** | `clean_core.runner.simulated_futures_feed.py` | Unit test mocks | ✓ No legacy deps |

### Audit Summary

```
clean_core modules analyzed: 25 files
Imports from src.services: 0
Imports from firebase legacy: 0
Isolated: YES ✓
```

**Reuse decision:** Port key components (market, execution, provenance, domain) directly into V5 namespace OR reuse via import with clear isolation boundary.

---

## 4. New V5 Firebase Schema — Separate Namespace

### Official V5 Collections

```text
v5_control/active
v5_epochs/{epoch_id}
v5_runtime/open_positions
v5_trades/{trade_id}
v5_learning/state
v5_metrics/daily_{quota_day_pt}
v5_metrics/segments_current
v5_dashboard/current
v5_readiness/current
v5_metrics_registry/current
v5_quota/{quota_day_pt}
v5_incidents/{incident_id}
```

### Legacy Collections — Read-Only Archival Only

```
paper_adaptive_learning_state        → archived, do not write
paper_trades                         → archived
paper_metrics                        → archived
(all other src/services collections) → do not read, do not write
```

---

## 5. Execution Truth Requirement

### Official Binance USDⓈ-M Futures Only

V5 uses:
- `wss://fstream.binance.com/ws/<symbol>@bookTicker` (order book snapshots)
- `wss://fstream.binance.com/market/ws/<symbol>@aggTrade` (aggregate trades)
- REST `/fapi/v1/ticker/24hr` for funding/mark price telemetry only (not fill truth)

No Spot URLs. No `stream.binance.com`. No legacy fill providers.

---

## 6. REAL Trading — Permanently Disabled at Architecture Level

### Code Guarantee

V5 architecture enforces:

```python
# In v5_bot/config.py
PAPER_ONLY_MODE: bool = True
REAL_ORDERS_ALLOWED: bool = False
```

REAL code path is absent, not merely gated by a boolean.

### Proof

- V5 `paper_broker.py` returns simulated fills (no order submission)
- No connection to Binance account keys for order placement
- No trade executor module imported from legacy
- Test suite verifies no REAL order attempt can occur

---

## 7. Daily Firestore Quota Design

### Internal Operational Caps

| Limit | Target | Hard Cap | Official Quota |
|-------|--------|----------|----------------|
| Document writes / day | ≤ 2,500 | ≤ 3,000 | 20,000 |
| Document reads / day | ≤ 3,000 | ≤ 8,000 | 50,000 |
| Document deletes / day | 0 | 0 | 20,000 |

### Pacific Timezone Daily Reset

Quota day = America/Los_Angeles midnight UTC-7/UTC-8.

Conversion: PT midnight = UTC 07:00 (PDT) or UTC 08:00 (PST)  
If operator in GMT+2: PT midnight = GMT+2 09:00 next day

SQLite quota ledger uses `datetime.now(pytz.timezone('America/Los_Angeles'))` for day boundary.

---

## 8. V5 Runtime Lifecycle Summary

### Startup
1. Load env/secrets; init Firebase Admin SDK
2. Init local SQLite quota ledger + outbox
3. Read (< 20 reads): v5_control/active, v5_epochs/{active}, v5_runtime/open_positions, v5_learning/state
4. Reconcile outbox; validate epoch schema
5. Connect Binance Futures feeds
6. Log V5_RUNTIME_READY

### Market Event Path (No Firebase)
- Validate source identity + freshness
- Update local book / regime / features
- Strategy candidate evaluation
- Cost edge hard gate check
- Quota reserve check
- Entry candidate ready

### PAPER Entry
- Atomic batch: create v5_trades/{trade_id}, update v5_runtime/open_positions
- If Firebase fail: persist to outbox, do not open locally until confirmed

### PAPER Close
- Write close payload to outbox first (durable WAL)
- Update v5_trades/{trade_id} (CLOSED)
- If eligible: batch update v5_learning/state + v5_metrics/daily_*
- Optional: coalesce v5_dashboard/current, v5_readiness/current

### Learning (Strict Eligibility Only)
- Metric update by: strategy_id : symbol : regime : side
- No learning from legacy; no ineligible outcomes
- Deterministic cooldown/downweight after sample sufficient and negative post-cost edge

### REAL Readiness (Informational Only)
- Status machine: NOT_READY_* → REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
- All gates and thresholds in v5_readiness/current
- But `real_orders_allowed=false` always

---

## 9. Development Workflow

### Topic Branch
```bash
git switch -c v5/integrated-paper-firebase-quota-safe origin/main
```

### Implementation Phases (V5.0–V5.6)
1. **V5.0:** Architecture decision + legacy boundary (THIS DOCUMENT + audit)
2. **V5.1:** Firebase schema + QuotaGuard + Outbox
3. **V5.2:** Futures feed + accounting truth
4. **V5.3:** Strategy candidates + hard cost gate
5. **V5.4:** PAPER lifecycle + Firebase persistence
6. **V5.5:** Clean learner + policy update
7. **V5.6:** End-to-end validation + cutover plan

### No Legacy Patch During V5 Development

Explicitly forbidden in this session:
- Do not modify `src/services/paper_adaptive_learning.py`
- Do not modify `src/services/paper_training_sampler.py`
- Do not merge O2/O2R discovery fixes into legacy
- Do not attempt to "repair" C segment cooldowns in legacy
- Do not write to legacy Firebase collections

---

## 10. Acceptance Criteria for V5.0

✅ **Complete:**
- V5 namespace/directory structure planned (src/v5_bot/)
- Legacy module list documented with reasons
- Clean core audit complete (no legacy imports found)
- Reusable components identified (market, execution, provenance, domain)
- Firebase v5_* schema defined (no legacy writes)
- REAL trading disabled at architecture level (code guarantee)
- Quota design and daily cap finalized
- Lifecycle summary complete

✅ **Audit Results:**
- `src.clean_core.*`: 0 imports from src.services ✓
- Reusable components: 8+ isolated modules ✓
- Legacy forbidden list: 10+ modules identified ✓
- Official Binance routes: fstream.binance.com only ✓

---

## 11. Next Steps → V5.1

Implement:
1. `src/v5_bot/firebase/quota_guard.py` — QuotaAwareFirestoreRepository
2. `src/v5_bot/firebase/schema.py` — v5_* dataclasses and validators
3. `src/v5_bot/firebase/outbox.py` — durable WAL for failures
4. `runtime/v5_quota_usage.sqlite` — local quota ledger
5. Unit tests for quota states (NORMAL, WARNING, DEGRADED, CRITICAL, HARD_STOP)
6. Firestore emulator tests

**Commit message:**
```
V5.0: Establish isolated integrated PAPER architecture and legacy non-import boundary
```

---

## 12. Final Statement

V5 is a **clean break** from legacy architecture. It is not an evolution of O2/O2R patches. It is a new runtime with:

- **Single canonical lifecycle** (no shadow probes, no learning-only routes)
- **Firebase durable state** (not in-memory rolling metrics)
- **Hard quota enforcement** (circuit breaker, not warnings)
- **Strict learning eligibility** (no cost_edge_ok=False admissions)
- **No REAL until explicit operator approval** (architecture-level enforcement)

The V5 bot will trade, close, learn, report readiness, and remain PAPER-only—forever, until separately authorized.
