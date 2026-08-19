# 41 — Duplicate closed-trade bug: P1.1AV fix (bucketed path), unbucketed path still open (cycle 109)

## Status: FIXED (bucketed path), DEPLOYED, LIVE-CONFIRMED. NEW FINDING: a separate, pre-existing unbucketed-path duplicate mechanism remains — needs its own cycle.

## Trigger

User asked: "nejsou nektere uzavrene obchody duplikovane?" (aren't some closed
trades duplicated?). Confirmed via SSH+sqlite: in a 1-hour window, 102 total
closed trades but only 48 distinct `(symbol, side, entry_price, exit_ts)`
combinations; worst cluster 13 near-identical SOLUSDT positions (same entry
price) within 1.86 seconds.

## Root cause (confirmed, fixed)

`_check_exploration_exposure_caps()` in `src/services/paper_trade_executor.py`
counted open positions by raw `explore_bucket` alone. Candidates admitted via
the internal P0.3C evidence-collection reroute (`trade_executor.py:2982` →
`open_paper_position()`) carry `training_bucket="A_STRICT_TAKE"` with
`explore_bucket=None` — so the symbol/bucket/symbol_bucket counts were
structurally 0 forever for that attribution, regardless of how many
identical positions were already open.

First attempted fix (P1.1AU, atomic re-check inside the insert lock) was
**REJECTED by reviewer-agent**: technically correct but inert for ~94% of
the affected volume (wrong bucket field), and the live cluster was proven
to be sequential admission through a no-op cap, not a concurrency race.

Root-cause fix (**P1.1AV**): added `_position_effective_bucket(p)` =
`training_bucket or explore_bucket`, mirroring the caller's own bucket
derivation (`open_paper_position:1621`); all three cap counts now use it.
P1.1AU retained as documented defensive hardening for a real but separate
TOCTOU window, explicitly relabeled as NOT the fix for the reported symptom.

## Review

- `reviewer-agent` (fresh dispatch on the corrected diff): **APPROVED WITH
  CONDITIONS**. Independently re-traced the root cause via
  `trade_executor.py:2982` + the P0.3C reroute at
  `paper_trade_executor.py:1739`, independently re-ran the mutation-kill,
  confirmed no over-blocking on RDE/P0.8+ admission paths (those set
  `training_bucket == explore_bucket` already, so the fix is a no-op there).
  Conditions (monitoring, non-blocking): expect a real throughput drop on
  the A_STRICT_TAKE path (intended); confirm P0.8+ evidence-collection still
  admits despite incidental additional tightening (now shares the symbol cap
  with strict_take).
- `trading-safety-agent`: **PASS**. Paper-only scope confirmed (zero touches
  to `trade_executor.py`/`risk_engine.py`/broker clients); fail-closed on
  exception verified in code (no try/except around the new cap calls, insert
  is the last statement in the lock); no real-trading gate touched; no
  orphaned state on early return (all commit-style side effects run after
  the insert). Flagged (non-blocking): scope the commit to exactly the two
  reviewed files, since the working tree carries unrelated concurrent
  dashboard/SEC-01 edits from other sessions.

## Deploy

Commit `b921d54`, pushed, deployed via gated `hetzner-deploy-apply.yml`
(PLAN run 32255837352 → DEPLOY run 32255897017), both green. Service active
at `b921d54b8e6c...`, `TRADING_MODE=paper_train` verified before switching.

## Live post-deploy verification

**Sanity check 1 (admission not stalled): PASS with caveat.** Admission hit
zero for ~15 min (13:03:46–13:18:45 UTC) — this was the 2-slot global
`max_open_per_bucket` cap being fully held, not a stall; it cleared once
both those positions closed (SL). Recovered on its own; last measured
throughput ~35/hr vs pre-deploy baseline 22-25/hr — same ballpark, not
collapsed.

**Methodology note for future cycles:** journalctl on the Hetzner box only
retains ~7 minutes at current log volume (~134k lines/hr) — an hourly
aggregate pulled from journalctl mid-investigation was a pure rotation
artifact and had to be discarded/rebuilt from `cache.sqlite` instead
(`closed_trades.entry_ts`, which persists). Don't trust hourly journalctl
aggregates on this host going forward.

**Sanity check 2 (caps firing, fix live-active): PASS.** Confirmed via live
log lines:
```
[PAPER_ENTRY_BLOCKED] symbol=ETHUSDT reason=max_open_per_symbol open_symbol=1 bucket=A_STRICT_TAKE
[PAPER_ENTRY_BLOCKED] symbol=ADAUSDT reason=max_open_per_bucket bucket=A_STRICT_TAKE open_bucket=2
```
`open_symbol=1` with `bucket=A_STRICT_TAKE` is exactly the counter that read
0 pre-fix. Pre-deploy the caps logged zero blocks for this attribution; now
they fire continuously, holding bucketed positions to 1/symbol, 2/bucket as
designed. `[PAPER_ENTRY_BLOCKED_RACE]` count = 0 (P1.1AU defensive block
present, hasn't needed to fire — consistent with the "sequential not
concurrent" finding).

## NEW FINDING: duplicates still occur on the UNBUCKETED admission path

Not a regression from `b921d54` — pre-existing, separate mechanism, now the
dominant remaining duplicate source. `_check_exploration_exposure_caps()`
line ~1401:
```python
if not bucket:
    return None  # Not an exploration trade, skip caps
```
Candidates arriving via `reason=P0_GATE` carry `training_bucket=None` AND
`explore_bucket=None` — effective bucket is `None`, so the entire
exposure-cap block is skipped by design (it was never meant to gate
non-exploration trades). The only remaining guard for these is
`_SYMBOL_CAPS["ETHUSDT"] = 10` (line ~168), which permits up to 10
concurrent ETHUSDT positions.

Live evidence, post-deploy: `ETHUSDT BUY @1936.095 tb=None eb=None` × 4 (all
admitted in the same second, 13:18:45 UTC) and `ETHUSDT BUY @1937.895
tb=None eb=None` × 2 (both admitted 13:21:06 UTC). 4 of these already closed
on TIMEOUT with `training_bucket=None`.

**User's original symptom is therefore only partially closed**: the
`training_bucket`-attributed clusters (SOLUSDT/A_STRICT_TAKE etc.) that
triggered this investigation are fixed and live-confirmed blocked. A
different, pre-existing, unattributed (`P0_GATE`, both bucket fields None)
admission path produces its own duplicate clusters and was not in scope for
P1.1AV (which only fixed the bucket-field *counting* logic — it never
applied to unbucketed candidates in the first place, by original design).

## Recommended next step (separate future cycle, needs its own forensics)

Design a cap (or same-price/same-second dedupe) for unbucketed `P0_GATE`
admissions specifically — likely either (a) give unbucketed candidates a
real per-symbol concurrency cap independent of `_SYMBOL_CAPS`'s generous
default-10, or (b) add an explicit same-symbol-same-side-same-price (or
tight price band) dedupe window at admission time regardless of bucket
attribution. Needs its own root-cause trace of the `P0_GATE` admission path
(why are 4-6 near-identical candidates being generated/admitted in the same
second in the first place — is this a signal-generation duplication issue
upstream of `open_paper_position()`, or purely an admission-cap gap?) before
a minimal patch is designed, per this session's standing evidence-first
discipline.
