# Claude Code Prompt — P1.1AP-K: Normalize ATR Price Move Before C_WEAK Cost-Edge Gate

## Mode

Implement one narrow patch only. Start by tracing the existing signal/ATR contract and writing regression tests, then modify only the minimal paper-training/exploration gating code needed.

## Current production baseline

Deployed validated chain:

```text
5e9179b P1.1AP-J: Clarify paper exploration telemetry and B route trigger
07fc451 P1.1AP-I2: Suppress D_NEG legacy LEARNING_UPDATE log
e80807d P1.1AP-I: Isolate D_NEG_EV_CONTROL from canonical learning
```

Already validated in production and must remain true:

```text
D_NEG_EV_CONTROL:
- PAPER_EXIT / QUALITY_EXIT / PAPER_LEARNING_SHADOW_SKIP remain visible
- no canonical LEARNING_UPDATE
- no LM_STATE_AFTER_UPDATE

C_WEAK_EV_TRAIN:
- canonical update emits LM_STATE_AFTER_UPDATE + [LEARNING_UPDATE] ok=True
- Firebase diagnostic save emits [PAPER_TRADE_SAVED], not fake LEARNING_UPDATE

B_RECOVERY_READY:
- routing unchanged; P1.1AP-J telemetry/attribution only
```

## Problem evidence

After P1.1AP-J, the bot repeatedly rejects C_WEAK candidates:

```text
[PAPER_EXPLORE_SKIP] reason=cost_edge_too_low bucket=C_WEAK_EV symbol=ADAUSDT expected_move_pct=0.0006 required_move_pct=0.2300
[PAPER_TRAIN_SKIP] reason=cost_edge_too_low symbol=ADAUSDT ... bucket=C_WEAK_EV_TRAIN ...

[PAPER_EXPLORE_SKIP] reason=cost_edge_too_low bucket=C_WEAK_EV symbol=XRPUSDT expected_move_pct=0.0006/0.0007 required_move_pct=0.2300
[PAPER_TRAIN_SKIP] reason=cost_edge_too_low symbol=XRPUSDT ... bucket=C_WEAK_EV_TRAIN ...
```

Current code evidence:

```text
src/services/paper_exploration.py:
- _estimate_expected_move(signal) reads atr first
- for atr it calls _normalize_pct_or_decimal(atr)
- C_WEAK gate calls:
    expected_move_dec, expected_move_pct = _estimate_expected_move(signal)
    has_edge = _check_cost_edge(expected_move_dec)
- no price normalization occurs before this gate

src/services/paper_trade_executor.py:
- has a later P1.1AI correction heuristic for mislabeled absolute ATR
- that correction occurs after the exploration cost-edge decision
- it cannot rescue candidates already rejected by paper_exploration gate
```

Why this matters:

```text
ADA-like case:
price ~= 0.2500, raw atr = 0.0006 absolute price move
correct relative move = 0.0006 / 0.2500 * 100 = 0.2400%
required = 0.2300%
=> should PASS edge gate if ATR is absolute-price ATR

XRP-like case:
price ~= 1.3700, raw atr = 0.0007 absolute price move
correct relative move = 0.0007 / 1.3700 * 100 ~= 0.0511%
required = 0.2300%
=> should still FAIL edge gate, but log should show correct relative value
```

This is a likely false-reject/unit-normalization bug for low-priced symbols, not a reason to weaken the cost-edge minimum.

## Objective

Correct expected-move unit handling **before** the C_WEAK cost-edge gate so that confirmed absolute-price ATR is normalized as:

```python
expected_move_dec = atr_abs / price
expected_move_pct = (atr_abs / price) * 100.0
expected_move_src = "atr_abs_price_normalized"
```

Preserve the cost threshold:

```text
required_move_pct = 0.2300
```

The gate must still reject moves below cost + buffer.

## Hard boundaries

Do **not** change:

- live/real trading behavior or routing
- `required_move_pct=0.2300` / cost constants / buffer
- RDE or ECON_BAD gates
- EV/score thresholds
- TP/SL geometry or holding times
- paper sampler caps/rate limits
- P1.1AO probe logic/caps
- D_NEG shadow-only isolation
- B_RECOVERY routing/threshold/bucket names
- canonical learning behavior
- Firebase contracts or Android snapshots

Do not broaden this into strategy/direction tuning.

## Required investigation before code edit

Trace the ATR field contract and all call paths to `_estimate_expected_move()`:

```bash
grep -R "def _estimate_expected_move\|_estimate_expected_move(\|\"atr\"\|expected_move_pct\|cost_edge_too_low" -n \
  src/services tests | head -250

grep -R "paper_exploration_override\|C_WEAK_EV\|C_WEAK_EV_TRAIN" -n \
  src/services tests | head -250
```

Confirm:
1. For the affected paper exploration path, `signal["atr"]` represents an absolute price distance, or identify an explicit field/source that does.
2. Whether any existing callers pass ATR already in percent/decimal units.
3. Whether there is a mirrored pre-entry cost-edge gate outside `paper_exploration.py` that must use the same corrected helper.

If ATR contract is mixed, do not blindly convert every ATR. Add a small explicit normalization helper/source detection using existing signal metadata or confirmed path-specific contract.

## Recommended implementation

### 1. Make `_estimate_expected_move()` source-aware

File:

```text
src/services/paper_exploration.py
```

Prefer changing the return value to include source where minimally compatible, e.g.:

```python
def _estimate_expected_move(signal: dict) -> tuple[float, float, str]:
    ...
```

or add a parallel helper without breaking existing callers/tests.

For the confirmed absolute ATR path:

```python
atr = float(signal.get("atr") or 0.0)
price = float(signal.get("price") or signal.get("entry_price") or 0.0)

if atr > 0.0 and price > 0.0 and atr_is_absolute_price_move:
    move_dec = atr / price
    move_pct = move_dec * 100.0
    return move_dec, move_pct, "atr_abs_price_normalized"
```

Fallbacks must preserve existing safe behavior for:
- explicitly percent/decimal expected-move fields, if present;
- volatility fallback;
- score fallback;
- missing/invalid price.

Do not introduce a heuristic that treats all small values as percent simply because they are `<0.05`; that is the current failure for micro-price symbols.

### 2. Use corrected value in C_WEAK gate and log its source

Where C_WEAK cost-edge is checked, keep:

```python
has_edge = _check_cost_edge(expected_move_dec)
```

but ensure `expected_move_dec` is normalized **before** this call.

Extend relevant logging/return metadata:

```text
expected_move_pct=0.2400 expected_move_src=atr_abs_price_normalized required_move_pct=0.2300
```

For an XRP reject, expected telemetry should become approximately:

```text
expected_move_pct=0.0511 expected_move_src=atr_abs_price_normalized required_move_pct=0.2300
```

### 3. Propagate normalized expected move safely

If an allowed paper entry carries `expected_move_pct` downstream, propagate the corrected percent value and optional `expected_move_src`. Ensure later `paper_trade_executor.py` does not re-correct an already normalized percentage incorrectly.

If the later P1.1AI correction has a source field available, honor:

```python
expected_move_src == "atr_abs_price_normalized"
```

as already normalized.

## Required regression tests

Add focused tests in the most suitable existing exploration test file (prefer `tests/test_p1_paper_exploration.py`) and only create a new test file if needed.

### Test A — ADA-like absolute ATR passes after normalization

```python
signal = {
    "symbol": "ADAUSDT",
    "price": 0.2500,
    "atr": 0.0006,
    "ev": 0.0300,
    "action": "BUY",
    # include minimum existing fields required by paper_exploration_override
}
```

For the C_WEAK/cost-edge path:

```text
expected_move_pct ~= 0.2400
expected_move_src == "atr_abs_price_normalized"
cost edge passes / not rejected for cost_edge_too_low
```

Use tolerance, not exact float equality.

### Test B — XRP-like absolute ATR still fails correctly

```python
signal = {
    "symbol": "XRPUSDT",
    "price": 1.3700,
    "atr": 0.0007,
    "ev": 0.0300,
    "action": "BUY",
}
```

Assert:

```text
expected_move_pct ~= 0.0511
expected_move_src == "atr_abs_price_normalized"
rejected with reason=cost_edge_too_low
```

### Test C — Threshold not weakened

A normalized expected move just below 0.2300% must fail; just above must pass. Do not alter `_MIN_REQUIRED_MOVE_PCT`.

### Test D — Missing/invalid price remains safe

For ATR present but no valid price, do not create a false-positive entry. Preserve an explicit safe reject/fallback and log source/reason.

### Test E — Existing P1.1AP-J/I2 invariants remain

Run existing tests to prove:
- D_NEG no canonical learning/log leak.
- `PAPER_TRADE_SAVED` telemetry remains separate.
- B route trigger behavior unchanged.
- Canonical C_WEAK update behavior unchanged once a sample closes.

## Required validation commands

Run narrow affected tests first:

```bash
python -m pytest -q tests/test_p1_paper_exploration.py -k "cost_edge or expected_move or recovery_ready or route_trigger"
```

Then full paper safety set:

```bash
python -m pytest -q \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ab_stale_position_quarantine.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_v10_13u_patches.py
```

Then server-safe full suite:

```bash
python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

## Post-deploy production validation

After deploy/restart, use a clean absolute timestamp starting at the new service restart.

```bash
sudo systemctl restart cryptomaster
sleep 120

sudo journalctl -u cryptomaster --since "10 min ago" --no-pager | grep -E \
"PAPER_EXPLORE_SKIP|PAPER_TRAIN_SKIP|PAPER_TRAIN_QUALITY_ENTRY|expected_move_pct|expected_move_src|cost_edge_too_low|ADAUSDT|XRPUSDT|PAPER_TRADE_SAVED|PAPER_LEARNING_SHADOW_SKIP|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|Traceback|UnboundLocalError"
```

Expected after patch:

```text
ADA-like signal with atr=0.0006 and price~0.25:
- expected_move_pct around 0.24
- expected_move_src=atr_abs_price_normalized
- not blocked solely as cost_edge_too_low when above 0.2300

XRP-like signal with atr=0.0006/0.0007 and price~1.37:
- expected_move_pct around 0.044–0.051
- still blocked as cost_edge_too_low

D_NEG:
- still shadow-only

C_WEAK accepted samples:
- still canonical learn only on close via LM_STATE_AFTER_UPDATE + LEARNING_UPDATE ok=True
- save telemetry remains PAPER_TRADE_SAVED
```

## Acceptance criteria

- False cost-edge rejection for ADA-like normalized-above-threshold cases is fixed.
- Correct low-edge XRP rejections remain.
- Telemetry identifies expected move source and reports correct units.
- Cost threshold is unchanged.
- No live/real, RDE, TP/SL, P1.1AO, D_NEG, B_RECOVERY, Firebase, or Android behavior changes.
- Targeted and full safety tests pass.
- No runtime/local artifacts committed.

## Commit message

```text
P1.1AP-K: Normalize ATR price move before C_WEAK cost-edge gate
```

Do not commit:

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary log/shell-output files
```
