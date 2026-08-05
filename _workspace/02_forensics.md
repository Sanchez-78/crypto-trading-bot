# Phase 1-2: Critical Re-Analysis of 4 Static-Audit Findings

Goal: try to falsify each finding with concrete evidence (git blame, call graphs,
serialization checks) before authoring any patch. Outcome per finding below.

## Finding #1 — PAPER_TP_ZONE_BPS/SL_ZONE_BPS default drift

**Original claim:** rehydration after restart silently changes an already-open
position's TP/SL on *every* restart, matching Cycle 24 (WR 57%→0%).

**Re-verification:**
- `_save_paper_state()` (paper_trade_executor.py:575-600) does
  `positions_snapshot = dict(_POSITIONS)` then `json.dump(...)` — the **full**
  position dict, including `tp`/`sl`, is persisted atomically (tmp file +
  `os.replace`) on every save.
- At open time (paper_trade_executor.py:1899-1900) `position["tp"]`/`["sl"]`
  are always set from `tp_sl["tp"]/["sl"]`, which is guaranteed non-null (a
  `None` result blocks the entry, see line 1842-1849 `tp_sl_impossible`).
- `_normalize_position_for_loading()` only overwrites tp/sl when
  `"tp" not in pos or pos.get("tp") is None or pos.get("tp") == 0` (line 671).
- **Conclusion: under normal operation the 35/30bps fallback does NOT fire on
  a routine restart** — the persisted state already carries the correct
  tp/sl. My original "fires on every restart" framing was WRONG.

**But the finding is not fully falsified either:**
- `git blame` on paper_trade_executor.py:675 shows the 35bps fallback was
  added in commit `55f78cf` ("Fix TP/SL blocker — add defaults in
  `_normalize_position_for_loading()`") — i.e. it exists *because* missing
  tp/sl has happened for real before (legacy list-format state, manual state
  edits, partial writes from an older schema) and caused a **100% TIMEOUT
  incident** per the code comment at line 668-670 ("missing tp/sl causes
  evaluation gate to fail... skips entire TP/SL block → ALL positions
  timeout").
- Since that fix landed, the open-flow default was later retuned from 35bps
  → 50bps (comment at line 1773: "V10.55 CYCLE 52+ FIX: Increase baseline TP
  to 50bps (was 35bps, too aggressive)") but the rehydration fallback at
  line 675 was never updated — a real, confirmed drift between two call
  sites that started in sync and silently diverged.
- The failure mode is not "every restart" but "any time tp/sl is missing on
  load" — a narrower, but real and previously-triggered, path (legacy list
  migration, corrupted/partial state write, manual edit, future schema
  change). If it fires today, the position gets 35/30bps instead of the
  intended 50/40bps band — a real risk/reward change, just gated on a rarer
  trigger than first claimed.

**Verdict: CONFIRMED, downgraded from CRITICAL → MEDIUM-HIGH.** Worth a
narrow, low-risk fix: single source of truth so the two paths cannot drift
again. This is a legitimate root-cause patch target.

## Finding #2 — 170+ silent `except Exception: pass`

**Re-verification:** sampled all `except Exception` blocks in
`paper_trade_executor.py` and re-read the ~56 blocks previously flagged in
`trade_executor.py`. Most `except Exception as e:` blocks (the majority)
already log via `log.warning/error/debug` — those are fine, not silent.
The genuinely silent subset (`except Exception:` / bare `except:` followed
immediately by `pass`, no `as e`, no log call) is concentrated in one place:
the **entry-sizing/scoring pipeline** in `trade_executor.py` roughly lines
2500-3100 (correlation penalty, policy score, regime-prediction adjustment,
replacement efficiency, exec-quality pre-filter) — i.e. optional *sizing*
enrichment factors on the entry path, not position-close / lock-release /
state-persistence code (which does log).

**Re-assessment of blast radius:** a silently-failed optional adjustment
here degrades trade *quality* (e.g. a correlation discount doesn't apply)
rather than corrupting state or leaving a position stuck open. It is **not**
mechanically related to the historical `_POSITION_LOCK` NameError incident
(a bad refactor introducing an undefined name) or the stuck-positions
incident (smart_exit_engine not wired into the main loop) — I over-connected
these in the original write-up; the causal link doesn't hold up.

**Verdict: directionally correct (real observability gap) but NOT a
root-cause bug with a concrete symptom, and the ~25-30 silent sites are
heterogeneous (each swallows a different optional computation).** Blanket-
patching all of them fails the harness's own "minimal patch, root cause
only" / "no overengineering" rule — there is no single root cause to fix,
and touching 25+ unrelated call sites in the hottest file in the repo is a
large blast radius for a cosmetic logging change with no reported symptom
behind it.

**Decision: NOT patched in this cycle.** Recorded as a scoped follow-up
recommendation (see FINAL_REPORT.md) for a deliberately separate, reviewed
pass — not bundled into an autonomous patch.

## Finding #3 — "dead" duplicate modules (execution_engine.py, risk_manager.py, meta_controler.py)

**Re-verification (this is where the original assessment was most wrong):**

- `execution_engine.py`: my first grep only matched literal
  `from src.services.execution_engine import` / `import execution_engine`
  and found 0 hits. A broader search finds it referenced by
  `tests/test_execution_engine_no_real_order.py`, which does
  `import src.services.execution_engine as ee` and **asserts it is the
  ONLY file in the entire repo containing a real
  `/api/v3/order` POST call** (`assert hits == ["src/services/execution_engine.py"]`).
  This is a **trading-safety regression test**, not incidental usage —
  `execution_engine.py` is deliberately kept OUT of the paper-trading live
  import graph (bot2/main.py never imports it) as an isolation boundary so
  real-order code can never be reached accidentally from the live runtime,
  and a dedicated test enforces that boundary. **Deleting it would break a
  safety test and remove the real-order isolation boundary.** The other
  "references" I found (learning_monitor.py, order_book_depth.py,
  signal_engine.py, state_manager.py, src/core/invariants.py) are all
  **comments/docstrings**, not imports — stale documentation, not evidence
  of aliveness, but also not evidence it's safe to delete.
  → **README.md's description of it is accurate for what it is; the "bug"
  is that it's not obvious from the README that it's an intentionally-
  isolated safety boundary rather than an active service.**

- `risk_manager.py`: real import found in `shared/bot1/execution_bot.py`.
  `shared/bot1/` is a **separate, self-contained legacy bot** (own
  `run.py`, own `risk_engine.py`) not referenced by any systemd/deploy/CI
  config — orphaned relative to the live `bot2` system, but not provably
  abandoned/authorized-for-deletion by me. Deleting `risk_manager.py` would
  break that standalone tool for anyone who still runs it.

- `meta_controler.py`: still genuinely zero references anywhere in the repo
  (code, tests, configs) after a repo-wide search — the one candidate that
  really is dead.

**Verdict: REJECTED as a deletion task.** Deleting `execution_engine.py`
or `risk_manager.py` would be a destructive, hard-to-reverse action based on
an incomplete import-graph read — exactly the kind of mistake this
re-analysis step exists to catch. **Decision: no files deleted.** Only a
1-line README clarification for `execution_engine.py`'s real role.
`meta_controler.py` deletion is safe but low-value housekeeping, not a bug
fix — left untouched, noted as optional cleanup for the user to request
explicitly if wanted.

## Finding #4 — DEV_FADE retirement not enforced

**Re-verification:** confirmed in signal_generator.py:81,
`_DEV_FADE = os.getenv("PAPER_DEVIATION_FADE", "false").lower() == "true"`
— default OFF at the code level, so the "retirement" is respected unless an
env var overrides it in production. This requires checking the live
Hetzner `.env` + systemd drop-in override (per project memory,
`systemd/service.d/override.conf` wins over `.env` — see
`project_systemd_dropin_override_precedence` memory).

**Verdict: CONFIRMED as a verify-only action**, no code change implied
unless the live value is found to be `true`. Executed as a read-only SSH
check (see FINAL_REPORT.md for result).

---

## Patch plan surviving this review

1. **Finding #1**: minimal patch — extract a single
   `_default_tp_sl_bps()` helper (or module-level constants) used by both
   `_normalize_position_for_loading()` (line 671-687) and the open-flow
   fallback (line 1763-1783), so the two paths cannot silently diverge
   again. No behavior change for the currently-configured 50/40 path;
   only the rare-trigger legacy-rehydration fallback changes from 35/30 →
   50/40 to match.
2. **Finding #3**: 1-line README.md clarification only. No file deletions.
3. **Finding #4**: read-only SSH verification of production env.
4. **Finding #2**: no patch; documented as follow-up recommendation.
