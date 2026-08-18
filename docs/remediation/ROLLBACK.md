# Rollback Plan

**Status:** documented, not executed. `ALLOW_GIT_COMMITS=false` and
`ALLOW_DEPLOYMENT=false` for this task — nothing below was run.

## Code rollback (this session's only change: STATE-01)

Two files changed, as one logical unit (revert together, not
independently — see rationale in `AUDIT_REMEDIATION_REPORT.md`'s
STATE-01 entry):

```text
src/services/paper_trade_executor.py
bot2/main.py
```

Since `ALLOW_GIT_COMMITS=false`, these changes exist only as uncommitted
working-tree edits at the end of this session (not staged, not
committed, not pushed, per `ALLOW_GIT_INDEX_CHANGES=false` /
`ALLOW_GIT_PUSH=false`). Rollback, if ever needed, is therefore either:

1. **Before any commit**: discard the two files' working-tree edits
   (an operator action, not performed by this session — this session
   does not run `git checkout --`/`git reset` per its own hard rules).
2. **After a future commit** (a separate, later authorization): a plain
   `git revert <that commit>` — the change is additive/refactor-only (an
   existing function's side effects moved into a new explicitly-named,
   explicitly-called function; no schema change, no data format change,
   no new dependency), so a straight revert is sufficient and low-risk.

## New test file

`tests/test_state_01_import_purity.py` is new and additive — no rollback
implication beyond the code rollback above (removing it is safe at any
time; it asserts a property of the fixed code, not a load-bearing runtime
behavior).

## New documentation

`docs/remediation/*.md` (this file and its three companions) are new,
additive documentation — no runtime rollback implication.

## State/schema rollback

**Not applicable this session.** No state or schema migration was run
(see `LEARNING_STATE_MIGRATION.md` — `NOT_RUN`). No runtime data file was
read for mutation, written, hashed for a migration, or otherwise touched
beyond the read-only `ls -la` metadata checks recorded in
`AUDIT_REMEDIATION_REPORT.md`'s Phase 0 section.

## Verification after any future rollback

Re-run the exact acceptance tests this session added:

```text
pytest tests/test_state_01_import_purity.py -v
```

All 5 must pass both before AND after any rollback of the STATE-01 fix —
before rollback they prove the fix works; after a rollback they would
correctly start failing again (proving the rollback actually reverted
the behavior, not just the visible diff), which is itself a useful
regression signal to check the rollback was complete.

## What this rollback plan explicitly does NOT cover

Every other finding in the governing contract (SEC-01 through OPS-05
except STATE-01) was `NOT_RUN` this session — there is no code, schema,
or data change to roll back for any of them.
