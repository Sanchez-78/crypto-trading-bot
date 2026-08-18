# P0.9 Acceptance Report — Order-Flow Imbalance / Microprice (shadow-confirmation)

**Status:** IMPLEMENTED, UNIT_TESTED. NOT wired into any live decision as
of 2026-08-18 — remains a pure diagnostic feature module with zero
consumers in the admission path.

**Commit:** `b0dc132` (2026-08-07)

## Scope

New `src/services/order_flow_features.py` per document §11. Deliberately
scoped per the document's own framing: "a diagnostic feature set... a
confirmation or conflict filter for trend signals... an A/B evidence
mechanism. Do not initially create an independent high-frequency OFI
trading strategy." This module has zero P0/admission authority — it
never calls or imports `P0SegmentEVGate` or any entry primitive
(dedicated AST bypass test file, same discipline as the P0.7/P0.8 bypass
tests).

Gate G0 confirmed no existing top-of-book-imbalance/microprice/
signed-trade-delta implementation existed anywhere in the repository
(`order_book_depth.py` covers a different concern — wall detection) —
this is genuinely new, not a duplicate.

## Files changed

| File | Purpose | Risk |
|---|---|---|
| `src/services/order_flow_features.py` (new, 314 lines) | Imbalance, microprice, signed-trade-delta rolling windows, `FlowEvaluation`/`FlowWindowStats`, `FLOW_CONFLICT_LONG`/`FLOW_CONFLICT_SHORT`/`FLOW_LARGE_TRADE_CONFLICT` reason codes | Low — no admission authority (bypass-tested), diagnostic only |
| `tests/test_order_flow_features.py` (new, 348 lines) | Unit tests | None |
| `tests/test_order_flow_features_bypass.py` (new) | AST-based bypass invariant | None |

## Behavior before

No order-flow/microprice feature computation existed anywhere in the
repository.

## Behavior after

`order_flow_features.py` exists, is importable, and is unit-tested — but
has **zero live callers**. `dynamic_trend_exit_v1.py`'s
`ExitEvaluationInput.flow_evaluation` field can accept a `FlowEvaluation`
object (its `_opposite_flow()` check is fully implemented), but the
live wiring done 2026-08-18 (`_workspace/36`) deliberately leaves this
field `None` — this module's output is never actually computed and
passed through in production. This is the single largest gap between
"P0.9 implemented" and "P0.9 live" in the whole program.

## Tests

42 new at this commit (imbalance 5, microprice 6, trade-event sign 2,
rolling window 5, persistence 4, flow evaluation 14, shadow counterfactual
4, bypass 3, plus fixed conflict tests), all passing. Full regression at
commit time: 1765 passed / 79 failed / 7 skipped / 7 errors — unchanged
failed/error counts from baseline.

A real fixture bug was caught and fixed in the test file (not the
production code) while writing these tests: two `FlowWindowStats`
fixtures had a `large_trade_signed_delta` pointing the same direction as
their own `signed_notional_delta`, which triggered the (correctly
higher-precedence) `FLOW_LARGE_TRADE_CONFLICT` path instead of exercising
the general `FLOW_CONFLICT_LONG`/`SHORT` path the tests meant to isolate.
The production code's precedence ordering was confirmed correct; the
fixtures were the bug.

## Known limitations

- **No live call site anywhere.** Not shadow-evaluated, not
  live-evaluated, not feeding `dynamic_trend_exit_v1`'s
  `FLOW_REVERSAL_EXIT` level despite that level's logic being fully
  implemented and ready to receive a `FlowEvaluation`.
- No aggTrade/bookTicker ingestion pipeline was verified to feed this
  module in this phase — building that (§8's stream normalization) was
  explicitly out of scope for P0.9 itself, and remains unbuilt.
- Wiring this in is the clearest, most concrete "next phase" item for
  the P0.8+ program: it would activate `dynamic_trend_exit_v1`'s
  `FLOW_REVERSAL_EXIT` level (currently permanently inert, per
  `docs/P1_0_ACCEPTANCE.md`) and could feed a trend-signal
  confirmation/conflict filter per the document's original framing.

## Rollback

`git revert b0dc132` — safe in isolation, zero live callers to break.

## Acceptance decision

ACCEPTED as evidence/diagnostic-only per its own explicit scope — this
phase never intended to reach live admission or exit authority, so
"implemented but not wired" is the CORRECT end state for P0.9 as
originally scoped, not a gap against this phase's own acceptance bar.
It IS a gap against the larger program's eventual goals (see
`_workspace/37_document_compliance_gap_analysis.md`).
