# Learning State Migration / Rebuild Plan

**Status:** `NOT_RUN` this session. LEARN-01 through LEARN-06 were not
classified, verified, or fixed — session time was spent entirely on the
governing contract's mandatory gating item, STATE-01 (see
`AUDIT_REMEDIATION_REPORT.md`).

**No migration was run. No learner state file was mutated, read for
mutation purposes, hashed, or copied by this session.** The contract's
own hard rule ("Do not mutate the current learner state... test it only
on synthetic fixtures or a temporary copy created from a deliberately
provided fixture — not the working runtime files") was honored by
performing no LEARN-* work at all this session, rather than attempting a
partial migration without the prerequisite LEARN-01 through LEARN-05
fixes in place.

## Why this cannot be done before LEARN-01..05

The governing contract's own dependency order places "clean versioned
labels -> learner rebuild/evaluation" strictly after the market/fill/cost
label schema is stabilized (Phase 4, ECON-01/EXIT-01/etc.) and the
provenance schema is fixed (Phase 5, LEARN-01). Building a rebuild/replay
tool against the CURRENT, confirmed-contaminated and confirmed-ambiguous
schema (readiness_eligible defaults, ATR bucket mismatch, PF-semantics
edge cases per LEARN-01/02/05) would encode today's bugs into the
"authoritative" ledger format — the opposite of the contract's intent.

## What is already known, disclosed (not re-verified this session)

Per the governing contract's own starting evidence:
- Evidence signals have `readiness_eligible=false`.
- The close adapter omits eligibility and entry provenance.
- The learner defaults missing timestamps to `now` and eligibility to
  `true` (the exact "fail open" pattern invariant #13 forbids).
- Local pre-contamination evidence showed 457 readiness-false evidence
  trades and `qualification_n=457` — i.e. readiness-ineligible evidence
  appears to have been incrementing qualification, the LEARN-01 finding.

This session additionally found and fixed (in a **separate**, earlier,
already-committed-and-deployed piece of standing autonomous work on this
same 2026-08-18 date, predating and independent of the governing
contract) an unrelated closed-trade persistence bug
(`_workspace/39_closed_trade_attribution_write_bug.md`): `bucket`/
`source`/`paper_source`/`learning_source`/etc. were computed correctly at
open time but silently never written to `cache.sqlite` on close, for
trades closed between approximately 06:48 and 10:32 UTC that day. That
fix is orthogonal to LEARN-01..06 (it is a persistence-completeness bug,
not a provenance/eligibility-semantics bug) but is relevant context for
any future LEARN-06 rebuild tool: trades closed in that window have
permanently NULL attribution in local SQLite regardless of what the
in-memory learner state says, and no backfill was attempted (the source
data is genuinely gone).

## Required content once this phase is actually executed

1. Source-of-truth selection (which store — local SQLite, the
   `learning_state.json` snapshot files, or Firestore — is authoritative
   for which field, and why).
2. Schema/version validation for every raw event before it is trusted.
3. Contaminated/unproven-record exclusion rules — MUST explicitly exclude
   anything traceable to the two disclosed diagnostic-probe contamination
   events (`paper_a4150885640f`, `paper_50ff8e7169a5`, outbox IDs
   369-480/483-487, and the `qualification_n` 457->468 jump) rather than
   silently absorbing them into a "clean" rebuild.
4. Checksummed snapshot procedure (SHA-256 + size + mtime recorded before
   any read).
5. `--dry-run` diff report as the only mode implemented until the
   operator explicitly authorizes a real run.
6. Idempotent migration/rebuild (safe to re-run).
7. Rollback plan, separate from code rollback.
8. Explicit statement (already true today, and must remain true in the
   tool's own output) that the current local learner state is **not**
   automatically trusted as evidence of readiness or profitability.

## Recommended next step

Do not build this tool until LEARN-01 (immutable close/learning event
schema, fail-closed missing provenance) and LEARN-02 (ATR bucket parity)
are independently classified, tested, and fixed. Building it earlier
risks encoding the current bugs as the new "ground truth."
