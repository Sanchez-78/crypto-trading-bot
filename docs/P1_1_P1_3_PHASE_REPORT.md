# P1.1–P1.3 Phase Report (Evidence-First Strategy Expansion v2)

**Status:** IMPLEMENTED, UNIT_TESTED. NOT INTEGRATION_TESTED, NOT REPLAY_VERIFIED, NOT RUNTIME_VERIFIED.
**Date:** 2026-08-10
**Baseline commit:** `fd2baa1` (P1.0, last commit before this phase)
**Builds on:** Gate G0 (`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md`), P0.7–P1.0 (commits `d4d69ee`, `85ef6b2`, `b0dc132`, `fd2baa1`)
**Source doc:** `D:\CryptoMaster_Evidence_First_Strategy_Expansion_v2_Reviewed.md` (Revision 2.0), §13/§14/§15

This report covers the three new evidence-only strategy modules added this
session, per §27.3 ("Phase reports").

---

## 1. What was built

| Phase | Section | Module | strategy_id | exit_profile |
|---|---|---|---|---|
| P1.1 | §13 Volatility Breakout V1 | `src/services/strategy_volatility_breakout_v1.py` | `volatility_breakout` | `dynamic_breakout_exit_v1` (identifier registered; engine deferred) |
| P1.2 | §14 Sideways Mean Reversion V1 | `src/services/strategy_sideways_mean_reversion_v1.py` | `sideways_mean_reversion` | `mean_reversion_exit_v1` (identifier registered; engine deferred) |
| P1.3 | §15 Funding Opportunity Observer | `src/services/strategy_funding_observer_v1.py` | `funding_observer` (not registered — see §3 below) | n/a (no positions) |

Each strategy module (P1.1, P1.2) follows the exact structural pattern
established by P0.8 (`strategy_trend_cost_aware_v1.py`): a frozen feature
dataclass, pure `long_candidate`/`short_candidate` gate functions, a
`generate_candidates()` entry point that self-filters on `cost_model.evaluate_edge()`
before emitting a `StrategySignal`, and `evidence_only=True` on every signal.
P1.3 is structurally different (see §3).

Tests: 5 new test files (`test_strategy_volatility_breakout_v1[.py|_bypass.py]`,
`test_strategy_sideways_mean_reversion_v1[.py|_bypass.py]`,
`test_strategy_funding_observer_v1[.py|_bypass.py]`), 88 new test cases.
Combined with the existing P0.7–P1.0 test files, the full Evidence-First
family (`test_strategy_*`, `test_order_flow_features*`, `test_dynamic_trend_exit_v1*`,
`test_signal_router*`, `test_strategy_registry.py`, `test_cost_model.py`) —
**278 passed, 0 failed** as of this report.

---

## 2. Regime taxonomy and evidence separation (§13.7)

The live regime classifier (`src/services/regime_filter.py`) uses exactly
four values: `SIDEWAYS`, `BULL_TREND`, `BEAR_TREND`, `VOLATILE`. Allowed-regime
sets across all P0.8+ strategies are disjoint by construction (asserted by
`test_strategy_identity_disjoint_from_*` in each new test file):

| Strategy | Allowed regimes |
|---|---|
| `trend_cost_aware` (P0.8) | `BULL_TREND`, `BEAR_TREND` |
| `volatility_breakout` (P1.1) | `SIDEWAYS`, `VOLATILE` |
| `sideways_mean_reversion` (P1.2) | `SIDEWAYS` only |

`volatility_breakout` and `sideways_mean_reversion` both accept `SIDEWAYS`
candles as raw input, but their gates are structurally different (breakout
requires a compression-percentile + expansion-ratio pattern culminating in a
Donchian-level clearance; mean-reversion requires a z-score extension with a
near-zero EMA slope) — the two cannot both admit the same candidate episode
in practice, but this was not exhaustively proven (no combined-fixture test
was written to demonstrate mutual exclusivity on identical input).
**DEFERRED, not BLOCKED**: worth a follow-up property test if both are ever
wired into the same live evaluation pass.

---

## 3. P1.3 scope note: observer only, not the funding-carry research thread

`strategy_funding_observer_v1.py` implements exactly what §15 specifies: a
single-leg, no-position diagnostic that scores a funding opportunity from
caller-supplied inputs (current rate, mark/index price, estimated costs) and
returns a `FundingObservation` record. It is **not registered** in
`strategy_registry.py` and has no `generate_candidates()` — it cannot reach
the P0 router because it never proposes a `StrategySignal`, and registering
it would misrepresent it as one.

This is a different thing from the delta-neutral spot+perp carry strategy
under active research in `EXTERNAL_AUDIT_PROMPT_v9.md` /
`scripts/research/funding_carry_v2.py` / `funding_carry_v3.py` /
`funding_carry_robustness.py`. That thread is explicitly **not authorized**
as of this report — it is awaiting an external auditor's Q1 ruling on
whether a perp-leg paper track is even in scope, per that document's own
Q1/Q2/Q3. Nothing in this phase moves that thread forward or backward; it
is flagged here only so the two are not conflated by a future reader of
either document.

---

## 4. THE central finding, restated (carried forward from Gate G0 and every phase since)

**None of P0.8, P0.9, P1.0, P1.1, P1.2 is wired into the live decision loop.**
Verified this session by direct grep:

```
grep -rn "strategy_trend_cost_aware_v1\|order_flow_features\|dynamic_trend_exit_v1\|strategy_volatility_breakout_v1\|strategy_sideways_mean_reversion_v1\|strategy_funding_observer_v1" \
    src/services/realtime_decision_engine.py src/services/market_stream.py start.py src/services/signal_router.py
```
→ zero matches, for every module including `signal_router.py` itself.

Concretely: five phases of code (P0.8 trend, P0.9 OFI, P1.0 dynamic exit,
P1.1 breakout, P1.2 mean-reversion) exist as fully unit-tested, standalone
modules with zero call sites from anything the running `cryptomaster.service`
process actually executes. `signal_router.py` (the central P0 routing point
these modules are designed to feed) is itself never imported by
`realtime_decision_engine.py`, `market_stream.py`, or `start.py`.

**This means zero live paper-trading evidence has been collected for any of
these five phases**, despite the document's stated goal being "produce
clean, attributable evidence and determine whether each strategy has
positive post-cost expected value" (§1). No amount of additional unit
testing changes this — evidence requires runtime execution against live
market data, which requires the wiring step this program has consistently
deferred phase after phase.

This is consistent with the document's own Gate G7 design ("Only after G7
may the agent recommend an evidence-collection window" — §36A) and its
explicit permission boundary ("the agent may not... deploy code" without
"explicit authorization" — §0.2). It is disclosed here, not silently
carried forward again, because five phases in is long enough that it is
worth surfacing as a decision point rather than an implicit default:

**Open question for the user:** wire P0.8–P1.2 into the live decision loop
(a Gate G7-scoped change — requires explicit authorization per §0.2, and a
concrete integration design: where in `realtime_decision_engine.py` or
`market_stream.py` candidates get generated per tick, how `signal_router.py`
gets invoked, and what the admission path into `paper_trade_executor.py`
looks like without becoming a 6th direct caller of `open_paper_position()`
per Gate G0's entry-path inventory) — or continue building P1.3-adjacent
scope and defer wiring further. Not decided by this report.

---

## 5. Deferred work disclosed in this phase (§0.3 truthfulness)

- `dynamic_breakout_exit_v1` and `mean_reversion_exit_v1` exit engines are
  NOT built — only the identifier strings are registered (same pattern as
  P0.8/P0.9 referencing `dynamic_trend_exit_v1` before P1.0 built it).
- No combined-fixture test proves `volatility_breakout` and
  `sideways_mean_reversion` are mutually exclusive on identical SIDEWAYS
  input (§2 above).
- P1.3's cost/funding inputs are 100% caller-supplied; no Binance funding-rate
  fetch, no scheduling, no caching layer exists. Wiring a real data source is
  out of scope for this phase and was not attempted.
- No machine-readable audit artifacts (§36D: `audit/strategy_registry.json`
  etc.) were produced this session — the existing `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md`
  Markdown report was extended instead. Flagged, not fabricated as done.

## 6. Self-review (§36E, spot-checked against the new modules only)

1. Direct import/reference to execution? No (all three bypass tests assert this).
2. Missing field defaults to admission? No — every gate function returns an
   explicit non-`None` rejection reason; `StrategySignal.__post_init__` and
   `FundingObservation.__post_init__` both fail closed on construction.
3–9, 12: N/A — none of the three new modules touches persistence, restarts,
   execution, or Firestore.
10. Can a shadow outcome enter canonical P0 trade counts? No —
   `evidence_only=True` is hardcoded on every signal these modules emit, and
   none of them is registered/routed, so nothing reaches P0 counts at all.
11. Can configuration change without cohort/version change? Thresholds are
   module constants (not env-driven) in this phase, same as P0.8 — no
   config surface exists yet to change silently.
13. Did any test mock away the exact safety boundary it claims to test? No —
   the bypass tests monkeypatch `open_paper_position` to raise, then execute
   the real `generate_candidates()`/`observe_funding_opportunity()` path
   against realistic fixtures, rather than mocking the strategy module itself.
14. Secrets exposed? No.
15. Did any command mutate production without authorization? No — additive
   files only (`src/services/*.py`, `tests/*.py`, this doc); no deploy, no
   service restart, no env change.
