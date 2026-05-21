# CryptoMaster P1.1AN — Paper-Training Fee-Dominated Calibration Prompt

## Status / Gate

Current production evidence after P1.1AT:

- P1.1AT fixed paper sampler rate-cap reservation flow.
- Training sample flow is restored.
- `PAPER_TRAIN_ENTRY_REAL = 30`
- `PAPER_TRAIN_QUALITY_ENTRY = 30`
- `PAPER_TRAIN_QUALITY_EXIT = 30`
- `PAPER_EXIT_TRAINING_BUCKET = 30`
- `PAPER_EXIT_NON_TRAINING = 0`
- `QUALITY_EXIT_MISSING_BY_TRADE_ID = 0`
- `LM_UPDATE_MISMATCH = 0`
- `LM_STATE_AFTER_UPDATE = 30`
- Dominant attribution:
  - `FEE_DOMINATED_MOVE = 16/30 = 53.3%`
  - `WRONG_DIRECTION = 10/30 = 33.3%`
  - `COST_EDGE_BYPASS_LOSS = 3/30 = 10.0%`
  - `TP_TOO_FAR_FOR_MFE = 1/30 = 3.3%`

P1.1AN gate is open only because:
1. closed training trades >= 10
2. quality entry mismatch = 0
3. quality exit missing = 0
4. LM update mismatch = 0
5. one attribution dominates > 50%

## Hard Freeze Rules

Do not add broad diagnostics.
Do not tune strategy logic.
Do not touch live/real execution.
Do not change RDE EV calculation.
Do not change signal generation.
Do not change production/live TP/SL.
Do not modify Firebase schema.

Allowed scope only:
Paper-training economic calibration for:
- `mode == "paper_train"`
- `source == "training_sampler"`
- `training_bucket == "C_WEAK_EV_TRAIN"`

## Problem

Paper training now works, but samples are almost always timeout losses or flat losses because the current TP/SL geometry is not realistic for the 300-second training hold window.

Observed:
- Timeout rate is effectively 100%.
- Fee drag is about `0.18%`.
- Current TP/SL is around `1.20%`, which is unreachable in the short 300-second paper sample window.
- Observed MFE is commonly around `0.02%–0.15%`.
- Dominant attribution is `FEE_DOMINATED_MOVE`.

Therefore, the next patch must calibrate paper-training TP/SL to produce useful short-horizon learning samples without affecting live/real trading.

## Required Implementation

### 1. Add paper-only training TP/SL calibration helper

Create a small helper near existing paper-training TP/SL construction logic, for example:

```python
def calibrate_paper_training_geometry(
    *,
    mode: str,
    source: str,
    training_bucket: str,
    side: str,
    entry: float,
    tp: float,
    sl: float,
    expected_move_pct: float | None,
    fee_drag_pct: float = 0.18,
) -> dict:
    ...
```

Hard requirements:
- Return original TP/SL unchanged unless:
  - mode is `paper_train`
  - source is `training_sampler`
  - training_bucket is `C_WEAK_EV_TRAIN`
- Use fee-aware TP:
  - minimum viable TP should be approximately `fee_drag_pct + 0.03`, so about `0.21%`
  - target TP should be expected-move aware
  - cap TP around `0.45%` during cold-start paper training
  - floor TP around `0.21%`
- Keep SL reasonable and safe:
  - avoid ultra-tight SL that just manufactures losses
  - recommended cold-start SL range: about `0.35%–0.60%`
  - preserve side-aware BUY/SELL TP/SL orientation
- Preserve `rr` calculation integrity.
- Preserve all existing quality/economic attribution logs.
- Add a clear field to quality entry logs if already easy:
  - `geometry_calibrated=True/False`
  - `tp_pct_before`, `tp_pct_after`
  - `sl_pct_before`, `sl_pct_after`
  Do not create a new diagnostics system.

### 2. Apply helper only at paper position creation

Patch the point where paper training position TP/SL is assigned, likely in `paper_trade_executor.py` or the existing paper training entry creation path.

Do not patch RDE or live executor.

### 3. Tests

Add focused regression tests only.

Required tests:
1. `paper_train + training_sampler + C_WEAK_EV_TRAIN` calibrates TP from ~1.20% down into the configured short-horizon range.
2. Live mode returns original TP/SL unchanged.
3. Real mode returns original TP/SL unchanged.
4. Non-training source returns original TP/SL unchanged.
5. Non-`C_WEAK_EV_TRAIN` bucket returns original TP/SL unchanged.
6. BUY orientation remains `tp > entry > sl`.
7. SELL orientation remains `tp < entry < sl`.
8. TP floor respects fee drag + minimum edge.
9. TP cap is enforced.
10. Existing P1.1AT/P1.1AF tests still pass.

Run:

```bash
python3 -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
```

## Acceptance Criteria

After deployment and at least 30 new closed training samples:

Audit must show:
- `PAPER_TRAIN_ENTRY_REAL > 0`
- `PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL`
- `QUALITY_EXIT_MISSING_BY_TRADE_ID = 0`
- `LM_UPDATE_MISMATCH = 0`
- `PAPER_EXIT_NON_TRAINING = 0`
- Timeout rate should begin to decline or MFE-to-TP ratio should materially improve.
- Attribution should move away from `FEE_DOMINATED_MOVE` dominance.

Do not require immediate profitability from the first 30 samples. The goal is better learning signal quality, not live trading optimization.

## Stop Conditions

Stop and do not continue patching if:
- live/real code paths are touched
- RDE EV thresholds are modified
- signal generator logic is modified
- learning monitor state is modified
- audit mismatches appear
- paper entries stop flowing again
- test suite fails

## Commit Message

Use:

```text
P1.1AN: calibrate paper-training TP/SL geometry for fee-dominated cold-start samples
```
