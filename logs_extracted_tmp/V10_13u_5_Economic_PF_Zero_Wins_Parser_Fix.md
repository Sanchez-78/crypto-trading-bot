# V10.13u+5 — Economic PF Zero-Wins Parser Fix

## Production symptom

Current live commit: `393e92b`

Logs prove V10.13u+4 is deployed, but PF still does not match dashboard:

```text
Dashboard Profit Factor  0.75x
[ECON_CANONICAL_ACTIVE] pf=1.00 source=canonical_closed_trades closed_trades=500 wins=0 losses=0 gross_win=0.00000000 gross_loss=0.00000000 net_pnl=0.00000000
Economic: 0.592 [CAUTION]
PF: 1.00
```

## Diagnosis

The source is now correct (`canonical_closed_trades`) and the trade count is correct (`closed_trades=500`), but the parser is wrong.

`canonical_profit_factor_with_meta()` receives 500 trades but extracts zero usable PnL/win/loss values:

```text
wins=0 losses=0 gross_win=0 gross_loss=0 net_pnl=0
```

So it returns neutral PF `1.00`.

This means the function is not reading the same fields as the dashboard `MetricsEngine.compute_canonical_trade_stats(recent_trades)`.

## Safety impact

Economic Health is still not authoritative.

Expected:
```text
Dashboard PF = 0.75
Economic PF = 0.75
Economic status = BAD or CAUTION, never GOOD
```

Current:
```text
Dashboard PF = 0.75
Economic PF = 1.00
Economic status = CAUTION
```

The old stale `12.08` bug is fixed, but a new field-normalization bug remains.

---

## Patch goal

Make `canonical_metrics.py` use the exact same PnL extraction and win/loss classification as the dashboard canonical stats.

Do not invent a new formula. Reuse or mirror `MetricsEngine.compute_canonical_trade_stats()`.

---

## Required implementation

### 1. Inspect dashboard canonical implementation

Find the dashboard source:

```bash
grep -R "def compute_canonical_trade_stats\|profit_factor\|gross_win\|gross_loss\|WR_canonical" -n src bot2 main.py start.py
```

Identify:
- which PnL field it uses
- how it classifies wins/losses/flats
- whether it uses `net_pnl`, `pnl`, `profit`, `profit_pct`, `realized_pnl`, `net_profit`, etc.
- whether it ignores scratch/flat trades
- whether it uses absolute gross loss

### 2. Replace `canonical_profit_factor_with_meta()` with dashboard-equivalent logic

In `src/services/canonical_metrics.py`, implement robust PnL extraction:

```python
PNL_KEYS = (
    "net_pnl",
    "pnl",
    "profit",
    "profit_pct",
    "realized_pnl",
    "realized_profit",
    "net_profit",
    "pnl_pct",
    "result",
)
```

Rules:
- Convert numeric strings safely.
- Ignore `None`, missing, empty string, NaN.
- Win if pnl > epsilon.
- Loss if pnl < -epsilon.
- Flat otherwise.
- `gross_win = sum(pnl for pnl > eps)`
- `gross_loss = abs(sum(pnl for pnl < -eps))`
- `pf = gross_win / gross_loss` if gross_loss > 0
- if wins == 0 and losses == 0: return `pf=0.0` or `pf=1.0` only with `source=no_decisive_trades`, but log as parser failure if `closed_trades >= 100`

Use same epsilon as dashboard if available; otherwise:

```python
EPS = 1e-12
```

### 3. Add parser diagnostic sample

If `closed_trades >= 100` and `wins == 0 and losses == 0`, log first 3 trade keys and small sanitized samples:

```python
logger.warning(
    "[ECON_CANONICAL_PARSE_FAIL] closed_trades=%s wins=0 losses=0 "
    "sample_keys=%s sample=%s",
    len(closed_trades), sample_keys, sample,
)
```

Do not log secrets. Only trade dict keys + small values for PnL/status/exit fields.

### 4. Prefer reuse if possible

Best option:

```python
from src.services.metrics_engine import MetricsEngine
stats = MetricsEngine().compute_canonical_trade_stats(closed_trades)
```

or the actual dashboard engine path if different.

Then `canonical_profit_factor_with_meta()` should wrap that output instead of duplicating logic.

If direct import causes circular import, extract the shared calculation into `canonical_metrics.py` and make dashboard call that same function.

### 5. Hard safety clamp remains

Keep this rule in `learning_monitor.py`:

```python
if pf < 1.0 and net_pnl <= 0:
    status = "BAD"
    economic_score = min(economic_score, 0.35)
elif pf < 1.0:
    status = min_status(status, "CAUTION")
    economic_score = min(economic_score, 0.49)
```

Also add:
```python
if closed_trades >= 100 and wins == 0 and losses == 0:
    status = "BAD"
    economic_score = 0.0
```

Reason: 500 trades with zero parsed wins/losses is a parser failure, not a valid neutral economy.

---

## Expected logs after deploy

```text
[RUNTIME_VERSION] commit=<new_commit> branch=main
[ECON_CANONICAL_ACTIVE] pf=0.75 source=canonical_closed_trades closed_trades=500 wins=78 losses=24 gross_win=... gross_loss=... net_pnl=-0.00052 economic_score=<low> status=BAD
Profit Factor  0.75x
PF: 0.75
Economic: <low> [BAD]
```

## Forbidden logs

```text
pf=12.08
pf=1.00 closed_trades=500 wins=0 losses=0
Economic: ... [GOOD]
Economic: ... [CAUTION] with parser failure
```

---

## Validation commands

```bash
cd /opt/cryptomaster
git pull --ff-only
git rev-parse --short HEAD

sudo systemctl restart cryptomaster
sleep 8

sudo journalctl -u cryptomaster -n 1200 --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_CANONICAL|ECON_CANONICAL_PARSE_FAIL|Profit Factor|Economic:|PF:|ERROR|WARNING" \
  | tail -100
```

## Acceptance criteria

Pass only if all are true:

- Runtime commit is the new commit.
- `source=canonical_closed_trades`.
- `closed_trades=500`.
- `wins` and `losses` are non-zero and match dashboard decisive trade counts approximately.
- Dashboard PF and Economic PF match.
- Economic status is not GOOD when PF < 1.0 or net PnL <= 0.
- No parser failure for 500 trades.

---

## Minimal Codex task

Fix `canonical_metrics.py` so `canonical_profit_factor_with_meta(closed_trades)` calculates from the exact same trade fields/classification as dashboard `Profit Factor 0.75x`. Current bug: receives 500 trades but parses wins=0 losses=0 gross_win=0 gross_loss=0, returning PF=1.00. Add parser diagnostics and tests. Preserve safety clamp: PF<1 + net_pnl<=0 => BAD.
