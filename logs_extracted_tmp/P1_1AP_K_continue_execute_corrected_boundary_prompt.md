# Continue P1.1AP-K — Execute Investigation, Tests and Minimal Fix

Proceed now without asking for confirmation. Do the investigation, implement only the minimal verified fix, run the required tests, and commit/push only if the evidence confirms the absolute-ATR unit bug.

## Critical correction before implementation

Your summary contains one incorrect test expectation:

```text
Test C — Entry at exactly 0.2300% boundary should fail.
```

Do **not** implement that. Current gate semantics use:

```python
expected_move_dec >= _MIN_REQUIRED_MOVE_DEC
```

P1.1AP-K must preserve gate logic and cost threshold. Therefore:

```text
normalized expected_move_pct < 0.2300%  => FAIL cost_edge_too_low
normalized expected_move_pct == 0.2300% => PASS
normalized expected_move_pct > 0.2300%  => PASS
```

Add a regression test preserving this exact boundary behavior.

## Execute investigation first

In `/opt/CryptoMaster_srv`, inspect:

```bash
grep -R "def _estimate_expected_move\|_estimate_expected_move(\|\"atr\"\|expected_move_pct\|cost_edge_too_low" -n src/services tests | head -300
grep -R "paper_exploration_override\|C_WEAK_EV\|C_WEAK_EV_TRAIN" -n src/services tests | head -300
sed -n '80,135p' src/services/paper_exploration.py
sed -n '370,510p' src/services/paper_exploration.py
sed -n '1810,1980p' src/services/paper_trade_executor.py
```

Confirm from code/tests/call-path evidence whether `signal["atr"]` on the C_WEAK paper exploration path is absolute price movement. Use production evidence only as supporting signal:

```text
ADAUSDT price~0.25, raw atr~0.0006 => normalized ~0.2400%, should pass threshold 0.2300%
XRPUSDT price~1.37, raw atr~0.0007 => normalized ~0.0511%, should still fail
```

If ATR is provably mixed across call paths, implement a source-aware/path-specific fix instead of globally converting every ATR. Do not use an unsafe blanket heuristic.

## Implementation scope

Edit only the smallest required files, expected primarily:

```text
src/services/paper_exploration.py
tests/test_p1_paper_exploration.py
```

Edit `src/services/paper_trade_executor.py` only if necessary to prevent double-normalization of the newly explicit normalized source.

### Required behavior

For confirmed absolute-price ATR used by the C_WEAK cost-edge gate:

```python
expected_move_dec = atr / price
expected_move_pct = expected_move_dec * 100.0
expected_move_src = "atr_abs_price_normalized"
```

Use corrected `expected_move_dec` before:

```python
_check_cost_edge(expected_move_dec)
```

Propagate/log source:

```text
expected_move_pct=...
expected_move_src=atr_abs_price_normalized
required_move_pct=0.2300
```

Preserve:
- `_MIN_REQUIRED_MOVE_DEC` and `_MIN_REQUIRED_MOVE_PCT`
- `>=` boundary behavior
- all B_RECOVERY routing and P1.1AP-J telemetry
- D_NEG P1.1AP-I/I2 shadow isolation
- canonical learning logic
- live/real behavior, ECON BAD/RDE gates, TP/SL, sizing, caps, P1.1AO, Firebase/Android contracts

## Required regression tests

1. ADA-like normalized pass:
```python
price=0.2500
atr=0.0006
```
Expected:
```text
expected_move_pct ~= 0.2400
expected_move_src == "atr_abs_price_normalized"
not rejected for cost_edge_too_low
```

2. XRP-like normalized fail:
```python
price=1.3700
atr=0.0007
```
Expected:
```text
expected_move_pct ~= 0.0511
expected_move_src == "atr_abs_price_normalized"
rejected for cost_edge_too_low
```

3. Boundary semantics unchanged:
```text
0.2299% => FAIL
0.2300% => PASS
0.2301% => PASS
```

4. Missing/zero/invalid price:
```text
safe reject or preserved safe fallback; never false-positive pass
```

5. Existing invariants:
```text
B_RECOVERY route_trigger unchanged
D_NEG shadow-only unchanged
PAPER_TRADE_SAVED / canonical LEARNING_UPDATE separation unchanged
```

## Validation commands

```bash
python -m pytest -q tests/test_p1_paper_exploration.py -k "cost_edge or expected_move or route_trigger or recovery_ready"

python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_p11ap_i_d_neg_learning_isolation.py   tests/test_v10_13u_patches.py

python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

## Before commit

```bash
git diff --stat
git diff -- src/services/paper_exploration.py src/services/paper_trade_executor.py tests/test_p1_paper_exploration.py
git status --short
```

Do not commit runtime/local artifacts:

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary outputs
```

## Commit only if confirmed and tests pass

```bash
git add <only edited source/test files>
git commit -m "P1.1AP-K: Normalize ATR price move before C_WEAK cost-edge gate"
git push
```

## Report back

Return:
- proof of ATR contract/call-path conclusion;
- exact changed files and minimal logic change;
- ADA/XRP/boundary test results;
- full test results;
- commit hash if pushed;
- post-deploy validation commands only after commit succeeds.
