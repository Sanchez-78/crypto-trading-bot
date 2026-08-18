# P1.0 Acceptance Report — dynamic_trend_exit_v1

**Status:** IMPLEMENTED, UNIT_TESTED. Wired into the live exit path
2026-08-18 (`_workspace/36`), scoped to `trend_cost_aware_v1`-sourced
positions only. Currently dormant in production (0 P0.8+ positions have
opened as of this report) — not yet RUNTIME_VERIFIED against a real
position.

**Commit:** `fd2baa1` (2026-08-07, module). `_workspace/36` (2026-08-18,
wiring).

## Scope

New `src/services/dynamic_trend_exit_v1.py` per document §12. Directly
motivated by an earlier forensic finding in this same program: 100%
TIMEOUT exits observed on the live bot 2026-08-06/07, and ~23% of trades
breaching a TP/SL band without the band firing
(`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md`). This module does not touch
that live bug — it lived, at commit time, only in
`paper_trade_executor.py`'s pre-existing exit path, out of P1.0's
original scope — but was built the way §12 demands specifically so the
new pipeline would not reproduce that failure mode: "the new exit logic
must treat timeout as a last-resort safety cap, not the primary business
rule."

Nine-level exit hierarchy (§12.1), evaluated in a fixed, deterministic
order, first match wins: data-integrity → hard stop (structural vs
volatility, classified by whether the stop has trailed) → [risk-limit
slot reserved, no central risk guard existed at commit time — same
honest gap as P0.7/P0.8, closed later by `p0_risk_guard_v1.py`,
2026-08-10] → opposite-flow → structural trend failure → regime
invalidation → edge decay → trailing stop (activates + tightens, never
loosens) → dynamic target → max-hold safety (last resort, mapped to the
legacy `"TIMEOUT"` label for backward-compatible dashboards).

## Files changed

At commit `fd2baa1`:

| File | Purpose | Risk |
|---|---|---|
| `src/services/dynamic_trend_exit_v1.py` (new, 276 lines) | Pure, deterministic `evaluate_exit()` — never opens/closes a position itself, returns an `ExitDecision` for a caller | Low — no execution authority (bypass-tested) |
| `tests/test_dynamic_trend_exit_v1.py` (new, 331 lines) | Unit tests | None |
| `tests/test_dynamic_trend_exit_v1_bypass.py` (new) | AST-based bypass invariant | None |

At `_workspace/36` (2026-08-18, the actual wiring):

| File | Purpose | Risk |
|---|---|---|
| `src/services/paper_trade_executor.py` | New `_evaluate_p0_8_plus_dynamic_exit()` helper; `update_paper_positions()` routes only `explore_bucket=="P0_8_PLUS_EVIDENCE_COLLECTION"` AND `strategy_id=="trend_cost_aware"` positions to it | Medium — touches the primary exit-evaluation loop, but scoped by two explicit field checks so every other position (including the other two P0.8+ strategies) is provably unaffected (12 tests including negative controls) |
| `tests/test_dynamic_trend_exit_wiring.py` (new, 12 tests) | Routing + helper unit tests | None |

## Behavior before

`dynamic_trend_exit_v1.py` existed, fully unit-tested, with **zero call
sites anywhere** in the codebase (module docstring itself said so
explicitly: "not yet wired to any live loop in this phase"). Any
position — including ones later opened by the P0.8+ live pipeline —
exited through the same generic TP/SL/timeout machinery as every other
paper position.

## Behavior after

A `trend_cost_aware_v1`-sourced P0.8+ position is evaluated through the
full hierarchy on every `update_paper_positions()` tick, with a throttled
(15s) real feature refresh via
`strategy_trend_cost_aware_v1.compute_trend_features()` (reusing the
existing shared candle cache, no new REST load). Live in this pass: hard
stop, structural trend failure, trailing stop (mutates the real stored
`sl`), target exit, max-hold safety (aliased to the position's existing
`timeout_s`, so it is a real backstop, not a second parallel timeout).

## Tests

At commit `fd2baa1`: 37 new (construction/validation 4, hierarchy levels
1-9 individually 19, ordering/priority 3, trailing monotonicity 3,
legacy-label mapping 1, determinism 1, bypass 3, misc 3), all passing.
Full regression at commit time: 1802 passed / 79 failed / 7 skipped / 7
errors — unchanged failed/error baseline. This commit's message notes it
"completes the document's §31 'must implement now' scope: P0.7 + central
signal contract/router + P0.8 + P0.9 (shadow) + P1.0."

At `_workspace/36` (wiring): `tests/test_dynamic_trend_exit_wiring.py`,
12 new tests (fail-closed on missing candle history, never raises,
`legacy_exit_label` mapping including `MAX_HOLD_SAFETY_EXIT -> "TIMEOUT"`,
non-terminal trailing-stop mutation, initial-stop snapshot survives a
later trailing update, side-aware MFE for both BUY and SELL, routing
confirmed only for `trend_cost_aware` P0.8+ positions with two negative
controls). Full regression sweep: 273 passed, 1 pre-existing failure
(confirmed via `git stash`), 4 skipped.

## Known limitations

- **`flow_evaluation` left `None`** in the wiring — `FLOW_REVERSAL_EXIT`
  never fires. Blocked on P0.9 (`order_flow_features.py`) still having no
  live call site of its own (see `docs/P0_9_ACCEPTANCE.md`).
- **`remaining_net_edge_bps` left `None`** — `EDGE_DECAY_EXIT` never
  fires. No safe, reviewed edge-decay model exists yet.
- **`allowed_regimes` left `None`** — `REGIME_INVALIDATED` never fires.
  This function has no live per-tick regime re-classification available
  (only the regime captured once at entry); passing a value that could
  only ever equal itself would be a false signal of active protection.
- **Not yet RUNTIME_VERIFIED against a real position** — 0 P0.8+
  positions have opened since this wired 2026-08-18; the hierarchy has
  never actually fired in production yet.

## Rollback

Module: `git revert fd2baa1` — safe in isolation (zero callers at that
commit). Wiring: `git revert <the _workspace/36 commit>` — reverts
`update_paper_positions()`'s routing branch and the helper function;
every P0.8+ position immediately falls back to the generic exit path
with no other side effects (the position-dict fields this wiring adds —
`dynamic_exit_initial_stop`, `_dyn_exit_trend_features`,
`_dyn_exit_atr_bps`, `_dyn_exit_features_ts` — are additive-only and
simply become unused).

## Acceptance decision

ACCEPTED for the "must implement now" scope at the module level
(`fd2baa1`). Wiring (`_workspace/36`) ACCEPTED as a narrow, tested,
negative-control-verified extension — but its own runtime acceptance
(§24.4: "do not claim runtime acceptance from startup alone") is still
pending a real live trigger.
