# Live-wiring plan for P0.8-P1.2 (Gate G7 scope)

**Date:** 2026-08-10, autonomous loop cycle 25
**Status:** DESIGNED (reconnaissance complete), NOT YET IMPLEMENTED

## Cycle 24 hotfix effect, measured

TP/SL cost-floor hotfix (`bb8f6f6`, deployed 06:43 UTC) effect after ~35 min:

| | before (12:00 sample) | after (~35min post-deploy) |
|---|---|---|
| WR (recent 100) | 12.0% | 13.0% |
| PF (recent 100) | 0.411 | 0.491 |
| flats (of 100) | 60 | 66 |

Flat as predicted in `_workspace/17_...md`: removing the guaranteed-losing
geometry gives a small PF bump (fewer bps lost per losing trade) but does
**not** move WR meaningfully -- confirms the 2026-08-07 grid-search finding
that no TP/SL geometry fixes this. `SAFE_MODE_FIREBASE_DEGRADED` cleared on
its own at the 07:00 UTC boundary (`degraded: False` confirmed) -- the
reset-logic fix from last week is working correctly; the underlying daily
read-quota burn source (rec #5, `risk_engine.py:695`) is a separate,
still-open item, not blocking right now.

## §17 risk guard: built and deployed (inert)

`p0_risk_guard_v1.py` (commit `9d75b18`) closes a second, independent gap:
`signal_router.evaluate_signal_for_paper_entry()` had `risk_allowed`
hardcoded `False` since its first commit -- the P0.8+ pipeline could never
have admitted a signal even if wired in. This is now fixed, but remains
**inert** because nothing calls `generate_candidates()` or
`evaluate_signal_for_paper_entry()` from the live loop yet (confirmed,
unchanged by this commit).

## Candle source for the new strategies: confirmed to already exist

`src/services/binance_client.py:fetch_candles(symbol, interval) -> list[dict]`
returns exactly the schema `strategy_trend_cost_aware_v1.py`,
`strategy_volatility_breakout_v1.py`, and `strategy_sideways_mean_reversion_v1.py`
were all written against (`{"open_time", "open", "high", "low", "close",
"volume"}`, chronological, oldest first) -- a REST `/api/v3/klines` call,
already used once at startup by `signal_generator.py:warmup()`. This
resolves the open question of where live candle data comes from without
needing to build the full §8 bookTicker/aggTrade tick-to-candle aggregation
pipeline from scratch.

**Scope decision:** use periodic REST polling (cached per symbol, refreshed
on an interval matching the candle timeframe -- e.g. every 60s for 1m
candles, not per-tick) rather than building live WebSocket-based candle
construction in this pass. §8.1 says "Do not use high-frequency REST
polling" -- a 60s-cadence poll for ~8 symbols is not high-frequency (it's
the same order of magnitude as the existing `warmup()` call), and is an
honestly-scoped MVP consistent with §5.3's "small gated phases": build the
minimum that lets real evidence start accumulating, disclose that full §8
stream normalization is deferred.

## Remaining work to actually admit a signal end-to-end

1. **Candle cache module** (new, small): per-symbol rolling window backed
   by `binance_client.fetch_candles()`, refreshed on a bounded cadence,
   in-memory only, bounded size (no unbounded growth, §8.4).
2. **Wiring glue** (new module, e.g. `p0_8_plus_candidate_loop.py`): per
   tick/interval, for each symbol: build candle window -> call each
   strategy's `generate_candidates()` (trend, breakout, mean-reversion) ->
   for each StrategySignal, call `signal_router.evaluate_signal_for_paper_entry()`
   -> on `admitted=True`, call `paper_trade_executor.open_paper_position()`
   with the signal's fields. This becomes call site #7 in Gate G0's entry-path
   inventory (`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` §3) -- must be
   documented there, and a bypass test must confirm ONLY this glue module
   (not the strategies, not the router, not the risk guard) ever reaches
   `open_paper_position()` for these three strategy_ids.
3. **Registration**: call each strategy's `build_registration()` into
   `strategy_registry.get_default_registry()` at startup (`allowed_symbols`
   needs to be populated per deployment config -- currently `frozenset()` in
   all three `build_registration()`s, deliberately left to the caller).
4. **Call site**: wire the glue's tick function into `start.py` or
   `realtime_decision_engine.py`'s existing loop, gated behind a new env
   flag (e.g. `PAPER_P0_8_PLUS_PIPELINE_ENABLED`, default `false` so a
   deploy of this code does not silently change live behavior until
   explicitly flipped) -- mirrors the existing (currently-dead)
   `PAPER_P0_DIRECT_SIGNAL_ROUTER_ENABLED` flag naming convention found in
   the live systemd overlay, reused rather than inventing a new one if it
   turns out to already be the intended hook (needs verification: that flag
   is currently unreferenced by any code, so either adopt it properly or
   confirm it's dead and pick a new name -- do not leave two flags implying
   the same thing).
5. **Tests**: unit (glue logic with fakes), integration (registration +
   router + risk guard together against synthetic candle fixtures),
   bypass (only the glue module reaches `open_paper_position` for these
   strategy_ids), and a dry-run/shadow mode first (log what WOULD have
   opened without actually opening) before flipping the env flag live.
6. **Full evidence-based-patch-orchestrator review** (trading-safety-agent,
   reviewer-agent, test-regression-agent) before deploying with the flag
   defaulting anything other than `false`.

## Why this is scoped as its own cycle, not crammed into this one

§5.3: "Implement the work in phases... Do not combine all changes into one
unreviewable patch." This session has already landed three separate,
independently-reviewable commits today (TP/SL hotfix, risk guard, this
plan doc). The wiring glue is the first change in this program that would
actually alter live bot behavior (once the flag is flipped) -- it deserves
its own dedicated forensics-informed patch-author/review/deploy cycle
rather than being appended to an already-large session.
