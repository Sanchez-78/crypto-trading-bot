# CryptoMaster P1.1AN-A — Paper-Train Fee/TP Calibration Prompt

> **Purpose:** Implement one narrow, paper-train-only economic calibration patch after P1.1AT restored sample flow.
>
> **Patch type:** Surgical economic calibration, not diagnostics expansion.
>
> **Target repo:** `C:\Projects\CryptoMaster_srv`
>
> **Python:** 3.11+
>
> **Do not touch live/real trading behavior.**

---

## 0. Current Production State

Production audit after `P1.1AT` at commit `27b41c9` shows the sample-flow blocker is fixed:

```text
PAPER_TRAIN_ENTRY_REAL:       30
PAPER_TRAIN_QUALITY_ENTRY:    30
PAPER_TRAIN_QUALITY_EXIT:     30
QUALITY_EXIT_MISSING:         0
QUALITY_MISMATCH:             0
LM_STATE_AFTER_UPDATE:        30
LM_UPDATE_MISMATCH:           0
PAPER_EXIT_NON_TRAINING:      0
```

P1.1AN gate is open:

```text
closed/econ samples:          30
dominant attribution:         FEE_DOMINATED_MOVE = 16/30 = 53.3%
```

Attribution:

```text
FEE_DOMINATED_MOVE:       16 / 30 = 53.3%
WRONG_DIRECTION:          10 / 30 = 33.3%
COST_EDGE_BYPASS_LOSS:     3 / 30 = 10.0%
TP_TOO_FAR_FOR_MFE:        1 / 30 = 3.3%
```

Observed pattern:

```text
timeout_rate = 1.000
fee_drag_pct ≈ 0.180%
tp_pct = 1.200%
typical MFE ≈ 0.02–0.15%
hold_limit_s = 300
```

Conclusion:

```text
The bot often captures a small favorable move, but the paper-training TP is too far for the 300s sample window.
Most samples time out, and fee drag dominates the net result.
```

---

## 1. Hard Freeze Rules

Do **not** implement broad changes.

Forbidden:

```text
❌ No new diagnostics expansion
❌ No dashboard/UI changes
❌ No live/real execution changes
❌ No RDE core changes
❌ No EV formula changes
❌ No strategy/signal/indicator changes
❌ No attribution feature expansion
❌ No Firebase schema changes
❌ No TP/SL changes outside paper_train training sampler scope
```

Allowed:

```text
✅ Paper-train-only TP/SL geometry calibration
✅ Only for training samples from training_sampler / C_WEAK_EV_TRAIN
✅ Tests proving live/real behavior is unchanged
✅ Minimal audit visibility if an existing log already contains TP/SL fields
```

---

## 2. Objective

Implement `P1.1AN-A`:

> Reduce `FEE_DOMINATED_MOVE` dominance by making paper-training TP/SL geometry economically realistic for a 300-second sample window, without changing live/real trading.

The calibration must make training targets reachable enough to evaluate signal direction and micro-edge, while still accounting for fees.

---

## 3. Required Behavior

### 3.1 Scope Gate

Apply the new TP/SL calibration only when all are true:

```python
mode == "paper_train"
paper_source == "training_sampler"
training_bucket == "C_WEAK_EV_TRAIN"
```

or equivalent existing fields in the repo.

If any condition is false, preserve current behavior exactly.

### 3.2 Fee-Aware Minimum TP

Do not ignore fees.

Use the existing fee source if available. Do not hardcode blindly if the repo already has a taker fee config.

Concept:

```python
fee_drag_pct = 2 * taker_fee_pct
min_viable_tp_pct = fee_drag_pct + 0.03
```

Expected current values:

```text
fee_drag_pct ≈ 0.180%
min_viable_tp_pct ≈ 0.210%
```

### 3.3 Expected-Move-Based TP

Use the best existing `expected_move_pct` / ATR-derived / position-derived field already available in paper training entry creation.

Concept:

```python
expected_based_tp = expected_move_pct * 0.65
```

Clamp:

```python
tp_pct = clamp(expected_based_tp, min_viable_tp_pct, 0.45)
```

Important:

```text
The goal is not to make every trade win.
The goal is to avoid impossible 1.2% TP targets when the observed 300s MFE is usually 0.02–0.15%.
```

### 3.4 SL Geometry

Keep SL near TP but slightly wider, still bounded:

```python
sl_pct = clamp(tp_pct * 1.10, min_viable_tp_pct, 0.60)
```

Do not allow:

```text
SL == TP due to rounding
negative TP/SL
zero TP/SL
inverted BUY/SELL geometry
```

### 3.5 Hold Time

Do **not** change `hold_limit_s` in this patch.

```text
hold_limit_s remains 300
```

### 3.6 BUY/SELL Correctness

Preserve side-aware TP/SL direction:

```text
BUY:
  tp > entry
  sl < entry

SELL:
  tp < entry
  sl > entry
```

This must be tested.

---

## 4. Suggested Implementation Shape

Prefer a small helper near existing paper TP/SL construction logic.

Example structure:

```python
def calibrate_paper_train_tp_sl_pct(
    *,
    mode: str,
    paper_source: str,
    training_bucket: str,
    expected_move_pct: float | None,
    default_tp_pct: float,
    default_sl_pct: float,
    taker_fee_pct: float,
) -> tuple[float, float, dict]:
    """
    P1.1AN-A: Paper-train-only fee-aware TP/SL calibration.

    Returns:
      tp_pct, sl_pct, context
    """
```

Rules:

```python
if not (
    mode == "paper_train"
    and paper_source == "training_sampler"
    and training_bucket == "C_WEAK_EV_TRAIN"
):
    return default_tp_pct, default_sl_pct, {"calibrated": False, "reason": "scope_not_matched"}
```

Then:

```python
fee_drag_pct = max(0.0, 2.0 * taker_fee_pct)
min_viable_tp_pct = fee_drag_pct + 0.03

safe_expected = expected_move_pct if expected_move_pct and expected_move_pct > 0 else default_tp_pct
expected_based_tp = safe_expected * 0.65

tp_pct = clamp(expected_based_tp, min_viable_tp_pct, 0.45)
sl_pct = clamp(tp_pct * 1.10, min_viable_tp_pct, 0.60)
```

Context should include enough to appear in existing quality logs if easy:

```text
tp_calibrated=True/False
fee_drag_pct
min_viable_tp_pct
expected_move_pct
old_tp_pct
new_tp_pct
old_sl_pct
new_sl_pct
```

Do not create a new log family unless necessary. Prefer extending existing `[PAPER_TRAIN_QUALITY_ENTRY]` fields if that is already centralized and safe.

---

## 5. Files to Inspect

Start by inspecting:

```text
src/services/paper_trade_executor.py
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/execution.py
tests/test_paper_mode.py
scripts/p11ag_quality_audit.sh
```

Find the actual TP/SL construction point for paper training entries. Apply the patch at the narrowest point where:

```text
mode/paper_source/training_bucket are known
entry price is known
side is known
expected_move_pct or ATR-derived expected move is known
```

Do not modify RDE acceptance logic.

---

## 6. Tests Required

Add focused regression tests. Minimum 8 tests.

### Required tests

1. **Scope: paper_train training sampler calibrated**

```text
mode=paper_train
paper_source=training_sampler
training_bucket=C_WEAK_EV_TRAIN
default tp=1.2
expected_move_pct small
=> tp_pct < 1.2 and >= fee_drag + buffer
```

2. **Live unchanged**

```text
mode=live
=> tp/sl unchanged
```

3. **Real unchanged**

```text
mode=real
=> tp/sl unchanged
```

4. **Non-training paper unchanged**

```text
paper_source != training_sampler
=> tp/sl unchanged
```

5. **Wrong bucket unchanged**

```text
training_bucket != C_WEAK_EV_TRAIN
=> tp/sl unchanged
```

6. **BUY geometry correct**

```text
tp_price > entry
sl_price < entry
```

7. **SELL geometry correct**

```text
tp_price < entry
sl_price > entry
```

8. **No invalid TP/SL**

```text
tp_pct > 0
sl_pct > 0
tp_pct != sl_pct after final price normalization where applicable
```

### Optional tests

9. **Fallback expected move**

```text
expected_move_pct missing/zero
=> no crash; bounded default or unchanged safe fallback
```

10. **Fee-aware minimum**

```text
very tiny expected_move_pct
=> tp_pct == min_viable_tp_pct or close
```

11. **Upper clamp**

```text
very large expected_move_pct
=> tp_pct <= 0.45
sl_pct <= 0.60
```

---

## 7. Validation Commands

Run locally before commit:

```bash
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
```

If touched shell scripts:

```bash
bash -n scripts/p11ak_core_flow_viewer.sh
bash -n scripts/p11ak_core_flow_viewer_cs.sh
```

Do not skip tests.

---

## 8. Production Validation After Deploy

After deploy, run:

```bash
bash scripts/p11ag_quality_audit.sh --since "90 min ago"
```

Then later:

```bash
bash scripts/p11ag_quality_audit.sh --since "180 min ago"
```

Pass criteria:

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_TRAIN_QUALITY_EXIT_MISSING = 0
LM_UPDATE_MISMATCH = 0
PAPER_TRAIN_ECON_ATTRIB >= 20 new samples
FEE_DOMINATED_MOVE < 50%
timeout_rate begins to fall OR avg_mfe_to_tp_ratio improves materially
some WIN/FLAT samples appear without cost-edge-bypass dominance
```

Do **not** require instant profitability. This patch only makes samples economically measurable.

---

## 9. Failure Rules

If after deployment entries stop again:

```text
STOP.
Do not add diagnostics.
Inspect direct rate-cap accounting and open-position caps.
```

If entries continue but all losses remain fee-dominated after 30+ new samples:

```text
Do not broaden scope automatically.
Prepare a short audit note with:
- new attribution distribution
- avg_mfe_to_tp_ratio
- timeout_rate
- cost_edge_ok vs cost_edge_bypassed split
```

If wrong-direction becomes dominant:

```text
Do not tune TP/SL again.
Next patch should address directional filtering, but only after explicit approval.
```

---

## 10. Commit Message

Use:

```text
P1.1AN-A paper-train fee-aware TP calibration
```

Commit body:

```text
- Calibrates TP/SL only for paper_train training_sampler C_WEAK_EV_TRAIN samples
- Uses fee-aware minimum TP and expected-move-based clamp
- Preserves live/real and non-training behavior
- Adds regression tests for scope isolation and BUY/SELL geometry
```

---

## 11. Final Output Required

When done, report only:

```text
P1.1AN-A complete
Commit: <hash>
Tests:
- python -m pytest tests/test_paper_mode.py -q: PASS
- bash -n scripts/p11ag_quality_audit.sh: PASS

Changed files:
- ...

Production validation command:
bash scripts/p11ag_quality_audit.sh --since "180 min ago"
```

No long explanation unless a test fails.
