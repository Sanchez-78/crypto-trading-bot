# CryptoMaster V10.15 — Analyze-First Non-Breaking Patch + Codex Delegation

Target: `C:\Projects\CryptoMaster_srv`  
Goal: improve observability/lifecycle safety inspired by Mammon **without breaking existing bot logic**.  
Mode: conservative, incremental, audit-first, additive-first.

---

## 0. Prime Directive

You are Claude Code acting as senior quant/backend implementation lead.

Do **not** rewrite the bot. Do **not** replace architecture. Do **not** change trading behavior unless a real bug is proven from code/log evidence.

Expected project may contain Binance feed, event bus, `signal_generator.py`, `realtime_decision_engine.py`, `trade_executor.py`, TP/SL/trailing/timeout exits, `learning_monitor.py`, `firebase_client.py`, Firestore, Android dashboard metrics, EV/WR/regime learning, V10.x patches.

Discover actual architecture from files. Do not assume.

Desired outcome:

```text
existing CryptoMaster behavior preserved
+ architecture audit
+ compatibility map
+ safe helper modules
+ canonical decision/lifecycle logs
+ structured error codes
+ optional Codex delegation for simple isolated tasks
```

---

## 1. Hard Safety Rules

1. No big-bang rewrite.
2. No deletion of working logic.
3. No public API/file/function renames unless every call site is updated and tests pass.
4. Do not change EV formula, score formula, thresholds, sizing, leverage, TP/SL, trailing, timeout, risk gates, Firebase schema, Android-facing collections, or live order behavior unless bug evidence is documented.
5. No new infrastructure: no Redis/DuckDB/Postgres/Timescale/Docker/dashboard unless already used.
6. Firebase remains canonical UI/state store.
7. Use technical names only: `DecisionFrame`, `OrderLifecycle`, `ErrorRegistry`, `CanonicalDecisionLog`.
8. New monitoring/log helpers must never break trading. Wrap optional logging in `try/except`.
9. Prefer additive modules. Integrate read-only first.
10. If uncertain, stop implementation and write blockers/plan.

---

## 2. Phase A — Baseline Snapshot Before Edits

Before editing code, run and record results:

```bash
git status
python -m compileall .
python -m pytest -q
```

If pytest is unavailable or fails due to existing baseline issues, document it. Do not “fix everything”; continue only if compile/runtime contracts are understandable.

Create:

```text
docs/V10_15_BASELINE_SNAPSHOT.md
```

Include:
- current branch/status
- compile result
- test result
- detected entrypoints
- risky pre-existing failures

---

## 3. Phase B — Architecture Audit Before Implementation

Create:

```text
docs/V10_15_ARCHITECTURE_AUDIT.md
```

Must include:

```text
1. Entrypoints: main.py, start.py, bot2/main.py, service/systemd/deploy files if present.
2. Runtime flow: market data → features → signal → RDE → executor → exits → learning → Firebase.
3. Contracts:
   - signal fields
   - decision fields
   - position/trade fields
   - event bus event names
   - log formats
   - Firestore collections/docs
   - Android-facing state if detectable
4. Gate map:
   EV, score, spread, timing, loss streak, loss cluster, pair block,
   exposure, max positions, same direction, TP/SL/RR, timeout/trailing.
5. Learning map:
   realized PnL source, fees/slippage handling, EV/WR/bandit/calibrator updates,
   model_state persistence, proxy-vs-real-PnL usage.
6. Persistence map:
   Firestore reads/writes, batching, compressed collections, daily budget guards.
7. Fragility map:
   duplicated logic, contradictory logs, side effects, fragile imports,
   production-version drift risks.
8. Classification:
   SAFE_NOW / CODEX_SAFE / CLAUDE_ONLY / POSTPONE.
```

No implementation until this file exists.

---

## 4. Phase C — Compatibility Map

Create:

```text
docs/V10_15_COMPATIBILITY_MAP.md
```

For each proposed change, use table:

```text
Component | Existing files touched | Behavior preserved | Risk | Test | Rollback
```

Expected additive components, unless equivalents already exist:

```text
src/core/decision_frame.py
src/core/error_registry.py
src/execution/order_lifecycle.py
src/monitoring/canonical_decision_log.py
```

If equivalent modules already exist, extend them instead of duplicating.

---

## 5. Claude vs Codex Decision

After audit/map, split work:

### Claude-only
Sensitive logic:
```text
RDE, EV, score, sizing, exposure/risk, executor, TP/SL/trailing/timeout,
Firebase schema/state, learning/PNL attribution, live order path.
```

### Codex-safe
Delegate to Codex if CLI exists:
```text
pure dataclasses, enums/constants, serialization helpers, log format helpers,
docs, unit tests for pure helpers.
```

### Postpone
Do not auto-implement:
```text
large refactors, storage migration, deployment changes, new infra,
threshold changes, learning formula changes, exchange adapter rewrite.
```

Check Codex:

```bash
codex --version
```

If available, Claude should create a narrow prompt and call Codex for simple isolated tasks. If unavailable, Claude may implement Codex-safe tasks itself.

Codex prompt path:

```text
docs/codex_prompts/V10_15_CODEX_TASK_001.md
```

Codex prompt must include:
```md
Implement only the listed files. Do not touch RDE/executor/Firebase/learning/main/start unless explicitly allowed.
No external deps. Preserve behavior. Add small tests. Return diff summary.
Allowed files: <exact list>
Forbidden files: realtime_decision_engine.py, trade_executor.py, learning_monitor.py, firebase_client.py, main.py, start.py
```

After Codex:

```bash
git diff --stat
git diff
python -m compileall .
python -m pytest -q
```

Reject/revert Codex changes if forbidden files changed, imports break, thresholds changed, execution behavior changed, or Firebase schema changed.

---

## 6. Implementation Order

### Patch 1 — Pure core helpers only

Add/extend:

```text
src/core/decision_frame.py
src/core/error_registry.py
```

Requirements:
```text
pure Python, no external deps, no exchange/Firebase calls, no side effects,
JSON-safe dict serialization, backward-compatible with dict signals/decisions.
```

Suggested objects:
```text
DecisionFrame
GateResult
ErrorCode / ErrorRegistry
```

DecisionFrame capabilities:
```text
from_signal_dict()
to_dict()
add_gate()
reject()
approve()
set_execution_state()
set_exit_state()
set_learning_state()
```

Do not force existing runtime to use it yet.

---

### Patch 2 — Canonical logging helper

Add/extend:

```text
src/monitoring/canonical_decision_log.py
```

Rules:
```text
logging only; accepts dict or DecisionFrame; one-line stable output;
missing fields must not crash; no behavior changes.
```

Example:
```text
CANON_DECISION id=... sym=BTCUSDT reg=BULL_TREND dir=BUY decision=REJECT reason=CM-RDE-001 ev=... score=... gates=...
```

---

### Patch 3 — Lifecycle helper

Add/extend:

```text
src/execution/order_lifecycle.py
```

States:
```text
SIGNAL_CREATED, DECISION_STARTED, FEATURES_LOCKED, REGIME_LOCKED,
EV_COMPUTED, GATES_EVALUATED, DECISION_APPROVED, DECISION_REJECTED,
ORDER_ARMED, PREFIRE_VALIDATED, ORDER_SENT, ORDER_FILLED,
POSITION_OPENED, EXIT_TRIGGERED, POSITION_CLOSED, PNL_ATTRIBUTED,
LEARNING_UPDATED, FIREBASE_STATE_UPDATED
```

Pure helper only.

---

### Patch 4 — Optional read-only integration

Only after Patches 1–3 compile/test.

Allowed integration:
```text
emit canonical log after RDE decision
emit canonical log after executor rejection
emit lifecycle log after trade close
emit lifecycle log after learning update
```

Forbidden in this patch:
```text
changing decisions, changing sizes, changing gates, blocking/approving trades,
changing Firebase schema, changing TP/SL/timeout.
```

Every integration must be safe:

```python
try:
    ...
except Exception:
    logger.debug("canonical helper failed", exc_info=True)
```

---

## 7. Checks After Every Patch

Run:

```bash
python -m compileall .
python -m pytest -q
git diff --stat
git diff
```

If tests are unavailable, state it and rely on compileall + targeted import checks.

---

## 8. Required Invariants

Final report must prove:

```text
- same startup path
- same signal → RDE flow
- same RDE decisions unless only logging added
- same executor input fields
- same TP/SL/trailing/timeout behavior
- same learning/EV/PNL behavior
- same Firebase/Android compatibility
- helper failure cannot stop trading
```

---

## 9. Rollback

For every changed file document:

```text
File | Change | Why safe | Rollback command
```

Example:

```bash
git checkout -- src/execution/trade_executor.py
```

---

## 10. Final Deliverables

Create/update:

```text
docs/V10_15_BASELINE_SNAPSHOT.md
docs/V10_15_ARCHITECTURE_AUDIT.md
docs/V10_15_COMPATIBILITY_MAP.md
docs/V10_15_IMPLEMENTATION_REPORT.md
docs/codex_prompts/... if Codex used
```

Implementation report:
```text
1. analyzed files/flows
2. changes implemented
3. intentionally unchanged areas
4. Claude vs Codex split
5. files changed
6. checks run
7. invariant proof
8. remaining risks
9. next recommended patch
```

---

## 11. Stop Conditions

Stop implementation and create:

```text
docs/V10_15_BLOCKERS_AND_NEXT_STEPS.md
```

if:
```text
architecture unclear; multiple entrypoints conflict; RDE/executor contracts unclear;
Firebase schema inconsistent; compile fails in a way that blocks safe analysis;
production code differs materially from expected V10.x; Codex touched forbidden files;
safe patch would require changing thresholds/execution/learning behavior.
```

Stability beats elegance. Compatibility beats refactor purity. Real net PnL/EV truth beats proxy scores.
