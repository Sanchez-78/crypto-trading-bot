# Finding + fix: `lifetime_pf`/`lifetime_expectancy` was secretly just `rolling100`

**Date:** 2026-08-13, autonomous monitoring cycles 50-60
**Severity:** Medium (misleading metric, not a safety/trading-logic bug — paper-only, informational)

## Symptom

Across cycles 50-59 of the autonomous monitoring loop, the dashboard's
`lifetime` block (`lifetime_expectancy`, `lifetime_profit_factor`) flipped
sign/direction **four times** within a handful of 30-minute cycles, despite
`lifetime_n` being ~3900-4000 trades:

| Cycle | lifetime_n | lifetime_expectancy | lifetime_pf |
|-------|-----------|---------------------|-------------|
| 49 | 3531 | +0.0200 | 1.272 |
| 52 | 3554 | -0.0410 | 0.573 |
| 57 | 3879 | -0.0294 | 0.308 |
| 58 | 3907 | +0.0097 | 1.307 |
| 59 | 3918 | -0.0023 | 1.042 |
| 60 | 3932 | +0.0097 | 1.308 |

A swing this large from +11 to +28 new trades, over an alleged ~3900-trade
average, is not statistically plausible for a true flat lifetime mean —
flagged as "likely noise" in real time and investigated once the pattern
was unambiguous (4 flips).

## Root cause

`src/services/paper_adaptive_learning.py`, `record_close()` (the path that
runs on every single paper trade close):

```python
self.lifetime_n += 1
self.lifetime_expectancy = self._compute_expectancy(
    [e[0] for e in self._lifetime_entries()]
)
self.lifetime_pf = self._compute_pf(
    [(e[0], e[1]) for e in self._lifetime_entries()]
)
```

where:

```python
def _lifetime_entries(self) -> List:
    """Get all lifetime entries (rolling20+50+100 combined)."""
    # This is approximate; ideally we'd track all lifetime entries
    # For now, combine rolling windows (will miss oldest after rotate)
    return list(self.rolling100)
```

`lifetime_n` is a true monotonic counter (correct, matches the real trade
count). But `lifetime_expectancy`/`lifetime_pf` were recomputed **every
close** from `list(self.rolling100)` — i.e. **only the last 100 trades**.
The docstring even says so ("This is approximate"), but nothing downstream
(dashboard, this session's own monitoring loop, `get_metrics()`'s
`PAPER_POLICY_SNAPSHOT`) treats it as anything other than a true full-history
average. It is exactly as noisy as `rolling100_pf`/`rolling100_expectancy`
(which are ALSO computed and logged alongside it, redundantly, under a
different — and honest — name).

## Fix (commit pending, this session)

Track true cumulative running sums, updated incrementally on every close,
independent of any rolling window:

- `self.lifetime_net_pnl` (already existed as a field, was declared but
  never actually incremented anywhere — always saved as `0.0`) now
  accumulates `sum(net_pnl_pct)` across all trades.
- New `self._lifetime_gross_wins` / `self._lifetime_gross_losses` accumulate
  the win/loss legs separately (needed for PF = gross_wins / gross_losses).
- `lifetime_expectancy = lifetime_net_pnl / lifetime_n` (true mean).
- `lifetime_pf = _pf_from_gross(gross_wins, gross_losses)` (true ratio).
- Both new accumulators are persisted (Firebase nested `lifetime_metrics`
  dict + flat local JSON backup) so they survive restarts/deploys — this
  session restarts the bot very frequently (many deploys/day), so without
  persistence the "fix" would just become a different, slower-decaying
  version of the same bug (reset to true-but-short history every restart).
- **Backward-compat migration:** state files saved before this fix have
  `lifetime_pf`/`lifetime_expectancy` but no `gross_wins`/`gross_losses`
  keys. On load, if those keys are absent, back-solve a one-time continuity
  seed from the legacy (rolling100-approximated) `pf`/`expectancy`/`n`
  via `losses = (expectancy*n) / (pf - 1)`, `wins = pf * losses` (clamped
  non-negative; falls back to a simpler split when `pf == 0` or `1.0`).
  Exact historical gross win/loss breakdown isn't recoverable once trades
  have aged out of `rolling100`, so this is an estimate — but it avoids an
  artificial discontinuity (e.g. PF jumping to 1.0 on the next close) and
  every trade recorded from the moment of this deploy onward is an exact,
  not approximated, increment.
- `_reconcile_state()`'s rare D_NEG-contamination cleanup branch (fires
  only if legacy D_NEG-tainted entries are found in the rolling windows,
  "shouldn't happen" per its own comment, no evidence it has fired this
  session) is left untouched — deliberately, to keep this patch narrow and
  evidence-scoped. It still recomputes from `_lifetime_entries()` (rolling100)
  in that rare path; documented as a known, unchanged limitation in the
  function's docstring.

## Tests

`tests/test_paper_adaptive_learning.py`:
- `test_4b_lifetime_survives_past_rolling100_window_2026_08_13` — 150
  trades (100 losses then 50 wins); asserts the true lifetime mix (100
  losses + 50 wins, pf=0.5) is preserved once trade 101+ would have started
  rotating losses out of a 100-entry deque, and that it now visibly differs
  from `rolling100_pf` (which legitimately only sees the last 100).
- `test_4c_lifetime_pf_survives_restart_past_rolling100_window` — 120
  trades, drop the singleton (simulated restart), confirm the reloaded
  instance's `lifetime_pf`/`lifetime_expectancy` match exactly (not
  reset toward a rolling100 approximation).
- `test_17b_load_state_migrates_legacy_state_without_gross_sums` — loads a
  pre-fix-format state file (no `gross_wins`/`gross_losses` keys), asserts
  the backfill is internally consistent (recomputed PF matches the legacy
  PF, net matches legacy expectancy*n) and that the next real close extends
  from that seed correctly.
- Also fixed two **pre-existing, unrelated** test bugs surfaced while
  working in this file (confirmed failing identically on `main` before this
  patch, via `git stash` + isolated run):
  - `test_4_rolling_metrics_compute_correct_pf_and_expectancy`: all 5
    trades shared `trade_id="t1"`, so the P0.2 persistent trade_id dedupe
    guard (which runs before the rolling-window append) silently discarded
    closes 2-5 — only 1 of 5 trades was ever actually recorded. Gave each
    trade a unique id.
  - New test's own first draft copied an existing-test typo
    (`learner._STATE_FILE = ...`, uppercase, a no-op — the real attribute
    is `self._state_file`, lowercase) from `test_17`; fixed in the new test
    only (didn't touch `test_16`/`test_17`/`test_18`, which "pass" today
    for an unrelated reason — all instances in those tests share the same
    fixture-provided module-level `_STATE_FILE`, so the typo'd per-instance
    assignment is harmless dead code there, not a real bug worth touching
    in this narrow patch).

42/42 tests in the file pass after both the feature fix and the two
unrelated fixes.

## Impact on this session's WR>55%/high-P&L monitoring

The `lifetime_pf`/`lifetime_expectancy` readings logged in cycles 49-59 of
`_workspace/monitoring_progress.json` should be read with this in mind:
they were a same-magnitude-as-`rolling100` noisy statistic mislabeled as a
~4000-trade average, not a true signal either way. `recent-100
win_rate_pct` (a different, honestly-labeled dashboard field) remains the
more reliable short-window indicator used throughout this session; once
this fix is deployed, `lifetime_pf`/`lifetime_expectancy` become trustworthy
for judging true long-run progress toward the goal for the first time this
session.
