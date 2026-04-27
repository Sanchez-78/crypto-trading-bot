# CryptoMaster V10.13u+18b — ECON BAD Diagnostic Flush Fix (token-safe)

## Goal
Fix observability only. V10.13u+18 was deployed, but live logs over ~20 minutes show many:
- `decision=REJECT_ECON_BAD_ENTRY weak_ev (...)`
- `decision=REJECT_NEGATIVE_EV ev=... ≤ 0`
and **no visible**:
- `[ECON_BAD_NEAR_MISS_SUMMARY]`
- `[NO_TRADE_DIAGNOSTIC]`
- `[ECON_BAD_RECOVERY_PROBE]`

This means diagnostics are not flushing from all early-return reject paths, or the summary logger is placed after returns. Do **not** loosen trading gates.

## Live evidence
Recent log window 06:42–07:02:
- many `REJECT_NEGATIVE_EV` with EV around `-0.0300` to `-0.0399`
- many `REJECT_ECON_BAD_ENTRY weak_ev` with EV around `0.0300–0.0348`
- no weak `TAKE` leak observed
- no recovery probe observed
- no near-miss summary observed

Interpretation:
- V10.13u+16 entry guard works.
- V10.13u+17 correctly does not probe because candidates are below probe floor (`probe_min_ev=0.038`) or negative EV.
- V10.13u+18 diagnostics are incomplete/not flushing.

## Hard constraints
Do NOT change:
- PF formula / `canonical_metrics.py`
- EV-only hard enforcement
- ECON BAD thresholds
- recovery probe thresholds
- V10.13u+8..u+17 close/entry/exit logic
- TP/SL, sizing, entry strategy, Firebase read/write strategy
- any trading decision semantics

Allowed changes:
- logging/diagnostics only
- counters/summary emission only
- tests only

## Required patch

### 1) Add a single safe flush helper in `src/services/realtime_decision_engine.py`

Create or adjust helper:

```python
def _maybe_flush_econ_bad_diagnostics(ctx: dict | None = None, *, force: bool = False) -> None:
    """
    Observability-only. Must never raise.
    If ECON BAD active and counters exist, emit throttled summary.
    Called before every early return reject path.
    """
```

Requirements:
- Wrapped in `try/except Exception` and never alters decision.
- Uses existing `_log_econ_bad_near_miss_summary()` and `_log_no_trade_diagnostic()`.
- Throttled with existing V10.13u+18 interval, default 10 min.
- First summary after process start should be allowed once counters > 0 (`last_log_ts == 0` should not block).
- Include current counters and best near-miss in log.
- Must work even when candidate is rejected before final TAKE path.

Expected log:
```text
[ECON_BAD_NEAR_MISS_SUMMARY] total=... weak_ev=... negative_ev=... forced_weak=... best_ev=... probe_ready=...
```

### 2) Update every early-return rejection branch to flush before return

At minimum cover:
- `REJECT_NEGATIVE_EV`
- `REJECT_ECON_BAD_ENTRY`
- `REJECT_ECON_BAD_FORCED`
- `FORCED_EXPLORE_GATE`
- `SKIP_SCORE_SOFT` if it returns before ECON BAD summary hook
- any other final reject path inside `evaluate_signal()` that can bypass the end-of-function diagnostics

Pattern:
```python
_update_econ_bad_near_miss(..., reason="negative_ev" or actual_reason)
_maybe_flush_econ_bad_diagnostics(ctx)
return rejection_result
```

Do not call Firebase here. Use cached ECON BAD state only.

### 3) Negative EV must be tracked

Currently most live rejects are `REJECT_NEGATIVE_EV`; V10.13u+18 must count them.

When EV-only rejects under ECON BAD:
```python
_update_econ_bad_near_miss(
    symbol=symbol,
    reason="negative_ev",
    ev=ev,
    score=score,
    p=p,
    coh=coh,
    af=af,
    forced=is_forced,
)
_maybe_flush_econ_bad_diagnostics(ctx)
```

Important:
- Negative EV must never be eligible for recovery probe.
- It is diagnostics only.

### 4) Summary must log even without near-miss probe readiness

If all candidates are unsafe, summary still logs:
```text
best_ev=0.0348 probe_ready=false reason=below_probe_ev
negative_ev=...
weak_ev=...
```

### 5) Add no-trade diagnostic path

If idle time exceeds configured threshold (existing V10.13u+18 threshold, e.g. 6h), log:
```text
[NO_TRADE_DIAGNOSTIC] idle_s=... pf=... econ=BAD positions=... blocked=... negative_ev=... weak_ev=... best_ev=...
```

Must not trigger trades.

## Tests

Add tests in existing V10.13u test file.

Required tests:
1. `test_v10_13u18b_negative_ev_updates_diagnostics`
   - ECON BAD active
   - EV-only reject
   - counter `negative_ev` increments
   - decision remains `REJECT_NEGATIVE_EV`

2. `test_v10_13u18b_summary_flushes_before_early_return`
   - Force `last_summary_ts=0`
   - Trigger early reject
   - caplog contains `[ECON_BAD_NEAR_MISS_SUMMARY]`

3. `test_v10_13u18b_summary_throttled`
   - Trigger two rejects within interval
   - only one summary log

4. `test_v10_13u18b_no_trade_diagnostic_logs_after_idle`
   - mock idle > threshold
   - caplog contains `[NO_TRADE_DIAGNOSTIC]`

5. `test_v10_13u18b_no_decision_semantics_change`
   - same weak EV still returns `REJECT_ECON_BAD_ENTRY`
   - same negative EV still returns `REJECT_NEGATIVE_EV`
   - no TAKE introduced

6. Regression:
   - V10.13u+16 tests still pass
   - V10.13u+17 tests still pass
   - V10.13u+18 tests still pass

Run:
```bash
python -m pytest tests/test_v10_13u_patches.py -k "18b or 18 or 17 or 16" -v
python -m pytest tests/test_v10_13u_patches.py -v
```

## Acceptance criteria
- Live logs show `[ECON_BAD_NEAR_MISS_SUMMARY]` within 10 minutes of rejects.
- Live logs show `negative_ev` counter in summary.
- No weak `decision=TAKE ev≈0.03 p≈0.50`.
- No recovery probe unless candidate passes V10.13u+17 probe floors.
- No PF/EV/entry/exit behavior changes.
- No new Firebase writes.

## Deployment validation
```bash
cd /opt/cryptomaster
git pull
sudo systemctl restart cryptomaster
sleep 20

sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager \
| grep -E "RUNTIME_VERSION|ECON_BAD_NEAR_MISS|NO_TRADE_DIAGNOSTIC|ECON_BAD_RECOVERY|REJECT_ECON_BAD_ENTRY|REJECT_NEGATIVE_EV|Traceback"
```

Expected after 10 min:
```text
[ECON_BAD_NEAR_MISS_SUMMARY] ... negative_ev=... weak_ev=... best_ev=... probe_ready=false
```

## Commit
```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+18b: flush ECON BAD diagnostics on early rejects"
git push
```

## Do not optimize further now
Do not change thresholds because live data shows:
- positive weak EV only `0.0300–0.0348`, below probe min `0.038`
- many negative EV candidates
- PF still BAD, so loosening gates would reintroduce churn
