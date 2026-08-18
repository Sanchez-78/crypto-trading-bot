# P1.0 dynamic_trend_exit_v1 wired into the exit path (trend_cost_aware_v1 only)

**Date:** 2026-08-18
**Trigger:** Operator directive, item #2 from the prioritized next-steps
list (after item #1, evidence-scope widening, was deployed and confirmed
healthy).

## What changed

`dynamic_trend_exit_v1.py` (P1.0) had zero call sites anywhere in the
codebase — positions opened by the P0.8+ live pipeline exited through the
exact same generic TP/SL/timeout machinery every other paper position
uses, missing the whole point of the module's purpose-built exit
hierarchy (Sec 12: structural trend failure, trailing stop, target,
regime invalidation, edge decay, max-hold-as-last-resort).

`paper_trade_executor.py`:
1. New helper `_evaluate_p0_8_plus_dynamic_exit(trade_id, pos,
   current_price, ts)` — builds a `dynamic_trend_exit_v1.ExitEvaluationInput`
   from the stored position's fields (entry/current price, stops, target,
   timing, MFE from the already-tracked `max_seen`/`min_seen`) plus a
   throttled (15s) live feature refresh via
   `strategy_trend_cost_aware_v1.compute_trend_features()` (candle fetch
   through the same shared `candle_cache_v1` the rest of the P0.8+
   pipeline already uses — no new REST load). Returns a legacy-mapped
   exit-reason string if the position should close, or `None` if it
   should stay open (including the case where the hierarchy only updated
   the trailing stop, applied directly to `pos["sl"]` under the position
   lock).
2. `update_paper_positions()`: a position is routed to this helper
   **only** when `explore_bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"` AND
   `strategy_id == "trend_cost_aware"` — every other position (including
   `sideways_mean_reversion_v1`/`volatility_breakout_v1` P0.8+ positions,
   which don't have a dedicated P1.x exit module and whose regime targets
   don't semantically fit a trend-specific hierarchy) is completely
   unaffected, unchanged generic exit path.
3. Added `"strategy_id"` to the fields `open_paper_position()` copies
   from `extra` onto the stored `position` dict — this was silently being
   dropped before (present in `p0_8_plus_live_pipeline.py`'s `extra`
   dict since `_workspace/33`, never actually stored), which this fix
   needed to distinguish `trend_cost_aware` positions from the other two
   P0.8+ strategies sharing the same bucket.

## Deliberately scoped out this pass (disclosed, not oversights)

- **`flow_evaluation`**: left `None` — would need P0.9 order-flow
  (`order_flow_features.py`) wired in, which is itself still
  shadow-only. `FLOW_REVERSAL_EXIT` simply never fires.
- **`remaining_net_edge_bps`**: left `None` — no safe, reviewed way yet
  to track edge decay over a position's life without risking a wrong,
  premature-exit-triggering estimate. `EDGE_DECAY_EXIT` never fires.
- **`allowed_regimes`**: left `None` (disables `REGIME_INVALIDATED`) —
  this function has no live regime re-classification per tick, only the
  regime captured once at entry; passing a value that could only ever
  equal itself would be a false signal of active protection, not a real
  check.
- **`max_hold_seconds`** deliberately reuses the position's own
  `timeout_s` (same value the generic path would have used) — so the
  hierarchy's own `MAX_HOLD_SAFETY_EXIT` (Sec 12.9: "rare compared with
  semantic exits") is the real safety backstop, not a separate parallel
  timeout that could disagree with it.

What IS live: data-integrity gate (trivially satisfied — a valid
`current_price` already exists by the time this runs), hard-stop breach,
structural trend failure (via a real `compute_trend_features()` call,
not a stub), trailing stop (activates + tightens per Sec 12.7, applied to
the real stored `sl`), target-based exit, max-hold safety timeout.

## Why this is safe to deploy even though 0 P0.8+ positions currently exist

The evidence-scope-widening fix deployed earlier today (`_workspace/35`)
still hasn't produced any admitted candidates as of this patch — so this
change is currently dormant in production, exactly like the live pipeline
itself was before its first patch. Built and reviewed now so that WHEN a
`trend_cost_aware_v1` position does open, it gets the intended exit
behavior from its very first trade, rather than needing a second,
rushed patch under time pressure once real positions are already open
and behaving suboptimally on the generic exit path.

## Tests

`tests/test_dynamic_trend_exit_wiring.py` (new, 12 tests): the routing
helper (no-candle-history fails closed, never raises, terminal decisions
map correctly via `legacy_exit_label` including the `MAX_HOLD_SAFETY_EXIT
-> "TIMEOUT"` case, non-terminal trailing-stop updates mutate `sl` and
keep the position open, initial-stop snapshot captured once and survives
a later trailing mutation, MFE computed side-aware for both BUY and
SELL) and `update_paper_positions()`'s routing (trend_cost_aware P0.8+
positions call the new helper; other P0.8+ strategies and regular
positions do not, both pinned with negative-control tests).

Full regression sweep (`test_paper_mode.py` + this new file +
`test_dynamic_trend_exit_v1_bypass.py` + `test_p0_8_plus_live_pipeline.py`
+ `test_tp_sl_cost_floor_invariant.py`): 273 passed, 1 failed (the same
pre-existing local-`.env` case), 4 skipped. `py_compile` clean.

## What to watch post-deploy

- If/when the first `trend_cost_aware_v1` P0.8+ position actually opens,
  watch for `[P0_8_PLUS_DYNAMIC_EXIT]` log lines to confirm the hierarchy
  is actually evaluating (not silently failing closed every tick due to
  e.g. insufficient candle history for that symbol).
- `dynamic_exit_initial_stop`/`_dyn_exit_trend_features`/
  `_dyn_exit_atr_bps`/`_dyn_exit_features_ts` are new, internal-only
  fields on the position dict — not part of any existing external
  contract, but worth knowing they exist if a future session greps
  position dict keys.
