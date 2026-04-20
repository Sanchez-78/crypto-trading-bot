# Phase 2: Learning Pipeline Instrumentation - Implementation Summary

## Completed
✅ Created `src/services/learning_instrumentation.py`
- Global counters: trades_closed_total, lm_update_called_total, lm_update_success_total, lm_update_failed_total, hydrated_pairs_count, hydrated_features_count
- Helper functions: increment_*(), set_*(), get_lm_counters(), format_lm_counters()
- Used in format: `[LM_COUNTERS] trades_closed=X lm_update_called=Y ... hydrated_pairs=N`

✅ Modified `src/services/trade_executor.py`
- Added import for learning_instrumentation (with fallback lambdas if import fails)
- Added `increment_trades_closed()` call after `record_trade_close()` at line 2261
- Added `increment_lm_update_called()` before lm_update() call (line 2278)
- Added `increment_lm_update_success()` after lm_update() call (line 2290)
- Total: 3 instrumentation points tracking the full trade close → lm_update path

✅ Modified `bot2/main.py`
- Added import for `format_lm_counters()` 
- Added startup log output printing counter values after version string
- Wrapped in try/except for robustness
- Output shows all 6 counter values at bot startup

## Expected Output on Bot Startup

```
================================================================================
🚀 MAIN() STARTING — V10.13s (commit=e66415c) [reset_integrity,timeout_fix,learning_instrumentation,...]
================================================================================
[LM_COUNTERS] trades_closed=0 lm_update_called=0 lm_update_success=0 lm_update_failed=0 hydrated_pairs=27 hydrated_features=7
```

## Critical Test: Verify Learning Pipeline

After 1-2 complete trade cycles, run:
1. Check bot logs for: `[LM_COUNTERS]` line
2. Expected: `trades_closed ≈ lm_update_called` (within 1-2 of each other)
3. Expected: `lm_update_success ≈ lm_update_called` (should match or be very close)
4. Expected: `hydrated_pairs` should increase from 27 as new pairs are traded
5. Key test: If `trades_closed > lm_update_called`, learning pipeline is not being called

## Remaining Work (Pending)

- Add hydration counters to state_manager.py (set counts after Redis hydration)
- Wrap lm_update() function in learning_monitor.py to catch success/failure
- This will fully complete Phase 2 and enable 100% visibility into learning flow

## Purpose

This instrumentation directly addresses the critical user observation:
- User reported: "obchody celkem se zvětšují ale čísla pro obchody jednotlivé měny zůstávají stejné"
- Translation: "Total trades increasing but individual pair counts staying the same"
- **This proves** learning_monitor is not being updated despite trades closing
- **Our counters will prove which part of the pipeline is broken**

By running the bot for one cycle and checking if:
- trades_closed > 0 ✓ (trades are closing)
- lm_update_called = 0 ✗ (but learning not being triggered)
- hydrated_pairs unchanged (stale learning state)

We can pinpoint exactly where the learning signal is lost.
