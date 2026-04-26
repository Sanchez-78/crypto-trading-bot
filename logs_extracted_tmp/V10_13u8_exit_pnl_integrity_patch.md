# V10.13u+8 — Exit PnL Integrity + Scratch/Stagnation Safety Patch

## Situation

Current production logs after V10.13u+7 show that the economic safety patch works, but exit accounting is still inconsistent.

Observed:

```text
Economic: 0.340 [BAD]
PF: 0.74–0.76
[ECON_SAFETY_BAD] ... action=conservative_mode
```

Good: economic health is now canonical and conservative.

New critical issue:

```text
[V10.13v EXIT_INTEGRITY_ERROR] Validation failed for XRPUSDT
- Net PnL mismatch: gross=0.000029 but got 0.000017
```

Same close event shows two different PnL values:

```text
UI / close log:
XRP BUY $1.4305→$1.4312 +0.000017 [SCRATCH_EXIT] fee: 0.00000

LM_CLOSE:
gross=+0.00001666 fee=-0.00000000 slip=+0.00001234 net=+0.00002901
```

This means at least two systems disagree about final trade PnL:
- close/notifier/dashboard path uses price PnL only: `+0.000017`
- LM/exit attribution path uses `gross + slip - fee`: `+0.000029`
- exit integrity validator compares incompatible definitions

This must be fixed before any tuning.

## Do Not Change

Do not change:
- canonical PF formula
- economic health source
- Firebase quota recovery
- EV-only enforcement
- maturity/bootstrap logic
- position sizing tiers except existing ECON BAD tightening
- entry signal generator logic
- TP/SL ATR ratios

This patch is accounting/integrity first, exit guard second.

## Goal

Implement one canonical closed-trade PnL object used everywhere:

```python
gross_pnl = price_move_pnl_before_fee
fee_pnl = negative cost
slippage_pnl = negative cost or 0
net_pnl = gross_pnl + fee_pnl + slippage_pnl
```

Rules:
- `fee_pnl` must never be positive.
- `slippage_pnl` must never be positive unless explicitly documented as price improvement.
- Default slippage should be `0` or negative cost.
- The displayed close log, Firebase trade record, LM_CLOSE, exit_attribution, dashboard canonical stats, and economic health must all read the same `net_pnl`.

## Patch Tasks

### 1. Add canonical close PnL helper

Create or update a single helper, preferably:

```text
src/services/exit_pnl.py
```

Implement:

```python
def canonical_close_pnl(
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    size: float,
    fee_rate: float,
    slippage_rate: float = 0.0,
    realized_fee: float | None = None,
    realized_slippage: float | None = None,
) -> dict:
    ...
```

Return:

```python
{
  "gross_pnl": float,
  "fee_pnl": float,
  "slippage_pnl": float,
  "net_pnl": float,
  "fee_rate": float,
  "slippage_rate": float,
  "source": "canonical_close_pnl"
}
```

Hard invariants:

```python
fee_pnl <= 0
slippage_pnl <= 0
abs(net_pnl - (gross_pnl + fee_pnl + slippage_pnl)) < 1e-12
```

If real exchange fee is unavailable, compute estimated fee from position size and fee rate. Do not print `fee: 0.00000` unless fee is truly zero by config or size is zero.

### 2. Replace local close calculations

Find all close PnL calculations in:

```text
src/services/trade_executor.py
src/services/exit_attribution.py
src/services/learning_monitor.py
src/services/canonical_metrics.py
main.py
start.py
```

Replace duplicated PnL math with the canonical helper.

Required behavior:

```text
[CLOSE_LOGIC]
[TRADE_CLOSE_DEBUG]
[V10.13w LM_CLOSE]
[EXIT_INTEGRITY]
Firebase closed trade record
Dashboard "Profit Factor"
Economic "PF"
```

must all reference the same `net_pnl`.

### 3. Fix exit integrity validator

Update `exit_attribution` validation so it compares:

```python
expected_net_pnl == actual_trade_record["net_pnl"]
```

Do not compare gross against net. Log all components when mismatch occurs:

```text
[EXIT_INTEGRITY_ERROR]
symbol=XRPUSDT close=SCRATCH_EXIT
gross=...
fee=...
slippage=...
expected_net=...
actual_net=...
actual_profit=...
```

Acceptance: no false mismatch where one path uses gross and another uses net.

### 4. Normalize persisted closed trade fields

When writing closed trades to Firebase/history, always include:

```python
profit = net_pnl          # backward compatibility for dashboard
pnl = net_pnl             # compatibility alias
net_pnl = net_pnl         # explicit canonical field
gross_pnl = gross_pnl
fee_pnl = fee_pnl
slippage_pnl = slippage_pnl
close_reason = reason
exit_type = reason
result = "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "FLAT"
```

Never persist only gross as `profit`.

### 5. Add safety guard for scratch/stagnation during ECON BAD

Current logs still show:

```text
STAGNATION_EXIT 73 net -0.00025955
SCRATCH_EXIT 328 net -0.00068915
```

These two exit types dominate losses.

Add conservative mode rule:

When economic status is BAD and `pf < 1.0`:
- block new entry if expected edge cannot cover estimated round-trip fee + slippage
- do not allow SCRATCH_EXIT to close negative net unless max hold or hard risk rule is reached
- do not allow STAGNATION_EXIT before minimum age and unless expected net if closed is at least `>= 0` or position is clearly deteriorating

Suggested constants:

```python
ECON_BAD_MIN_NET_EDGE = 2.0 * fee_rate + slippage_buffer
SCRATCH_NEGATIVE_GRACE_S = 240
STAG_NEGATIVE_GRACE_S = 300
STAG_MIN_AGE_ECON_BAD_S = 240
```

Log holds:

```text
[SCRATCH_GUARD] symbol=... age=... net_if_closed=... reason=econ_bad_negative_net_hold
[STAG_GUARD] symbol=... age=... net_if_closed=... reason=econ_bad_negative_net_hold
```

### 6. Keep emergency exits unchanged

Do not block:
- hard SL
- timeout loss after max hold
- risk liquidation
- drawdown halt
- exchange/order failure safety close

### 7. Add tests

Add tests for:

```text
test_canonical_close_pnl_buy()
test_canonical_close_pnl_sell()
test_fee_and_slippage_are_non_positive()
test_net_equals_gross_plus_costs()
test_exit_integrity_compares_net_not_gross()
test_closed_trade_persists_profit_as_net_pnl()
test_scratch_guard_holds_negative_net_in_econ_bad()
test_stag_guard_holds_negative_net_in_econ_bad()
test_emergency_exit_not_blocked()
```

Run:

```bash
pytest -q tests/test_v10_13u_patches.py
pytest -q
```

## Validation on Hetzner

After deploy:

```bash
cd /opt/cryptomaster
git pull
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 20

sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "RUNTIME_VERSION|EXIT_INTEGRITY|LM_CLOSE|CLOSE_LOGIC|SCRATCH_GUARD|STAG_GUARD|ECON_SAFETY_BAD|Economic:|PF:|Profit Factor|ERROR|Traceback"
```

## Success Signals

Required:

```text
Economic: ... [BAD]
PF: 0.7x
Profit Factor 0.7x
[ECON_SAFETY_BAD] ...
```

No more:

```text
EXIT_INTEGRITY_ERROR Net PnL mismatch
fee: 0.00000 when fee_rate > 0 and size > 0
LM_CLOSE net != close log net
```

Desired:

```text
[SCRATCH_GUARD] ... econ_bad_negative_net_hold
[STAG_GUARD] ... econ_bad_negative_net_hold
```

## 30-Minute Observation

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager \
| grep -E "decision=TAKE|SCRATCH_EXIT|STAGNATION_EXIT|SCRATCH_GUARD|STAG_GUARD|EXIT_INTEGRITY|ECON_SAFETY_BAD|ERROR|Traceback" \
> /tmp/v10_13u8_exit_integrity_observation.log

grep -c "decision=TAKE" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "SCRATCH_EXIT" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "STAGNATION_EXIT" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "SCRATCH_GUARD" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "STAG_GUARD" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "EXIT_INTEGRITY_ERROR" /tmp/v10_13u8_exit_integrity_observation.log
grep -c "Traceback" /tmp/v10_13u8_exit_integrity_observation.log
```

Patch accepted only if:
- `EXIT_INTEGRITY_ERROR = 0`
- dashboard PF equals economic PF
- close log net equals LM_CLOSE net
- scratch/stagnation negative churn is reduced
- no emergency exits are blocked
