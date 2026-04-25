# RTK Commands for CryptoMaster V10.13s.4

Complete reference for all RTK commands covering 8 priorities.

## Priority 1: Canonical State
Module: src/services/canonical_state.py

```
rtk read src\services\canonical_state.py
rtk grep "initialize_canonical_state" bot2\main.py
rtk grep "get_authoritative_trade_count" src
rtk grep "Canonical state" bot2\main.py
```

## Priority 3: Economic Health
Module: src/services/learning_monitor.py

```
rtk grep "lm_economic_health" src
rtk grep "profit_factor" src
rtk grep "scratch_rate" src
rtk grep "Economic:" src\services\learning_monitor.py
```

## Priority 4: Bootstrap Risk Reduction
Module: src/services/execution.py

```
rtk grep "is_bootstrap_reduced_mode" src
rtk grep "size" src\services\execution.py
rtk grep "BOOTSTRAP_REDUCED_MODE" src
```

## Priority 2: Scratch Exit Forensics (DEEP)
Module: src/services/scratch_forensics.py

```
rtk read src\services\scratch_forensics.py
rtk grep "LOSSY_PREMATURE" src
rtk grep "instrument_scratch_exit" src
rtk grep "health_decomposition_v2" src
```

## Priority 6: Forced-Explore Gates (DEEP)
Module: src/services/forced_explore_gates.py

```
rtk read src\services\forced_explore_gates.py
rtk grep "is_forced_explore_allowed" src
rtk grep "SKIP_FE_GATE" src
```

## Priority 7: Economic Gate
Module: src/services/realtime_decision_engine.py

```
rtk grep "economic_gate" src
rtk grep "SKIP_ECONOMIC" src
```

## Priority 8: Dashboard

```
rtk grep "Economic:" src
rtk grep "BOOTSTRAP_REDUCED_MODE" src
```

## System Check

```
rtk grep "canonical_state\|economic_health\|scratch_forensics\|forced_explore" src
rtk grep "SKIP_ECONOMIC\|SKIP_FE_GATE" src\services\realtime_decision_engine.py
```

Version: V10.13s.4 - All RTK commands documented
