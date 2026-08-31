# 50 — Cycle 187-188: confirmed ~90+ min trading stall, root-caused to a missing weak_ev exemption for C_NEG_EV_PROBE

## Status: DEPLOYED (901fc39 + f4dd5ee, 2026-08-31 12:25 UTC) — incident resolved, but the fix's own path is UNPROVEN, not "validated." Do not close this as a clean win. See "Deploy verification" section below.

## Trigger

User said "wr stale klesa" (WR keeps dropping). Checked immediately: WR was
actually flat/slightly up, not evidence of a new problem on its own. But
while watching subsequent 30-min cycles, `closed_trades` stopped
incrementing entirely for 3 consecutive checks (~70+ minutes) with
`open_positions=0` throughout — investigated directly rather than assuming
either "just quiet" or "definitely broken."

## Forensic findings (in order discovered)

1. **Confirmed real, not a dashboard artifact.** Queried `cache.sqlite`
   directly (bypassing the dashboard API entirely): 0 trades closed in the
   last 1 hour, last real close at `2026-08-31T10:07:35Z` — ~90 minutes
   before this was caught. Service itself was healthy throughout
   (`NRestarts=0`, same PID since the last deploy, no crash loop).

2. **EMERGENCY_MONITOR was already firing real alerts** (`RECON_FAILURE`,
   `LEARNING_STALL`, `DASHBOARD_ZERO`) every single 60s check for at least
   7+ minutes — these were NOT false positives (unlike the cycle-123/130
   false-positive findings); `[V10.13x.1 RECON]` itself showed
   `recent_ok=False status=MISMATCH`, an independent internal signal that
   something real was wrong. (Separately noted: `detect_recon_failure()`
   in `emergency_health_monitor.py` only flags literal `status=WARN`/
   `status=FAIL` substrings — a `status=MISMATCH` line doesn't match either,
   so a RECON line WAS present in some checks but wasn't itself flagged as
   the failure; the `RECON_FAILURE` alert that did fire came from the
   "RECON not found in logs" branch instead, i.e. from log-sampling
   variance, not from correctly parsing MISMATCH as bad. Not fixed this
   cycle -- flagged as a separate follow-up.)

3. **Signals ARE being generated and reaching ACCEPT/TAKE decisions.** In a
   20-min sample: 2,741 `REJECT_NEGATIVE_EV`, 320 `NO_CANDIDATE_PATTERN`,
   86 `SKIP_SCORE_HARD`, 55 `SKIP_SCORE_SOFT`, and **39 `TAKE`** decisions.
   So the bot is not idle upstream — plenty of candidates are evaluated,
   most correctly rejected on genuine grounds (matches the already-
   established "no directional edge in most candidates" finding from
   cycles 111/113), but 39 in 20 min *did* clear the decision-engine gates.

4. **Every one of those 39 TAKE-adjacent admissions is blocked downstream.**
   `[PAPER_ENTRY_ATTEMPT]` x6, `[PAPER_ENTRY_BLOCKED]` x23,
   `[PAPER_ENTRY_SKIP]` x6 in the same window — **zero** `[PAPER_ENTRY]`
   successes. Every sampled `PAPER_ENTRY_BLOCKED` line reads
   `reason=weak_ev ev=0.0000 threshold=0.0100 bucket=C_NEG_EV_PROBE` (or
   `bucket=None`).

5. **Root cause: `C_NEG_EV_PROBE` was never added to the weak_ev floor's
   exemption tuple.** `paper_trade_executor.py`'s `open_paper_position()`
   has a floor (`_MIN_EV_THRESHOLD=0.01`) blocking any entry with
   `ev < threshold`, with an explicit exemption list for buckets that are
   *deliberately* allowed to admit low/zero-EV candidates:
   `("PAPER_STARVATION_DISCOVERY", "P0_8_PLUS_EVIDENCE_COLLECTION")`.
   `C_NEG_EV_PROBE` (`paper_training_sampler.py`, tag `P1.1AO`, docstring
   "cold-start starvation recovery") is **exactly** this same class of
   mechanism — its own admission precondition is literally `ev <= 0`
   (`_get_training_bucket()`: `if ev <= 0 and "REJECT_NEGATIVE_EV" in
   reject_reason and _is_cold_start_starvation(): ... return
   ("C_NEG_EV_PROBE", 0.01)`, where `0.01` is a `size_mult`, not an EV
   value) — but it was never added to the exemption tuple. Every single
   admission attempt through this bucket has therefore always been
   self-blocked, since the bucket was introduced.

   **This is the identical failure mode already documented in this exact
   file, one incident earlier** (`P0-FIX 2026-08-06`, the
   `PAPER_STARVATION_DISCOVERY` exemption): a bounded, deliberate
   starvation-recovery exploration bucket added without a corresponding
   floor exemption, silently self-blocking 100% of its own attempts,
   causing the bot's own recovery valve to be non-functional during
   exactly the dry-spell conditions it exists to handle. `C_NEG_EV_PROBE`
   was added later (after that fix) and repeated the same gap.

## Fix

Added `"C_NEG_EV_PROBE"` to the exemption tuple at
`paper_trade_executor.py`'s weak_ev floor (~line 1684), with a comment
explaining the finding and citing the parallel to the 2026-08-06 incident.
New test `test_open_paper_position_c_neg_ev_probe_bypasses_weak_ev` in
`tests/test_paper_mode.py`, mirroring the existing
`PAPER_STARVATION_DISCOVERY`/`P0_8_PLUS_EVIDENCE_COLLECTION` exemption
tests exactly. 234 tests in the file: 229 pass, 4 skipped, 1 pre-existing
failure (`test_strict_take_disabled_for_training`, confirmed via `git
stash` to fail identically without this change — an unrelated environment
variable default check, not caused by this fix).

## Not fixed this cycle (deferred, separate findings)

1. **`bucket=None` blocked entries** — some `PAPER_ENTRY_BLOCKED
   reason=weak_ev` lines show `bucket=None` rather than `C_NEG_EV_PROBE`.
   Not traced to a specific call site this cycle; could be legitimate
   (ordinary negative-EV signals with no special exploration bucket,
   correctly blocked by design) or could be a second, separate gap. Needs
   its own dedicated forensic pass before concluding either way.
2. **`detect_recon_failure()`'s incomplete status parsing** (finding #2
   above) — only catches literal `status=WARN`/`status=FAIL`, not
   `status=MISMATCH` with `recent_ok=False`. A real signal is currently
   only caught indirectly (via the "not found in logs" fallback branch,
   which depends on log-sampling luck), not by correctly interpreting the
   MISMATCH status this monitor's own upstream RECON check already
   computes. Worth a dedicated fix in a future cycle.
3. **`LEARNING_STALL`/`DASHBOARD_ZERO` alerts during the stall** — plausible
   knock-on symptoms of the same root stall (no new trades → no new
   learning updates → dashboard-visible activity stalls), not
   independently investigated as separate root causes this cycle.

## Verification plan

Deploy through the standard review pipeline (reviewer-agent,
trading-safety-agent), then confirm live: `C_NEG_EV_PROBE` admissions
should start succeeding (`[PAPER_ENTRY]` lines with `bucket=C_NEG_EV_PROBE`
appearing in logs, `_probe_state["lifetime_closed"]` incrementing, capped
at `_PROBE_MAX_LIFETIME_CLOSED=20` per process lifetime), and the extended
zero-close stalls should stop recurring during genuine dry spells (though
the bot's real edge-generation limitation from cycles 111/113 remains
unfixed — this only restores the intended *safety-valve*, it does not
create new profitable signal).

## Review (reviewer-agent: APPROVED WITH CONDITIONS)

Source change (901fc39) judged safe/low-risk to deploy as-is (one-line
allowlist addition, paper-only path). Two conditions, both addressed same
day: (1) `test_open_paper_position_c_neg_ev_probe_bypasses_weak_ev` was
vacuous — passed even without the fix present, because it never restored
`_MIN_EV_THRESHOLD` from the test file's autouse `-inf` fixture the way
its two sibling exemption tests do; fixed in f4dd5ee, verified directly
(fails against 901fc39^, passes against 901fc39). (2) 901fc39's commit
message claimed a pre-existing unrelated test failure
(`test_strict_take_disabled_for_training`) was "confirmed via git stash"
— invalid method (stash doesn't touch untracked files); real cause is an
untracked `.env` with `PAPER_TRAIN_STRICT_TAKE_ENABLED=true`. Conclusion
(pre-existing/unrelated) still holds, only the stated method was wrong;
corrected via this note rather than rewriting the pushed commit.

Reviewer also flagged, as a non-blocking risk: bypassing the weak_ev
floor does not guarantee `C_NEG_EV_PROBE` entries succeed — a later
gate (`paper_trade_executor.py` ~1751-1818, legacy P0.3B/P0.3C reroute,
and `_should_skip_segment_by_profitability()` ~1821) is not exempted for
this bucket either. This turned out to be the right thing to worry
about — see below.

## Deploy verification (deploy-verify-agent, 2026-08-31 12:25 UTC): PASS, but attribution is NOT clean

Deployed clean (`d8befbb` = `901fc39`+`f4dd5ee`, PLAN+DEPLOY gates all
OK, fix confirmed live in code at `paper_trade_executor.py:1691`,
dashboard restart OK). The incident itself resolved:
`closed_trades` 12969→12977 (+8) in 14 min post-deploy, open positions
0→4 and cycling, zero real ERROR/CRITICAL, zero `weak_ev`+
`bucket=C_NEG_EV_PROBE` blocks post-deploy.

**But the resolution cannot be credited to this fix.** Independently
verified: trading resumed via `bucket=A_STRICT_TAKE`, a bucket this
patch never touches — and `C_NEG_EV_PROBE` has **never once** opened a
position: 0 `[PAPER_NEG_EV_PROBE_ACCEPTED]` lines post-deploy, 0 in 7
days of journal history, 0 of 12,977 closed trades ever tagged
`bucket=C_NEG_EV_PROBE`. Per `paper_training_sampler.py:951`,
`C_NEG_EV_PROBE` requires `_is_cold_start_starvation()`; once
`A_STRICT_TAKE` started flowing again (for reasons unrelated to this
fix), that precondition stopped holding, so the bucket now emits zero
candidates — it isn't being blocked downstream, it simply isn't being
generated. The reviewer's downstream-gate risk (P0.3B/P0.3C reroute,
`_should_skip_segment_by_profitability()`) is therefore **still
completely untested in production**, not cleared.

`deploy-verify-agent`'s own words: *"A restart alone is a plausible
sole cause [of the resolution]."* What the evidence DOES independently
confirm is the root-cause claim itself — `C_NEG_EV_PROBE` was 100%
self-blocked since introduction (0 trades, ever, until this fix).

**New open question, not investigated this cycle:** `A_STRICT_TAKE`
resuming immediately after the restart, following a 2h18m total freeze,
doesn't obviously look like "market conditions changed" — it looks like
"something was stuck and a restart unstuck it," which would echo the
known dashboard in-memory-freeze failure mode already documented in
`CLAUDE.md` (a separate service, but the same *symptom shape*: long
flat/frozen state, cleared incidentally by an unrelated deploy restart).
If total-stall incidents recur on a cadence that correlates with time-
since-last-restart rather than with genuine market dry spells, that
would be evidence for a broader stuck-state bug independent of
`C_NEG_EV_PROBE` — worth a dedicated forensic pass in a future cycle,
not chased further here.

**Correct status going forward:** treat this fix as *correct and
harmless but latent* — it only gets exercised the next time genuine
cold-start starvation recurs, which is exactly when the still-untested
downstream gates could bite. Watch for: `[PAPER_NEG_EV_PROBE_ACCEPTED]`
appearing (fix works end-to-end) vs. `C_NEG_EV_PROBE` reappearing in
`PAPER_ENTRY_BLOCKED` with a **non**-`weak_ev` reason (necessary-but-
not-sufficient, confirms the downstream-gate risk, needs a fast
follow-up). `bucket=None` weak_ev blocks were confirmed still present
post-deploy — still untraced, still deferred (finding #1 above).
