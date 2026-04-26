# CryptoMaster V10.13u+2 — Fix Missing `canonical_metrics` Import

## Problem seen in production

Log:

```text
WARNING:src.services.learning_monitor:[ECONOMIC_HEALTH] Calculation failed: No module named 'src.services.canonical_metrics'
```

Meaning:
- deployed runtime is calling canonical PF / economic health logic
- but `src/services/canonical_metrics.py` is missing on the Hetzner runtime path, not committed, not deployed, or the service runs from a different project directory
- PATCH 2 cannot work until this module exists and is importable

This is not a trading-logic problem. It is a deployment/package/import consistency problem.

---

## Goal

Make `canonical_metrics` import-safe and production-safe.

After patch:

```text
[ECON_CANONICAL] pf=0.75 source=canonical trades=500
```

Must not appear:

```text
No module named 'src.services.canonical_metrics'
[ECONOMIC_HEALTH] Calculation failed
```

---

## Step 1 — Verify file exists locally and on server

Run locally:

```bash
dir src\services\canonical_metrics.py
git status --short
git ls-files | findstr canonical_metrics
```

Run on Hetzner:

```bash
cd /opt/cryptomaster || cd ~/CryptoMaster_srv
ls -la src/services/canonical_metrics.py
git rev-parse --short HEAD
git status --short
python3 - <<'PY'
from src.services.canonical_metrics import canonical_profit_factor
print("canonical_metrics import OK", canonical_profit_factor([]))
PY
```

If file is missing locally or not tracked, create it.

---

## Step 2 — Create/repair `src/services/canonical_metrics.py`

Create this file exactly:

```python
# src/services/canonical_metrics.py
"""Canonical trading metrics.

Single source of truth for dashboard, audit, economic health and backend gates.
All helpers are defensive: bad/missing fields must not crash production.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable


EPS = 1e-12


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def canonical_trade_pnl(trade: dict[str, Any]) -> float:
    """Return normalized net PnL from any known trade schema."""
    if not isinstance(trade, dict):
        return 0.0

    for key in (
        "net_pnl",
        "pnl_net",
        "realized_pnl",
        "realizedPnL",
        "pnl",
        "profit",
        "profit_pct",
        "pnl_pct",
    ):
        if key in trade:
            return _as_float(trade.get(key), 0.0)

    return 0.0


def canonical_closed_trades(trades: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only closed/history trades. If status is absent, assume historical item is closed."""
    out: list[dict[str, Any]] = []
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        status = str(t.get("status") or t.get("state") or t.get("phase") or "closed").lower()
        if status in {"closed", "done", "finished", "exit", "exited", "settled"} or "close" in status:
            out.append(t)
        elif "status" not in t and "state" not in t and "phase" not in t:
            out.append(t)
    return out


def canonical_win_rate(trades: Iterable[dict[str, Any]]) -> float:
    """Wins / (wins + losses). Flats are excluded."""
    wins = 0
    losses = 0

    for t in canonical_closed_trades(trades):
        pnl = canonical_trade_pnl(t)
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    denom = wins + losses
    return wins / denom if denom else 0.0


def canonical_profit_factor(trades: Iterable[dict[str, Any]]) -> float:
    """Gross wins / abs(gross losses). Flats ignored.

    Returns:
      0.0 if no wins/losses
      inf if wins exist but losses are zero
    """
    gross_win = 0.0
    gross_loss = 0.0

    for t in canonical_closed_trades(trades):
        pnl = canonical_trade_pnl(t)
        if pnl > 0:
            gross_win += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)

    if gross_loss <= EPS:
        return float("inf") if gross_win > EPS else 0.0

    return gross_win / gross_loss


def canonical_expectancy(trades: Iterable[dict[str, Any]]) -> float:
    pnls = [canonical_trade_pnl(t) for t in canonical_closed_trades(trades)]
    return mean(pnls) if pnls else 0.0


def canonical_exit_breakdown(trades: Iterable[dict[str, Any]]) -> dict[str, float]:
    closed = canonical_closed_trades(trades)
    total = len(closed)
    if not total:
        return {"tp": 0.0, "sl": 0.0, "scratch": 0.0, "timeout": 0.0, "other": 0.0}

    counts = {"tp": 0, "sl": 0, "scratch": 0, "timeout": 0, "other": 0}

    for t in closed:
        reason = str(
            t.get("exit_reason")
            or t.get("close_reason")
            or t.get("reason")
            or t.get("type")
            or ""
        ).lower()

        if "tp" in reason or "take" in reason or "micro" in reason or "partial" in reason:
            counts["tp"] += 1
        elif "sl" in reason or "stop" in reason or "loss" in reason:
            counts["sl"] += 1
        elif "scratch" in reason or "flat" in reason:
            counts["scratch"] += 1
        elif "timeout" in reason or "time" in reason:
            counts["timeout"] += 1
        else:
            counts["other"] += 1

    return {k: v / total for k, v in counts.items()}


def canonical_rr(tp_distance: Any, sl_distance: Any) -> float:
    tp = abs(_as_float(tp_distance, 0.0))
    sl = abs(_as_float(sl_distance, 0.0))
    if sl <= EPS:
        return 0.0
    if tp <= EPS:
        return 0.0
    return tp / sl


def canonical_overall_health(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    closed = canonical_closed_trades(trades)
    wr = canonical_win_rate(closed)
    pf = canonical_profit_factor(closed)
    exp = canonical_expectancy(closed)

    pf_score = 1.0 if pf == float("inf") else max(0.0, min(pf / 1.5, 1.0))
    wr_score = max(0.0, min(wr / 0.55, 1.0))
    exp_score = 1.0 if exp > 0 else 0.35 if exp == 0 else 0.0

    score = round(0.45 * pf_score + 0.35 * wr_score + 0.20 * exp_score, 3)

    if score >= 0.80:
        status = "EXCELLENT"
    elif score >= 0.60:
        status = "GOOD"
    elif score >= 0.40:
        status = "CAUTION"
    else:
        status = "CRITICAL"

    return {
        "score": score,
        "status": status,
        "trades": len(closed),
        "win_rate": wr,
        "profit_factor": pf,
        "expectancy": exp,
    }


def get_metrics_snapshot(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    closed = canonical_closed_trades(trades)
    pnls = [canonical_trade_pnl(t) for t in closed]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    flats = sum(1 for p in pnls if p == 0)

    return {
        "trades": len(closed),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": canonical_win_rate(closed),
        "profit_factor": canonical_profit_factor(closed),
        "expectancy": canonical_expectancy(closed),
        "net_pnl": sum(pnls),
        "exit_breakdown": canonical_exit_breakdown(closed),
        "health": canonical_overall_health(closed),
    }
```

---

## Step 3 — Ensure package import works

Check `src/services/__init__.py` exists:

```bash
touch src/__init__.py
touch src/services/__init__.py
```

Run:

```bash
python - <<'PY'
from src.services.canonical_metrics import canonical_profit_factor, canonical_rr
print("PF empty:", canonical_profit_factor([]))
print("RR:", canonical_rr(1.2, 0.8))
PY
```

Expected:

```text
PF empty: 0.0
RR: 1.4999999999999998
```

---

## Step 4 — Commit and deploy

```bash
git add src/services/canonical_metrics.py src/__init__.py src/services/__init__.py
git commit -m "fix canonical metrics import in production"
git push origin main
```

Wait for GitHub Actions deploy, then on Hetzner:

```bash
sudo systemctl restart cryptomaster
sleep 5
sudo journalctl -u cryptomaster -n 250 --no-pager | egrep "RUNTIME_VERSION|ECON_CANONICAL|ECONOMIC_HEALTH|canonical_metrics|PATCH_MATURITY|LM_HYDRATE|Traceback|ERROR|WARNING"
```

---

## Step 5 — Acceptance criteria

Required:

```text
[RUNTIME_VERSION] ... commit=<new_commit> branch=main
[ECON_CANONICAL] pf=0.75 source=canonical trades=500
[LM_HYDRATE_CANONICAL] trades=500 pairs=17
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False
```

Forbidden:

```text
No module named 'src.services.canonical_metrics'
[ECONOMIC_HEALTH] Calculation failed
Traceback
commit=UNKNOWN
trades=0 bootstrap=True
```

---

## Important note

The log also shows:

```text
SCRATCH_EXIT 341/500 = 68%
STAGNATION_EXIT 55/500 = 11%
```

Do not tune exits yet. First fix canonical import and confirm PF/economic health consistency. Exit optimization comes after the canonical metrics module is stable in production.
