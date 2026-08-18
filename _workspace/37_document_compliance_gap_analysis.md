# Evidence-First Strategy Expansion v2 — Full Document Compliance Gap Analysis

**Date:** 2026-08-18
**Trigger:** Operator directive "kromě monitoringu pokracuj v implementaci
dokumentu az do uplneho splneni" (besides monitoring, continue
implementing the document until full compliance).

**Honest framing up front, per the document's own §0.3 rule** ("never use
'verified'/'production-ready'/'safe' without exact evidence") and §37
("prefer incomplete implementation with proven safety over broad
implementation with hidden bypasses"): this document specifies dozens of
subsystems, test categories, and governance processes. Full literal
compliance with every subsection (a complete deterministic-replay
fixture with 12 named scenarios and hash-stable evidence, a 9-state
regime classifier with hysteresis and transition logging, full
universe/liquidity governance with contract-metadata validation,
machine-readable audit artifacts for every category, baseline-measured
SLOs) is a multi-week undertaking, not something completed in one
session. This document tracks real progress honestly, phase by phase,
rather than claiming a false "done."

## §36E Required Self-Review (answered now, per the document's own mandate)

1. Did any strategy gain a direct import or reference to execution? **No** — every P0.8+ strategy module is bypass-tested (AST scan) to confirm no import of any entry primitive.
2. Can any missing field default to admission? **No** — `StrategySignal.__post_init__` fail-closes on missing/invalid fields; `signal_router.py`'s `_reject()` path is the default for any unhandled case, not an implicit admit.
3. Can a restart duplicate a position? **Not newly introduced by this program** — `open_paper_position()`'s existing dedup/lock machinery (pre-existing, not touched) is what this program relies on; not independently re-verified against the NEW P0.8+ call site specifically this session (gap — see below).
4. Can a paper fill occur at midprice? **No for the live pipeline** — `p0_8_plus_live_pipeline.py` books at the crossed ask (long)/bid (short) from a real live quote, never mid, and skips opening entirely rather than fall back to a synthetic/mid price (2026-08-17 fix, `_workspace/33`).
5. Can same-interval stop/target ambiguity favor the strategy? **Not evaluated this session** — the paper-fill model's existing same-interval handling was not specifically re-audited against the new pipeline (gap — see §22.10 below).
6. Can an all-market slow book stream feed OFI? **N/A** — `order_flow_features.py` has zero live callers (no stream feeds it at all yet, see `docs/P0_9_ACCEPTANCE.md`).
7. Can a COIN-M payload enter a USDⓈ-M feature window? **Not applicable / not evaluated** — the P0.8+ pipeline uses `binance_client.py`'s existing REST candle fetch (already USDⓈ-M scoped elsewhere in the repo); not independently re-verified this session.
8. Can Firestore local-midnight reset exceed provider quota? **Fixed this session** — `_reset_quota_if_new_day()`'s boundary logic was already correct (2026-08-07 fix); the separate read/write conflation bug (2026-08-18, `_workspace/34`) is fixed.
9. Can two service instances write simultaneously? **No new risk** — single canonical service confirmed (`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` §1), unchanged by this program.
10. Can a shadow outcome enter canonical P0 trade counts? **No** — the shadow evaluator structurally cannot open a position (bypass-tested); the live pipeline's positions are real, tagged, and distinguishable via `explore_bucket`/`training_bucket` = `P0_8_PLUS_EVIDENCE_COLLECTION` (survives the internal P0.3C reroute even though other attribution fields don't, per `_workspace/33`).
11. Can configuration change without cohort/version change? **Partial gap** — `StrategySignal.strategy_version` is checked against the registry, but no formal "bump version on behavior change" enforcement exists (documented as an open gap in `docs/COST_AWARE_STRATEGY_DESIGN.md`).
12. Can an evidence failure leave a position unrecorded? **Not newly introduced** — relies on the existing (pre-this-program) outbox/retry machinery in `paper_trade_executor.py`/`v5_legacy_bridge`, not independently re-audited against the new call site this session.
13. Did any test mock away the exact safety boundary it claims to test? **No, actively checked** — `tests/test_p0_8_plus_live_pipeline.py`'s integration test deliberately runs a REAL (unmocked) `open_paper_position()` specifically because mocked-only tests would have missed the `p0_gate_reason` dict-placement bug (reviewer-agent finding, `_workspace/33`).
14. Did any code or report expose secrets? **No** — no API keys, tokens, or credentials appear in any commit, test, or doc from this session (spot-checked; not exhaustively scanned with a secret-scanning tool — gap, see §36B below).
15. Did any command mutate production without explicit authorization? **No** — every deploy this session went through the gated `hetzner-deploy-apply.yml` workflow (PLAN dry-run confirmed clean, then DEPLOY), under the standing full-autonomy grant for this program; no raw `git push`-triggers-deploy or manual server edit was used for code (the one direct SSH+`systemctl restart` was for the tracked, git-committed systemd overlay file specifically, per that file's own documented governance process).

**No unsafe "yes" answer above.** Items 3, 5, 7, 12, 14 are marked "not independently re-verified this session" — genuine gaps in verification depth, not known failures. Tracked below.

## Compliance status by section (document status vocabulary: NOT_INSPECTED / INSPECTED / DESIGNED / IMPLEMENTED / UNIT_TESTED / INTEGRATION_TESTED / REPLAY_VERIFIED / RUNTIME_VERIFIED)

| Section | Status | Notes |
|---|---|---|
| §2 Mandatory safety state | RUNTIME_VERIFIED | Paper-only confirmed throughout; §36E above |
| §7 Core data contracts | IMPLEMENTED, UNIT_TESTED | `strategy_contracts.py` |
| §9-12 P0.7-P1.0 | IMPLEMENTED, UNIT_TESTED, partially RUNTIME_VERIFIED | See individual acceptance reports |
| §13 P1.1 volatility_breakout_v1 | IMPLEMENTED, UNIT_TESTED, admission-reachable since 2026-08-18 | 0 real admits observed |
| §14 P1.2 sideways_mean_reversion_v1 | IMPLEMENTED, UNIT_TESTED, admission-reachable since 2026-08-18 | 0 real admits observed |
| §15 P1.3 funding_observer_v1 | IMPLEMENTED, UNIT_TESTED | Correctly never-wired (§15.4, by design) |
| §15A Paper execution realism | PARTIALLY INSPECTED | Fill model exists (pre-program); not re-audited against new P0.8+ call site (item 5 above) |
| §15B Concurrency/crash recovery | NOT_INSPECTED against the new call site | Relies on pre-existing machinery, not independently re-tested this session (items 3, 12 above) |
| §16 Central P0 routing | IMPLEMENTED, UNIT_TESTED, RUNTIME_VERIFIED | **FIXED 2026-08-18** (`_workspace/38_admission_path_unification.md`) — `paper_trade_executor.py`'s internal P0.3C reroute is now bypassed for the P0.8+ bucket specifically; the document's "one central signal admission path" (§34) is now literally true for this pipeline. Deployed, verified live (legacy path unaffected: 20 PAPER_ENTRY/2min post-deploy, 0 tracebacks). |
| §17 Risk guard | IMPLEMENTED, UNIT_TESTED, RUNTIME_VERIFIED | `p0_risk_guard_v1.py`, wired 2026-08-10 |
| §18 Evidence model | PARTIALLY IMPLEMENTED | Entry/close metadata present via existing position-dict fields; not independently checked against every §18 required field |
| §19 Firestore/Outbox | PARTIALLY INSPECTED | Priority classes (§19.1), idempotency (§19.2) rely on pre-existing v5_legacy_bridge machinery, not re-audited this session. Close reserve (§19.3, `REJECT_EVIDENCE_CLOSE_RESERVE`) — **not implemented**, no such reject code exists. |
| §20 Configuration | DONE (2026-08-18) | `src/services/p0_8_plus_config_validation.py` — fail-closed startup assertion (same pattern as `assert_real_orders_prohibited()`), validates the config surface that actually exists (fee/slippage/synthetic-spread non-negative, data-age/quote-age windows positive). `OFI_MODE`/dynamic-exit-toggle/max-spread checks from the document's suggested list have no analog in this repo (no such flags exist) — not invented. 13 tests, deployed, `[8/8] Warmup complete` confirmed on the live server (assertion is a genuine no-op under production config). `.env.example` updated with the actual P0.8+ flags. |
| §21 Logging | PARTIAL | `[P0_8_PLUS_LIVE]`/`[P0_8_PLUS_SHADOW]`/`[P0_8_PLUS_DYNAMIC_EXIT]` event families exist but don't match the document's suggested event-name taxonomy exactly (again, adapted to repo convention) |
| §22.1-22.3 Unit/integration/bypass tests | SUBSTANTIALLY DONE | Every phase has dedicated unit + bypass tests; integration paths (candidate→signal→cost→P0→risk→open→evidence) covered piecemeal across `test_signal_router.py`/`test_p0_8_plus_shadow_evaluator.py`/`test_p0_8_plus_live_pipeline.py`, not as one named end-to-end fixture |
| §22.4 Deterministic replay | **NOT DONE** | No replay fixture with fixed timestamps + stable evidence hashes exists for the P0.8+ pipeline. Largest concrete test-infrastructure gap. |
| §22.5 Lookahead prevention | NOT_INSPECTED | Not specifically audited this session |
| §22.6 Recursive indicator stability | NOT_INSPECTED | `compute_trend_features()`'s `MIN_CANDLES=200` warmup floor exists; not tested for "stabilizes after sufficient history" specifically |
| §22.7 Property invariants | PARTIAL | Several already covered incidentally (e.g. trailing-stop-never-loosens has a dedicated test in `test_dynamic_trend_exit_v1.py`); not compiled as one named invariant suite |
| §22.8 Performance tests | NOT DONE | No explicit memory/CPU/logging-rate test for the new pipeline |
| §22.9 Concurrency/restart tests | NOT DONE for the new call site specifically (items 3, 12 above) | |
| §22.10 Paper-fill model tests | NOT DONE for the new call site specifically (item 5 above) | |
| §22A Regime classifier governance | GAP | Current classifier (`regime_classifier_v1.py`) has 4 states (BULL_TREND/BEAR_TREND/SIDEWAYS/VOLATILE), not the document's suggested 9 (missing UNKNOWN/WARMUP/VOLATILITY_EXPANSION_UP/DOWN/PANIC/DATA_UNHEALTHY as distinct states). No hysteresis/dwell-time, no transition logging, no confidence-based low-confidence-trend-vs-sideways separation. |
| §22B Universe/liquidity governance | **NOT DONE** | No contract-active/metadata-valid/spread-distribution/notional-activity check before enabling a symbol; `_env_symbols()` is a flat static list |
| §23 Statistical evaluation | **NOT DONE** | No walk-forward, multiple-testing correction, or cohort-immutability infrastructure exists — moot until real admitted-candidate evidence accumulates (currently 0) |
| §24 Deployment/runtime acceptance | SUBSTANTIALLY DONE via the existing gated workflow | `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` §8 confirms the workflow already implements most of §24.1's checklist |
| §25 Backward compatibility | RUNTIME_VERIFIED | Confirmed no Android/dashboard contract breakage across every deploy this session |
| §26 Prohibited changes | RUNTIME_VERIFIED clean | No item on the prohibited list was done — confirmed by review of every commit this session |
| §27 Required deliverables | IN PROGRESS | This session: `docs/P0_7_ACCEPTANCE.md`..`P1_0_ACCEPTANCE.md`, `docs/COST_AWARE_STRATEGY_DESIGN.md`, `docs/P0_7_P1_3_ROLLBACK.md` written 2026-08-18. `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` updated. §27.4 test evidence exists piecemeal in workspace docs, not consolidated. §27.7 final implementation summary — not yet written as a standalone artifact. |
| §28 Implementation quality standards | SUBSTANTIALLY FOLLOWED | Type hints, frozen dataclasses, DI for testability, structured reason codes all present in the P0.8+ modules; not audited line-by-line against every bullet |
| §29 Module boundaries | ADAPTED, not literal | Repo uses `src/services/` flat structure, not the document's suggested `trading/market_data/` tree — deliberate, documented adaptation |
| §30 Decision codes | IMPLEMENTED | `strategy_contracts.py`'s `REJECT_*`/`P0_*` constants |
| §36B Security/supply-chain | PARTIAL | No new dependencies added (compliant by default); no dedicated secret-scan run this session (gap) |
| §36C SLOs/cardinality budgets | **NOT DONE** | No baseline measurement, no formal SLO definitions |
| §36D Machine-readable audit artifacts | PARTIAL | `audit/entry_paths.json` exists (P0.7); the other 7 suggested files (`audit/strategy_registry.json`, `reports/test_manifest.json`, etc.) do not |
| §36E Self-review | DONE (this document, above) | |
| §37 Final principle | Directionally honored | Every change this session was attributable, cost-aware, fail-closed by construction, and disclosed rather than overclaimed |

## Prioritized remaining work (roadmap for subsequent cycles)

**Tier A — tractable, high-value, low-risk:**
1. ~~§20 Configuration validation at startup~~ — DONE 2026-08-18.
2. ~~Unify the two independent P0.8+ admission checks~~ — DONE 2026-08-18 (`_workspace/38`).
3. ~~§22.7 Property invariants~~ — DONE 2026-08-18.
4. §36D — generate the missing machine-readable audit artifacts (mostly plumbing given the facts already exist in code/tests). **Next up.**

**Tier B — larger but bounded:**
5. §22.4 Deterministic replay fixture — meaningful engineering effort, no external dependency, high evidentiary value once the pipeline starts producing real candidates.
6. §22.9/§22.10/item 3/5/12 from the self-review — dedicated concurrency/crash/fill-model tests against the specific new P0.8+ call site (reusing/extending existing pre-program test patterns, not building new infrastructure).

**Tier C — large, and some carry real risk to the live primary path (approach with extra caution, likely needs its own dedicated review cycle):**
7. §22A Regime classifier governance overhaul (9 states, hysteresis, transition logging) — touches `regime_classifier_v1.py`, which the shared shadow/live pipeline already depends on; a careless change here could destabilize currently-working candidate generation.
8. §22B Universe/liquidity governance — new subsystem, moderate scope.
9. §23 Statistical evaluation infrastructure — genuinely moot until real admitted-candidate evidence exists (currently 0); lower priority than actually getting evidence flowing.

**Explicitly deferred, not scheduled:** §36C SLO baselines (needs weeks of real traffic data to be meaningful, not something to fabricate), full §36B secret-scanning tooling integration (would need to evaluate/introduce a new dependency — itself subject to §36B's own "prefer existing dependency set" rule).
