# Deep audit: the learning process and automatic strategy adjustment

**Date:** 2026-08-17
**Trigger:** Operator directive "udelej hlubokou analyzu procesu uceni a
automaticke upravy strategie" (deep analysis of the learning process and
automatic strategy adjustment)

**Method:** For every module in the codebase whose name suggests it learns
or adapts strategy, traced whether it is actually reachable from the true
live entry point (`start.py` → `bot2.main.main()`) and, if reachable,
whether its *output* is ever consulted by anything that affects a real
trading decision -- not just whether it's imported or defined. This is the
same "compute vs. consume" test that found the `segment_weights` gap
(`_workspace/24`) and the `SKIP_SCORE_HARD` gap (`_workspace/28`) earlier
this session, applied systematically across the whole codebase.

## Summary table

| Mechanism | Computes/updates? | Consulted by a live decision? | Verdict |
|---|---|---|---|
| `segment_weights` (per-segment adaptive weight) | Yes, correctly (`_update_segment_policy`) | Yes — size_mult for EV>0 candidates (pre-existing); admission skip for confirmed-bad segments in the discovery path (**fixed this session**, `_workspace/24`+`27`) | **LIVE** |
| `regime_tp_strategy` (adaptive TP per regime+vol) | Yes, correctly (`_update_regime_tp_strategy`) | Yes — `get_regime_tp_target()` called from `paper_trade_executor.open_paper_position()` (confirmed via live `[LEARNING_TP_USED]` logs) | **LIVE** |
| `lifetime_pf`/`lifetime_expectancy` | Yes, now a true cumulative (**fixed this session**, `_workspace/23`) | Dashboard display + REAL_READY lifecycle gating (a safety gate, not an admission input) | **LIVE** (informational/safety scope) |
| `_STARVATION_DISCOVERY_BUCKET_COOLDOWN` | Yes | Yes, consulted in admission | **LIVE but weak** — trigger requires `pf==0.0` exactly (zero wins), never true with any real winners present; has not fired in the live history checked this session |
| `_SEGMENT_COOLDOWNS` (C_WEAK_EV_TRAIN-scoped) | Yes | Yes, consulted in admission | **LIVE but narrow-scoped** — only watches `admission_bucket=="C_WEAK_EV_TRAIN"`, never the dominant `PAPER_STARVATION_DISCOVERY` bucket |
| RL/DQN agent (`src/services/rl_agent.py`, `bot2.main.train_rl_agent()`) | **No** | **No** | **FULLY DEAD** — `train_rl_agent` appears exactly once in `bot2/main.py`: its own `def` line. Never called. `.remember()`/`.replay()` never execute; the agent never trains, let alone gets consulted. `RLAgent.predict()`/`.act()` is never called anywhere in `src/services/` outside its own file. |
| V4 Genetic Algorithm strategy evolution (`_genetic_pool`, `_strategy_selector`, `_current_strategy` in `bot2/main.py`) | **No** | **No** | **FULLY DEAD** — `update_strategy_fitness()` (the function containing `_genetic_pool.evolve()` and `_strategy_selector.select()`) appears exactly once: its own `def` line. Never called. Even fitness *tracking* never runs. |
| `strategy_learner.py`, `filter_learner.py`, `feature_learner.py`, `conviction_learner.py` | Unknown (not traced in detail) | **No** | **UNREACHABLE** — only referenced by `learning_system.py`, which is itself not imported by `bot2/main.py`, `realtime_decision_engine.py`, or `paper_trade_executor.py` |
| `auto_strategy.py`, `auto_walkforward.py`, `feature_pruning.py` | Unknown | **No** | **UNREACHABLE** — zero references anywhere outside their own files |
| `parameter_tuner.py`, `learning_optimizer.py` | Unknown | **No** | **UNREACHABLE** — only referenced by `learning_monitor_v2.py`, itself not imported by the 3 live core files |
| `learning_engine.py` | Unknown | **No** | **UNREACHABLE** — referenced by `learning_system.py` and `metrics_api.py`, neither imported by the live core |
| `feature_weights.py` | Unknown | Possibly, very indirectly | **LIKELY UNREACHABLE** — only referenced by `trade_executor.py` (the *real*-order executor, not paper), which the live paper-mode files import only for 4 narrow, unrelated functions (`get_close_lock_health`, `get_open_positions`, `can_open_unblock_trade`, `record_unblock_trade`, `MIN_TP_PCT`) — no evidence `feature_weights` functionality is on that call path |
| `strategy_learning.py` | Unknown | Possibly, indirectly | **LIKELY UNREACHABLE** — only referenced by `learning_integration.py`, imported by `paper_trade_executor.py`; not traced further this session (lower priority given the pattern already established) |
| `src/optimized/orchestrator.py` (a whole alternate "V5 orchestrator" that DOES reference `train_rl_agent`) | N/A | N/A | **NOT THE LIVE ENTRY POINT** — `start.py` imports `bot2.main.main`, not this module. Confirms `orchestrator.py` is an abandoned/parallel implementation, not what's actually deployed. |

## The real, live learning loop (as of this audit)

Only **two** mechanisms genuinely close the loop from "the bot learns
something" to "the bot's behavior changes as a result":

1. **`segment_weights`** — downweights/upweights position sizing for
   EV>0 candidates per `symbol:regime:side` segment based on rolling
   performance, and (new this session) hard-skips further discovery-path
   admissions into segments already conclusively proven bad.
2. **`regime_tp_strategy`** — nudges the take-profit target per
   `regime:volatility_band` up/down every 50 closes based on win rate.

Both are real, both are evidenced live in production logs
(`[PAPER_POLICY_ADAPTATION]`, `[LEARNING_TP_USED]`), and both were
touched/improved this session. Everything else with "learning" in its
name or docstring in this codebase -- and there is a *lot* of it, per the
sheer module count seen in `journalctl`'s `[PATH] SERVICES` debug dump
earlier this session -- is either fully inert (RL agent, genetic
algorithm) or structurally unreachable from the process `start.py` actually
launches (a long tail of `*_learner.py`/`*_optimizer.py`/`*_engine.py`
modules).

## Why this matters for the WR>55%/high-P&L goal

The codebase's *apparent* sophistication (a DQN reinforcement learner, a
genetic strategy-evolution system, a dozen specialized `*_learner.py`
modules) is almost entirely cosmetic from a live-behavior standpoint. The
actual adaptive surface area the bot has to work with is much smaller:
one size/admission weight and one TP target, both scoped to a handful of
`symbol:regime:side` combinations. This is consistent with -- and helps
explain -- why the bot's performance has been so persistently hard to move
with incremental fixes this session: there simply isn't much live
adaptive machinery to lean on. The two real levers were both found to have
real gaps (documented and partially fixed this session), but even fully
correct, they're a small toolkit against a signal generator whose EV has
been independently confirmed near-zero-to-negative across this session and
prior ones (per project memory, 4 independent historical analyses).

## What this analysis does NOT do

This is intentionally an audit, not a fix. Wiring the RL agent or the
genetic strategy selector into the live decision path would be a
substantial design task (what state/action/reward should the RL agent
actually optimize? what parameters should a "selected strategy" actually
override, and how does that interact with the existing segment_weights/
regime_tp_strategy mechanisms so they don't fight each other?) -- not a
narrow, evidence-scoped patch of the kind this session has otherwise
stuck to. Recommending it as a candidate for a dedicated future design
session, not attempting it here.

## Recommendation priority for a future session

1. **`_workspace/28`'s `SKIP_SCORE_HARD` fix** — still the top blocker;
   without it, even the two live mechanisms above never get a chance to
   run when EV/score is persistently negative.
2. Decide whether to **delete or genuinely wire in** the RL agent and
   genetic algorithm — dead, fully-built subsystems sitting in the
   codebase are a maintenance and comprehension cost even if harmless at
   runtime (someone reading `bot2/main.py` today would reasonably assume
   `train_rl_agent`/`update_strategy_fitness` are part of the live loop;
   they are not).
3. Widen the two narrow existing cooldown mechanisms
   (`_STARVATION_DISCOVERY_BUCKET_COOLDOWN`'s `pf==0.0`-exact trigger;
   `_SEGMENT_COOLDOWNS`'s `C_WEAK_EV_TRAIN`-only scope) now that
   `segment_weights` covers some of the same ground more effectively --
   possibly consolidate rather than maintain three overlapping
   mechanisms.
