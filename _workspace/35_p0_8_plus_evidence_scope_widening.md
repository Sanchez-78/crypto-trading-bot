# P0.8+ evidence-collection scope widening (sideways_mean_reversion_v1 / volatility_breakout_v1 unblocked)

**Date:** 2026-08-18
**Trigger:** Operator directive "jdi do toho, zaciname bodem 1" (go ahead,
starting with item 1) from a prioritized list of next steps, following
the document-status report flagging this as the single item most likely
to actually start evidence flowing (0 admitted candidates observed across
~24h of the live pipeline running).

## Root cause (confirmed via code, not assumption)

`P0SegmentEVGate` (`p0_segment_ev_gate.py`), shared by both the legacy
signal path and the new P0.8+ pipeline's `signal_router.py`:
- `EVIDENCE_COLLECTION_REGIMES = {"BULL_TREND", "BEAR_TREND"}` — no
  SIDEWAYS/VOLATILE, ever.
- `QUARANTINED_REGIMES = {"BEAR_TREND"}` (comment: "paper trading is
  long-only") and `QUARANTINED_SYMBOLS = {"BTCUSDT", "SOLUSDT"}`.

Checked against each strategy's own registered scope
(`build_registration().allowed_regimes`):
- `sideways_mean_reversion_v1`: `ALLOWED_REGIMES = {"SIDEWAYS"}` —
  **structurally excluded** by the shared gate, 100% of the time.
- `volatility_breakout_v1`: `ALLOWED_REGIMES = {"SIDEWAYS", "VOLATILE"}`
  — same, 100% excluded.
- `trend_cost_aware_v1`: `ALLOWED_LONG_REGIMES` (BULL_TREND) +
  `ALLOWED_SHORT_REGIMES = {"BEAR_TREND"}` — the strategy itself
  explicitly supports SHORT entries in BEAR_TREND via a dedicated
  `short_candidate()` path (confirmed by reading the strategy source,
  not assumed), directly contradicting the shared gate's "paper trading
  is long-only" premise for the BEAR_TREND quarantine. Also blocked
  outright for BTCUSDT/SOLUSDT regardless of regime.

So of the 3 registered strategies, only `trend_cost_aware_v1` in
BULL_TREND on non-BTC/SOL symbols could ever realistically get
`admitted=True` before this fix — matching the observed 0-candidates
history.

## Fix — narrowly scoped, does not touch the legacy signal path

1. **`signal_router.py`**: `evaluate_signal_for_paper_entry()` gained two
   new optional, injectable params — `quarantine_fn`/
   `evidence_eligibility_fn` — defaulting to
   `P0SegmentEVGate.is_quarantined_for_strict_ev`/
   `is_eligible_for_evidence_collection` (zero behavior change for any
   caller that doesn't specify them). Same dependency-injection pattern
   already used for `risk_guard_fn`.
2. **`p0_8_plus_shadow_evaluator.py`**: two new functions,
   `_p0_8_plus_quarantine_fn`/`_p0_8_plus_evidence_eligibility_fn` — never
   quarantine, allow evidence collection for any of the 4 known
   `regime_classifier_v1.py` regimes (`BULL_TREND`/`BEAR_TREND`/
   `SIDEWAYS`/`VOLATILE`), fail closed (quarantine + reject) on an
   unrecognized regime string. Wired into `evaluate_symbol()`'s call to
   the router — shared by BOTH the shadow evaluator and the live pipeline
   (which reuses `evaluate_symbol()` verbatim), so both benefit
   identically.
3. **`paper_trade_executor.py`**: `_can_admit_paper_evidence_collection()`
   gained a `bucket` kwarg. When `bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"`,
   it also allows all 4 known regimes instead of the legacy
   `EVIDENCE_REGIMES = {"BULL_TREND", "BEAR_TREND"}` — this was necessary
   because `open_paper_position()`'s own internal P0.3C reroute
   *independently* re-checks this same legacy constant on every P0.8+
   position (confirmed structurally always triggered, per
   `_workspace/33`'s finding), so widening only `signal_router.py` would
   have been silently re-blocked one layer downstream.

**Why not just widen the shared `P0SegmentEVGate`/`_can_admit_paper_
evidence_collection` constants directly?** That would also change the
LEGACY signal path's behavior — a separate, wider-blast-radius decision
explicitly out of scope (flagged already in `_workspace/33`). Every
change here is either an injectable override (opt-in, default unchanged)
or scoped to the literal `"P0_8_PLUS_EVIDENCE_COLLECTION"` bucket string.

## What is still unaffected (by design)

- Each strategy's own `allowed_symbols`/`allowed_regimes`
  (`StrategyRegistration`, checked FIRST in `signal_router.py` step 1-2)
  remains the primary per-strategy boundary — this fix only removes a
  *redundant, more restrictive* second gate layered on top of it, not the
  boundary itself.
- Cost/edge gate (`cost_model.evaluate_edge()`), risk guard
  (`p0_risk_guard_v1.py`), exploration exposure caps, cost-floor TP/SL
  clamp, symbol blacklist choke (`_workspace/33`'s C1 fix) — none touched,
  all still apply to every candidate regardless of regime.
- BTCUSDT/SOLUSDT symbol quarantine is now lifted for the P0.8+ pipeline
  specifically (via the same `_p0_8_plus_quarantine_fn` override) — no
  documented rationale was found tying that quarantine to the new
  pipeline specifically (unlike the "long-only" BEAR_TREND rationale,
  which is explicitly falsified for `trend_cost_aware_v1`), and each
  strategy's own registration (`ensure_registered()`, currently the full
  7-symbol deployment list) is the actual per-strategy symbol boundary.

## Tests

- `tests/test_signal_router.py` (+3): custom `quarantine_fn` lets a
  normally-quarantined symbol through; custom `evidence_eligibility_fn`
  admits a normally-ineligible regime (SIDEWAYS); negative control
  confirming the *default* (unchanged) behavior still rejects SIDEWAYS.
- `tests/test_p0_8_plus_shadow_evaluator.py` (+5): both new functions
  allow all 4 known regimes / fail-closed on an unknown one; a wiring
  test (via a spy on `signal_router.evaluate_signal_for_paper_entry`)
  confirms `evaluate_symbol()` actually passes the two override functions
  through by identity, not just that correct-looking functions exist
  unused.
- `tests/test_paper_mode.py` (+3): `_can_admit_paper_evidence_collection`
  allows SIDEWAYS/VOLATILE for the P0.8+ bucket; negative control confirms
  the legacy bucket (`None` or any other bucket) is completely unaffected;
  fail-closed on an unknown regime even within the P0.8+ bucket.
- Full regression sweep (signal_router + bypass + P0.4 routing + shadow
  evaluator + bypass + live pipeline + paper_mode + deploy_integrity):
  340 passed, 2 failed, both confirmed pre-existing via `git stash`
  earlier this session (local-`.env` `PAPER_TRAIN_STRICT_TAKE_ENABLED`
  case, and an unrelated deploy-script CLI-action validator).

## What to watch post-deploy

- `[P0_8_PLUS_LIVE]`/`[P0_8_PLUS_SHADOW]` log lines should start showing
  `admitted=True` for `sideways_mean_reversion_v1`/`volatility_breakout_v1`
  candidates when the market is actually in a SIDEWAYS/VOLATILE regime
  (confirmed live via an earlier smoke test that the market frequently is)
  — if still zero after a reasonable observation window, the next
  hypothesis is each strategy's own internal pattern thresholds (already
  the confirmed reason candidates were sparse even at the shadow-only
  stage, per `_workspace/24`'s "0 candidates across every single 60s tick
  for 24h+" finding on the OLD 3-symbol subset), not the admission scope.
- `trend_cost_aware_v1` SHORT entries in BEAR_TREND, and any symbol
  including BTCUSDT/SOLUSDT, should now also be able to reach
  `admitted=True` for the first time.
