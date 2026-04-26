# CryptoMaster V10.13u+3 — Economic PF Source Drift Fix

## Context
Production confirms commit `2f3e491` is live and version injection works:

```text
[RUNTIME_VERSION] app=CryptoMaster version=V10.13u+1 commit=2f3e491 branch=main
```

But Economic Health still uses a different PF source than the dashboard:

```text
Dashboard:  Profit Factor 0.75x
Economic:   0.832 [GOOD]
Economic PF: PF: 12.08
```

This is a safety bug. Dashboard/canonical PF says the strategy is unprofitable, but Economic Health says GOOD because it still uses stale/local/synthetic PF.

## Goal
Make Economic Health use the exact same canonical PF source as dashboard everywhere.

Expected after patch:

```text
Profit Factor 0.75x
[ECON_CANONICAL_ACTIVE] pf=0.75 source=canonical_profit_factor economic_score=<low>
Economic: <not GOOD>
PF: 0.75
```

Must not appear again:

```text
PF: 12.08
Economic: 0.832 [GOOD]
```

## Files
Primary:

```text
src/services/learning_monitor.py
```

Possible/supporting:

```text
src/services/canonical_metrics.py
tests/test_v10_13u_patches.py
```

## Patch Instructions

### 1. Locate all PF/economic calculations
Run:

```bash
grep -n "profit_factor\|PF:\|Economic:\|ECONOMIC_HEALTH\|canonical_profit_factor" src/services/learning_monitor.py
```

Find every place that calculates, stores, scores, or prints Economic PF.

### 2. Forbid local PF for Economic Health
If `learning_monitor.py` has a local function like:

```python
def canonical_profit_factor(...):
    ...
```

or any gross-win/gross-loss PF formula used by Economic Health, do not use it for Economic Health.

Allowed:
- Keep deprecated helper only if needed for backward compatibility.
- Rename/comment it clearly as deprecated.

Not allowed:
- Economic Health must not use LM pair state, Redis state, feature stats, bootstrap state, synthetic stats, edge stats, or local fallback PF.

### 3. Force canonical source
Where Economic Health calculates/prints PF, use:

```python
from src.services.canonical_metrics import canonical_profit_factor

pf = canonical_profit_factor()
```

If closed canonical trades are already available in scope, prefer:

```python
pf = canonical_profit_factor(closed_trades)
```

Do not silently fall back to LM/Redis/synthetic PF if canonical PF is available.

### 4. Economic score must not be GOOD when PF < 1.0
Apply this PF score logic:

```python
if pf < 1.0:
    pf_score = max(0.0, min(0.35, pf / 3.0))
elif pf < 1.5:
    pf_score = 0.35 + (pf - 1.0) * 0.5
else:
    pf_score = min(1.0, 0.60 + min(pf, 3.0) / 7.5)
```

Hard rule:

```python
if pf < 1.0 and net_profit <= 0:
    economic_status = "BAD"  # or at maximum "CAUTION", but never GOOD
```

Do not let other sub-scores make Economic `GOOD` when canonical PF < 1.0 and closed net profit is negative.

### 5. Add diagnostic log
Add a throttled or once-per-cycle diagnostic near Economic Health calculation:

```python
log.warning(
    "[ECON_CANONICAL_ACTIVE] pf=%.2f source=canonical_profit_factor economic_score=%.3f",
    pf,
    economic_score,
)
```

### 6. Add/adjust tests
Add tests for:

```text
canonical PF 0.75 -> Economic PF prints 0.75, not stale high PF
canonical PF < 1.0 + net_profit <= 0 -> Economic status is not GOOD
missing canonical source -> explicit warning, no fake GOOD score
```

## Validation
Restart and check logs:

```bash
sudo systemctl restart cryptomaster
sleep 5
sudo journalctl -u cryptomaster -n 500 --no-pager | grep -E "RUNTIME_VERSION|ECON_CANONICAL|Economic:|PF:|Profit Factor|ERROR|WARNING"
```

Success signals:

```text
[RUNTIME_VERSION] ... commit=2f3e491 branch=main
[ECON_CANONICAL_ACTIVE] pf=0.75 source=canonical_profit_factor economic_score=<low>
Profit Factor 0.75x
PF: 0.75
Economic: <BAD/CAUTION/LOW, not GOOD>
```

Failure signals:

```text
PF: 12.08
Economic: 0.832 [GOOD]
No module named 'src.services.canonical_metrics'
[ECONOMIC_HEALTH] Calculation failed
```

## Acceptance Criteria
Patch is accepted only when:

```text
Dashboard PF == Economic PF within rounding
Economic Health is not GOOD when PF < 1.0 and net profit <= 0
No missing canonical_metrics import warning
No stale PF value such as 7.48 or 12.08 appears in Economic Health
```

## Do Not Change
Do not tune strategy, thresholds, exits, sizing, forced explore, or filters in this patch.

This patch is only about Economic PF source correctness and safety status truthfulness.
