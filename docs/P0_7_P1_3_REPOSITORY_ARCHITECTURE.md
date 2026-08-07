# P0.7–P1.3 Repository Architecture Report (Gate G0)

**Status:** INSPECTED
**Date:** 2026-08-07
**Baseline commit:** `f54cdd55f3ca08ca9c38252d3ac8834f84d3387b` (branch `main`)
**Working tree at inspection time:** `_workspace/monitoring_progress.json` modified (session bookkeeping, unrelated); several untracked `_workspace/*.md` forensic docs and `scripts/research/*.py` from an unrelated earlier task; no code files dirty. No user changes at risk.
**Source-of-truth used:** live systemd unit on Hetzner (`root@78.47.2.198`, via `systemctl cat cryptomaster`) + current repository code, per document section 0.1 precedence.

This report is Gate G0's mandatory deliverable per Evidence-First Strategy Expansion v2, section 27.1. It records what actually exists before any P0.7+ implementation begins, per section 5.1–5.2 ("do not begin strategy implementation until no unknown entry path remains").

---

## 1. Canonical Service (verified against live systemd unit, not local docs)

```
Service:            cryptomaster.service (single instance, confirmed no duplicate templates)
ExecStart:           /usr/bin/python3 -u /opt/cryptomaster/start.py
WorkingDirectory:     /opt/cryptomaster
PYTHONPATH:           /opt/cryptomaster:/opt/cryptomaster/src
```

Entry point `start.py` (repo root) boots directly — no WSGI/Gunicorn wrapper, matches `CLAUDE.md`'s documented dashboard-service precedent for "run directly" style deploys (this is the trading service, a separate unit from the dashboard).

**Live safety-relevant environment (confirmed via `/proc/<pid>/environ` on the running process, 2026-08-07):**

```
TRADING_MODE=paper_train
ENABLE_REAL_ORDERS=false
REAL_ORDERS_ALLOWED=false
REAL_TRADING_ENABLED=false
LIVE_TRADING_CONFIRMED=false
PAPER_ONLY_MODE=true
```

Five independent guards (not one) — see §5 below. This matches the finding from this session's earlier `trading-safety-agent` audit (`_workspace/12_supervisor_bypass_safety_audit.md`), re-confirmed here independently.

**No second daemon exists.** Other running processes on the box: `tick_recorder.py` (data collection, not trading), `start_flask_dashboard.py` (read-only reporting, separate unit `cryptomaster-dashboard.service`, deliberately `PartOf`-decoupled per `CLAUDE.md`), and a plain `python3 -m http.server` (static file serving, unrelated). None open positions.

---

## 2. THE central finding: three parallel, non-equivalent architectures exist in this repository

This is the single most important fact for scoping every phase below. The document assumes a single "legacy bot" to extend. The repository actually contains **three**:

| # | Tree | Wired into live `cryptomaster.service`? | Purpose (inferred from code + tests + root-level `CLEAN_CORE_*.md`/`V5_*.md` reports) |
|---|---|---|---|
| A | `src/services/*` (176 files) — the **legacy bot** | **YES — this is the live path** | The system this document's changes must land in. Contains the current P0-like gate, signal generation, paper execution, risk, learning. |
| B | `src/clean_core/*` (domain, market, execution, provenance, strategy, runner) | **NO — deliberately isolated, enforced by tests** | An offline/replay research sandbox. `tests/clean_core/test_no_legacy_runtime_wiring.py` and `test_non_wiring.py` assert, by import-source-scanning, that clean_core code never imports `src.services`, Firebase, or any live socket, and never writes to `data/` or `server_local_backups/`. This is a **ground-truth reference implementation** (cost accounting, deterministic replay, provenance journal) used to validate ideas offline — not a runtime to wire in. Multiple `CLEAN_CORE_*_TRIAL_REPORT.md` files at repo root document past bounded live-public-data trials run *through this isolated path*, separately from the trading bot. |
| C | `src/v5_bot/*` (market, execution, learning, firebase, paper, strategy) | **NO — not imported by `start.py` or any `src/services/*` file** (confirmed by grep; zero hits for `src.v5_bot` outside its own tree) | A second, more complete standalone runtime (own CLI `v5_bot/cli.py`, own paper broker/runner, own Firebase repository/outbox/quota_guard, own cost-edge gate and feature engine). Appears to be the design source that **`src/services/v5_legacy_bridge/`** (see below) was extracted from — but the full `v5_bot` runtime itself is not live. |

**A fourth item is live and important:** `src/services/v5_legacy_bridge/` (distinct from `src/v5_bot/`) **is wired into the legacy bot** — confirmed by 5 import sites in `paper_trade_executor.py` (lines 402, 1965, 2826, 2852, plus `emergency_health_monitor.py`). It provides: durable outbox (`outbox.py`), Firebase quota guard (`quota.py`), idempotent Firebase writer (`firebase_writer.py`), learning bridge, metrics publisher, and an outbox flush worker. Its log markers (`[V5_BRIDGE_...]`) have appeared throughout this session's live forensics — this is real, running infrastructure, not dead code.

**Consequence for every phase below:** per document section 0.1 ("repository and runtime facts are stronger evidence than assumptions in this document") and the explicit instruction to adapt rather than invent — new P0.7+ code must be added to **tree A** (`src/services/`, the live path), and should **reuse `v5_legacy_bridge`'s outbox/quota/idempotency machinery** rather than building a second one (document §19 requirements — priority classes, idempotency keys, close reserve, bounded backoff — are already substantially implemented there). It should **not** attempt to wire in `clean_core` or `v5_bot` — both are intentionally isolated (B by enforced test, C by simple absence of any import edge), and pulling them into the live path would itself violate this document's own "one canonical bot" / "no second daemon" rule in spirit (it would silently promote a shadow runtime to production without the gated gate gates this document requires). `clean_core`'s fee/funding/accounting formulas (`src/clean_core/execution/fees.py`, `funding.py`, `paper_accounting.py`) are, however, a useful cross-check reference for the new cost model's arithmetic, since they were built and tested independently.

---

## 3. Entry-Path Inventory (document §5.2 format)

| ID | Source file | Function | Caller(s) | Entry type | Current gate | Can bypass P0? | Can reach real orders? | Test coverage | Required action |
|---|---|---|---|---|---|---|---|---|---|
| E1 | `src/services/paper_trade_executor.py:1433` | `open_paper_position()` | 5 call sites (E2–E6) | Canonical paper-open primitive | Caller-dependent (see below) | **Yes — multiple callers reach it without a uniform central gate** (see finding below) | No — paper-only function, does not touch `execution_engine.py` | Partial (`test_paper_close_pipeline.py`, `test_p0_3_paper_integration.py`, others) | Must become the single point all new strategy signals funnel through via the new `evaluate_signal_for_paper_entry()` router (document §16); existing callers are historical and out of this task's scope to rewrite, but no *new* code may add a 6th direct caller. |
| E2 | `src/services/paper_trade_executor.py` (self) | — | internal | — | — | — | — | — | — |
| E3 | `src/services/paper_training_sampler.py` | `maybe_open_training_sample()` → calls `open_paper_position()` | training sampler loop | Bootstrap/training evidence | Routes through `_route_training_sample_through_p0_rde()` in `realtime_decision_engine.py:2866` (per project history, this was the fix for a prior bypass — see `CLAUDE.md`/memory "Bootstrap Bypass Fix") | Historically yes (fixed); current status **INSPECTED, not re-verified in this pass** — flag for P0.7 bypass-test phase | No | `test_p0_4_rde_routing.py`, `test_p11ap_o2_scoped_bootstrap.py` | Add an explicit AST/import-scan bypass test (document §22.3) asserting this path cannot skip `_route_training_sample_through_p0_rde` |
| E4 | `src/services/trade_executor.py:125` | `open_paper_position()` (thin wrapper, `*args, **kwargs`) | legacy compat shim | Compatibility wrapper | Delegates to E1 | Inherits E1's gate | No | Not directly covered — inherited | Confirm this wrapper cannot be imported by any new strategy module (add to bypass test) |
| E5 | `src/services/paper_exploration.py` | calls `open_paper_position()` | exploration/curiosity sampler | Exploration entries | `TRADING_AGENT_EXPLORATION_ENABLED` gated at config level (confirmed live: `true`, capped `TRADING_AGENT_EXPLORATION_MAX_PER_HOUR=60`) | **INSPECTED, not yet verified against central P0** — flag | No | `test_p1_paper_exploration.py` | Same as E3 — needs explicit bypass-test coverage before new strategies are added |
| E6 | `src/services/realtime_decision_engine.py` | calls `open_paper_position()` | main decision loop (the actual P0-adjacent gate today) | Primary signal path | This file contains `_route_training_sample_through_p0_rde` — it **is** today's closest equivalent to the document's "Central P0 Segment EV Gate" | N/A — this is closer to the gate itself | No | `test_p0_segment_ev_gate.py`, `test_p0_integration.py` | This is the integration point for the new `evaluate_signal_for_paper_entry()` — new strategies must route through here, not around it |
| E7 | `src/services/paper_adaptive_learning.py` | `record_close()` (learning-side close hook, not an entry) | close pipeline | Evidence/learning update | N/A (close-side) | N/A | No | `test_paper_adaptive_learning.py` | None — out of scope for entry-path bypass concerns |
| E8 | `src/services/candidate_dedup.py:182` | `record_open()` | dedup bookkeeping (not a trading primitive) | Dedup ledger, name collision with document's example names — **this is not an order-entry function**, it records a *candidate* for TOCTOU dedup | N/A | N/A | No | covered by dedup tests | None — document §3's `record_open(...)` concern refers to a *different, hypothetical* function name; verified the real `record_open` here is a dedup-ledger write, not an entry primitive. Recorded per §0.1 rule: discrepancy between prompt's assumed name and actual repo semantics. |
| E9 | `src/services/v5_legacy_bridge/__init__.py:108,130` | `record_open()`/`record_close()` (bridge methods) | called *after* E1/paper-close, for Firebase persistence only | Evidence persistence, not order entry | N/A | N/A — persistence-only | No | `test_v5_legacy_bridge_hooks.py`, `test_v5_legacy_bridge_outbox.py`, `test_v5_legacy_bridge_quota.py` | None — this is exactly the evidence-recorder tier the document wants (§18); reuse it. |
| E10 | `src/services/execution_engine.py:154` | `client.post("/api/v3/order", ...)` | `market_order()`, itself gated by `check_live_order_guard()` at line 137 (before the POST) | **The only REAL-order call site in the codebase** (confirmed by repo-wide grep, 2 hits total, both in this file: the guard comment and the call itself) | `runtime_mode.check_live_order_guard()` (4-flag AND gate, all default-safe) + `EXECUTION_ENGINE_ENABLED` (unset, so the whole async engine is never instantiated) + no Binance API keys present anywhere on the box | N/A (not a paper path) | **Unreachable today** — 5 independent guard layers, re-confirmed live 2026-08-07 (env dump above) | `test_execution_engine_no_real_order.py` | None required; re-verify this test still passes as part of the Phase 12 regression run before any deploy. |

**Open item carried into P0.7 bypass-test work (not yet "no unknown entry path remains"):** E3 and E5's current bypass-safety needs a fresh assertion-level test, not just historical fix confidence — recorded as a concrete action above rather than asserted as already proven, per document §0.3 truthfulness rules.

---

## 4. Central Gate / Evidence / Data-Flow Map

```
Market data:      src/services/market_stream.py (WebSocket) -> event_bus.py (per CLAUDE.md)
Decision:          src/services/realtime_decision_engine.py (closest existing analog to "Central P0 Segment EV Gate";
                    contains _route_training_sample_through_p0_rde)
Signal source:      src/services/signal_generator.py
Paper execution:    src/services/paper_trade_executor.py (open_paper_position, update_paper_positions,
                     TP/SL evaluation, close pipeline)
Compat wrapper:      src/services/trade_executor.py (delegates to paper_trade_executor; also the sole
                     REAL-order-adjacent module via its import of execution_engine, itself gated — see E10)
Real execution:      src/services/execution_engine.py (guarded, unreachable — E10)
Evidence bridge:     src/services/v5_legacy_bridge/ (outbox.py, firebase_writer.py, quota.py,
                     learning_bridge.py, metrics_publisher.py, outbox_flush_worker.py) — LIVE
Firestore client:    src/services/firebase_client.py (quota gate, batching, save_batch/_RETRY_QUEUE outbox
                     — this is the OLDER/broader Firestore client; v5_legacy_bridge's outbox.py is a newer,
                     narrower durable outbox specifically for trade open/close idempotency. Both exist;
                     do not build a third.)
Cost/exit reference: src/clean_core/execution/{fees,funding,paper_accounting}.py — ISOLATED, reference only
                     src/services/shadow_excursion_recorder.py, trade_excursion.py — LIVE, already tracks
                     MFE/MAE-adjacent "excursion" data (server-side sqlite file confirmed 8.95GB, written
                     through 2026-07-23 — i.e. it was live and has since stalled; needs investigation as
                     part of P0.7, not a fresh build)
Maker-fill model:    scripts (Hetzner "Run Maker-Fill Model v2" scheduled workflow) + related module —
                     a maker-fill realism model (document §15A.3) already exists in some form; P0.7 should
                     audit and reuse, not re-derive, before writing a new one.
```

---

## 5. Real-Order Path Safety (re-verified independently, matches this morning's dedicated audit)

Five layers, all confirmed live on 2026-08-07 (not merely read from code):

1. `src/core/runtime_mode.py:83-107` `live_trading_allowed()` — 4-flag AND gate, every flag defaults to the safe value.
2. `src/services/execution_engine.py:137-145` `check_live_order_guard()` — defense-in-depth, immediately before the HTTP POST.
3. `EXECUTION_ENGINE_ENABLED` unset — the async order-submission engine is never instantiated.
4. No `BINANCE_API_KEY`/`BINANCE_API_SECRET` anywhere on the box (`.env` or process environ) — even a defeated guard chain has no credentials to sign an order with.
5. `src/services/paper_trade_executor.py:44-82` `_enforce_paper_safe_mode()` — runs at import time, forcibly rewrites any live-leaning env var back to paper-safe.

**Assertion required by document §2.1** (`if enable_real_orders: raise RuntimeError(...)`) — **INSPECTED, not found as a literal startup assertion**. The 5 layers above are guards-at-use, not a single fail-fast startup assertion. This is a genuine gap against the document's explicit requirement and is scoped into Phase P0.7 as a small, additive, zero-risk fix (add the assertion; it can never fire under current config, so it changes no behavior).

---

## 6. Configuration System

- Environment-variable driven, primarily via systemd `Environment=` drop-ins on the server (the actual source of truth — **not** `.env`, which is present but largely superseded; confirmed today that `.env`-only changes are silently inert against systemd-set keys, e.g. `hetzner-set-paper-tp.yml` writing to `.env` has no effect because systemd `Environment=` wins).
- A newer drop-in mechanism, `systemd/99-cryptomaster-managed-runtime.conf`-style file, replaced the older `override.conf` as of this session's earlier investigation; **this file is currently untracked on the server** (governance gap, flagged in this session's earlier forensics, not yet remediated) — new P0.7+ flags (§20 of the document) must be added in a way that is trackable on `main`, not perpetuate the untracked-drop-in pattern.
- No central typed config-validation module was found equivalent to document §20's "validate at startup, reject invalid combinations" — this is a real gap, scoped into P0.7.

---

## 7. Test Structure

104 test files under `tests/`, including a dedicated isolated subtree `tests/clean_core/` (10 files) and `tests/v5_bot/` (9 files) for the two non-wired architectures, plus the main `tests/*.py` covering the legacy bot. Relevant pre-existing coverage for this program:

- `test_p0_segment_ev_gate.py`, `test_p0_integration.py`, `test_p0_4_rde_routing.py` — existing P0-analog gate tests, to be extended rather than replaced.
- `test_execution_engine_no_real_order.py` — existing real-order bypass test.
- `test_shadow_excursion_recorder.py`, `test_shadow_admission_features.py`, `test_shadow_aggtrade_capture.py`, `test_shadow_spread_capture.py`, `test_shadow_coverage_integrity.py` — existing MFE/MAE/excursion-adjacent shadow-recording tests; P0.7 must audit these before adding new ones.
- `test_maker_fill_model_v2.py` — existing maker-fill realism tests.
- `test_v5_legacy_bridge_*.py` (4 files) — existing outbox/quota/hooks coverage for the evidence bridge P0.7+ should reuse.
- **Known pre-existing baseline (from this session's earlier, independent full-suite run today):** ~1411 passed / 79 failed / 6 skipped / 7 errors outside `tests/v5_bot`, plus a known-hanging test (`tests/v5_bot/test_quota_guard.py::test_warning_state_triggered_reads`, pre-existing on `main`, unrelated to this program — exclude with `--ignore` in any full-suite gate run). This is the honest baseline; "all tests pass" is not achievable as a gate criterion without first fixing ~79 unrelated pre-existing failures, which is out of this program's scope. Gates in this program must be scoped as **no new failures**, not **zero failures**.

---

## 8. Deployment Path (re-confirmed today, used successfully this session)

Auto-deploy-on-push is **not** the live mechanism (a stale assumption in project memory, corrected today). The actual, sole path that mutates the live checkout and restarts the service is the manually-dispatched, 8-gate `Hetzner Deploy Apply (manual, gated)` GitHub Actions workflow (`confirm=PLAN` dry-run, then `confirm=DEPLOY`), which already implements almost exactly what this document's §24 "Before deployment" checklist and Gate G7 ask for: staging compile+test of incoming code, live-flag safety block, zero-open-position fail-closed gate, operator hold, rich READY convergence verify, and automatic rollback on failure. **Gate G7 in this program should use this existing workflow, not a new deployment mechanism.**

---

## 9. Summary of Gaps Found (feeds directly into Phase P0.7 scope)

| Gap | Severity | Action |
|---|---|---|
| No single literal startup assertion for real-order prohibition (document §2.1) | Low risk (already unreachable via 5 other layers) but a direct spec requirement | Add in P0.7, zero behavior change |
| E3/E5 (training sampler, exploration) bypass-safety not freshly re-verified against a central router | Medium — exactly the historical bug class this project has been bitten by before | Add explicit bypass tests before/alongside P0.8 |
| No central typed config-validation-at-startup module | Medium | Add narrowly scoped version in P0.7, additive |
| `shadow_excursion_recorder.py` / `trade_excursion.py` exist but excursion sqlite stopped growing 2026-07-23 (14 days stale) | Needs investigation — may mean P0.7's MFE/MAE requirement is *mostly* already met and just needs an unstick, not a rebuild | First P0.7 sub-task: diagnose before building anything new |
| Maker-fill model v2 exists as a scheduled read-only workflow — integration status with live paper fills unconfirmed | Needs investigation before document §15A.3 work begins | P0.7/15A follow-up |
| Untracked systemd config drop-in on server (governance gap, pre-existing, flagged this session) | High (separate incident, already known) | Not this program's scope to fix, but new P0.7+ flags must not be added the same untracked way |

**Gate G0 verdict: PASS.** Entry-path inventory complete for all currently-reachable paths; two items (E3, E5) carry forward as explicit test obligations rather than closed items — this is disclosed, not hidden, per document §0.3. Service command identified. Effective configuration identified from live source. Real-order path identified and independently re-confirmed unreachable. Working tree protected (no destructive operations performed; only new files added under `docs/`, `audit/`).
