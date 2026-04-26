# V10.13u+8 — Canonical Exit PnL Integrity Patch

## Purpose
Fix false `EXIT_INTEGRITY_ERROR` caused by divergent PnL calculations.

Current divergence:
- `trade_executor`: `profit = (move - fee_used) * size + realized_pnl`
- `exit_attribution`: `gross_pnl = move * size` without `realized_pnl`
- `LM_CLOSE`: computes `gross - fee - slip`, also missing `realized_pnl`

When partial TP exists, `realized_pnl != 0`, so validator compares incompatible values.

## Files
- CREATE `src/services/exit_pnl.py`
- MODIFY `src/services/trade_executor.py`
- MODIFY `src/services/exit_attribution.py`
- MODIFY `src/services/smart_exit_engine.py`
- MODIFY `tests/test_v10_13u_patches.py`

## Hard Rules
Do not change:
- `canonical_profit_factor`
- `canonical_profit_factor_with_meta`
- `lm_economic_health`
- partial TP accumulation logic
- EV-only enforcement
- TP/SL/emergency paths
- `build_exit_ctx` signature
- Firebase quota logic

---

## 1) Create `src/services/exit_pnl.py`

```python
"""V10.13u+8: Canonical close-PnL helper."""
from __future__ import annotations


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
    prior_realized_pnl: float = 0.0,
) -> dict:
    side_u = str(side).upper()
    if side_u == "BUY":
        raw_move_pnl = (exit_price - entry_price) / entry_price * size
    elif side_u == "SELL":
        raw_move_pnl = (entry_price - exit_price) / entry_price * size
    else:
        raise ValueError(f"Unsupported side={side!r}")

    gross_pnl = raw_move_pnl + prior_realized_pnl

    fee_pnl = -abs(realized_fee) if realized_fee is not None else -(abs(fee_rate) * size)
    slippage_pnl = (
        -abs(realized_slippage)
        if realized_slippage is not None
        else -(abs(slippage_rate) * size)
    )

    net_pnl = gross_pnl + fee_pnl + slippage_pnl

    assert fee_pnl <= 0
    assert slippage_pnl <= 0
    assert abs(net_pnl - (gross_pnl + fee_pnl + slippage_pnl)) < 1e-12

    return {
        "gross_pnl": gross_pnl,
        "fee_pnl": fee_pnl,
        "slippage_pnl": slippage_pnl,
        "net_pnl": net_pnl,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "source": "canonical_close_pnl",
    }
```

Design: `gross_pnl` includes `prior_realized_pnl`, so `gross + fee + slip == net`.

---

## 2) Modify `src/services/trade_executor.py`

### Import
Add near exit attribution import:

```python
from src.services.exit_pnl import canonical_close_pnl
```

### Replace close profit calculation

Old:
```python
fee_used = pos.get("fee_rt", FEE_RT)
profit = (move - fee_used) * pos["size"] + pos.get("realized_pnl", 0.0)
```

New:
```python
fee_used = pos.get("fee_rt", FEE_RT)
_realized_pnl_val = pos.get("realized_pnl", 0.0)

_pnl_result = canonical_close_pnl(
    symbol=sym,
    side=pos["action"],
    entry_price=entry,
    exit_price=curr,
    size=pos["size"],
    fee_rate=fee_used,
    slippage_rate=pos.get("fill_slippage", 0.0),
    prior_realized_pnl=_realized_pnl_val,
)

profit = _pnl_result["net_pnl"]
```

### Replace LM_CLOSE diagnostic vars

Old:
```python
_fee_cost = fee_used * pos["size"]
_slip_cost = pos.get("fill_slippage", 0.0) * pos["size"]
_gross_pnl = move * pos["size"]
_net_pnl = _gross_pnl - _fee_cost - _slip_cost
```

New:
```python
_fee_cost = -_pnl_result["fee_pnl"]
_slip_cost = -_pnl_result["slippage_pnl"]
_gross_pnl = _pnl_result["gross_pnl"]
_net_pnl = _pnl_result["net_pnl"]
```

### Fix `build_exit_ctx`

Old:
```python
gross_pnl=(move * pos["size"]),
fee_cost=(fee_used * pos["size"]),
slippage_cost=pos.get("fill_slippage", 0.0) * pos["size"],
net_pnl=profit,
```

New:
```python
gross_pnl=_pnl_result["gross_pnl"],
fee_cost=_fee_cost,
slippage_cost=_slip_cost,
net_pnl=_pnl_result["net_pnl"],
```

### Add persisted fields to trade dict

After:
```python
"pnl": profit,
```

Add:
```python
"net_pnl": _pnl_result["net_pnl"],
"gross_pnl": _pnl_result["gross_pnl"],
"fee_pnl": _pnl_result["fee_pnl"],
"slippage_pnl": _pnl_result["slippage_pnl"],
```

---

## 3) Modify `src/services/exit_attribution.py`

Replace `validate_exit_ctx` net check:

```python
if ctx.get("gross_pnl") is not None and ctx.get("net_pnl") is not None:
    expected = (
        ctx["gross_pnl"]
        - ctx.get("fee_cost", 0.0)
        - ctx.get("slippage_cost", 0.0)
    )
    actual = ctx["net_pnl"]
    if abs(actual - expected) > 1e-9:
        errors.append(
            f"[EXIT_INTEGRITY] net_pnl mismatch: "
            f"gross={ctx['gross_pnl']:.8f} "
            f"fee={ctx.get('fee_cost', 0.0):.8f} "
            f"slip={ctx.get('slippage_cost', 0.0):.8f} "
            f"expected_net={expected:.8f} "
            f"actual_net={actual:.8f} "
            f"delta={abs(actual - expected):.2e}"
        )
```

Update error log prefix:

```python
log.error(
    f"[V10.13u8 EXIT_INTEGRITY_ERROR] "
    f"sym={ctx.get('symbol')} exit_type={ctx.get('exit_type')}"
)
```

---

## 4) Modify `src/services/smart_exit_engine.py`

Add constants near V10.13u+7 constants:

```python
SCRATCH_NEGATIVE_GRACE_S = 240
STAG_MIN_AGE_ECON_BAD_S = 240
```

### Add ECON BAD scratch guard

Inside `_check_scratch`, after minimum age check and before returning `SCRATCH_EXIT`:

```python
if abs(position.pnl_pct) < SCRATCH_MAX_PNL:
    estimated_fee_pct = 0.002
    net_if_closed = position.pnl_pct - estimated_fee_pct

    if net_if_closed < 0 and position.age_seconds < SCRATCH_NEGATIVE_GRACE_S:
        _econ_bad = False
        try:
            from src.services.learning_monitor import lm_economic_health
            _econ_bad = lm_economic_health().get("status") == "BAD"
        except Exception:
            pass

        if _econ_bad:
            log.info(
                f"[SCRATCH_GUARD] symbol={position.symbol} "
                f"age={position.age_seconds}s "
                f"net_if_closed={net_if_closed * 100:.4f}% "
                f"reason=econ_bad_negative_net_hold"
            )
            self._exit_audit_rejections["SCRATCH_EXIT:too_young"] += 1
            return None

    return {
        # keep existing SCRATCH_EXIT return unchanged
    }
```

### Add ECON BAD stagnation extension

Inside `_check_stagnation`, in negative `net_if_closed` guard block:

```python
if position.age_seconds < STAG_MIN_AGE_ECON_BAD_S:
    _econ_bad = False
    try:
        from src.services.learning_monitor import lm_economic_health
        _econ_bad = lm_economic_health().get("status") == "BAD"
    except Exception:
        pass

    if _econ_bad:
        log.info(
            f"[STAG_GUARD] {position.symbol} age={position.age_seconds}s "
            f"net_if_closed={net_if_closed * 100:.4f}% "
            f"reason=econ_bad_stagnation_hold"
        )
        self._exit_audit_rejections["STAGNATION_EXIT:too_young"] += 1
        return None
```

---

## 5) Add tests

Append before `if __name__ == "__main__":`

Required tests:
- `test_canonical_close_pnl_buy`
- `test_canonical_close_pnl_sell`
- `test_fee_and_slippage_are_non_positive`
- `test_net_equals_gross_plus_costs`
- `test_prior_realized_pnl_included_in_gross`
- `test_exit_integrity_compares_net_not_gross`
- `test_scratch_guard_holds_negative_net_in_econ_bad`
- `test_scratch_guard_allows_exit_when_econ_good`
- `test_stag_guard_holds_negative_net_in_econ_bad`

Minimum accounting test:

```python
def test_prior_realized_pnl_included_in_gross():
    from src.services.exit_pnl import canonical_close_pnl

    r = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=1.0,
        exit_price=1.01,
        size=1.0,
        fee_rate=0.0015,
        slippage_rate=0.0005,
        prior_realized_pnl=0.005,
    )

    expected = r["gross_pnl"] + r["fee_pnl"] + r["slippage_pnl"]
    assert abs(r["net_pnl"] - expected) < 1e-12
    assert r["gross_pnl"] > 0.01
```

---

## Verification

```bash
python -m pytest tests/test_v10_13u_patches.py -k "canonical_close_pnl or exit_integrity or scratch_guard or stag_guard" -v
```

Smoke invariant:

```bash
python -c "from src.services.exit_pnl import canonical_close_pnl; r=canonical_close_pnl(symbol='X',side='BUY',entry_price=100,exit_price=101,size=1.0,fee_rate=0.0015,prior_realized_pnl=0.005); assert abs(r['gross_pnl']+r['fee_pnl']+r['slippage_pnl']-r['net_pnl'])<1e-12; print('Invariant OK')"
```

Hetzner after deploy:

```bash
cd /opt/cryptomaster
git pull
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 20
sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "RUNTIME_VERSION|EXIT_INTEGRITY|LM_CLOSE|CLOSE_LOGIC|SCRATCH_GUARD|STAG_GUARD|ECON_SAFETY_BAD|Economic:|PF:|Profit Factor|ERROR|Traceback"
```

Success:
- `EXIT_INTEGRITY_ERROR = 0`
- `LM_CLOSE net` matches persisted/close net
- dashboard PF matches economic PF
- no `Traceback`
- ECON BAD still active when PF < 1.0
- scratch/stagnation guards appear only for negative-net churn exits
