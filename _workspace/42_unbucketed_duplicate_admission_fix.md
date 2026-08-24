# 42 — Unbucketed P0_GATE duplicate admission fix (P1.1AW, cycle 110)

## Status: FIXED, REVIEWED (APPROVED WITH CONDITIONS + PASS), NOT YET DEPLOYED.

## Recap: what cycle 109 left open

Cycle 109 (commit `b921d54`, P1.1AV) fixed duplicate admission for
**bucketed** candidates (e.g. `training_bucket="A_STRICT_TAKE"`). Post-deploy
live verification found duplicates STILL occurring on a separate,
**unbucketed** admission path (`training_bucket=None` AND
`explore_bucket=None`), which P1.1AV never touched by design — see
`_workspace/41_duplicate_trades_p1_1av_fix.md`.

## Root cause (this cycle's forensics)

1. `_check_exploration_exposure_caps()` returns `None` immediately for a
   falsy bucket (`if not bucket: return None`) — correct behavior for its
   actual contract (exploration-bucket exposure caps), but it means
   unbucketed candidates get ZERO admission-time deduplication from it.
2. `paper_training_sampler.py` has its own dedicated dedupe mechanism
   (`_recent_dedupe`/`_recent_dup_candidate`, P1.1N) but it lives entirely
   inside `maybe_open_training_sample()`. The unbucketed path never calls
   that function.
3. The unbucketed path is `_on_signal_created()` (`paper_trade_executor.py`),
   subscribed to the `signal_created` event, which calls
   `open_paper_position(signal, price, ts, reason="P0_GATE",
   extra={"p0_decision": decision.reason})` — no bucket keys at all.
4. `signal_generator.py`'s `on_price()` publishes a fresh `signal_created`
   event on EVERY qualifying tick, unconditionally, with no debounce. When
   ticks for a symbol arrive in a sub-second burst and the underlying
   signal decision hasn't changed, each publish independently triggers
   `_on_signal_created()` → `open_paper_position()`. With bucket=None the
   only remaining guard is the generous per-symbol `_SYMBOL_CAPS` default
   (e.g. `ETHUSDT=10`).

Live evidence (`cache.sqlite`, 24h window post-P1.1AV-deploy): 15 tight
duplicate clusters (entries within 10s, price within 0.15%), worst case 4
near-identical ETHUSDT positions within 0.9 seconds. Nearly all
`training_bucket=None AND explore_bucket=None` — the bucketed A_STRICT_TAKE
path stayed clean, confirming P1.1AV holds.

`reviewer-agent` independently corroborated this from the same data with a
different method (consecutive same-`(symbol,side)` entry-gap distribution
split by `paper_source`): `paper_evidence_collection` (the P0_GATE path's
persisted attribution) → 54/56 gaps <1s; `normal_rde_take` → zero gaps <1s.

## The fix (P1.1AW)

Added `_UNBUCKETED_LAST_ADMISSION` (module-level dict, key `(symbol, side)`
→ last admission timestamp) and `_UNBUCKETED_ADMISSION_COOLDOWN_S`
(env-configurable via `PAPER_UNBUCKETED_ADMISSION_COOLDOWN_S`, default
5.0s). Inside `open_paper_position()`'s existing atomic `with
_POSITION_LOCK:` block (the same lock P1.1AU/P1.1AV added last cycle),
added a check gated on `if not bucket and reason == "P0_GATE":` — blocks
with `{"status": "blocked", "reason": "unbucketed_admission_cooldown"}` if
within the cooldown window.

**Scoping decision**: the guard is scoped to `reason == "P0_GATE"`
specifically, NOT `if not bucket:` alone. A broader version was tried first
and reverted after it regressed 13 pre-existing tests that legitimately
call `open_paper_position(..., "RDE_TAKE")` (default reason, no bucket)
multiple times in quick succession for the same symbol within a single test
(e.g. `test_open_paper_position_respects_max_open` deliberately fills
`_MAX_OPEN` slots on one symbol). `reviewer-agent` independently verified
this scoping against all 9 real call sites of `open_paper_position(` in the
codebase and confirmed every other caller either always sets a bucket
(RDE, P0.8+ pipeline, paper_exploration, the P0.3C reroute) or routes
through `maybe_open_training_sample()` (which owns its own P1.1N dedupe) —
`reason=="P0_GATE"` is the sole precondition-matching gap.

## Review

- `reviewer-agent`: **APPROVED WITH CONDITIONS**. Verified the `P0_GATE`
  scoping independently against all call sites plus live `cache.sqlite`
  gap-distribution data. Conditions:
  - **C1 (must, before commit)**: stage exactly the two reviewed files —
    working tree also carries unrelated concurrent SEC-01
    dashboard/auth/systemd changes from other sessions. **Applied.**
  - **C2 (must, before deploy)**: `_on_signal_created()` was logging
    unconditional `[SIGNAL_OPENED] ... SUCCESS` even when
    `open_paper_position()` returned `status="blocked"` — with
    `[PAPER_ENTRY_BLOCKED_RACE]` throttled to once/60s, this made it
    impossible to verify from journalctl whether P1.1AW (or any admission
    guard) was actually firing post-deploy. **Applied**: now branches on
    `result.get("status")`, logs `[SIGNAL_BLOCKED] ... status=... reason=...`
    when not opened.
  - **C3 (must, this commit)**: `_UNBUCKETED_LAST_ADMISSION` was cleared by
    nothing (`reset_paper_positions()` only cleared `_POSITIONS`) — leaked
    across tests. **Applied**: added to `reset_paper_positions()`.
  - **C4 (should)**: the cooldown timestamp was stamped as soon as the
    cooldown check itself passed, BEFORE the later symbol-cap/max-open
    checks — so a candidate rejected by one of THOSE unrelated caps would
    still burn the cooldown window for a position that never opened.
    **Applied**: moved the stamp to immediately before the actual
    `_POSITIONS[trade_id] = position` insert, so it only fires on genuine
    admission. New regression test
    `test_unbucketed_admission_cooldown_not_stamped_on_unrelated_block`
    (mutation-killed — required simulating the race via the same
    `_check_exploration_exposure_caps` two-call side-effect technique
    `test_toctou_race_blocked_by_atomic_recheck` uses, since a naive
    `_SYMBOL_CAPS` override triggers a separate, earlier non-atomic
    symbol-cap check at ~line 1859 instead of reaching this code at all).
  - C5 (post-deploy, 24h): count `unbucketed_admission_cooldown` blocks,
    re-run the duplicate-cluster query; if total P0_GATE volume drops
    materially more than expected, consider lowering the cooldown to 2.0s
    (needs a restart, read at import).
  - C6 (optional nits): not applied (test `extra={}` vs production's
    `extra={"p0_decision": ...}` doesn't affect the guard; one negative
    control uses a different symbol rather than same-symbol — both flagged
    as non-blocking, left as-is to keep the diff narrow).
- `trading-safety-agent`: **PASS**. Paper-only scope confirmed (zero
  deletions in either file — 181 insertions, structurally cannot weaken any
  existing gate); fail-closed confirmed (no exception path exists in the
  new code — `dict.get` and float arithmetic cannot raise; if it somehow
  did, it propagates while still holding `_POSITION_LOCK`, before the
  insert); unbounded-dict concern assessed as NOT a real operational risk
  (cardinality bounded by `|symbols| × |sides|`, same unpruned pattern as
  the pre-existing, larger-cardinality `_PAPER_ENTRY_BLOCKED_THROTTLE`);
  directionally-restrictive-only confirmed by reading (only two outcomes:
  block, or fall through unchanged to pre-existing checks). Also flagged
  the same C1 (path-scoped commit) and C4 (stamp-before-check) findings
  independently, corroborating reviewer-agent.

## Tests

`tests/test_paper_mode.py`, class `TestPaperExecutorBasics`:
- `test_unbucketed_admission_cooldown_blocks_rapid_duplicate` — reproduces
  the live pattern (`reason="P0_GATE"`, `extra={}`, same symbol+side twice).
- `test_unbucketed_admission_cooldown_allows_different_symbol` — negative
  control.
- `test_unbucketed_admission_cooldown_allows_opposite_side` — negative
  control.
- `test_unbucketed_admission_cooldown_allows_after_expiry` — cooldown
  expiry works correctly.
- `test_unbucketed_admission_cooldown_not_stamped_on_unrelated_block` (C4
  regression) — a candidate rejected by the unrelated atomic max-open check
  must not stamp the cooldown.
- `test_unbucketed_admission_cooldown_does_not_affect_bucketed_candidates`
  — negative control (bucketed RDE_TAKE candidate unaffected).

All 6 mutation-killed via `git stash`/targeted revert-and-restore against
pre-fix baseline. Full regression sweep (`test_paper_mode.py` full file +
8 other files known to touch this module): 309 passed, 1 failed (same
pre-existing, unrelated local-`.env` contamination as cycle 109:
`test_strict_take_disabled_for_training`), 4 skipped.

## Deploy and live verification (DONE)

Deployed via gated `hetzner-deploy-apply.yml` (PLAN run 32702136941 → DEPLOY
run 32702196387, both green). Live SHA pinned to `3a294cd` (the docs-only
commit directly on top of `5b22812` — code-identical, keeps the server in
sync with `origin/main` HEAD). Service active, 0 restarts, dashboard
restarted cleanly, real-trading gate (Gate 2) confirmed still PAPER-only.

**Sanity check 1 (admission not stalled): PASS, throughput went UP.** 6×
`[PAPER_ENTRY]` in ~20 min post-restart (3 via `reason=P0_GATE`) vs only 3
total in the 2h pre-deploy window on `b921d54`. No stall.

**Sanity check 2 (cooldown live-active): PASS, direct proof.** A duplicate
0.27s behind a genuine admission was blocked:
```
07:38:22 [PAPER_ENTRY] symbol=ETHUSDT side=BUY ... reason=P0_GATE
07:38:22 [PAPER_ENTRY_BLOCKED_RACE] trade_id=paper_4958ba1f780a symbol=ETHUSDT side=BUY reason=unbucketed_admission_cooldown elapsed=0.27s cooldown=5.0s
```
Exactly the sub-second burst class the patch targets.

**Sanity check 3 (C2 log-observability fix): PASS, and it immediately
surfaced a much bigger pre-existing truth gap.** Pre-deploy, the old
unconditional `[SIGNAL_OPENED] ... SUCCESS` log fired 1231× in 2h against
only 3 real `[PAPER_ENTRY]` — ~99.8% false. Post-deploy the honest
`[SIGNAL_BLOCKED]` breakdown is now visible: `bootstrap_open` 1619,
`buy_enforcement` 1552, `max_open_per_symbol` 805 (this is cycle 109's
P1.1AV fix visibly firing too), `allowed_for_evidence_collection` 798,
`regime_quarantined_p0` 610, `edge_generation_failed` 389,
`symbol_quarantined_p0` 196, plus
`p0_gate:regime_not_in_evidence_scope:QUIET_RANGE`.

### Known limitation surfaced live (not a bug, by design)

The 5.0s window does not cover wider-spaced repeats: at 07:38:22 and again
at 07:38:30 (8s apart, outside the cooldown), two ETHUSDT BUY
`reason=P0_GATE` positions both admitted and are both currently open
concurrently. This is correct behavior for a 5.0s window, not a defect —
but if the eventual goal is "no near-identical unbucketed duplicates at
all" rather than specifically "no sub-second burst", 5.0s may be too
short. Tunable via `PAPER_UNBUCKETED_ADMISSION_COOLDOWN_S` (requires a
restart, read at import) without a code change. Watch the duplicate-
cluster query over the next 24h (per reviewer's C5) to decide whether
widening is warranted — do not change blind.

### Unrelated, incidentally fixed by the restart

The old process had been emitting `[CRITICAL] DASHBOARD_ZERO: Dashboard
stale: 2882s without update` for ~48 min before this deploy — the known,
previously-documented dashboard-freeze gap (see CLAUDE.md's "KNOWN GAP
(found 2026-08-06)" section and `_workspace/05_dashboard_staleness_intake.md`).
The deploy workflow's best-effort `cryptomaster-dashboard` restart cleared
it as a side effect (0 `DASHBOARD_ZERO` since). Not caused by, and not a
target of, this cycle's fix — noted here only because it happened to
surface during this deploy's health check.

## Next cycle candidates

- Watch the 24h duplicate-cluster query (per C5) to decide if the 5.0s
  window needs widening given the confirmed 8s-apart concurrent-open case
  above.
- The dashboard-freeze recurrence is a known, unresolved gap (not root-
  caused) — still just mitigated by best-effort restart-on-deploy, per
  CLAUDE.md. Not this cycle's scope, but worth a dedicated cycle eventually.
