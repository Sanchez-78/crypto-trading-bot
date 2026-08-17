# Dead code removal: V4 genetic algorithm + V5.1 RL agent in bot2/main.py

**Date:** 2026-08-17
**Trigger:** Operator directive "odstran nepouzivany kod" (remove unused
code), the second step of "proved kompletni opravu procesu uceni,
odstran nepouzivany kod, pak vse znovu analyzuj" (complete repair of the
learning process, remove unused code, then re-analyze everything).

Follows directly from `_workspace/29_deep_learning_process_audit.md`'s
finding that the RL/DQN agent and V4 genetic-algorithm strategy selector
were fully dead code (defined, never called from the live path).

## What was removed from `bot2/main.py`

1. **Imports/instantiation** (former lines ~114-143): `from src.core.
   genetic_pool import GeneticPool`, `strategy_selector import
   StrategySelector`, `strategy_executor import StrategyExecutor`, and
   `from src.services.rl_agent import RLAgent` + `rl_agent_instance =
   RLAgent()`.
2. **Module-level state** (former lines ~334-352): `_genetic_pool`,
   `_strategy_selector`, `_current_strategy`, `_strategy_trade_count`,
   `_evolution_interval`, `_rl_agent`, `_state_builder`, `_reward_engine`,
   `_prev_state`, `_prev_action`, `_episode_reward`,
   `_rl_training_interval`.
3. **Dead functions**: `update_strategy_fitness(trade)` (the V4
   evolution-cycle handler -- contained `_genetic_pool.evolve()`,
   `_strategy_selector.select()`), `train_rl_agent(trade, ...)` (the DQN
   experience-replay trainer -- contained `.remember()`/`.replay()`),
   `rl_force_exploration()`, `rl_force_exploitation()`.
4. **`main()`'s one-time startup init block**: constructed the genetic
   pool, selected one initial "current strategy," bound the RL agent
   reference, and logged both -- all with zero downstream consumer once
   the (also-removed) functions above are gone.

## What was deliberately NOT removed

- The underlying module files (`src/core/genetic_pool.py`,
  `strategy_selector.py`, `strategy_executor.py`,
  `src/services/rl_agent.py`) are untouched. They're substantial,
  potentially reusable implementations; deleting entire files carries
  more risk (could break isolated unit tests of those modules even though
  they're unreachable from the live loop) for less benefit than removing
  the dead wiring in the live entry point, which is what actually matters
  behaviorally. A future session that decides to wire either system in
  for real, or to formally retire them, can act on
  `_workspace/29`'s recommendation with this context.
- `watchdog()`'s unused `agent=None` parameter and its
  `if agent and hasattr(agent, 'exploration_rate')` branch: `agent` is
  never passed a non-None value at either of its two call sites, so this
  branch was already effectively dead before and after this change --
  left alone as a smaller, lower-priority item not touched in this pass.

## Verification

- `python -m py_compile bot2/main.py`: OK.
- Exhaustive text sweep of the whole file confirmed zero remaining CODE
  references (only explanatory comments) to any removed name.
- Zero test files reference any of the removed names
  (`train_rl_agent`, `update_strategy_fitness`, `rl_force_exploration`,
  `rl_force_exploitation`, `rl_agent_instance`) -- this removal changes
  no test outcomes because no test ever exercised this code.
- Full regression sweep across every test touching `bot2.main`
  (`test_deploy_integrity.py`, `test_p11ap_hotfix.py`,
  `test_runtime_mode_startup_assertion.py`, `test_trading_env_guard.py`,
  `test_v5_legacy_bridge_hooks.py`,
  `test_paper_training_sampler_segment_skip.py`): 6 failures in
  `test_v5_legacy_bridge_hooks.py`/`test_deploy_integrity.py` confirmed
  identical before and after via `git stash` (pre-existing, unrelated --
  `open_paper_position()` admission/table-setup issues in that test file's
  own fixtures, nothing to do with this change). Deploy-gate test set
  (`test_paper_mode.py` + `test_app_metrics_contract.py`): clean except
  the same pre-existing local-env-only failure documented repeatedly
  elsewhere this session.

## A note on the RL agent's constructor cost

Removing `rl_agent_instance = RLAgent()` from module import time also
means the agent's constructor (whatever model-loading/initialization it
does) no longer runs on every process start -- a minor startup-cost
reduction as a side effect of removing genuinely dead weight, not a
deliberate optimization target of this change.
