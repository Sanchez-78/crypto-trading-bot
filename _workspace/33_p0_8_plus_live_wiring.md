# P0.8+ live wiring glue — patch for orchestrator review

**Date:** 2026-08-17
**Trigger:** Operator directive "zapoj wiring glue přes orchestrator a pak
monitoring a nasazovani dalsich fazi" (wire the glue via the orchestrator,
then monitoring and deploying further phases), following the document
status report that identified this as the biggest remaining lever
(`_workspace/18_live_wiring_plan.md`'s deliberately-stopped-short plan).

## What changed

1. **New file** `src/services/p0_8_plus_live_pipeline.py`: reuses
   `p0_8_plus_shadow_evaluator.evaluate_symbol()` verbatim (candle fetch,
   regime classify, candidate generation, `signal_router.
   evaluate_signal_for_paper_entry()`), and for each `admitted=True`
   candidate backed by a REAL (not synthetic) quote, calls
   `open_paper_position()`. Gated by `PAPER_P0_8_PLUS_LIVE_ENABLED`,
   **default "false"** (opt-in, unlike the shadow evaluator's opt-out
   default — this thread can spend paper capital).
2. **`bot2/main.py`**: added the matching daemon-thread startup call site
   (mirrors the existing shadow-evaluator call site immediately above it).
3. **`src/services/paper_trade_executor.py`**: one-line narrow exemption —
   the pre-existing weak-EV floor (`_MIN_EV_THRESHOLD=0.01`, previously
   exempting only `PAPER_STARVATION_DISCOVERY`) now also exempts the new
   `P0_8_PLUS_EVIDENCE_COLLECTION` bucket, because that bucket's `ev` field
   is a bps→fraction conversion of an already-validated
   `net_expected_edge_bps` (a different scale than this floor assumes),
   not an unvetted zero/negative-EV admission.

## Safety architecture — nothing new invented, everything inherited

Does **not** flip `evidence_only` on any of the three strategy
registrations (stays `True`, per each `strategy_*.py`'s own §2.4 design).
The admission path used is the pre-existing `P0_ADMIT_EVIDENCE_COLLECTION`
code in `signal_router.py`, already reviewed and deployed under commit
`d4d69ee`+ — this patch is the first *caller* that acts on that decision,
not a new decision path.

Every gate a position must pass, in order, none reimplemented:

1. `cost_model.evaluate_edge()` — net-edge-positive requirement (bps scale)
2. `P0SegmentEVGate.is_quarantined_for_strict_ev` / `is_eligible_for_evidence_collection`
   — same class + same `EVIDENCE_COLLECTION_REGIMES = {"BULL_TREND", "BEAR_TREND"}`
   constant the legacy signal path already uses. **Known, disclosed
   consequence:** `sideways_mean_reversion_v1` and `volatility_breakout_v1`
   candidates will typically evaluate `admitted=False` while the market is
   in `SIDEWAYS`/`VOLATILE` regime (confirmed live smoke test,
   `_workspace/18`: "all three symbols currently SIDEWAYS"). Only
   `trend_cost_aware_v1` in `BULL_TREND`/`BEAR_TREND` can realistically get
   admitted right now. Widening `EVIDENCE_COLLECTION_REGIMES` is a
   **separate**, wider-blast-radius decision (it also affects the legacy
   signal path) intentionally NOT bundled into this patch.
3. `p0_risk_guard_v1.evaluate_risk_guard()` — daily-DD / quota-health /
   position-conflict / real-order-config check
4. `_check_exploration_exposure_caps()` — max 1 open position per symbol
   (across ALL exploration buckets, shared with the legacy discovery
   mechanism), max 2 per bucket, max 1 per symbol+bucket — applies
   automatically because every position sets `extra["explore_bucket"] =
   "P0_8_PLUS_EVIDENCE_COLLECTION"`
5. `_min_valid_tp_bps()` cost-floor clamp on the `extra["tp_from_executor"]`
   path (2026-08-14 fix, still active)
6. P0.3F fail-closed metadata guard — `learning_source`/`strict_ev`/
   `readiness_eligible` must be present or the entry is blocked outright;
   this patch sets all three explicitly from the already-computed
   `SignalEvaluation`

**Real-price requirement:** only opens when `quote_source == "live"`
(`live_quote_cache_v1`, a real event_bus-subscribed bid/ask) — a candle-
close synthetic approximation is logged by the shadow evaluator but never
used to actually commit paper capital here.

## What is NOT wired (disclosed gaps)

- `dynamic_trend_exit_v1.py` (P1.0) still has zero call sites anywhere —
  positions this patch opens exit through the same existing generic
  TP/SL/timeout machinery every other paper position uses (seeded with the
  strategy's own `initial_stop_price`/`target_reference_price` where
  present via `tp_from_executor`/`sl_from_executor`).
- `EVIDENCE_COLLECTION_REGIMES` widening (would unblock 2 of 3 strategies)
  — separate future decision.

## Evidence bar before flipping `PAPER_P0_8_PLUS_LIVE_ENABLED=true`

Live journalctl check at authoring time (48h window, only ~12 minutes of
actual process uptime visible due to a recent restart): **zero admitted
candidates observed, zero non-zero-candidate ticks** — consistent with the
weeks-long pattern already documented in the shadow evaluator's own
history (selective strategy thresholds + narrow regime scope). This means
even once enabled, the pipeline may open nothing for a while — that is
expected, not a bug, and is itself evidence to watch for (see below).

## Tests

`tests/test_p0_8_plus_live_pipeline.py` (new, 16 tests): signal/extra
mapping (P0 metadata fields, side normalization, bps→fraction ev
conversion, distinct bucket naming, TP/SL passthrough), `run_live_tick`
(opens only for admitted+live-quote, skips non-admitted, skips synthetic
quote even if admitted, survives exceptions in either
`evaluate_symbol`/`open_paper_position`, does not count a `blocked` result
as opened, evaluates every requested symbol), and the disabled-by-default
thread gating (3 tests).

`tests/test_paper_mode.py` (+2 tests): weak-EV floor exemption for the new
bucket (positive case) and a negative-control test pinning that an
unrecognized bucket name is still blocked (guards against the exemption
silently becoming a blanket bypass later).

**Regression sweep:** `test_paper_mode.py` + `test_p0_8_plus_shadow_evaluator.py`
+ `test_p0_8_plus_shadow_evaluator_bypass.py` + `test_signal_router_bypass.py`:
253 passed, 1 failed (pre-existing, local-`.env`-only,
`test_strict_take_disabled_for_training` — documented repeatedly this
session, unrelated to this patch), 4 skipped. `py_compile` clean on all
three changed/new files.

## trading-safety-agent verdict (2026-08-17): APPROVED_WITH_CONDITIONS

- Confirmed zero real-money exposure path; risk guard actively refuses if
  `live_trading_allowed_fn()` is ever true (`p0_risk_guard_v1.py:61-72`),
  fail-closed on exception.
- Confirmed caps/risk-guard/cost-floor all genuinely apply (tighter than
  first described: `_check_position_conflict` blocks on ANY open position
  for a symbol, same or opposite side, before the exploration-bucket caps
  even run).
- Confirmed weak-EV exemption is a narrow 2-name allowlist, not a bypass;
  confirmed P0.3F metadata guard is satisfiable and non-bypassable (all
  three strategies register `evidence_only=True`, so strict_ev/readiness
  are structurally always False -- no escalation path exists).
- **Real finding (FIXED, see below):** the entry price booked was always
  `r.signal.reference_price` (candle close), even when `quote_source ==
  "live"` -- the "live" gate only governed the cost-model inputs, not the
  actual fill price. Not a real-money risk (still a real traded price,
  satisfies open_paper_position()'s own requirement), but it bit into the
  evidence-quality goal this whole pipeline exists for.
- **Fix applied same session:** `run_live_tick()` now re-fetches the live
  quote via `live_quote_cache_v1.get_last_quote()` and books the fill at
  the correctly-crossed side (ask for BUY, bid for SELL), failing closed
  (skip, not fallback-to-candle-close) if the quote aged out between
  `evaluate_symbol()`'s check and the open call. 4 new tests added
  (`test_run_live_tick_books_buy_at_ask_not_candle_close`,
  `..._sell_at_bid...`, `..._skips_when_live_quote_aged_out...`, plus the
  existing tests updated to mock the new quote fetch) -- 19/19 pass.
- **Recommendation, independently reasoned:** `PAPER_P0_8_PLUS_LIVE_ENABLED`
  should ship **false** in code (kept as-is) and be enabled only via the
  systemd overlay -- decouples "is this code deployed" from "is this
  trading," reversible in seconds without a redeploy.
- **Tooling caveat raised:** the agent's own Bash tool briefly served a
  stale pre-patch filesystem snapshot in its environment (self-caught,
  re-verified via PowerShell/Read) and asked that the "253 passed" sweep
  be independently re-run. Done: re-ran the full sweep via PowerShell
  (a genuinely separate tool/process from this session's Bash) --
  `270 passed, 3 failed` (`test_p0_8_plus_live_pipeline.py` +
  `test_paper_mode.py` + shadow evaluator + bypass suites combined; the
  live-pipeline file alone is 19/19). The 3 failures
  (`test_strict_take_disabled_for_training`,
  `test_audit_script_syntax_valid`, `test_sampler_state_check_script_syntax_valid`)
  confirmed pre-existing via `git stash` on the same PowerShell session --
  identical with the patch stashed away, unrelated to this change (the
  first is the session's long-documented local-`.env`-only issue; the
  latter two are script-syntax checks unrelated to this patch's files).

## reviewer-agent verdict (2026-08-17): APPROVED_WITH_CONDITIONS, all 9 conditions addressed

Full adversarial checklist run against the actual code (not the doc's
claims). Summary of fixes applied in response, in the reviewer's own
numbering:

- **C1 (BLOCKS ENABLING, now fixed):** `PAPER_SYMBOL_BLACKLIST`
  (`systemd/99-cryptomaster-managed-runtime.conf`) was enforced only in
  `signal_generator.py:694`, upstream of `open_paper_position()` --
  meaning BNBUSDT/XRPUSDT/DOTUSDT (blacklisted for documented anti-edge)
  were tradeable through this new direct-call pipeline. Fixed at the
  choke: `open_paper_position()` itself now checks the blacklist first,
  same pattern as the existing `PAPER_DATA_COLLECTION_ONLY` gate --
  closes this for every current AND future caller, not just this one.
- **C2 (fixed):** `run_live_tick()` now calls
  `live_quote_cache_v1.ensure_subscribed()` itself rather than silently
  depending on the shadow thread staying enabled.
- **C3 (fixed):** TP/SL geometry is now re-anchored to the actually-booked
  live price (offset from the strategy's own reference_price reapplied to
  the booked price), not passed through as raw absolute prices computed
  against a different (candle-close) reference.
  **Bonus discovery while integration-testing this fix:** in the current
  deployment, `PAPER_TP_ZONE_BPS`/`PAPER_SL_ZONE_BPS` are set (`.env`,
  35/25bps), and `paper_trade_executor.py`'s env-override block
  unconditionally supersedes `tp_from_executor`/`sl_from_executor`
  regardless of source -- pre-existing behavior (shared with every other
  caller of that path, already flagged by that block's own 2026-08-14
  comment), not introduced by this patch. Net effect: this pipeline's
  strategy-specific TP/SL currently has NO effect on the stored position
  -- every P0.8+ position gets the same global band as everything else.
  The C3 fix is still correct and is the thing that becomes load-bearing
  the day that env var is ever removed. Pinned by two new tests.
- **C4 (fixed):** corrected the docstring/doc's false claim that
  BULL_TREND and BEAR_TREND were both in evidence-collection scope.
  Verified against `p0_segment_ev_gate.py`: `is_quarantined_for_strict_ev`
  runs BEFORE the evidence-collection check and unconditionally rejects
  `QUARANTINED_REGIMES={"BEAR_TREND"}` ("paper trading is long-only") and
  `QUARANTINED_SYMBOLS={"BTCUSDT","SOLUSDT"}`. Real scope: BULL_TREND
  only, never BTC/SOL.
- **C5 (fixed):** `p0_gate_reason` moved from `extra` to `signal_dict` --
  `open_paper_position()` reads it from `signal`, not `extra`; it was
  silently always `None` before.
- **C6 (disclosed, not "fixed" -- inherent to reused legacy machinery):**
  `open_paper_position()`'s own internal P0.3B/P0.3C gate re-decides
  admission using a different segment-key shape and always finds
  `reject_p0=True` for a brand-new evidence-only strategy (no history
  under that shape), which unconditionally overwrites `learning_source`,
  `p0_gate_reason`, `segment_key`, and `extra["paper_source"]` on the way
  to storage. Confirmed empirically via the new integration test.
  `explore_bucket`/`training_bucket` (BUCKET) survive untouched and are
  documented as the reliable attribution field. `_map_to_legacy_signal`'s
  docstring and the mapping-output test now both disclose this explicitly.
- **C7 (disclosed):** documented why every position sizes at the smallest
  0.3x multiplier (`_calculate_dynamic_position_size` branches on the
  bps->fraction-converted `ev`, which is always well under its 0.03
  floor at realistic edge magnitudes) -- conservative, not unsafe,
  now stated as a deliberate/known consequence rather than an
  undisclosed side effect.
- **C8 (fixed):** added an integration test running real (unmocked)
  `open_paper_position()` against `_map_to_legacy_signal`'s output --
  this is what surfaced C5's dict-placement bug and empirically confirmed
  C6's attribution overwrite and the TP/SL env-override discovery above.
- **C9 (fixed):** `test_pipeline_thread_starts_when_enabled` now
  synchronizes on a `threading.Event` set from inside the mock, closing
  the race where the real (unmocked) `run_live_tick` could execute in the
  background thread if the patch context exited before the first tick.
- Also fixed a fixture drift the reviewer noted in passing:
  `exit_profile="trend_default"` in the test fixture didn't match
  production's actual `EXIT_PROFILE="dynamic_trend_exit_v1"`.

Checklist items that PASSED outright (no fix needed): #2 double-gating
(Gate A strictly narrower than Gate B, no contradiction possible), #3
exception/failure modes (no crash path, no `_POSITIONS` corruption), #6
weak-EV exemption (narrow, no collision).

**Test count:** `tests/test_p0_8_plus_live_pipeline.py` grew from 16 to
23 tests. Full regression sweep (both Bash and PowerShell, cross-checked
per the safety-agent's tooling caveat): 302 passed, 4 failed, all 4
confirmed pre-existing via `git stash` (the 3 from before, plus
`test_blacklist_validator_rejects_injection_on_every_action` -- an
unrelated deploy-script CLI-action validator, not the PAPER_SYMBOL_
BLACKLIST this patch touches; identical failure with this patch fully
stashed away).

**Reviewer's bottom line:** "your price fix closed the one issue that
made this unshippable. C1 is now the only thing between this and a green
light to enable." C1 is now fixed too.

## reviewer-agent final verdict (2026-08-17): APPROVED

Independently re-verified all 9 fixes against the actual code (not the
summary). All confirmed correct. Ran the suites itself: 238 passed, 1
failed (the known pre-existing local-`.env` case), 4 skipped.

**One factual correction resolved (SSH-verified, not assumed either way):**
the reviewer hypothesized the C3 "inert in production" conclusion was
backwards -- `.env` is gitignored and the systemd overlay deliberately
removed `PAPER_TP_ZONE_BPS`/`PAPER_SL_ZONE_BPS` on 2026-08-10, so the
reviewer's hypothesis was that the var is likely *unset* on the server,
making `tp_from_executor` load-bearing there right now. Checked directly
via SSH: `/opt/cryptomaster/.env` (dated 2026-07-29, present on the
server, outside git) DOES set `PAPER_TP_ZONE_BPS=35`/`PAPER_SL_ZONE_BPS=25`,
and `systemctl show cryptomaster -p Environment` confirms systemd itself
sets neither var (matching the reviewer's read of the overlay) --
`load_dotenv(override=False)` therefore fills them in from that real file
at process start. **Original conclusion confirmed correct as written:**
the env-override path IS active in production too, so this patch's C3
re-anchoring fix is presently inert there, exactly as in the local test
environment -- not backwards. Both states are pinned by the two tests
regardless of which is true, so no code changed; this only corrects the
doc's own factual claim (which, on verification, needed no correction).

**Two nits applied:**
1. `_map_to_legacy_signal`'s docstring corrected: "absolute-price offset"
   (matches the code), not "bps offset".
2. `.strip()` added to both `PAPER_SYMBOL_BLACKLIST` enforcement sites
   (`paper_trade_executor.py`'s new choke AND `signal_generator.py:694`,
   kept in lockstep) so a spaced list value (`"BNBUSDT, XRPUSDT"`) can't
   silently fail to match the second entry.

Full regression re-run after these three touch-ups: 238 passed, 1 failed
(same pre-existing case), 4 skipped -- clean.

## test-regression-agent: did not complete (infrastructure failure, not a code finding)

Hit the account's monthly spend limit mid-task (`idleReason: "failed"`,
`failureReason: "You've hit your monthly spend limit"`) -- an external
billing condition, not a rejection or a finding against this patch.

**Decision: proceeding without its formal sign-off**, on the basis that
its core mandate (regression validation) was independently, substantively
covered by the other two agents and by this session's own repeated
verification, not merely asserted:

- `reviewer-agent` ran the suite itself as part of its own independent
  verification (not trusting the patch author's numbers) and got the
  identical result: "238 passed, 1 failed ... 4 skipped" -- the one
  failure being the same known pre-existing local-`.env` case.
- This session independently ran the full sweep via TWO separate tool
  paths (Bash and PowerShell) at multiple points during the patch, and
  used `git stash` to confirm every failure encountered (4 distinct ones
  across the whole process) was pre-existing and unrelated, not a
  regression from this patch.
- `trading-safety-agent` separately flagged and got a real cross-tool
  discrepancy resolved earlier in this same process (its own Bash tool
  briefly served a stale snapshot) -- precisely the class of problem
  test-regression-agent exists to catch -- and that was independently
  re-verified via PowerShell at the time, not glossed over.

This is a judgment call under an external constraint, not a claim that a
third redundant test run was unnecessary in principle -- if the account's
spend limit resets and a true test-regression-agent pass becomes cheap
again, re-running it against the final diff would still be good hygiene,
just not treated as blocking given the above.

## FINAL DECISION

- **Verdicts:** trading-safety-agent APPROVED_WITH_CONDITIONS (conditions
  met), reviewer-agent APPROVED, test-regression-agent did not complete
  (external billing failure, mandate independently covered as above).
- **Deploy:** commit and push with `PAPER_P0_8_PLUS_LIVE_ENABLED` staying
  its coded default of `false` (safe, opt-in) -- verify the deploy and
  service health first.
- **Enabling live opens:** a deliberate, separate follow-up step (systemd
  overlay, not a code change), per trading-safety-agent's explicit
  recommendation, with the 24h close-monitoring condition it attached.
  Not bundled into the same action as the initial deploy -- consistent
  with this whole session's "small gated phases" discipline.

## Open question for review: should `PAPER_P0_8_PLUS_LIVE_ENABLED` ship `true` or `false`?

Shipping this deliberately defaults to `false` (opt-in). Recommendation to
the reviewing agents: given (a) the exhaustive inherited safety net above,
(b) the hard 1-open-per-symbol-across-all-exploration-buckets cap, (c) the
paper-only (not real) capital at stake, and (d) the zero-candidates-so-far
evidence meaning it likely won't even fire immediately — flipping to
`true` post-approval is low-risk and is how evidence will actually start
accumulating. But this is exactly the kind of call the trading-safety-agent
and reviewer-agent exist to make independently, not something the patch
author should decide unilaterally. Final default in the deployed systemd
overlay/commit will follow their verdict.
