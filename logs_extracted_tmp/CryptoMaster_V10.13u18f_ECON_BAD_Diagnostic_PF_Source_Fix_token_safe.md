# CryptoMaster V10.13u+18f — ECON BAD Diagnostic PF Source Fix

## ROLE
You are a senior Python backend/quant safety engineer. Implement a **surgical observability-only patch**. Do not change trading behavior.

## LIVE CONTEXT
Production path is confirmed:
`systemd -> start.py -> bot2/main.py -> RDE`

Current deployed commit:
`9246bfc V10.13u+18e`

Live validation confirmed diagnostics now emit:
```text
[RUNTIME_VERSION] commit=9246bfc
[ECON_BAD_DIAG_HOOK_ACTIVE]
[ECON_BAD_DIAG_HEARTBEAT] source=main ...
[ECON_BAD_NEAR_MISS_SUMMARY] ...
```

Current heartbeat example:
```text
[ECON_BAD_DIAG_HEARTBEAT] source=main pf=1.000 total=39 neg_ev=33 weak_ev=6 best_symbol=XRPUSDT best_ev=0.0370 best_score=0.183 best_p=0.523 best_coh=0.741 best_af=0.750 probe_ready=False probe_block=below_probe_ev
[ECON_BAD_NEAR_MISS_SUMMARY] total=39 negative_ev=33 weak_ev=6 best_symbol=XRPUSDT best_ev=0.0370 ... probe_ready=False probe_block=below_probe_ev
```

Dashboard/Economic panel still shows PF around `0.74`, while heartbeat logs `pf=1.000`. This likely means diagnostic heartbeat uses fallback/default PF instead of the same canonical PF source used by dashboard / `lm_economic_health()`.

## PROBLEM
Diagnostics are visible, but PF in diagnostic heartbeat may be misleading:
- dashboard: `Profit Factor 0.74x`
- heartbeat: `pf=1.000`

This can hide true ECON BAD state in logs and make recovery/probe interpretation confusing.

## OBJECTIVE
Make ECON BAD diagnostics report the same PF/status source as production economic health, or explicitly mark fallback.

## HARD CONSTRAINTS
Do **not** change:
- EV-only rule
- entry gates V10.13u+16
- recovery probe logic V10.13u+17
- exit guards V10.13u+15
- close-lock fixes V10.13u+14
- TP/SL, sizing, strategy, score formula
- Firebase writes
- Firestore quota behavior
- trading decisions

This patch is **observability only**.

## FILES LIKELY INVOLVED
Inspect first, then patch minimally:
- `src/services/realtime_decision_engine.py`
- `src/services/learning_monitor.py`
- `src/services/canonical_metrics.py`
- optionally `bot2/main.py` only if needed for call signature, but avoid unless necessary
- `tests/test_v10_13u_patches.py`

## IMPLEMENTATION PLAN

### 1. Add a safe PF/status resolver for diagnostics
In `src/services/realtime_decision_engine.py`, add helper near ECON BAD diagnostic helpers:

```python
def _resolve_econ_bad_diag_pf_status() -> dict:
    """Return PF/status for diagnostics from canonical economic health source.
    Must be exception-safe and never affect trading.
    Expected keys:
      pf: float
      status: str
      source: str
      fallback: bool
      error: str|None
    """
```

Resolution order:
1. Try `from src.services.learning_monitor import lm_economic_health`
2. Call `lm_economic_health()` safely
3. Extract PF from one of these keys, in order:
   - `profit_factor`
   - `pf`
   - `canonical_pf`
4. Extract status from one of these keys:
   - `status`
   - `economic_status`
   - `alert`
5. Return:
```python
{"pf": pf_float, "status": status_str, "source": "lm_economic_health", "fallback": False, "error": None}
```
6. If unavailable or invalid, return explicit fallback:
```python
{"pf": 1.0, "status": "UNKNOWN", "source": "fallback", "fallback": True, "error": "..."}
```

Never raise from this helper.

### 2. Use resolver in diagnostic snapshot/heartbeat
Update `get_econ_bad_diagnostics_snapshot()` and/or `maybe_emit_econ_bad_diag_heartbeat()` so heartbeat logs include:
```text
pf=<resolved_pf>
econ_status=<resolved_status>
pf_source=<source>
pf_fallback=<true|false>
```

If fallback occurs, make it obvious:
```text
pf=1.000 econ_status=UNKNOWN pf_source=fallback pf_fallback=true pf_error=<short_error>
```

### 3. Keep existing fields unchanged
Do not remove existing heartbeat fields:
- `total`
- `neg_ev`
- `weak_ev`
- `weak_score`
- `weak_p`
- `weak_coh`
- `weak_af`
- `forced`
- `best_symbol`
- `best_ev`
- `best_score`
- `best_p`
- `best_coh`
- `best_af`
- `probe_ready`
- `probe_block`

Only append PF/status source fields.

### 4. Summary log should also show PF source
Update `[ECON_BAD_NEAR_MISS_SUMMARY]` to include the same fields:
```text
pf=<resolved_pf> econ_status=<resolved_status> pf_source=<source> pf_fallback=<true|false>
```

### 5. Preserve throttle behavior
Do not change existing throttle durations unless strictly necessary.
First heartbeat behavior from V10.13u+18d/18e must remain.

## TESTS TO ADD
Add focused tests to `tests/test_v10_13u_patches.py`.

Required tests:

1. `test_v10_13u18f_pf_resolver_uses_lm_economic_health`
- Patch/mock `src.services.learning_monitor.lm_economic_health`
- Return `{"profit_factor": 0.74, "status": "BAD"}`
- Assert resolver returns `pf=0.74`, `status=BAD`, `source=lm_economic_health`, `fallback=False`

2. `test_v10_13u18f_pf_resolver_accepts_pf_key`
- Return `{"pf": 0.73, "status": "BAD"}`
- Assert `pf=0.73`

3. `test_v10_13u18f_pf_resolver_fallback_is_explicit`
- Make `lm_economic_health()` raise
- Assert `pf=1.0`, `status=UNKNOWN`, `source=fallback`, `fallback=True`, `error` not empty

4. `test_v10_13u18f_heartbeat_logs_pf_source`
- Force heartbeat emission
- Capture logs
- Assert log contains `pf_source=` and `pf_fallback=`

5. `test_v10_13u18f_no_decision_change`
- Verify only diagnostics helpers changed behavior
- No gate/probe decision semantics should change

Use existing V10.13u+18 test style and reset helpers.

## VALIDATION COMMANDS
Use project venv on Hetzner:

```bash
cd /opt/cryptomaster
source venv/bin/activate
python -m py_compile src/services/realtime_decision_engine.py src/services/learning_monitor.py src/services/canonical_metrics.py bot2/main.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u18f" -v
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u18" -v
git diff --check
git status --short
```

Existing old unrelated failures in full test suite must not be treated as caused by this patch unless touched. Focus on V10.13u+18 family regression.

## COMMIT
Commit message:
```text
V10.13u+18f: align ECON BAD diagnostic PF with canonical economic health
```

## DEPLOYMENT VALIDATION
After deploy/restart:

```bash
sudo systemctl restart cryptomaster
sleep 90
sudo journalctl -u cryptomaster --since "5 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DIAG_HOOK_ACTIVE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|Traceback"
```

Expected:
```text
[RUNTIME_VERSION] commit=<new_commit>
[ECON_BAD_DIAG_HOOK_ACTIVE] ...
[ECON_BAD_DIAG_HEARTBEAT] source=main pf=0.74x-ish econ_status=BAD pf_source=lm_economic_health pf_fallback=false ...
[ECON_BAD_NEAR_MISS_SUMMARY] ... pf=0.74x-ish econ_status=BAD pf_source=lm_economic_health pf_fallback=false ...
```

If still `pf=1.000`, it must include:
```text
pf_source=fallback pf_fallback=true pf_error=...
```

## SUCCESS CRITERIA
- Heartbeat PF matches dashboard/economic PF, or fallback is explicit.
- No trading behavior changes.
- No new Firebase writes.
- No Traceback.
- V10.13u+18 diagnostics remain visible in real production path.

## DO NOT IMPLEMENT YET
Do not lower recovery probe threshold from `0.038` to `0.037` in this patch. First fix PF observability.
