# Finding (not yet fixed): SKIP_SCORE_HARD short-circuits before discovery ever runs

**Date:** 2026-08-17 (found during routine monitoring, ~2.8 days after the
last deploy)
**Severity:** High -- zero trades opened for ~66+ hours in production
**Status:** Root-caused and evidenced. **Deliberately NOT patched this
session** -- see "Why not fixed now" below.

## Symptom

Multi-day monitoring gap revealed `closed_trades` grew by only 13 over
~67 hours (vs hundreds per 30 minutes during normal operation). Direct
investigation:

```
journalctl ... | grep 'PAPER_ENTRY\]'   # 0 lines in the last 48 hours
[HBLOCK] SKIP_SCORE_HARD ADAUSDT score=-0.070 ... idle=239328s zone=HEALTHY   threshold=0.020
[HBLOCK] SKIP_SCORE_HARD ETHUSDT score=-0.037 ... idle=239366s zone=CRITICAL  threshold=0.020
[HBLOCK] SKIP_SCORE_HARD SOLUSDT score=-0.121 ... idle=239393s zone=HEALTHY   threshold=0.020
```

`idle=239397s` = ~66.5 hours. The service itself never crashed or
restarted (`ActiveEnterTimestamp` matches the last deploy, 2026-08-14
11:44 UTC) -- this is a live, sustained, silent stall, not a crash.

## Root cause

`src/services/hardblock_adapter.py`'s `HardBlockZones.adjust()` **is
already working correctly**: at `idle_seconds > 900` it self-relaxes to
its most lenient possible setting (`relaxation="CRITICAL"`,
`hard_floor=0.02`, the lowest tier the ladder goes). This is confirmed
live -- the logged `threshold=0.020` matches exactly.

But the observed scores are **negative** (-0.070, -0.121, -0.037, ...).
`decision_score(ev, ws) = 0.7*ev + 0.3*ws`
(`realtime_decision_engine.py:2477-2479`) -- a negative score this
persistent and this deep can only happen if `ev` (expected value from the
primary signal path) is itself persistently negative, consistent with
this session's (and prior sessions', per project memory) repeated finding
that the primary/old signal path has near-zero-to-negative exploitable
edge. **No amount of threshold relaxation can rescue a negative score
against a positive floor** (0.02) -- the adaptive system was designed to
relax the bar, not to ever admit a negative-EV candidate outright, which
is a deliberate, sensible design choice in isolation.

The actual bug-shaped gap: `realtime_decision_engine.py:3564-3588`, the
`SKIP_SCORE_HARD` branch, ends in an unconditional `return None`
(line 3588). This function has a **separate, later** code path
(`REJECT_NEGATIVE_EV`, ~line 3774 onward) that routes exactly this kind of
negative-EV candidate through `_route_training_sample_through_p0_rde()` →
`maybe_open_training_sample()` (the "starvation discovery" exploration
mechanism this session extensively investigated and improved in
`_workspace/24`/`27`) -- but `SKIP_SCORE_HARD`'s early `return None` at
line 3588 means execution **never reaches that later code** when the
score-based hard floor is breached first. The two rejection paths
(score-based HARD floor vs. EV<=0 business-rule reject) are structurally
independent checks in the same function, and only one of them (the later,
EV-based one) is wired to the discovery/learning fallback that's supposed
to keep the bot minimally active during exactly this kind of extended dry
spell.

Confirmed via `is_unblock_mode()` (`realtime_decision_engine.py:2486`):
it correctly detects idle >= 900s, but the ONLY consumer of that signal
near `SKIP_SCORE_HARD` is a soft-zone fallback (line 3591,
`if not _skip_score_soft and is_unblock_mode() and _ev_adj >= 0.020 and
_score_adj >= 0.110`) that (a) is unreachable after the HARD branch's own
`return None`, and (b) requires *positive* `_ev_adj`/`_score_adj`
thresholds anyway, so it wouldn't help here even if reached.

## Why not fixed this session

This session already shipped a same-shaped gap-and-fix once today
(`_workspace/24` → `27`: the segment-skip fix caused an unintended total
admission stall, caught and fixed within the same session). Doing so again
in the more central, more historically fragile file
(`realtime_decision_engine.py`, 3500+ lines, the subject of numerous past
incidents per project memory: signal inversion bugs, RSI/ADX saturation,
cost-floor violations reaching production via untracked config) within the
same extended session raises real risk of compounding mistakes in exactly
the module where a subtle error is hardest to detect and most consequential
to get wrong. A correct fix requires reconstructing the exact `signal`
dict and adjusted-EV state available at the `SKIP_SCORE_HARD` branch (not
fully traced this session -- the function's data flow from signal
construction to this point spans hundreds of lines not yet read in full)
to safely call the same P0-routing + sampler functions the
`REJECT_NEGATIVE_EV` path already uses, rather than inventing new logic.

Critically: **the current behavior, while resulting in zero trades, is not
unsafe.** A stalled bot doesn't lose money or corrupt state; it just
collects no new data. This is the safer failure mode to leave in place
pending a properly scoped, dedicated investigation, versus a rushed fix to
the most sensitive file in the codebase.

## Recommendation for a future session

Route `SKIP_SCORE_HARD` through the same discovery mechanism
`REJECT_NEGATIVE_EV` already uses, gated by an extreme, conservative idle
threshold (e.g. >= 1800s-3600s, deliberately higher than the 900s used
elsewhere, since this is a more consequential last-resort escape hatch)
instead of unconditionally `return None`-ing. Needs: (1) full read of the
function's `signal`/`_score_before_adj`/`ev` construction leading up to
line 3564 to confirm all fields `_route_training_sample_through_p0_rde()`
and `maybe_open_training_sample()` expect are actually available and
correctly populated at that point; (2) a regression test exercising the
exact HARD-floor-breach-during-critical-idle scenario; (3) careful staged
verification (PLAN-mode dry run, then a short, closely-monitored live
window) given this file's incident history.

## What's confirmed still working

- Quota fix (`_workspace/26`): reads=768/50000 after ~2.8 days --
  overwhelming confirmation the audit_worker fix holds.
- Service stability: continuous uptime since the last deploy, no crashes.
- The segment-skip safety valve (`_workspace/27`) did work correctly when
  it was reachable -- 33 hits logged in the last healthy window before
  this deeper stall took over entirely.
- Lifetime metric (`_workspace/23`) remains stable/consistent across the
  gap, no anomalous swings.
