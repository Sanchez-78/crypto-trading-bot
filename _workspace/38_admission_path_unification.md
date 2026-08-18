# Admission-path unification — single central admission decision for P0.8+

**Date:** 2026-08-18
**Trigger:** Tier A top priority from `_workspace/37_document_compliance_gap_analysis.md`
— the most architecturally significant remaining gap against document
§34's "one central signal admission path" requirement.

## The problem (confirmed structural, not hypothetical)

`signal_router.py`'s `evaluate_signal_for_paper_entry()` is the document's
central admission decision for P0.8+ signals — cost gate, P0 segment
eligibility (colon-separated segment key), risk guard, all already
applied before `p0_8_plus_live_pipeline.py` ever calls
`open_paper_position()`.

`open_paper_position()` itself then ran its OWN, independent P0.3B/P0.3C
admission re-check (`_should_skip_segment_p0_strict_ev`/
`_can_admit_paper_evidence_collection`) on **every** position, using a
different, underscore-separated segment-key format and its own
closed-trade history lookup. For a brand-new evidence-only strategy with
no history under that legacy shape, this second check always found
`reject_p0=True` and rerouted — unconditionally **overwriting**
`learning_source`, `p0_gate_reason`, `segment_key`, and `paper_source`
with its own values, discarding everything `signal_router.py` had
already correctly computed (documented, not fixed, in `_workspace/33`).

Net effect: two independent admission decisions per P0.8+ candidate, not
one. Fail-safe in direction (the second check was, if anything, more
conservative before the 2026-08-18 regime-scope widening made them
consistent) but not architecturally unified, and actively corrupting
attribution data.

## Fix — narrow, bucket-scoped bypass

`paper_trade_executor.py`'s `open_paper_position()`: the entire P0.3B/P0.3C
block is now skipped when `bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"`.
For that bucket specifically, the position trusts the values
`_map_to_legacy_signal()` already set on the `signal` dict (`strict_ev`,
`readiness_eligible`, `learning_source`, `segment_key`, `p0_gate_reason`)
— `signal_router.py`'s own decision — rather than recomputing (and
overwriting) them a second time.

**`regime`/`side_normalized` are computed unconditionally before the
branch** (they're needed by the very next block,
`_should_skip_segment_by_profitability`, regardless of which path was
taken) — the bypass only skips the actual P0.3B/P0.3C re-decision logic,
not variable setup other code depends on.

**Every other caller/bucket is completely unaffected** — the `else`
branch is byte-for-byte the same code this function already ran for
every P0.3B/P0.3C-gated caller before this patch (the entire legacy
`signal_generator.py` path, `PAPER_STARVATION_DISCOVERY`,
`C_WEAK_EV_TRAIN`, etc., none of which pass `bucket=="P0_8_PLUS_EVIDENCE_COLLECTION"`).

**`_should_skip_segment_by_profitability`** (the "Optional: Old segment
profitability gate" immediately after) is deliberately left untouched
and still runs for P0.8+ positions too — it's an orthogonal,
PF-based safety filter (currently gated `off` by default, `_MIN_SEGMENT_PF`),
not a duplicate of the same admission decision this fix targets.

## What this fixes as a side effect

`_workspace/33`'s disclosed C6 finding (attribution overwritten on every
P0.8+ position) is now resolved for real, not just documented around.
`p0_8_plus_live_pipeline.py`'s own docstring updated to reflect this.

## Risk assessment

Touches the admission gate every single paper position (legacy and new)
passes through — the highest-stakes single function change made this
session. Mitigated by:
- The change is a pure `if/else` branch on an exact string match
  (`bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"`) — no existing behavior
  path is modified, only gated.
- Full regression sweep: 352 passed, 1 pre-existing failure (confirmed
  via `git stash`), 4 skipped, across every P0.8+/signal_router/paper_mode
  test file.
- Explicit extra verification: `tests/test_v5_legacy_bridge_hooks.py`
  (12 failures, all pre-existing) independently re-confirmed via
  `git stash` scoped to exactly the 3 files this patch touches — identical
  failure set with the patch fully removed, proving this change is not
  the cause.
- Updated `tests/test_p0_8_plus_live_pipeline.py`'s integration test
  (the one that runs a REAL, unmocked `open_paper_position()`) to assert
  the corrected attribution directly — this is the test that originally
  caught the C5 dict-placement bug in `_workspace/33`, so it's the right
  test to trust for this class of bug.

## Tests

`tests/test_p0_8_plus_live_pipeline.py`'s
`test_live_pipeline_signal_opens_a_real_paper_position` extended with 3
new assertions: `learning_source == "trend_cost_aware_v1"` (not
"paper_evidence_collection"), `segment_key` matches
`signal_router.py`'s own colon-separated format (not the legacy
underscore one), `p0_gate_reason` matches `signal_router.py`'s own
decision code (not "no_segment_history"). 23/23 tests in that file pass.

## Rollback

`git revert <this commit>` — a pure code revert, no schema/config
change. Positions already opened under the fixed behavior keep their
(correct) attribution; the revert only affects future opens.
