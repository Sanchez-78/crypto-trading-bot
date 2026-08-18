# Audit Remediation Report

**Source contract:** `CLAUDE_COMPREHENSIVE_REMEDIATION_PROMPT_2026-08-18.md`
**Session status:** PARTIAL (see below)
**Execution parameters honored:** no git commit/push/index change, no
deployment, no production access, no real orders, no runtime data
cleanup/migration, all test writes confined to `tmp_path`-provided
temporary directories.

## Scope note

This contract enumerates ~30 findings (P0: 3, P1: ~27) each requiring
independent classification, verification against current code, a
regression test, a minimal fix, and documentation. That is a multi-day
engagement for a careful, evidence-based implementation, consistent with
the contract's own explicit allowance: *"If context, time, or tool
limits prevent completion... return PARTIAL. Never skip a phase,
compress unverified work into a success claim."* This report follows
that instruction literally: one finding is fully classified, fixed, and
tested (the one the contract's own dependency order requires be fixed
*first*, since it gates safe dynamic testing of everything else); every
other finding is recorded as `NOT_RUN` with the exact reason, not
guessed at or partially patched.

## Phase 0 — static baseline (COMPLETE)

- `rtk git status` (effectively `git status --short`, `rtk` unavailable
  in this environment — see Residual Risks) captured before any edit;
  matches the contract's disclosed pre-existing worktree state
  (`_workspace/*.md` untracked forensic docs, `runtime/v5_quota_usage.sqlite`
  modified, `scripts/research/*.py` untracked) plus this session's own
  standing autonomous-loop work from earlier the same day (all already
  committed+pushed under a separate, explicit "plná autonomie" grant —
  distinct from and prior to this contract).
- Active entrypoint confirmed unchanged from the contract's own
  assumption: `start.py -> bot2/main.py -> src/services/*`.
- Contamination artifacts confirmed present via read-only filesystem
  metadata only (`ls -la`, no file opened/parsed):
  - `data/paper_open_positions.json` — present, 1.9K.
  - `src/runtime/v5_trade_outbox.sqlite` — present, 409600 bytes.
  - `server_local_backups/learning_state_phase1.json`,
    `paper_adaptive_learning_state.json` — present.
  - `local_learning_storage/learning_database.sqlite-wal`/`-shm` —
    present, confirmed untracked via `git status`.
  - The zero-byte `=` file described in the contract — **not found** in
    this working tree at the time of this check (path searched at repo
    root). Not otherwise investigated; recorded as a discrepancy, not
    resolved.
- None of these artifacts were opened, hashed, migrated, or modified by
  this session's remediation work.

## Finding classifications

### STATE-01 — import-time business side effects

**Classification: CONFIRMED, FIXED.**

- **Evidence (file:line, pre-fix):** `src/services/paper_trade_executor.py`,
  module-bottom (former lines ~4418-4434, no `if __name__`/lazy guard):
  `subscribe_once("signal_created", _on_signal_created)` followed by an
  unconditional `try: _init_paper_state_once() except: ...` block with
  raw `print()` calls.
- **Active call path:** `bot2/main.py:87` does
  `from src.services.paper_trade_executor import get_open_positions` at
  module scope — the first `import` of this module anywhere in the
  active entrypoint's chain (or in any test file) triggered the full
  cascade.
- **Root cause:** `_init_paper_state_once()` -> `_load_paper_state()`
  (line 914) unconditionally reads `_STATE_FILE`
  (`data/paper_open_positions.json`), migrates/normalizes records, calls
  `_reconcile_stale_paper_positions()` (real business logic capable of
  closing stale positions and emitting learning updates — the confirmed
  source of the disclosed contamination pattern: fabricated
  `paper_close`/`learning_update` events for real trade IDs, outbox rows
  created, learner `qualification_n` mutated), and writes the state file
  back to disk on a schema conversion.
- **Affected invariant:** #1 ("Importing an application module performs
  zero filesystem writes, DB changes, business reconciliation, network
  calls, worker/thread creation, timers, or event-bus registration.")
- **Planned minimal change:** extract the exact same side-effecting
  calls (`subscribe_once(...)`, `_init_paper_state_once()`) into a new,
  explicitly-named, idempotent function
  (`initialize_paper_trade_executor()`); call it exactly once from
  `bot2/main.py`'s startup sequence, immediately after
  `_init_event_handlers()` (so the event bus exists for `subscribe_once`
  to register against) and before any market-data/signal processing can
  start. No other behavior changed — `_init_paper_state_once()`'s own
  pre-existing `_PAPER_STATE_INITIALIZED` idempotency guard is untouched,
  and the exception-handling behavior (catch, log, do not propagate)
  deliberately matches the original code exactly, to keep this patch
  scoped to import-purity only (see OPS-02 for the separate, unbundled
  question of whether a state-load failure should instead halt startup).
- **Files changed:**
  - `src/services/paper_trade_executor.py` — module-bottom side effects
    replaced with the `initialize_paper_trade_executor()` function
    definition; module now defines symbols only on import.
  - `bot2/main.py` — added the explicit call site immediately after
    `_init_event_handlers()`.
- **Regression test:** `tests/test_state_01_import_purity.py` (new, 5
  tests):
  1. `test_bare_import_creates_no_files_in_cwd` — subprocess import with
     CWD = fresh `tmp_path`, asserts zero new files appear.
  2. `test_bare_import_does_not_flip_initialization_flags` — asserts
     `_PAPER_STATE_INITIALIZED`/`_PAPER_TRADE_EXECUTOR_SUBSCRIBED` remain
     `False` after a bare import.
  3. `test_bare_import_does_not_touch_real_project_state_file` —
     belt-and-suspenders: subprocess import with CWD = the **real** repo
     root, asserts `data/paper_open_positions.json`'s mtime is bit-for-bit
     unchanged before/after.
  4. `test_explicit_initialize_function_exists_and_is_idempotent` —
     confirms the new function exists, is callable, flips both flags to
     `True`, and a second call does not raise.
  5. `test_bot2_main_calls_initializer_after_event_bus_init` — static
     check that the call site exists and is ordered after
     `_init_event_handlers()`.
- **Result:** 5/5 new tests pass. Full regression sweep across every
  test file that imports `paper_trade_executor` directly (not via
  subprocess): `test_paper_mode.py` + this new file +
  `test_dynamic_trend_exit_wiring.py` + `test_p0_8_plus_live_pipeline.py`
  + `test_p0_8_plus_document_invariants.py` +
  `test_local_persistent_cache_attribution.py` +
  `test_tp_sl_cost_floor_invariant.py`: **291 passed, 1 failed** (the
  same single pre-existing, local-`.env`-only failure documented
  repeatedly elsewhere in this repository's own `_workspace/` history —
  `PAPER_TRAIN_STRICT_TAKE_ENABLED` set truthy in this machine's `.env`),
  4 skipped. `test_v5_legacy_bridge_hooks.py` (12 failures) +
  `test_deploy_integrity.py` (1 failure): identical count/pattern to
  every other check of these same files earlier the same day, already
  independently confirmed pre-existing via `git stash` comparisons in
  this session's separate standing work (not re-run here to avoid
  touching git state, per this contract's `ALLOW_GIT_INDEX_CHANGES=false`).
  Empirically verified belt-and-suspenders: `data/paper_open_positions.json`
  mtime recorded before (`1787049030.8775034`) and after
  (`1787049030.8775034`) running the full test suite including the
  real-CWD import test — bit-for-bit identical.
- **Residual risk:** None identified for the fix itself. The
  contamination artifacts from the ORIGINAL bug remain in place
  (untouched, per the contract's hard rules) and are not automatically
  trustworthy for any downstream analysis — this is unchanged by the
  fix and is the subject of LEARN-06's separate, `NOT_RUN` migration
  work.
- **Rollback boundary:** revert the two changed files together (the
  `bot2/main.py` call site and the `paper_trade_executor.py` function
  extraction are a single logical change; reverting one without the
  other would either silently disable paper-state loading entirely, or
  reintroduce the import-time side effect).

### All other findings — NOT_RUN

**Classification: `NOT_RUN`** for SEC-01, MARKET-01, EXEC-01, STATE-02
through STATE-05, DATA-01 through DATA-03, ECON-01, ECON-02, EXIT-01,
CONFIG-01, ROUTE-01, INPUT-01, LEARN-01 through LEARN-06, PERSIST-01
through PERSIST-03, OPS-01 through OPS-05.

**Exact reason:** session time/turn budget was spent entirely on STATE-01
per the contract's own mandatory dependency order ("static baseline ->
import purity -> isolated test harness -> security perimeter -> atomic
position/persistence lifecycle" — import purity gates everything that
follows, including P0 items SEC-01/MARKET-01/EXEC-01, which the
contract's own Phase 2 places *after* Phase 1's gate gate). No other
finding was verified against current code, no other regression test was
written, no other fix was applied. This is a deliberate stop, not a
missed item — continuing to a second finding without the same
verify-test-fix-document rigor applied to STATE-01 would violate the
contract's own change-discipline loop and its explicit prohibition on
"compress[ing] unverified work into a success claim."

Per the contract's own rule ("Any `BLOCKED_*` or `NOT_RUN` P0/P1 item
prevents overall status `COMPLETE`"), overall status is **PARTIAL**.

## Traceability appendix

```text
STATE-01 -> P1 -> CONFIRMED, FIXED
  -> evidence: paper_trade_executor.py module-bottom (pre-fix, no guard)
     + bot2/main.py:87 (first import site)
  -> root cause: _load_paper_state()/_reconcile_stale_paper_positions()
     reachable unconditionally from import
  -> changed files: src/services/paper_trade_executor.py, bot2/main.py
  -> regression test: tests/test_state_01_import_purity.py (5 tests)
  -> exact result: 5/5 new pass; 291/292 broad regression pass (1
     pre-existing, unrelated failure); mtime-identical belt-and-suspenders
     check passed
  -> residual risk: none for the fix; pre-existing contamination
     artifacts remain untouched and still untrusted (separate, NOT_RUN
     LEARN-06 scope)
  -> rollback boundary: both changed files together, single logical revert

SEC-01, MARKET-01, EXEC-01, STATE-02..05, DATA-01..03, ECON-01..02,
EXIT-01, CONFIG-01, ROUTE-01, INPUT-01, LEARN-01..06, PERSIST-01..03,
OPS-01..05 -> NOT_RUN -> reason: session scope exhausted after completing
  the contract's own mandatory gating item (STATE-01) with full rigor;
  no shortcut classification attempted for any of these.
```
