# External audit prompt — WR>50 single-path refactor (Phase 0-3/5/6, 3 rounds)

## 0. Role and terminal boundary

You are the independent external auditor of the CryptoMaster HF-Quant paper-trading
project, continuing the same adversarial-review lineage that ruled NO-GO on
delta-neutral funding-carry (Kolo 9) and separately audited the host/code security
posture (`EXTERNAL_AUDIT_CODE_SSH_REPORT_2026-09-02.md`). This round covers a
different track: an architecture-consolidation + measurement-integrity refactor
aimed at honestly earning `WR > 50%` (paper-only), not a new trading strategy.

The work under audit lives on branch `wr50/canonical-single-path-phase2`
(now **pushed to origin**, 10 commits, latest `15d4870`), never merged to `main`,
never deployed. `REAL trading = ABSOLUTE NO-GO` regardless of any verdict below.
Nothing here authorizes deployment, a restart, or a REAL order.

### 0.1 Update (2026-09-15) — gate work since the 3 rounds above, and two new findings

Following the 3 rounds documented in the full report, the orchestrating session
(not a dispatched agent — the spend limit blocking background agents recurred)
worked the release gate directly:

- **`protected_paths_dirty` resolved.** Of the 5 protected paths, 4 were already
  clean on this branch; only `systemd/cryptomaster-dashboard.service` was dirty.
- **New finding: an uncommitted dashboard-hardening draft was sitting in that
  file** (`DASHBOARD_SECURITY_ENABLED=1`, bind `127.0.0.1`, `DynamicUser`,
  bearer-token auth via `LoadCredential`, extensive systemd sandboxing) —
  directly addressing the P0/P1 exposure `EXTERNAL_AUDIT_CODE_SSH_REPORT_
  2026-09-02.md` flagged (dashboard on `0.0.0.0:5001`, unauthenticated, root).
  **Deliberately NOT committed as part of this gate resolution**: `git log`
  shows this exact class of change was already tried once (commit `c664f3d`,
  "audit(PR5/P1.6): dashboard auth + localhost bind + non-root hardening") and
  later reverted (commit `fbcd709`, "stop recurring Android API outage") — i.e.
  binding the dashboard to loopback previously broke live Android app
  connectivity. The draft was reverted to HEAD to unblock this gate cleanly and
  preserved verbatim at `_workspace/52_uncommitted_dashboard_hardening_
  preserved_20260915.service.txt` for its own separately-scoped decision.
  **Audit this call**: was reverting-and-deferring the right choice, or should
  the hardening have shipped alongside a check for whether the Android app's
  connectivity story has changed since the `fbcd709` incident?
- **Both remaining artifacts attached**: `release_artifacts/wr50_phase2_
  manifest_2026-09-15.json` (SHA-256 manifest, commit identity, explicit
  scope/exclusions) and `release_artifacts/wr50_phase2_paper_smoke_evidence_
  2026-09-15.txt` (fresh 61-test run + reference to the already-verified
  207-test/6-mutant evidence from the full report).
- **New finding: `tools/release_gate.py` appears to have a bug.** Its
  `evaluate()` function's final line is `return False, reasons, hashes` — the
  `ready` flag is a **hardcoded `False` literal**, not `len(reasons) == 0`.
  After resolving all three original blockers, `python tools/release_gate.py
  --json --artifact ... --paper-smoke-evidence ...` now returns `"reasons": []`
  (empty — every condition the script itself checks is satisfied) but
  `"ready": false` and exit code `2` regardless. **This was deliberately NOT
  patched by the same session trying to pass the gate** — fixing the checker
  that grades your own readiness is exactly the self-certification this
  project's adversarial-review culture exists to prevent. **Rule on this
  specifically**: is `return False, ...` a genuine bug (should be `len(reasons)
  == 0`), or an intentional design forcing every deploy through a manual
  override regardless of automated checks? Either answer has a different
  correct next action, and neither should come from the session with an
  interest in the outcome.

Updated terminal state: engineering `PARTIAL` (unchanged), release gate
`reasons=[]` but `ready=false` (script anomaly, see above), nothing merged or
pushed to `main`, nothing deployed, zero REAL orders throughout.

Full evidence: `CLAUDE_WR50_SINGLE_PATH_PHASE2_REPORT_2026-09-14.md` (3 rounds,
686 lines — read it in full, don't work from this prompt's summary alone).
Governing architecture mandate: `CLAUDE_SINGLE_PATH_POLICY_2026-09-14.md`.
Original task spec: `CLAUDE_WR50_SINGLE_PATH_IMPLEMENTATION_PROMPT_2026-09-14.md`.
Prior WR-by-source claim that this work **retracted**:
`WR_TARGET_ANALYSIS_2026-09-14.md` (its 75%/30% figures came from a 34-minute,
39.8-day-old, 24.6%-synthetic-contaminated slice — do not treat as valid evidence,
and check whether the retraction itself was done correctly).

## 1. What happened, in one table (verify this yourself against the report, don't take it as given)

| Round | Claimed done | Claimed NOT done |
|---|---|---|
| 1 | Phase 0 baseline+contamination audit; Phase 1 RED tests (2 suites); Phase 2 core (9 call-sites → one `canonical_admit()` wrapper); Phase 5 partial (dashboard qualified/excluded fields); Phase 6 partial (3 mutants) | Phase 2 attribution *persistence* (no schema columns existed); Phase 3, 4, 7 |
| 2 | Test-sink separation for `cache.sqlite` (root cause: relative path resolved against CWD); schema migration (6 columns) + fixed a second gap (position-dict allowlist silently dropping 4/6 stamped fields); Phase 3 (`TIMEOUT_NO_PRICE` → new `TradeOutcome.VOID` state, not a filter); 2 more mutants (M4/M5) | Sink separation for the other 2 production files; test-order-dependence fix; Phase 4 |
| 3 | Sink separation extended to `learning_database.sqlite` (discovered: resolves to a **mounted network share**, not just CWD-relative) and `paper_open_positions.json`/`paper_adaptive_learning_state.json`; centralized guard (`src/core/test_sink_guard.py`); test-order-dependence fixed (autouse fixture pins `_PAPER_STATE_STATUS=READY`) with a measured (git-worktree-isolated) before/after: 30failed/45passed → 24failed/51passed; 1 more mutant (M6) | 24 pre-existing failures in `test_p1_paper_exploration.py`; a full sweep for other hardcoded production paths (only one pattern was audited); Phase 4 itself |

**Two disclosed near-miss incidents**, both self-caught (not caught by any external
check), both reverted with SHA-256 verification:
1. Round 2: the agent's own RED-state-confirmation probe wrote one row
   (`id=58840`, `trade_id=paper_sinkprobe01`) into the live production
   `cache.sqlite` — reproducing the exact bug being fixed, on itself.
2. Round 3: 39 hardcoded literal paths in `test_p1_paper_exploration.py` bypassed
   the module-constant redirect entirely and **deleted** the real
   `data/paper_open_positions.json` during a full-suite run. Gitignored, so it
   never showed in `git status` — caught only because the agent was independently
   hashing production files before/after every run.

## 2. Adversarial checks I want you to actually run, not just read about

1. **Re-derive the contamination math yourself.** 116/472 = 24.6%; 76 fake-clock +
   35 TEST/MANUAL (all wins) + 3 SYM* symbols. Does the union arithmetic hold? Does
   "all 35 TEST/MANUAL rows are wins" actually bias WR upward by the claimed
   direction and magnitude, or is this asserted without a counterfactual
   (WR with vs. without those 35 rows, holding everything else fixed)?
2. **Check `canonical_admit()` is genuinely a passthrough, not a second brain.**
   The report claims it "contains no admission logic... cannot re-decide, bypass,
   or retry admission." Read the actual wrapper in
   `src/services/paper_trade_executor.py` and confirm this against the 9 call-sites
   it now serves — does any call-site's pre-existing surrounding logic still make
   an admission-relevant decision *before* calling the wrapper, in a way that could
   look like "single path" on paper but isn't in practice?
3. **Stress the VOID-outcome fix.** Verify `compute_win_rate` truly excludes VOID
   only, not also silently excluding something else (the report's own M4 mutant
   claims to have tested exactly this — check the mutant's diff is what it claims,
   and that no OTHER path recomputes WR without going through the audited
   function). Does the dashboard's `_qualified_window_metrics` reconcile
   (`raw_n == qualified_n + excluded_n`) against a case with BOTH a VOID row and a
   legacy pre-fix TIMEOUT_NO_PRICE row in the same window (mixed old/new
   semantics) — the report only shows single-window reconciliation, not a mixed
   case.
4. **Verify the "not a metric trick" claim independently.** `qualified_win_rate_pct
   = 64%` is repeatedly, loudly flagged as NOT goal-met. Confirm: does the
   `test_all_source_headline_is_not_redefined` test actually assert the headline
   field's value/name is unchanged, or only that a *differently-named* field
   exists? A determined future editor could still quietly swap which field the
   Android app or a future dashboard reads — is there a structural guard against
   that class of drift, or only a test that would need to be remembered and kept
   passing?
5. **Audit the sink-separation guard for the exact failure mode it was built to
   prevent.** `_assert_not_production_sink()` triggers on `PYTEST_CURRENT_TEST`
   being set. Is there any code path (a subprocess spawned by a test without
   inheriting that env var, a test that imports and calls production code via
   `multiprocessing`, a fixture that clears `os.environ`) that could evade this
   check while still being "run under pytest" in every way a developer would
   recognize? The report itself flags "other tests may hold more hardcoded
   production paths... not yet swept" — is the guard's env-var-based detection
   robust even against paths the sweep hasn't found yet, or does it only catch
   the *redirected-constant* violation pattern, not a genuinely hardcoded
   absolute path that never goes through the constant at all?
6. **Check the worktree-based before/after measurement (R3-F) for a subtle bias.**
   Baseline was run at `f01b19f` (mid-branch, after some of this session's own
   fixes were already committed) with `FORCE_LOCAL_STORAGE`, not at the branch's
   pre-existing base commit on `main`. Does comparing branch-commit-N against
   branch-commit-M (both already containing several of this session's changes)
   correctly isolate "caused by the order-dependence fix" from "caused by
   something else fixed between those two commits"? Would comparing against the
   actual `main` HEAD give a materially different (larger or smaller) delta?
7. **Ownership/mixed-commit risk.** Four production files are explicitly flagged
   as carrying "mixed" ownership with unrelated prior sessions' uncommitted work
   (STATE-02 loader, READY guard, ROUTE-01, dashboard fields) baked into the same
   commits. If that prior work is later abandoned, reverted, or conflicts with a
   fix from a different session, what breaks in `canonical_admit()`'s dependency
   on it? Name the single most load-bearing piece of that "mixed" prior work this
   refactor now depends on, and whether that dependency is tested independently
   of this branch's own tests.
8. **Merge-readiness, independent of Phase 4.** The release gate (`ready=false`:
   `protected_paths_dirty`, `immutable_artifact_not_created`,
   `paper_smoke_evidence_not_attached`) is about *deployment*, not about whether
   this branch is safe to merge into `main` as an internal refactor with no
   behavior change to admission decisions. Should merge-to-main and
   deploy-to-production be treated as two separate gates here? If yes, what
   would the (much lighter) merge-only gate need that isn't already satisfied?

## 3. Specific questions to rule on

**Q1 (architecture).** Does Phase 2's `canonical_admit()` genuinely satisfy the
Single Path Policy's contract (`signal -> canonical admission -> open ->
one close writer -> metrics`, sources as labels only), or does it satisfy the
*letter* of "one wrapper" while multiple pre-wrapper decision points still exist
across the 9 call-sites? Cite specific file:line evidence either way.

**Q2 (measurement integrity).** Is the VOID-outcome fix + qualified/raw dashboard
split methodologically sound, or does it introduce a new risk (e.g., future
confusion between VOID and FLAT, or a path where VOID rows silently affect P&L
sums despite being excluded from the WR denominator)?

**Q3 (process risk from the two near-misses).** Two accidental production writes
happened in one session, both self-caught only through the operator's own
discipline (hashing files around each run), not through any structural
guarantee that existed *before* this session started. Is "hash files before/after
and disclose if they change" an adequate standing practice for this project going
forward, or does this warrant a permanent, automated pre/post-test integrity
check (e.g., a pytest session-scoped fixture that hashes the three production
files and fails the whole run if they differ) rather than relying on an operator
remembering to do this by hand each time?

**Q4 (prioritization).** Given: (a) Phase 4 is blocked on wall-clock data
accumulation and cannot be accelerated, (b) 24 pre-existing test failures exist
in `test_p1_paper_exploration.py`, (c) a hardcoded-path sweep hasn't been done
beyond the one pattern found, (d) separately, `EXTERNAL_AUDIT_CODE_SSH_REPORT_
2026-09-02.md`'s still-open findings (dashboard on `0.0.0.0:5001` without auth,
disk ~96% full, host/local SHA drift) remain unaddressed and are a live
production exposure independent of this refactor — rank these for the operator.
Should any of (b)/(c) happen before or in parallel with waiting on Phase 4's data
accumulation? Should (d) take priority over all of the WR50 work, given it's a
standing security/capacity risk on a live host regardless of trading outcome?

**Q5 (Phase 4 design review, prospective).** The next session will need to design
a real Phase 4 shadow cohort: fixed `code_version`/`config_version`, minimum
sample size, confidence interval, max-loss cap, holdout window, `training_sampler`
vs `rde_take` comparison without dropping rows. Propose the specific minimum
sample size and confidence-interval methodology you'd require before accepting a
future "WR>50 achieved" claim on this cohort, given the clean (contamination-free)
historical split was `rde_take` 99/118=83.90% vs `training_sampler` 57/221=25.79%
— both on a stale, non-version-homogeneous, unpushed-fix-predating cohort that
must not be reused as if it were live.

## 4. Ground rules (unchanged from this project's standing practice)

Be adversarial; refute where the evidence allows. Cite file:line, not paraphrase,
wherever you make a factual claim about the code. Do not soften a verdict for
continuity — if something in Phase 2/3/5/6 is unsound, say so plainly, the same
way Kolo 9 said NO-GO on funding-carry despite genuinely rigorous supporting work.
REAL trading stays an absolute NO-GO regardless of any answer above.
