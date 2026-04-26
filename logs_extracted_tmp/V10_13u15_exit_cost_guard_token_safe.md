# CryptoMaster V10.13u+15 — Exit Cost Guard + Economic BAD Entry Clamp

Token-safe Claude/Codex implementation prompt. Apply surgically. Do not refactor unrelated code.

## Context

Live state after V10.13u+8..u+14:

- Runtime is deployed and visible via `[RUNTIME_VERSION]`.
- Canonical PF and Economic Health are aligned.
- Close-lock storm was reduced by V10.13u+13/u+14.
- Current issue is economic/churn, not canonical metrics.
- Latest logs show roughly:
  - Profit Factor around `0.73x` → Economic BAD.
  - `SCRATCH_EXIT` is dominant and net negative.
  - `STAGNATION_EXIT` is net negative.
  - `replaced` is net negative.
  - `PARTIAL_TP_25` remains profitable and must not be harmed.
  - Health is BAD, learning edge weak, harvest low.

Core live symptoms:

```text
Profit Factor 0.73x
Economic: BAD
SCRATCH_EXIT 325 net -0.000637 avg -0.00000196
STAGNATION_EXIT 73 net -0.000259 avg -0.00000356
replaced 33 net -0.000084 avg -0.00000257
PARTIAL_TP_25 58 net +0.000497 avg +0.00000857
[V10.13g EXIT] TP=0 SL=0 micro=4 partial=(8,0,0) scratch=48 stag=35 harvest=12.4%
```

## Hard Constraints

Do not change:

- PF formula or canonical metrics.
- Firebase read/write behavior.
- EV-only principle.
- Runtime version logic.
- LM hydration/canonical trade parsing.
- Position sizing model except explicit Economic BAD clamp below.
- TP/SL distances.
- V10.13u+8..u+14 close-lock logic unless strictly required for guard integration.
- Partial TP behavior except ensuring partial TP is not routed through full-close lock.

This patch should be cost/churn safety only.

## Goal

Reduce negative-net churn from `SCRATCH_EXIT`, `STAGNATION_EXIT`, and weak `replaced` closes while Economic Health is BAD.

Expected behavior:

- Hold small negative-net scratch/stag exits when closing would only pay fees/slippage and PF is BAD.
- Still allow emergency/risk/SL exits.
- Require stronger replacement edge before closing an existing position.
- Tighten entries while PF < 1.0.
- Preserve profitable `PARTIAL_TP_25` and true protective exits.

## Files Likely Modified

```text
src/services/smart_exit_engine.py
src/services/realtime_decision_engine.py
src/services/trade_executor.py
tests/test_v10_13u_patches.py
```

Use existing patterns and names where available. Do not create large new abstractions unless needed.

---

# Patch 1 — Shared Exit Cost Guard Helpers

In `smart_exit_engine.py`, add local helper functions near existing exit constants/helpers.

```python
def _estimated_close_cost_pct(position) -> float:
    """Conservative close-cost estimate as pct/ratio units matching position.pnl_pct."""
    fee = getattr(position, "fee_rt", None) or 0.0015
    slip = getattr(position, "fill_slippage", None) or 0.0005
    return abs(float(fee)) + abs(float(slip))


def _econ_bad() -> bool:
    try:
        from src.services.learning_monitor import lm_economic_health
        return lm_economic_health().get("status") == "BAD"
    except Exception:
        return False


def _is_emergency_exit_context(position) -> bool:
    """Keep conservative. Return True only if existing position fields clearly indicate protective/emergency exit."""
    return bool(
        getattr(position, "emergency", False)
        or getattr(position, "risk_exit", False)
        or getattr(position, "force_exit", False)
        or getattr(position, "hard_stop", False)
    )
```

If equivalent helpers already exist, reuse them instead of duplicating.

---

# Patch 2 — SCRATCH_EXIT Cost Guard

In `smart_exit_engine.py`, inside `_check_scratch` immediately before returning `SCRATCH_EXIT`, add:

```python
cost = _estimated_close_cost_pct(position)
net_if_closed = float(position.pnl_pct) - cost

if (
    _econ_bad()
    and not _is_emergency_exit_context(position)
    and net_if_closed < 0
    and getattr(position, "age_seconds", 0) < 360
):
    log.info(
        f"[EXIT_COST_GUARD] {position.symbol} reason=SCRATCH_EXIT "
        f"age={position.age_seconds}s pnl_pct={position.pnl_pct:.6f} "
        f"cost={cost:.6f} net_if_closed={net_if_closed:.6f} "
        f"action=hold_econ_bad_negative_net"
    )
    try:
        self._exit_audit_rejections["SCRATCH_EXIT:cost_guard"] += 1
    except Exception:
        pass
    return None
```

Rules:

- Do not block SL/emergency/risk exits.
- Do not affect positive-net scratch exits.
- Do not affect old positions above age threshold.
- Do not change existing scratch thresholds except this additional guard.

---

# Patch 3 — STAGNATION_EXIT Cost Guard

In `smart_exit_engine.py`, inside `_check_stagnation` immediately before returning `STAGNATION_EXIT`, add:

```python
cost = _estimated_close_cost_pct(position)
net_if_closed = float(position.pnl_pct) - cost

if (
    _econ_bad()
    and not _is_emergency_exit_context(position)
    and net_if_closed < 0
    and getattr(position, "age_seconds", 0) < 360
    and float(position.pnl_pct) > -0.003
):
    log.info(
        f"[EXIT_COST_GUARD] {position.symbol} reason=STAGNATION_EXIT "
        f"age={position.age_seconds}s pnl_pct={position.pnl_pct:.6f} "
        f"cost={cost:.6f} net_if_closed={net_if_closed:.6f} "
        f"action=hold_small_negative_net"
    )
    try:
        self._exit_audit_rejections["STAGNATION_EXIT:cost_guard"] += 1
    except Exception:
        pass
    return None
```

Allow STAGNATION_EXIT when:

- age >= 360s, or
- loss is material/worsening, or
- emergency/risk context exists.

---

# Patch 4 — Replacement Cost Guard

In `trade_executor.py`, before closing an existing position with reason `replaced`, add a minimum edge improvement requirement.

Add constants near replacement/close constants:

```python
REPLACEMENT_MIN_EV_EDGE = 0.025
REPLACEMENT_MIN_COST_MULT = 2.0
```

Before triggering `close_position(... reason="replaced" ...)`, estimate improvement:

```python
old_ev = float(pos.get("ev", pos.get("risk_ev", 0.0)) or 0.0)
new_ev = float(signal.get("ev", signal.get("risk_ev", 0.0)) or 0.0)
fee_rt = float(pos.get("fee_rt", FEE_RT) or FEE_RT)
slip = float(pos.get("fill_slippage", 0.0005) or 0.0005)
close_cost = abs(fee_rt) + abs(slip)
required_improvement = max(REPLACEMENT_MIN_EV_EDGE, close_cost * REPLACEMENT_MIN_COST_MULT)

if (new_ev - old_ev) < required_improvement and not pos.get("emergency", False):
    log.info(
        f"[REPLACE_COST_GUARD] {sym} blocked "
        f"old_ev={old_ev:.4f} new_ev={new_ev:.4f} "
        f"delta={(new_ev-old_ev):.4f} required={required_improvement:.4f} "
        f"close_cost={close_cost:.6f}"
    )
    return None  # or continue/skip depending current local flow
```

Important:

- Use the local function return/continue style that matches existing code.
- Do not block emergency/risk replacement.
- Do not change replacement logic beyond this guard.

---

# Patch 5 — Economic BAD Entry Clamp

In `realtime_decision_engine.py`, when Economic Health status is BAD, enforce stricter thresholds.

Target values:

```python
ECON_BAD_MIN_EV = 0.050
ECON_BAD_MIN_SCORE = 0.220
ECON_BAD_FORCED_MULT_MAX = 0.15
```

Add/extend existing threshold logic:

```python
try:
    from src.services.learning_monitor import lm_economic_health
    _econ = lm_economic_health()
except Exception:
    _econ = {}

if _econ.get("status") == "BAD":
    ev_threshold = max(ev_threshold, ECON_BAD_MIN_EV)
    score_threshold = max(score_threshold, ECON_BAD_MIN_SCORE)
    forced_mult = min(forced_mult, ECON_BAD_FORCED_MULT_MAX) if "forced_mult" in locals() else ECON_BAD_FORCED_MULT_MAX
    log.info(
        f"[ECON_BAD_ENTRY_CLAMP] pf={_econ.get('pf', _econ.get('profit_factor', 'NA'))} "
        f"min_ev={ev_threshold:.3f} min_score={score_threshold:.3f} "
        f"forced_mult={forced_mult:.2f} reason=pf_bad"
    )
```

Rules:

- This must only tighten, never loosen.
- Do not weaken EV-only enforcement.
- Avoid duplicate import spam; throttle log if existing logging framework supports it.

---

# Patch 6 — Exit Cost Summary Log

Add a throttled 60s log, wherever exit breakdown stats are already available. Prefer existing metrics path, no Firebase writes.

Format:

```text
[EXIT_COST_SUMMARY] scratch_net=-0.000637 stag_net=-0.000260 replaced_net=-0.000085 pf=0.73 action=guarding
```

Constraints:

- Log only.
- No DB writes.
- Do not recompute expensive history if already available.

---

# Tests

Add tests to `tests/test_v10_13u_patches.py`.

Required test names:

```text
test_scratch_cost_guard_holds_negative_net_when_econ_bad
test_scratch_cost_guard_allows_positive_net
test_stag_cost_guard_holds_small_negative_net_when_econ_bad
test_stag_cost_guard_allows_old_position
test_replace_cost_guard_blocks_weak_replacement
test_replace_cost_guard_allows_strong_replacement
test_econ_bad_entry_clamp_raises_thresholds
test_exit_cost_guard_does_not_block_emergency_exit
```

Keep tests lightweight with mocks. Do not require real Firebase or Binance.

Run:

```bash
python -m pytest tests/test_v10_13u_patches.py -k "cost_guard or replace_cost or econ_bad_entry" -v
python -m pytest tests/test_v10_13u_patches.py -v
```

---

# Deployment Validation

After deploy:

```bash
cd /opt/cryptomaster
git pull
sudo systemctl restart cryptomaster
sleep 10
sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "RUNTIME_VERSION|EXIT_COST_GUARD|REPLACE_COST_GUARD|ECON_BAD_ENTRY_CLAMP|EXIT_COST_SUMMARY|CLOSE_FORCE_RECONCILE|EXIT_INTEGRITY|Traceback"
```

Live monitor:

```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "EXIT_COST_GUARD|REPLACE_COST_GUARD|ECON_BAD_ENTRY_CLAMP|EXIT_COST_SUMMARY|CLOSE_FORCE_RECONCILE|Traceback"
```

Success signals:

```text
[RUNTIME_VERSION] commit=<new_commit> branch=main
[ECON_BAD_ENTRY_CLAMP] ... min_ev=0.050 min_score=0.220 ...
[EXIT_COST_GUARD] ... SCRATCH_EXIT ... action=hold_econ_bad_negative_net
[EXIT_COST_GUARD] ... STAGNATION_EXIT ... action=hold_small_negative_net
[EXIT_COST_SUMMARY] ... action=guarding
```

Allowed but should not loop:

```text
[CLOSE_FORCE_RECONCILE]
```

Forbidden:

```text
Traceback
EXIT_INTEGRITY_ERROR
CLOSE_LOCK_ACQUIRED ... PARTIAL_TP_25
Repeated CLOSE_FORCE_RECONCILE for same key
Economic GOOD while PF < 1.0
EV threshold lowered while Economic BAD
```

---

# Observation Window

Let run 2–3 hours after deploy.

Track:

```bash
sudo journalctl -u cryptomaster -n 3000 --no-pager | grep -E "Profit Factor|Economic:|SCRATCH_EXIT|STAGNATION_EXIT|replaced|PARTIAL_TP_25|EXIT_COST_SUMMARY"
```

Expected direction:

- PF should stop degrading quickly.
- SCRATCH/STAGNATION net bleed should slow.
- Entry frequency may drop while Economic BAD.
- PARTIAL_TP_25 should remain profitable and unaffected.

Do not tune feature selection/calibration until churn bleed is contained.
