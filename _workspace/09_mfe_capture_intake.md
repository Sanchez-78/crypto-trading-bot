# Intake: MFE-not-harvested TIMEOUT exits (unpatched, deferred from task 15/16)

## Established evidence (from earlier forensic pass, task 15)
Last-100 window (pre-stall-fix data): 76 TIMEOUT exits split:
- 41 trades: never reach +12bps favorable (avg MFE 5.4bps) — weak entry edge,
  timeout at avg -23.9bps. NOT this investigation's target (separate,
  bigger "entry quality" question).
- **35 trades: reach avg +21.3bps MFE (well past the 12bps TP zone) but
  capture only +1.1bps at close.** THIS is the target — TP should have
  fired on the favorable move and didn't.

Counterfactual: if these 35 had closed at TP, total P&L improves ~38%
(-0.9286 -> -0.5708 USD in that sample window) — real, but secondary, not
enough alone to flip to profitable.

## Candidate mechanism (from forensic Finding 6, unconfirmed)
Two candidate code paths in paper_trade_executor.py, either could produce
"high MFE, no TP fire, TIMEOUT anyway":
1. `[TP_SL_INVALID]` guard (~line 2148-2170, V10.46) — skips TP/SL eval
   entirely if pos["tp"]/["sl"] is None/0, falls through to timeout-only.
2. The AGE-BASED timeout scanner (`check_and_close_timeout_positions`,
   ~line 1951-1970) — force-closes on age using last_price with **NO TP/SL
   check at all**. If this scanner fires and closes a position BEFORE the
   tick-based TP/SL evaluator (`update_paper_positions`) gets a chance to
   see a favorable tick, MFE would be recorded (from the price-tracking
   code that updates max_seen on every tick) but TP never evaluated for
   that specific close.

Prior investigation couldn't pin which mechanism via logs (journal
retention was ~7min at the time). Longer retention is now available (bot
has been running cleanly since the 08:07:47 UTC deploy).

## What to verify with live evidence
1. Set up or confirm `_DEBUG_TP_SL_EVAL=1` is NOT needed -- first check
   if the two candidate log markers already fire under normal logging:
   `[TP_SL_INVALID]`, and whatever check_and_close_timeout_positions logs
   on a force-close (grep the function for its own log lines first).
2. Correlate: for trades closing via TIMEOUT with high mfe_gross_bps
   (>=12) in the NOW-FRESH cache.sqlite data (post-stall-fix, more data
   accumulating live), check which code path actually closed them --
   the age-based scanner or the tick evaluator's own timeout branch.
3. If it's the age-based scanner (no TP check): is this a genuine gap
   (scanner should check TP/SL before defaulting to age-timeout) or
   intentional (age cap is meant to be an absolute ceiling regardless)?
4. Do NOT patch until the mechanism is pinned by evidence -- this project's
   history includes multiple "TP/SL evaluation" cycles (V10.18, CYCLE#15,
   24, 28, V10.46) that each fixed a DIFFERENT bug in this exact area; read
   that history before touching this code, high risk of reintroducing a
   past regression if changed carelessly.

## Scope
PAPER only. Do not touch real-trading gates. No recurring/cron loop.
