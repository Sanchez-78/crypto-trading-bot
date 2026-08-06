# Resolution: MFE-not-harvested TIMEOUT exits — NOT A BUG, no patch

Forensic verdict (live evidence, 53 fresh post-redeploy closes): both
candidate exit-mechanism bugs from the intake are REJECTED.
`[TP_SL_INVALID]` guard: 0 occurrences (not firing). Age-scanner racing
ahead of the tick evaluator: disproven (`max_seen`/MFE and the TP check use
the same tick/price, so a recorded high MFE proves TP was genuinely
evaluated and legitimately didn't trigger).

**Real cause:** live TP band is calibrated to 20bps (`MIN_TP_PCT` cost-floor
guard, `trade_executor.py:219`, "20bps sits just above the 18bps cost floor
— cycle-27: never below cost"), while realized MFE in the current flat
tape averages only 13.6bps (max 21.6bps). Favorable moves genuinely don't
reach TP most of the time. The exit machinery is working exactly as
designed.

**Decision: do not patch.** Lowering TP toward observed MFE would
reintroduce documented, previously-reverted regressions:
- Cycle-27 (project memory): TP=7bps below cost floor → every TP exit
  net-negative, 0% WR → reverted.
- V10.47 → reverted 2026-07-03: a 60bps floor caused 100% TIMEOUT the
  other direction → reverted back to 20bps.
- CYCLE 37 (commit 7dbe9b7, reverted by 0517ae7): someone already tried
  "fix flat-market TP unreachability with dynamic scaling" for this exact
  symptom — reverted.

This is an entry-edge-quality question (why is MFE only 13.6bps in this
tape), not an exit-mechanism bug — out of scope for a quick patch. The
only economically-sound lever identified (not pursued now, no clear
scoped trigger to justify it yet) would be a cost-floor-aware trailing/
partial-harvest that locks gains once price clears ~18bps, without placing
a sub-cost TP. Noted for a future, deliberately-scoped session if this
pattern persists and the user wants to pursue it.

One residual open question (not decisive, doesn't change the verdict): a
6-trade A_STRICT_TAKE sub-cohort with MFE marginally >20bps still timed
out; their entry-geometry log fell outside the available journal window,
so their calibrated TP couldn't be confirmed (plausibly a wider strict-take
band, consistent with everything else observed, just not proven).
