# URGENT intake: bot completely stalled (0 opens for ~55+ min)

## Confirmed live (2026-08-06 ~07:37 UTC)
- `cryptomaster.service`: active, NRestarts=0, same PID since 06:09:13 — NOT crashed/restarted.
- Open positions: **0**.
- Last closed trade in cache.sqlite: **06:42:22 UTC** (~55 min stale as of 07:37).
- Price feed is alive: ~2000 tick/signal log lines in a 5-min sample.
- `[WATCHDOG] Critical idle (15min) -> enabling micro-trades` firing repeatedly.
- `[CRITICAL] DASHBOARD_ZERO: Dashboard stale: 4202s without update` — the
  bot's OWN internal monitor is flagging this.
- Every entry attempt in the sample is blocked:
  `[PAPER_ENTRY_BLOCKED] symbol=ETHUSDT reason=weak_ev ev=0.0000
  threshold=0.0100 bucket=PAPER_STARVATION_DISCOVERY` (and `bucket=None`).

## Code trace done so far (static, needs live confirmation)
`paper_trade_executor.py:1400-1412`: `ev = float(signal.get("ev") or 0.0)`;
`if ev < _MIN_EV_THRESHOLD: ... return {"status":"blocked","reason":
f"weak_ev_below_{_MIN_EV_THRESHOLD}"}`. This is an **unconditional** gate
(V10.26 comment: "Changed from 'and bucket == C_WEAK_EV_TRAIN' to ALL
trades") — applies regardless of bucket, INCLUDING
`PAPER_STARVATION_DISCOVERY`.

But the log immediately preceding entry attempts shows:
`[PAPER_AGGRESSIVE_MODE] symbol=ETHUSDT side=BUY bucket=PAPER_STARVATION_DISCOVERY
reason=REJECT_NEGATIVE_EV allowed=TRUE (ALL GATES DISABLED)` — i.e. an
EARLIER stage (realtime_decision_engine.py / admission routing) explicitly
says "ALL GATES DISABLED" for this bucket, yet the LATER weak_ev gate in
`open_paper_position()` still blocks it. Either:
(a) this is by design — weak_ev is a hard floor even discovery mode must
    respect, and the REAL question is why `ev` is coming through as exactly
    0.0000 (missing/stripped, not a real computed value) for every single
    discovery-routed signal, or
(b) "ALL GATES DISABLED" is supposed to bypass this specific gate too and
    doesn't — a genuine wiring bug.

`ev=0.0000` recurring EXACTLY (not varying) across many different signals
strongly suggests the EV value is not being carried from the upstream
decision (which computed e.g. `ev_raw=-0.2341 ev_final=-0.1426` for one
logged case) into the `signal` dict that reaches `open_paper_position()` —
i.e. a **field-carrying/wiring bug in the training-route re-admission path**
(`P0_RDE_TRAINING_ROUTE_ADMIT` / `PAPER_AGGRESSIVE_MODE` construction),
not a genuine "no edge right now" market condition.

## What must be verified with live/code evidence, not guessed
1. Is this NEW (started recently, e.g. correlating with the DEV_FADE
   disable or dashboard-service restart earlier today) or a LONG-STANDING
   condition that happened to be masked while DEV_FADE was providing enough
   real-EV signals that this path rarely got exercised? Check journalctl
   further back (retention allowing) and/or cache.sqlite exit timestamps
   across the whole day for prior stalls of similar length.
2. Trace the EXACT code path from `realtime_decision_engine.py`'s
   `P0_RDE_TRAINING_ROUTE_ADMIT` / whatever emits `[PAPER_AGGRESSIVE_MODE]
   ... allowed=TRUE` through to the call into `open_paper_position()` (or
   whatever the actual entry function is) — find where/whether the `ev`
   key is set, overwritten, or dropped from the `signal`/`extra` dict along
   the way. Grep for `PAPER_AGGRESSIVE_MODE`, `P0_RDE_TRAINING_ROUTE_ADMIT`
   in signal_generator.py / realtime_decision_engine.py / wherever they
   live (identify the actual file, don't assume).
3. Is `_MIN_EV_THRESHOLD` (`PAPER_MIN_EV_THRESHOLD`, default 0.01) meant to
   apply to `PAPER_STARVATION_DISCOVERY`/exploration-bucket trades at all?
   Check other admission code (`paper_training_sampler.py`,
   `forced_explore_gates.py`) for the INTENDED design — does exploration
   mode have its own EV computation that's supposed to flow through, or is
   it supposed to be genuinely EV-agnostic (explicitly bypass this
   threshold) since its whole purpose is forced discovery under starvation?
4. How long has PAPER_STARVATION_DISCOVERY been the dominant/only bucket
   getting routed since DEV_FADE was disabled (06:09) — i.e. did removing
   DEV_FADE (which was providing plenty of real signals, just bad ones)
   inadvertently starve the bot down into a discovery-only mode that hits
   this latent bug, whereas before DEV_FADE masked it by always having
   *something* with a real EV to trade?

## Severity
This is currently blocking ALL paper trading — 0 new positions in 55+
minutes and counting while the process runs normally otherwise. Highest
priority open item.
