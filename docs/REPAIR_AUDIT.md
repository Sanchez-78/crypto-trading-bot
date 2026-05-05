# CryptoMaster Repair Audit — V3 Senior Review

Generated: 2026-05-05  
Branch: `claude/code-analysis-bug-report-6PcEa`  
HEAD SHA: `4d3b131410c056665a216028b521e353230eed4a`

---

## Session state

```
current branch:             claude/code-analysis-bug-report-6PcEa
current HEAD sha:           4d3b131410c056665a216028b521e353230eed4a
runtime version log present: no (BOOT_VERSION not emitted at startup)
paper_train loop status:    mostly working — double bucket-metrics write bug
Android app_metrics/latest: missing (module not yet created)
Firebase quota risk:        low (firebase_admin not installed in audit env)
```

---

## File-by-file audit

### `src/core/runtime_mode.py`
```
status: ok
important functions present:
  get_trading_mode()           ✓
  is_paper_mode()              ✓
  is_live_trading_enabled()    ✓
  live_trading_allowed()       ✓
  check_live_order_guard()     ✓
  paper_train_enabled()        ✓
known-good behavior present: yes — all 4 guard conditions enforced
repair needed: none
tests needed:
  test_paper_train_never_allows_live_order
  test_paper_live_never_allows_live_order
  test_live_real_requires_all_confirm_flags
  test_paper_train_enabled_only_in_paper_train
```

### `src/services/paper_trade_executor.py`
```
status: risky
important functions present:
  open_paper_position()          ✓
  update_paper_positions()       ✓
  close_paper_position()         ✓
  get_paper_open_positions()     ✓
  check_and_close_timeout_positions() ✗ MISSING

known-good behavior missing:
  - check_and_close_timeout_positions(now) — timeout scan must cover ALL open positions,
    not only the symbol whose price is ticking. Current update_paper_positions only
    receives _symbol_prices = {current_symbol: price}, so symbols not in current tick
    can only close on TP/SL, not on TIMEOUT, until their own price tick arrives.
  - [PAPER_TIMEOUT_SCAN] log tag missing
  - [PAPER_TIMEOUT_DUE] log tag missing
  - [PAPER_CLOSE_PATH] log tag missing

BUG (double bucket update):
  close_paper_position() always calls _safe_bucket_metrics_update_for_paper_trade()
  (line 867). Then _save_paper_trade_closed() in trade_executor also calls
  update_bucket_metrics(closed_trade) unconditionally (line 1567).
  This double-updates bucket metrics for every paper trade.

repair needed:
  1. Add check_and_close_timeout_positions(now) scanning all positions
  2. Remove duplicate bucket metrics update from trade_executor._save_paper_trade_closed
  3. Add [PAPER_TIMEOUT_SCAN] / [PAPER_TIMEOUT_DUE] / [PAPER_CLOSE_PATH] log markers

tests needed:
  test_training_position_closes_after_effective_hold
  test_training_position_before_hold_stays_open
  test_timeout_close_scans_all_symbols
  test_timeout_close_calls_learning_once
  test_timeout_close_calls_bucket_metrics_once
  test_closed_position_frees_symbol_cap
  test_paper_timeout_never_touches_live_order_path
```

### `src/services/paper_training_sampler.py`
```
status: risky
important functions present:
  maybe_open_training_sample()         ✓
  record_training_closed()             ✓
  record_training_learning_update()    ✓
  _training_quality_gate()             ✓

known-good behavior issue:
  _is_training_enabled() checks is_paper_mode() AND NOT is_live_trading_enabled().
  paper_live satisfies both conditions (paper_live is paper_mode, not live).
  Should check get_trading_mode() == PAPER_TRAIN explicitly to prevent
  accidental sampler activation in paper_live mode.

required buckets present: C_WEAK_EV_TRAIN ✓, D_NEG_EV_CONTROL ✓, E_NO_PATTERN_BASELINE ✓

repair needed:
  Fix _is_training_enabled() to require PAPER_TRAIN mode explicitly

tests needed:
  test_training_sampler_disabled_in_paper_live
  test_training_sampler_enabled_in_paper_train
  test_training_sampler_requires_real_price
  test_training_sampler_disabled_in_live_real
  test_training_sampler_caps_per_symbol
  test_training_sampler_caps_per_bucket
  test_training_sampler_duplicate_cooldown
  test_training_sampler_health_logging_never_raises
  test_record_training_closed_never_raises
  test_record_training_learning_update_never_raises
```

### `src/services/candidate_dedup.py`
```
status: risky
important functions present:
  check_duplicate()              ✓ (but mutates on first call — see below)
  check_symbol_side_cooldown()   ✓
  check_bootstrap_frequency()    ✓
  record_open()                  ✓
  mark_candidate_evaluated()     ✗ MISSING

known-good behavior issue:
  check_duplicate() marks _recent_fingerprints[fp] = now immediately
  on the first call (line 96). V3 spec requires check_duplicate() to be
  read-only and mark_candidate_evaluated() to be called separately after
  entry attempt or terminal route.

repair needed:
  Split check_duplicate() into separate check (read-only) and
  mark_candidate_evaluated() (mutating). Update callers.

tests needed:
  test_check_duplicate_does_not_mark_first_candidate
  test_mark_candidate_evaluated_marks_after_attempt
  test_same_cycle_candidate_reaches_sampler_once
  test_different_symbol_not_duplicate
```

### `src/services/trade_executor.py`
```
status: risky
important functions present:
  _save_paper_trade_closed()        ✓ (bug inside — see below)
  _maybe_route_to_paper_training()  ✓
  _pipeline_record_drop()           present (via inline logging)
  on_price()                        ✓

BUG (double bucket metrics):
  Line 1567: update_bucket_metrics(closed_trade) called unconditionally.
  close_paper_position() already called _safe_bucket_metrics_update_for_paper_trade().
  Result: bucket metrics updated 2× per paper trade.

repair needed:
  Remove line 1567-1570 (update_bucket_metrics call) from _save_paper_trade_closed.
  bucket_metrics is already handled in close_paper_position().

tests needed:
  test_accepted_candidate_drop_routes_to_training_in_paper_train
  test_quiet_atr_fee_bypass_only_in_paper_train
  test_live_mode_respects_quiet_atr_fee
  test_strict_take_disabled_by_default_in_paper_train
```

### `src/services/learning_monitor.py`
```
status: ok
important functions present:
  update_from_paper_trade()    ✓
  lm_update()                  ✓
  lm_health()                  ✓
  lm_pnl_hist                  ✓
known-good behavior present: yes
repair needed: none
```

### `src/services/learning_event.py`
```
status: ok
important functions present:
  update_metrics()             ✓  (increments METRICS["trades"])
  get_metrics()                ✓
  bootstrap_from_history()     ✓
  track_price()                ✓
known-good behavior present: yes
repair needed: none
```

### `src/services/bucket_metrics.py`
```
status: ok
important functions present:
  update_bucket_metrics()      ✓
  get_bucket_metrics()         ✓
  reset_bucket_metrics()       ✓
known-good behavior present: yes
repair needed: none (double-call is in trade_executor, not here)
```

### `src/services/metrics_engine.py`
```
status: risky
important functions present:
  MetricsEngine._trade_profit()   ✓
  MetricsEngine.compute()         ✓

known-good behavior issue:
  _trade_profit() priority: profit → pnl → evaluation.profit
  Missing "net_pnl" field (paper trades store net_pnl_pct, unit_pnl)

repair needed:
  Add net_pnl to extraction chain (lower priority than profit/pnl)

tests needed:
  test_metrics_engine_and_canonical_metrics_match_profit_factor
```

### `src/services/canonical_metrics.py`
```
status: risky
important functions present:
  _extract_trade_profit()      ✓
  canonical_profit_factor()    ✓
  canonical_win_rate()         ✓
  canonical_expectancy()       ✓
  canonical_exit_breakdown()   ✓
  canonical_overall_health()   ✓

known-good behavior issue:
  _extract_trade_profit() uses profit → pnl → evaluation.profit
  Missing "net_pnl" field

repair needed:
  Add net_pnl to extraction chain

tests needed:
  test_neutral_timeout_not_counted_as_loss
  test_tiny_positive_timeout_not_counted_as_win
  test_per_symbol_counts_sum_to_total
```

### `src/services/canonical_state.py`
```
status: broken
important functions present:
  initialize_canonical_state()       ✓
  get_authoritative_trade_count()    ✓
  _load_from_history()               ✓ (wrong field)

BROKEN:
  _load_from_history() uses t.get("pnl_closed", 0) to classify WIN/LOSS.
  Firebase trades store profit/pnl (not pnl_closed).
  This means history always counts 0 wins/losses — canonical state from
  history source will always report trades_won=0, trades_lost=0.

repair needed:
  Replace pnl_closed lookup with consistent profit extraction
  (same priority as canonical_metrics._extract_trade_profit)

tests needed:
  test_canonical_state_history_uses_profit
  test_canonical_state_history_uses_pnl
  test_canonical_state_history_uses_net_pnl
  test_canonical_state_history_does_not_mismatch_on_flats
```

### `src/services/firebase_client.py`
```
status: risky (missing app_metrics functions)
important functions present:
  load_history()                    ✓
  load_stats()                      ✓
  get_quota_status()                ✓
  get_firebase_health()             ✓
  should_skip_noncritical_write()   ✓
  save_batch()                      ✓

missing:
  save_app_metrics_snapshot()       ✗
  load_stats_cached()               ✗
  _app_metrics_semantic_hash()      ✗

repair needed:
  Add load_stats_cached(ttl_s=300)
  Add _app_metrics_semantic_hash(snapshot)
  Add save_app_metrics_snapshot(snapshot, force=False)

tests needed:
  test_app_metrics_semantic_hash_ignores_generated_at
  test_app_metrics_semantic_hash_ignores_age_fields
  test_save_app_metrics_snapshot_throttles
  test_save_app_metrics_snapshot_skips_unchanged
  test_save_app_metrics_snapshot_heartbeat_writes_after_interval
  test_save_app_metrics_snapshot_skips_when_degraded
  test_save_app_metrics_snapshot_never_raises
```

### `bot2/main.py`
```
status: ok
paper trade update path present: yes (on_price calls update_paper_positions)
timeout scan: handled via symbol-tick, see paper_trade_executor note above
repair needed: integrate publish_app_metrics_snapshot call (cadence ~60s)
```

### `start.py`
```
status: ok
repair needed: none
```

### `tests/test_paper_mode.py`
```
status: ok — 75 tests pass
repair needed: add tests per sections 5-12 above
```

### `src/services/app_metrics_contract.py`
```
status: missing — create from scratch
```

---

## Paper train chain status

```
[SIGNAL_RAW]                  ✓ generated by signal_generator
[RDE_CANDIDATE]               ✓ evaluated by realtime_decision_engine
[TRAINING_SAMPLER_CHECK]      ✓ routed via _maybe_route_to_paper_training
[PAPER_ENTRY_ATTEMPT]         ✓ open_paper_position called
[PAPER_TRAIN_ENTRY]           ✓ logged in open_paper_position
[PAPER_TIMEOUT_SCAN]          ✗ missing log tag (timeout scans do happen but unlogged)
[PAPER_CLOSE_PATH]            ✗ missing log tag
[PAPER_EXIT]                  ✓ logged in close_paper_position
[LEARNING_UPDATE] ok=True     ✓ via _safe_learning_update_for_paper_trade
[PAPER_TRAIN_CLOSED]          ✓ via record_training_closed

Chain verdict: MOSTLY WORKING — double bucket write and missing timeout scan function
are bugs but do not fully block learning data flow.
```

---

## Repair priority

```
P0 — Fix double bucket metrics write (trade_executor:1567)
P0 — Fix canonical_state._load_from_history pnl_closed field
P1 — Add check_and_close_timeout_positions to paper_trade_executor
P1 — Add [PAPER_TIMEOUT_SCAN] / [PAPER_CLOSE_PATH] log markers
P1 — Fix paper_training_sampler._is_training_enabled paper_train mode check
P1 — Separate mark_candidate_evaluated from check_duplicate
P2 — Add net_pnl to profit extraction (canonical_metrics + metrics_engine)
P3 — Create app_metrics_contract.py
P3 — Add save_app_metrics_snapshot + load_stats_cached to firebase_client
P3 — Integrate publish_app_metrics_snapshot
P4 — scripts/validate_learning_loop.py
P4 — docs/ANDROID_FIREBASE_CONTRACT.md
P4 — tests/test_app_metrics_contract.py
```
