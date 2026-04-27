# CryptoMaster V10.13u+18d — ECON BAD Diagnostic Heartbeat Hook Fix (token-safe)

## Context
Production logs after V10.13u+18/18b/18c still show only:
- `decision=REJECT_NEGATIVE_EV`
- `decision=REJECT_ECON_BAD_ENTRY weak_ev`
- many ECON BAD rejections

But no visible:
- `[ECON_BAD_DIAG_HEARTBEAT]`
- `[ECON_BAD_NEAR_MISS_SUMMARY]`
- `[NO_TRADE_DIAGNOSTIC]`

This means trading guards are working, but diagnostics are still not reliably emitted from the live path. Do **not** change trading/entry/exit logic.

## Goal
Make ECON BAD diagnostics visible in production even when all signals exit early or no valid signal reaches normal end-of-evaluate paths.

## Hard Constraints
Do NOT change:
- PF formula / canonical metrics
- EV-only hard rejection
- V10.13u+8..u+17 close/exit/entry/probe logic
- position sizing, TP/SL, Firebase read/write behavior
- recovery probe thresholds
- decision semantics

This patch is observability-only.

## Required Fix

### 1) Verify runtime hook
Add a one-shot startup/runtime marker near the heartbeat registration/init path:
```python
logger.warning(
    "[ECON_BAD_DIAG_HOOK_ACTIVE] source=live_path_heartbeat interval_s=%s throttle_s=%s",
    interval_s,
    ECON_BAD_DIAG_HEARTBEAT_THROTTLE_S,
)
```
Must appear once after service restart.

### 2) Call heartbeat from a guaranteed live loop
If `live_path_heartbeat.py` is not guaranteed to run in production, also call:
```python
maybe_emit_econ_bad_diag_heartbeat(source="main_loop")
```
from the existing always-running main/status/loop path that already emits dashboard/status every ~10s.

The helper must remain exception-safe:
```python
try:
    maybe_emit_econ_bad_diag_heartbeat(source="main_loop")
except Exception:
    logger.exception("[ECON_BAD_DIAG_HEARTBEAT_ERROR]")
```

### 3) Use WARNING level for production visibility
Emit heartbeat and summary at `logger.warning(...)`, not debug/info, because production logging already surfaces warnings reliably:
```python
logger.warning(
    "[ECON_BAD_DIAG_HEARTBEAT] source=%s pf=%.2f total=%d neg_ev=%d weak_ev=%d "
    "weak_score=%d weak_p=%d weak_coh=%d weak_af=%d forced=%d best_symbol=%s "
    "best_ev=%.4f best_score=%.3f best_p=%.3f best_coh=%.3f best_af=%.3f "
    "probe_ready=%s probe_block=%s",
    ...
)
```

### 4) First heartbeat must not wait 10 minutes
Allow first heartbeat within 30–60s after restart:
```python
if _last_heartbeat_ts == 0:
    should_emit = True
```
Then throttle normally, e.g. every 10 min.

### 5) Snapshot must include current counters even if only negative EV occurs
Ensure `get_econ_bad_diagnostics_snapshot()` includes:
- `total_econ_bad_blocks`
- `negative_ev`
- `weak_ev`
- `weak_score`
- `weak_p`
- `weak_coh`
- `weak_af`
- `forced_weak`
- `forced_explore`
- `best_symbol`
- `best_ev`
- `best_score`
- `best_p`
- `best_coh`
- `best_af`
- `probe_ready`
- `probe_block`
- `last_trade_age_s` if available
- `pf`

### 6) Do not spam
Keep rejection logs as-is. Heartbeat/summary max once per throttle window except first post-restart emission.

## Tests
Add/extend tests:
1. `test_diag_hook_marker_emitted_on_startup_or_init`
2. `test_heartbeat_first_emit_without_waiting_10min`
3. `test_heartbeat_emits_from_main_loop_source`
4. `test_heartbeat_warning_level_visible`
5. `test_heartbeat_exception_safe_no_decision_change`
6. `test_snapshot_contains_negative_ev_and_weak_ev_counts`
7. Regression: existing V10.13u+16/+17/+18 tests still pass.

Run:
```bash
python -m pytest tests/test_v10_13u_patches.py -k "econ_bad or heartbeat or near_miss or recovery" -v
python -m pytest tests/test_v10_13u_patches.py -v
python -m py_compile src/services/realtime_decision_engine.py src/services/live_path_heartbeat.py start.py
```

## Deployment Validation
```bash
cd /opt/cryptomaster
git pull --ff-only
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 90

sudo journalctl -u cryptomaster --since "5 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DIAG_HOOK_ACTIVE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|NO_TRADE_DIAGNOSTIC|Traceback"
```

Expected within 90s:
```text
[ECON_BAD_DIAG_HOOK_ACTIVE] ...
[ECON_BAD_DIAG_HEARTBEAT] source=main_loop ... total=... neg_ev=... weak_ev=... best_ev=... probe_ready=...
```

## Acceptance Criteria
- Heartbeat appears within 90s after restart during ECON BAD.
- Hook marker appears once after restart.
- Rejection behavior unchanged.
- No new Firebase writes.
- No new trading decisions.
- No Traceback.
- Existing tests pass.
