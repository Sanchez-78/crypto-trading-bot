# CryptoMaster V10.13u+18c — ECON BAD Diagnostic Heartbeat Fallback

## Purpose
Fix missing ECON BAD diagnostic output. V10.13u+18b added early-return flushes, but live grep still shows no:
- `[ECON_BAD_NEAR_MISS_SUMMARY]`
- `[NO_TRADE_DIAGNOSTIC]`
- `[ECON_BAD_RECOVERY_*]`
- recent `[RUNTIME_VERSION]`

This patch is **observability only**. Do not change trading behavior.

## Preflight first
Run before coding:

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
git log --oneline -5
sudo systemctl show cryptomaster -p ExecStart -p WorkingDirectory
ps -fp "$(systemctl show -p MainPID --value cryptomaster)"
sudo journalctl -u cryptomaster --since "2026-04-27 07:00:00" --no-pager | grep -m1 RUNTIME_VERSION || true
sudo journalctl -u cryptomaster --since "2026-04-27 07:00:00" --no-pager | grep -E "ECON_BAD_NEAR_MISS_SUMMARY|NO_TRADE_DIAGNOSTIC|ECON_BAD_RECOVERY|Traceback" || true
```

If server HEAD is **not** `5c8c353` or newer, deploy first:
```bash
git pull --ff-only
sudo systemctl restart cryptomaster
sudo journalctl -u cryptomaster -n 300 --no-pager | grep -E "RUNTIME_VERSION|Traceback"
```

## Problem
Current diagnostic flush is still too coupled to `evaluate_signal()` paths. Live logs show many:
- `decision=REJECT_NEGATIVE_EV`
- `decision=REJECT_ECON_BAD_ENTRY weak_ev`

But no diagnostic summary appears. That means either:
1. commit not actually running, or
2. diagnostics are still not called from a stable periodic path, or
3. counters/log tags are not visible via current grep.

## Non-negotiables
Do **not** change:
- PF/canonical metrics formulas
- EV-only hard rejection
- ECON BAD thresholds
- recovery probe thresholds
- position sizing / TP / SL
- V10.13u+8..u+17 close-lock / exit logic
- Firebase read/write behavior
- decision semantics

No new Firebase writes. No new per-symbol DB reads.

## Patch goal
Add a stable periodic diagnostic heartbeat that emits ECON BAD diagnostics even when every signal returns early.

Expected live tags:
```text
[ECON_BAD_DIAG_HEARTBEAT]
[ECON_BAD_NEAR_MISS_SUMMARY]
[NO_TRADE_DIAGNOSTIC]
```

## Implementation plan

### 1. In `src/services/realtime_decision_engine.py`
Add/ensure these helpers are module-level and exception-safe:

```python
def get_econ_bad_diagnostics_snapshot(reset: bool = False) -> dict:
    \"\"\"Return ECON BAD diagnostic counters/state without changing decisions.\"\"\"
```

Snapshot fields:
- `econ_bad`
- `pf`
- `total_econ_bad_blocks`
- `hard_negative_ev_blocks`
- `weak_ev`
- `weak_score`
- `weak_p`
- `weak_coh`
- `weak_af`
- `forced_weak`
- `forced_explore`
- `best_near_miss`: `{symbol, ev, score, p, coh, af, reason, ts}`
- `probe_ready`: bool
- `probe_block_reason`
- `last_trade_age_s` if available
- `positions` if cheaply available
- `last_summary_ts`

Add:

```python
def maybe_emit_econ_bad_diag_heartbeat(force: bool = False, source: str = "rde") -> None:
    \"\"\"Emit diagnostic summary from any caller. Must never throw.\"\"\"
```

Rules:
- If ECON BAD is false: do nothing except optional debug.
- If `force=True`: emit regardless of throttle.
- Else throttle to 300–600s.
- Emit even if counters are zero, with `reason=counters_empty`, so grep proves hook works.
- Use existing diagnostic state from V10.13u+18/18b.
- Never changes TAKE/REJECT result.

Log format:
```text
[ECON_BAD_DIAG_HEARTBEAT] source=<source> pf=<pf> total=<n> neg_ev=<n> weak_ev=<n> best_ev=<ev|None> probe_ready=<bool> probe_block=<reason>
[ECON_BAD_NEAR_MISS_SUMMARY] total=<n> negative_ev=<n> weak_ev=<n> weak_score=<n> weak_p=<n> weak_coh=<n> weak_af=<n> forced_weak=<n> forced_explore=<n> best_symbol=<sym|None> best_ev=<ev|None> best_score=<score|None> best_p=<p|None> best_coh=<coh|None> best_af=<af|None> probe_ready=<bool> probe_block=<reason>
```

### 2. Hook from stable periodic runtime path
Find a loop that runs even when no trades are opened. Prefer existing dashboard/status/heartbeat path.

Search:
```bash
grep -R "CRYPTOMASTER  |\|CYCLE SNAPSHOT\|LEARNING MONITOR\|print_dashboard\|dashboard\|heartbeat\|sleep(10" -n src start.py main.py
```

Add safe call:
```python
try:
    from src.services.realtime_decision_engine import maybe_emit_econ_bad_diag_heartbeat
    maybe_emit_econ_bad_diag_heartbeat(source="dashboard")
except Exception:
    pass
```

Important:
- One call per dashboard cycle is fine because helper throttles.
- Do not call Firebase from this hook.
- Do not block the loop.
- Do not import at module top if circular imports risk exists; use lazy import.

### 3. Add startup sanity marker
Ensure `[RUNTIME_VERSION]` appears on every service start and includes current commit. If already present, do not duplicate. If it is not reliably visible, add a one-time startup log in `start.py` or the current service entrypoint.

Required:
```text
[RUNTIME_VERSION] app=CryptoMaster version=<version> commit=<short_hash> branch=<branch> host=<host> python=<py> started_at=<iso>
```

### 4. Tests
Add tests without altering trading behavior:
1. `test_diag_heartbeat_emits_when_econ_bad_and_counters_empty`
2. `test_diag_heartbeat_emits_after_negative_ev_early_return`
3. `test_diag_heartbeat_throttles_without_force`
4. `test_diag_heartbeat_force_bypasses_throttle`
5. `test_diag_heartbeat_exception_safe`
6. `test_no_decision_semantics_change_for_negative_ev`
7. `test_no_decision_semantics_change_for_econ_bad_weak_ev`
8. `test_no_new_firebase_writes_or_reads_from_heartbeat` if Firebase mocks exist

Run:
```bash
python -m pytest tests/test_v10_13u_patches.py -k "econ_bad or diagnostic or heartbeat or near_miss" -v
python -m pytest tests/test_v10_13u_patches.py -v
python -m compileall src
```

## Acceptance criteria
After deploy:

```bash
cd /opt/cryptomaster
git pull --ff-only
sudo systemctl restart cryptomaster
sleep 20
sudo journalctl -u cryptomaster -n 500 --no-pager | grep -E "RUNTIME_VERSION|Traceback"
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -E "ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|NO_TRADE_DIAGNOSTIC|ECON_BAD_RECOVERY|Traceback"
```

Must see:
- `[RUNTIME_VERSION]` after restart
- `[ECON_BAD_DIAG_HEARTBEAT]` within first few dashboard cycles if ECON BAD
- `[ECON_BAD_NEAR_MISS_SUMMARY]` at throttle interval or immediately if force/startup path is used
- No `Traceback`
- No new `decision=TAKE ev=0.0300 p=0.5000` while ECON BAD

## Expected interpretation
If diagnostics show:
- `negative_ev` dominates → signal model/regime side is producing bad directional edge; do not loosen gates.
- `weak_ev` dominates with best_ev < 0.038 → recovery probe correctly blocked.
- best_ev >= 0.038 but probe_ready=false → inspect probe_block_reason.
- probe_ready=true but no probe accepted → integration bug in V10.13u+17 path.
