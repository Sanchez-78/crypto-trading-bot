# Phase: critical self-review before deployment

## Finding #2 fix (firebase_learning_persistence schema drop) — trying to falsify

1. **Single caller confirmed** (grep, repo-wide): only `paper_adaptive_learning.py`
   uses `save_learning`/`load_learning`. Widening the persisted schema cannot
   break an unknown third consumer.
2. **Load path unchanged**: `load_learning_state()` already returned whatever
   was in the file; the fix is entirely in what `save_learning_state()`
   chooses to write. No new failure mode introduced on load.
3. **Red/green proof, not just static reasoning**: new regression test
   (`tests/test_firebase_learning_persistence_schema.py`) fails on unpatched
   code (`KeyError: 'segment_weights'`) and passes on patched code — the fix
   is proven, not just argued.
4. **Firestore payload size**: `recorded_trade_ids` (maxlen 5000 strings) is
   the largest now-included field. Live production JSON with real data is
   ~38KB — well under Firestore's 1MiB/doc limit even at the 5000-entry cap.
   Sync cadence (every 5 min, best-effort) is unchanged by this fix — only
   payload size grew, not write frequency. Flagged to firebase-quota-agent,
   not treated as a blocker.
5. **Test-isolation fallout was real, not swept under the rug**: fixing the
   schema-drop bug exposed that ~10 tests across 3 files relied (via a
   previously-masked module-singleton path) on the bug's side effect of
   always resetting state to empty. Root-caused each (missing
   `_firebase_available=False` isolation in 2 files' fixtures, a missing
   `get_learner()` patch in 1 specific test) rather than reverting the fix or
   loosening the new test's assertions. Verified with a byte-for-byte diff
   against the true pre-patch baseline: **zero tests newly broken, 23
   previously-broken tests now pass, 11 pre-existing unrelated failures
   (env issues: missing `dotenv`/`yaml` modules, and 2 unrelated
   `test_p11ap_o2_fixes.py` failures) untouched.**

## Finding #1 (rolling100 PF=0.70) — no code patch, by design

Root cause (DEV_FADE) is a live strategy/config decision
(`PAPER_DEVIATION_FADE=true`), not a code defect. Consistent with last
session's explicit boundary ("this is a business decision, not a bug — I
will not touch it without you"), no patch authored. Evidence handed to user
for a decision, not silently acted on.

## Scope discipline check

- Did NOT touch `live_trading_allowed`, `TRADING_MODE`, `ENABLE_REAL_ORDERS`,
  `LIVE_TRADING_CONFIRMED`, or any real-order code path.
- Did NOT set up any recurring/cron autonomous loop (respecting last
  session's permission-system block).
- Patch stays within `firebase_learning_persistence.py` (1 function) +
  3 test files' isolation fixtures + 1 new test file. No unrelated
  refactoring.
