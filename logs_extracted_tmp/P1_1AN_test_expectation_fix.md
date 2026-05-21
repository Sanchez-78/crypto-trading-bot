# P1.1AN Test Expectation Fix — P1AG MFE/MAE Tests

## Situation

`P1.1AN` changed paper-training TP/SL geometry for:

- `TRADING_MODE=paper_train`
- `paper_source="training_sampler"`
- `training_bucket="C_WEAK_EV_TRAIN"`

The old P1AG tests still assume the old ~1.2% TP distance.

Now these test movements hit TP immediately:

- BUY: `3000 -> 3020` = `+0.6667%`
- SELL: `600 -> 595` = `+0.8333%` favorable move

After P1.1AN, TP is intentionally much closer, roughly `0.21%–0.45%`, so both test positions close correctly.  
This is not a production bug. The tests are stale.

## Required Fix

Do **not** revert P1.1AN.

Update only the two old P1AG MFE/MAE tests so their intermediate price moves stay below the new calibrated TP/SL.

File:

```bash
tests/test_paper_mode.py
```

Failing tests:

```text
TestP1AG1QualityDiagnostics.test_mfe_mae_calculation_for_buy
TestP1AG1QualityDiagnostics.test_mfe_mae_calculation_for_sell
```

## Minimal Patch

### BUY test

Replace:

```python
update_paper_positions({"ETHUSDT": 3020.0}, 1010.0)
```

with:

```python
update_paper_positions({"ETHUSDT": 3003.0}, 1010.0)
```

If the test later moves price down, prefer a small adverse move:

```python
update_paper_positions({"ETHUSDT": 2997.0}, 1020.0)
```

Expected values should become approximately:

```python
mfe_pct = 0.1000
mae_pct = -0.1000
```

### SELL test

Replace:

```python
update_paper_positions({"BNBUSDT": 595.0}, 1010.0)
```

with:

```python
update_paper_positions({"BNBUSDT": 599.4}, 1010.0)
```

If the test later moves price up, prefer a small adverse move:

```python
update_paper_positions({"BNBUSDT": 600.6}, 1020.0)
```

Expected values should become approximately:

```python
mfe_pct = 0.1000
mae_pct = -0.1000
```

## Better Assertion Pattern

Avoid hardcoding old TP assumptions like:

```python
# TP at 3036
# TP at 592.8
```

Instead assert the position is still open after a deliberately small sub-TP move:

```python
assert trade_id in _POSITIONS
```

Then assert `max_seen` / `min_seen` changed as intended.

For BUY:

```python
assert _POSITIONS[trade_id]["max_seen"] == 3003.0
assert _POSITIONS[trade_id]["min_seen"] == 2997.0
```

For SELL:

```python
assert _POSITIONS[trade_id]["min_seen"] == 599.4
assert _POSITIONS[trade_id]["max_seen"] == 600.6
```

## Validation Commands

Run from the project root:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m pytest tests/test_paper_mode.py::TestP1AG1QualityDiagnostics::test_mfe_mae_calculation_for_buy -q
python -m pytest tests/test_paper_mode.py::TestP1AG1QualityDiagnostics::test_mfe_mae_calculation_for_sell -q
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
git status
```

Expected:

```text
218 passed
```

or current total + 0 failures.

## Guardrails

Do not change:

- `calibrate_paper_training_geometry()`
- live/real behavior
- RDE logic
- EV logic
- TP/SL production logic
- learning update semantics

This is a test-expectation repair only.
