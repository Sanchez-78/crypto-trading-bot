# CryptoMaster V10.13u+17 — ECON_BAD Controlled Recovery Probe

## Context
V10.13u+16 works:
- `Economic: BAD`, PF ~0.74
- `ECON_BAD_ENTRY` rejects >1000
- weak TAKE signals are blocked
- safety/consistency patches V10.13u+8..u+16 must remain untouched

Problem:
- Bot is over-blocked.
- PF cannot recover without rare high-quality new closed samples.
- Do NOT loosen normal ECON_BAD guard globally.

## Goal
Add a tiny, controlled recovery-probe mode during ECON_BAD.

This is NOT old unblock mode.
This is NOT forced weak exploration.
This is a narrow safety valve for rare micro-size probes.

## Hard Do-Not-Change
Do not modify:
- canonical PF formula / `canonical_metrics.py`
- `lm_economic_health()` semantics
- EV-only enforcement
- TP/SL distances
- position sizing except explicit probe multiplier
- Firebase read/write behavior
- close-lock patches V10.13u+8..u+15
- partial TP behavior
- exit PnL logic
- Android/firestore schema unless already writing normal decision fields

## Live Symptom
Current logs:
```text
Economic: 0.340 [BAD]
PF: 0.74
ECON_BAD_ENTRY: 1022
decision=REJECT_ECON_BAD_ENTRY weak_ev (ev=0.0348<0.045)
```

Expected after patch:
```text
[ECON_BAD_RECOVERY_ACTIVE] pf=0.74 rejects=...
[ECON_BAD_RECOVERY_PROBE] symbol=... ev=... score=... p=... coh=... af=... size_mult=0.15
```

## Add Constants
File: `src/services/realtime_decision_engine.py`

```python
ECON_BAD_RECOVERY_MIN_IDLE_S = 3600          # 60 min no closed trades
ECON_BAD_RECOVERY_MIN_REJECTS = 500
ECON_BAD_PROBE_MIN_EV = 0.038
ECON_BAD_PROBE_MIN_SCORE = 0.18
ECON_BAD_PROBE_MIN_P = 0.52
ECON_BAD_PROBE_MIN_COH = 0.55
ECON_BAD_PROBE_MIN_AF = 0.70
ECON_BAD_PROBE_SIZE_MULT = 0.15
ECON_BAD_PROBE_COOLDOWN_S = 1800            # 30 min per probe
ECON_BAD_PROBE_MAX_OPEN = 1
ECON_BAD_PROBE_MAX_PER_HOUR = 2
```

## Add Module State
```python
_ECON_BAD_PROBE_STATE = {
    "last_probe_ts": 0.0,
    "probe_ts": [],
    "last_summary_ts": 0.0,
}
```

## Add Helper
```python
def _econ_bad_recovery_probe_allowed(signal: dict, ctx: dict) -> tuple[bool, str]:
    """
    Allows tiny recovery probe only when ECON_BAD_ENTRY is over-blocking.

    Return:
      (True, "controlled_probe") OR (False, reason)

    Never allow:
    - negative/zero EV
    - af < 0.70
    - p < 0.52
    - coh < 0.55
    - score < 0.18
    - forced weak signal
    - LOSS_CLUSTER
    - spread/toxic orderflow block
    - active close-lock recovery / force-reconcile storm
    - more than 1 open position
    - more than 2 probes/hour
    """
```

Suggested logic:
```python
def _econ_bad_recovery_probe_allowed(signal: dict, ctx: dict) -> tuple[bool, str]:
    now = time.time()

    ev = float(signal.get("ev", ctx.get("ev", 0.0)) or 0.0)
    score = float(signal.get("score", ctx.get("score", 0.0)) or 0.0)
    p = float(signal.get("p", ctx.get("p", 0.0)) or 0.0)
    coh = float(signal.get("coh", ctx.get("coh", 0.0)) or 0.0)
    af = float(signal.get("af", ctx.get("af", 0.0)) or 0.0)

    if ev <= 0:
        return False, "negative_ev"
    if ev < ECON_BAD_PROBE_MIN_EV:
        return False, "probe_ev_too_low"
    if score < ECON_BAD_PROBE_MIN_SCORE:
        return False, "probe_score_too_low"
    if p < ECON_BAD_PROBE_MIN_P:
        return False, "probe_p_too_low"
    if coh < ECON_BAD_PROBE_MIN_COH:
        return False, "probe_coh_too_low"
    if af < ECON_BAD_PROBE_MIN_AF:
        return False, "probe_af_too_low"

    reason = str(signal.get("reason", ctx.get("reason", ""))).upper()
    block_reason = str(signal.get("block_reason", ctx.get("block_reason", ""))).upper()
    tags = f"{reason} {block_reason}"

    forbidden = ("LOSS_CLUSTER", "TOXIC", "SPREAD", "NEGATIVE_EV", "FAST_FAIL")
    if any(x in tags for x in forbidden):
        return False, "unsafe_block_reason"

    if bool(signal.get("forced", False)) and (
        ev < 0.050 or p < 0.55 or coh < 0.60 or af < 0.70
    ):
        return False, "weak_forced_probe"

    try:
        from src.services.trade_executor import get_close_lock_health
        close_health = get_close_lock_health()
        if int(close_health.get("active", 0) or 0) > 0:
            return False, "close_lock_active"
    except Exception:
        return False, "close_lock_unknown"

    open_positions = int(ctx.get("open_positions", signal.get("open_positions", 0)) or 0)
    if open_positions >= ECON_BAD_PROBE_MAX_OPEN:
        return False, "max_open_positions"

    econ_bad_rejects = int(ctx.get("econ_bad_entry_rejects", 0) or 0)
    idle_s = float(ctx.get("seconds_since_last_closed_trade", 0.0) or 0.0)
    if econ_bad_rejects < ECON_BAD_RECOVERY_MIN_REJECTS and idle_s < ECON_BAD_RECOVERY_MIN_IDLE_S:
        return False, "not_blocked_long_enough"

    if now - float(_ECON_BAD_PROBE_STATE.get("last_probe_ts", 0.0)) < ECON_BAD_PROBE_COOLDOWN_S:
        return False, "probe_cooldown"

    _ECON_BAD_PROBE_STATE["probe_ts"] = [
        t for t in _ECON_BAD_PROBE_STATE.get("probe_ts", []) if now - t < 3600
    ]
    if len(_ECON_BAD_PROBE_STATE["probe_ts"]) >= ECON_BAD_PROBE_MAX_PER_HOUR:
        return False, "probe_hourly_cap"

    return True, "controlled_probe"
```

## Integration Point
File: `src/services/realtime_decision_engine.py`

Place inside the V10.13u+16 ECON_BAD_ENTRY block:
- after EV/score/p/coh/af are finalized
- before final TAKE is returned/logged to execution

Current behavior:
```python
if econ_bad and decision == "TAKE":
    allowed, reason = _econ_bad_entry_quality_gate(...)
    if not allowed:
        return REJECT_ECON_BAD_ENTRY
```

Replace with:
```python
if econ_bad and decision == "TAKE":
    allowed, reason = _econ_bad_entry_quality_gate(signal_or_ctx)

    if not allowed:
        probe_allowed, probe_reason = _econ_bad_recovery_probe_allowed(signal_or_ctx, ctx)

        # Recovery can only override weak_ev-like rejection, never unsafe metrics.
        recovery_overridable = reason in {"weak_ev", "weak_score"}

        if recovery_overridable and probe_allowed:
            now = time.time()
            _ECON_BAD_PROBE_STATE["last_probe_ts"] = now
            _ECON_BAD_PROBE_STATE.setdefault("probe_ts", []).append(now)

            ctx["econ_bad_probe"] = True
            ctx["size_mult"] = float(ctx.get("size_mult", 1.0)) * ECON_BAD_PROBE_SIZE_MULT
            ctx["decision_reason"] = "ECON_BAD_RECOVERY_PROBE"

            log.warning(
                f"[ECON_BAD_RECOVERY_PROBE] symbol={symbol} "
                f"ev={ev:.4f} score={score:.3f} p={p:.3f} coh={coh:.3f} af={af:.3f} "
                f"size_mult={ctx['size_mult']:.3f} reason={probe_reason}"
            )
            # continue to normal TAKE return with probe metadata
        else:
            log.info(
                f"[ECON_BAD_RECOVERY_BLOCK] symbol={symbol} reason={probe_reason} "
                f"entry_reason={reason} ev={ev:.4f} score={score:.3f} p={p:.3f} coh={coh:.3f} af={af:.3f}"
            )
            return {
                "decision": "REJECT_ECON_BAD_ENTRY",
                "reason": reason,
                "symbol": symbol,
                "ev": ev,
                "score": score,
                "p": p,
                "coh": coh,
                "af": af,
            }
```

Important:
- Preserve existing project decision object shape.
- If project uses `allocation_factor`, `af`, or `size_multiplier`, attach probe multiplier to the same field actually consumed by executor.
- Do not return `None`.
- Do not bypass canonical logging.

## Logging
Add throttled summary every 60s:
```text
[ECON_BAD_RECOVERY_ACTIVE] pf=0.74 rejects=1022 idle_s=...
[ECON_BAD_RECOVERY_PROBE] symbol=... ev=... score=... p=... coh=... af=... size_mult=0.15 reason=controlled_probe
[ECON_BAD_RECOVERY_BLOCK] symbol=... reason=...
```

## Tests
Add to `tests/test_v10_13u_patches.py`:

1. ECON_BAD still blocks normal weak EV as before.
2. Recovery allows `ev=0.039` only after idle/reject threshold.
3. Recovery blocks `af < 0.70`.
4. Recovery blocks negative EV.
5. Recovery caps probes to max 2/hour.
6. Recovery blocks when open positions >= 1.
7. Recovery applies size multiplier `0.15`.
8. PF formula unchanged regression.
9. ECON GOOD path unchanged.
10. Forced weak signal remains blocked.

## Acceptance
Success:
```text
ECON_BAD_ENTRY still increases for junk signals.
Rare [ECON_BAD_RECOVERY_PROBE] appears only after long block/idle.
No TAKE with ev=0.0300 p=0.5000 during BAD.
TAKE during BAD is either strong normal signal or ECON_BAD_RECOVERY_PROBE.
No Traceback.
No CLOSE_FORCE_RECONCILE storm.
PF formula unchanged.
```

Forbidden:
```text
decision=TAKE ev=0.0300 p=0.5000
TAKE with af=0.35
TAKE with negative EV
forced weak TAKE
global ECON_BAD guard disabled
PF/canonical_metrics changes
Firebase quota changes
close-lock refactor
```

## Validation Commands
```bash
cd /opt/cryptomaster
git pull
sudo systemctl restart cryptomaster
sleep 15

sudo journalctl -u cryptomaster -n 2500 --no-pager | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY|ECON_BAD_RECOVERY|decision=TAKE|Economic:|Profit Factor|Traceback|CLOSE_FORCE|EXIT_INTEGRITY"
```

Live:
```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "ECON_BAD_ENTRY|ECON_BAD_RECOVERY|decision=TAKE|Traceback|CLOSE_FORCE"
```

## Commit Message
```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+17: ECON BAD controlled recovery probes"
git push
```
