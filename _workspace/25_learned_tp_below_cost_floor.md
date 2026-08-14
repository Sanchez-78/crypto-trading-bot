# Finding + fix: live TP was cost-floor-violating, and the learned-TP path had drifted to zero net edge

## CORRECTION (post-deploy verification, same day)

The "live TP=35bps violates at cost=18bps" finding below was measured via a
standalone SSH diagnostic script that called `load_dotenv()` -- which reads
`.env`, not the systemd-injected environment the real running process
actually uses. `_workspace/project_systemd_dropin_override_precedence.md`
(prior session) already documented that PAPER_* params are authoritative
via `service.d/override.conf`, not `.env` -- I re-made exactly that mistake
here before catching it. Verified directly on the live systemd process
after deploying this fix: `PAPER_FEE_PCT=0.0004` / `PAPER_SLIPPAGE_PCT=0.0`
**are** set in the systemd override (cost = 4bps, not 18bps); `PAPER_TP_
ZONE_BPS`/`PAPER_SL_ZONE_BPS` are **not** set there, so they fall through
to `.env`'s 35/25. At the real 4bps cost, 35bps TP / 25bps SL needs only
~23.3bps to clear the floor -- **the currently-active production geometry
was NOT actually violating.** No `[TP_SL_COST_FLOOR_VIOLATION]` logged at
this deploy's startup, and no `[TP_COST_FLOOR_CLAMPED]` fired on live
entries afterward -- both consistent with a compliant live geometry, not a
bug in the fix.

The fix itself is still correct and worth keeping: it reads the same
`_ROUND_TRIP_COST_BPS`/`_MAX_BREAKEVEN_TP_SHARE` module globals the rest of
the file already uses (so it automatically sees the real 4bps at runtime,
not my flawed diagnostic's 18bps), and it still closes two real, live gaps:
(1) the learned-TP path (`regime_tp_strategy`) had adapted to 18bps for
SOLUSDT/BEAR_TREND, which **does** violate even at the correct 4bps cost
(needs ~23.3bps) -- it just isn't the path currently winning in production,
since the env override takes precedence; (2) the `trade_executor`-provided
TP/SL path had zero cost-floor protection of its own. Both remain latent
regressions-in-waiting (e.g. if `PAPER_TP_ZONE_BPS` is ever removed from
`.env`, as has happened by design in a past cost-floor fix this session),
now closed. Kept as a defense-in-depth fix, not the single root cause of
the WR problem it first looked like.

---


**Date:** 2026-08-14
**Trigger:** Operator directive "zapoj vse co pomuze k uspesnosti bota a jeho uceni"
(wire in everything that helps the bot's success and its learning)

## Forensic evidence

While verifying whether `regime_tp_strategy` (adaptive per-regime TP learning
in `paper_adaptive_learning.py`) is actually consumed anywhere -- initially
suspected it was dead code like `segment_weights`' admission-side gap
(`_workspace/24_...md`), but confirmed it IS wired: `paper_trade_executor.
open_paper_position()` calls `_learning_instance.get_regime_tp_target(regime,
atr_pct)`, which reads `self.regime_tp_strategy[regime][vol_band]["tp_pct"]`.

Checked the live values used, though, and found two compounding problems:

1. **The live, env-configured TP itself is cost-floor-violating.**
   `validate_tp_sl_cost_floor()` runs exactly once, at module import, against
   the static defaults -- and that startup `log.critical` (easy to miss, per
   its own comment) showed:
   ```
   [TP_SL_COST_FLOOR_VIOLATION] tp=35bps sl=25bps cost=18.0bps —
   TP leg does not clear cost with margin: tp=35.0bps < 2x cost (36.0bps)
   ```
   `_ROUND_TRIP_COST_BPS` is 18bps here (`_FEE_PCT=0.0015` + `_SLIPPAGE_PCT
   =0.0003`), not the 4bps figure from earlier session history -- the cost
   model itself has apparently changed since the last TP/SL fix. Worse: the
   *actual* binding constraint (break-even TP-hit-share <= 60%) requires
   **~46.7bps**, not just the 36bps the "2x cost" condition alone suggests
   (verified: `sl_net=43bps`, `tp_net_min = 43*(1-0.6)/0.6 = 28.67bps`,
   `+18bps cost = 46.67bps`). The live TP (35bps, from `PAPER_TP_ZONE_BPS`
   env) clears neither threshold.

2. **The learned-TP path had adapted itself to an even worse geometry.**
   Live logs: `[LEARNING_TP_USED] symbol=SOLUSDT regime=BEAR_TREND
   learned_tp=18.000% (18bps)` -- `regime_tp_strategy`'s adaptive rule
   (`_update_regime_tp_strategy()`, purely WR-reactive: widen TP if WR<45%,
   tighten if WR>55%, floor 10bps / ceiling 40bps) has **zero cost
   awareness**. At 18bps TP against an 18bps round-trip cost, a TP hit nets
   **~0bps** -- not a real edge, regardless of how often it's hit. This
   value never actually got used to open a position (the env-override branch
   wins whenever `PAPER_TP_ZONE_BPS` is set, which it currently is), but it
   demonstrates the adaptation logic itself can converge on a
   self-defeating geometry with nothing to stop it.

Both problems share the same root cause: `validate_tp_sl_cost_floor()`
exists and is correct, but is **never actually enforced** against the value
used to open a real position -- only checked once, at import, against
values that may not even be what's live.

## Fix (this session)

`open_paper_position()`: after `tp_zone_bps`/`sl_zone_bps` are resolved
(whichever of the three paths -- env override, learned TP, dynamic ATR --
set them), clamp `tp_zone_bps` **up** (never down) to the minimum TP that
would actually satisfy `validate_tp_sl_cost_floor()` for the current
`sl_zone_bps`/cost/max-breakeven-share, via a new `_min_valid_tp_bps()`
helper (inverts both of `validate_tp_sl_cost_floor`'s conditions and
returns whichever is binding -- usually the break-even-share one, not the
naive "2x cost" shortcut). Also applied the same clamp to the
`extra["tp_from_executor"]` path (currently superseded in production by the
env-override branch, but with zero cost-floor protection of its own if that
env var is ever removed -- closing the gap now rather than leaving a latent
regression for later).

This does not touch signal generation, admission, or which trades open --
only widens the TP distance on trades that would otherwise open with a
structurally non-profitable-even-on-a-win geometry. Logs
`[TP_COST_FLOOR_CLAMPED]` whenever it actually changes a value, so the
effect is auditable.

## Tests

`tests/test_tp_sl_cost_floor_invariant.py` (existing file, extended):
- `_min_valid_tp_bps()` reproduces the exact live-observed floor (~46.7bps
  for sl=25/cost=18/max_share=60%).
- The floor `_min_valid_tp_bps()` returns always itself passes
  `validate_tp_sl_cost_floor()` (round-trip consistency check across
  several sl/cost/max_share combinations).
- Confirms the break-even-share constraint (not the bare 2x-cost one) is
  correctly picked as binding when it's the larger requirement.
- End-to-end: `open_paper_position()` called with the exact live-observed
  violating env config (`PAPER_TP_ZONE_BPS=35`, `PAPER_SL_ZONE_BPS=25`,
  cost=18bps) opens a real paper position whose stored
  `tp_zone_bps_at_entry` is clamped above 35bps and passes
  `validate_tp_sl_cost_floor()`.

17/17 pass. Full `tests/test_paper_mode.py` + `tests/test_app_metrics_
contract.py` (deploy-gate test set) clean except the same pre-existing
local-env-only failure noted in `_workspace/24_...md`.

## Expected effect / what to watch

Every future TP-hit trade should now net a real positive edge (at least
clearing 2x cost with margin) rather than breaking even or worse. This
directly targets the profit-factor side of the goal (WR>55% + high P&L) --
distinct from `_workspace/24_...md`'s volume-mix fix, which targets WR via
trade selection. Watch `[TP_COST_FLOOR_CLAMPED]` log frequency (how often
the clamp actually fires -- tells us how far off the unclamped geometry
usually was) and the `exit_distribution` TP-share going forward.
