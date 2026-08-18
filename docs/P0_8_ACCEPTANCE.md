# P0.8 Acceptance Report — trend_cost_aware_v1 (evidence-only)

**Status:** IMPLEMENTED, UNIT_TESTED, RUNTIME_VERIFIED (live-wired and
confirmed opening bounded evidence-collection paper positions is the
correct target — actual admission count still 0 as of 2026-08-18, see
Known limitations).

**Commit:** `85ef6b2` (2026-08-07). Live-wired: `_workspace/33`
(2026-08-17), scope-widened: `_workspace/35` (2026-08-18).

## Scope

New `src/services/strategy_trend_cost_aware_v1.py` per document §10.
`generate_candidates()` produces `StrategySignal` objects for the central
router. Never opens a position, never imports any entry-primitive module
or symbol — verified by a dedicated AST bypass test file (same discipline
as `test_signal_router_bypass.py`). Contains no P0/strict-EV promotion
logic (§10.9 — that decision stays in `signal_router.py` only).

Reuses `src/services/feature_extractor.py` (`regime()`/`vol()`) instead
of recomputing EMA/ATR a second, possibly-diverging way (Gate G0
discipline). Candle schema is the real one already in production
(`binance_client.py`'s `open_time`/`open`/`high`/`low`/`close`/`volume`),
not invented.

Feature computation (§10.2): fast/slow EMA slope in bps/minute
(interval-agnostic, derived from actual `open_time` deltas), VWAP offset,
higher-high/higher-low/lower-high/lower-low structure scores, trend
persistence ratio, ATR-derived volatility in bps.

## Files changed

| File | Purpose | Risk |
|---|---|---|
| `src/services/strategy_trend_cost_aware_v1.py` (new, 450 lines) | Trend candidate generation, cost-aware self-filter, `ALLOWED_LONG_REGIMES`/`ALLOWED_SHORT_REGIMES` (BULL_TREND long, BEAR_TREND short) | Low — additive, no entry-primitive import (bypass-tested) |
| `tests/test_p0_8_integration.py` (new) | End-to-end integration fixtures | None |
| `tests/test_strategy_trend_cost_aware_v1.py` (new, 334 lines) | Unit tests | None |
| `tests/test_strategy_trend_cost_aware_v1_bypass.py` (new) | AST-based bypass invariant | None |

## Behavior before

No cost-aware trend strategy existed for the new pipeline; the legacy
`signal_generator.py` path was the only signal source.

## Behavior after

`trend_cost_aware_v1` candidates flow through `signal_router.py` →
`p0_8_plus_shadow_evaluator.py` (shadow, 2026-08-10) → since 2026-08-17,
`p0_8_plus_live_pipeline.py` can open a real bounded paper position for
an admitted candidate. As of 2026-08-18 (`_workspace/35`), the shared
`P0SegmentEVGate` regime restriction that previously made BEAR_TREND
(short) and BTCUSDT/SOLUSDT unreachable for this strategy specifically
was lifted (does not affect the legacy signal path).

## Tests

35 new at this commit (feature computation 6, candidate gates 8,
`generate_candidates` 11, bypass 4, end-to-end integration 2, replay
scenarios 4), all passing. Full regression at commit time: 1723 passed /
79 failed / 7 skipped / 7 errors — failed/error counts unchanged from the
P0.7+router baseline; the passed-count increase is exactly this commit's
new tests. (Later sessions, e.g. `_workspace/33`/`35`/`36`, added further
tests exercising this strategy's live-wiring path — see those workspace
docs and `docs/P1_1_P1_3_PHASE_REPORT.md`-adjacent history for current
totals.)

A real bug caught and fixed during test-writing, not the test adjusted to
match it: §10.3's candidate-criteria list explicitly includes "net
expected edge positive after costs" as a candidate-level gate, not only a
router-level one — an early `continue` when `edge.admitted is False` was
missing and added.

## Known limitations

- **Real admission count is 0** as of 2026-08-18, ~29h after live-wiring
  deployed. Not a bug — confirmed via forensics (`_workspace/35`) that
  the bottleneck is now the strategy's own internal pattern thresholds
  under current market conditions, not admission scope (which was the
  confirmed blocker before the 2026-08-18 fix).
- `evidence_only=True` is structural (never flipped) — this strategy can
  never receive strict-EV/scaled admission in this phase, by design
  (§2.4).
- TP/SL geometry (`initial_stop_price`/`target_reference_price`) is
  currently superseded in this deployment by the global
  `PAPER_TP_ZONE_BPS`/`PAPER_SL_ZONE_BPS` env override whenever those are
  set (confirmed via SSH, `_workspace/33`) — the strategy's own computed
  geometry becomes load-bearing only the day that override is removed.

## Rollback

`git revert 85ef6b2` (code) is safe in isolation but leaves later commits
(`d4d69ee` central router, `_workspace/33`/`35`/`36` live-wiring) with a
dangling import — revert the live-wiring commits first, or revert this
whole chain together. Disable without reverting: unset
`PAPER_P0_8_PLUS_LIVE_ENABLED` (systemd overlay) and/or
`PAPER_P0_8_PLUS_SHADOW_ENABLED=false` — no code change needed for either.

## Acceptance decision

ACCEPTED for the "must implement now" scope. Live-wiring and
scope-widening (both later, separately reviewed changes) are consistent
extensions of this phase's original design, not new decision paths.
