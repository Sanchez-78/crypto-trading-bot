# V10.13x.1 — Dashboard Truth Patch

## Goal

Repair the **dashboard truth layer** so every displayed KPI comes from one canonical closed-trade source and no block can silently fall back to fake zeros or stale parallel aggregators.

This patch is **not** about strategy tuning, EV tuning, entry filters, or risk changes.

This patch is only about:

- truthful totals
- truthful PnL
- truthful WR
- truthful recent-window stats
- truthful calibration state
- explicit mismatch detection
- removal of silent fallback values

---

## What the latest logs prove

The current deployment still has cross-layer inconsistency.

### Confirmed contradictions

From the observed output:

- `Obchody 100 (OK 0 X 0 ~ 100)` does **not** reconcile with per-symbol counts.
- `WR_canonical N/A (malo dat: 0/10 rozhodujicich)` conflicts with visible per-symbol/per-regime trade results.
- `Zisk +0.00000000` conflicts with non-zero per-symbol PnL totals.
- `Trend uceni SBÍRÁ DATA...` with `Poslednich 0` and `WR=0.0%` looks like a fallback/default branch, not real data.
- `Kalibrace KALIBROVAN ✓ (100 obchodu celkem)` while recent decision-quality stats still show zero-like placeholders means different sections are reading different sources.
- The dashboard is still mixing:
  - canonical summary
  - legacy symbol/regime aggregators
  - default/fallback recent-window values

### Root cause hypothesis

The canonical stats object exists, but **not all render paths use it**.

Likely architecture problem:

1. header summary reads canonical stats
2. symbol/regime blocks read older cached or legacy aggregators
3. learning summary / recent-window block still uses fallback logic or a stale event-driven source
4. render functions do not fail loudly on mismatch

---

## Required outcome

After this patch, every user-visible dashboard metric must obey:

- one authoritative canonical closed-trade source
- one authoritative recent-window derivation from canonical data
- no zero fallback unless the underlying data is truly empty
- explicit warning if any displayed section disagrees with canonical truth

---

## Scope

### In scope

- dashboard truth repair
- reconciliation checks
- recent-window truth repair
- fallback suppression
- calibration truth gating
- explicit warnings for mismatch
- source tagging in debug logs

### Out of scope

- strategy logic
- regime detection changes
- EV math changes
- bandit logic changes
- risk engine changes
- Firebase quota redesign
- execution sizing changes

---

## Implementation target

Create **V10.13x.1 Dashboard Truth Patch**.

Primary intent:

- make the dashboard mathematically truthful
- make data-source usage explicit
- make mismatch impossible to miss

---

## Files to inspect first

Read before modifying:

- `src/services/metrics_engine.py`
- `src/services/learning_monitor.py`
- `src/services/learning_event.py`
- `src/services/dashboard.py`
- `src/services/dashboard_live.py`
- `bot2/main.py`

Search specifically for:

- `compute_canonical_trade_stats`
- `WR_canonical`
- `Obchody`
- `Kalibrace`
- `Poslednich`
- `Trend uceni`
- `VYSLEDKY PO MENACH`
- `WR dle rezimu`
- `EXIT_AUDIT`
- `recent`
- `fallback`
- `N/A`
- `0/10`
- `0.0%`

---

## Patch requirements

## 1. Canonical object must drive all summary sections

Create or confirm one canonical object per render cycle, derived only from **closed trades**.

Example shape:

```python
canonical = compute_canonical_trade_stats(closed_trades)
```

Every displayed summary block must derive from this same object or from a clearly documented derivative of it.

### Blocks that must be unified

- `Obchody`
- `WR_canonical`
- total `Zisk`
- `Profit Factor`
- `Expectancy`
- `Nejlepsi`
- `Nejhorsi`
- `Posledni obchod`
- `VYSLEDKY PO MENACH`
- `WR dle rezimu`
- `VYSLEDKY PODLE TYPU UZAVRENI`
- `Kalibrace`
- `Trend uceni`
- `Poslednich X`
- `Kalibrace p`

If a section cannot be driven from canonical truth yet, it must print:

- `N/A`
- `source unavailable`

and log a warning.

It must **not** print fake zeros.

---

## 2. Remove silent fallback zeros

Anywhere the dashboard currently produces values like:

- `0.0%`
- `0/10`
- `+0.00000000`
- `Poslednich 0`
- `WR=0.0%`

without proving that the underlying dataset is truly empty, replace that with guarded output.

### Required guard pattern

```python
def fmt_optional_metric(value, known: bool, fmt: str = "{:.1%}", na: str = "N/A"):
    if not known:
        return na
    return fmt.format(value)
```

Use the same principle for counts, windows, and PnL.

### Rule

If the metric dataset is missing, stale, filtered out incorrectly, or unresolved:

- do not print a numeric zero
- print `N/A`
- log why

---

## 3. Add strict reconciliation check per render cycle

Before rendering the dashboard, build a reconciliation report.

### Minimum checks

#### Count reconciliation
- `wins + losses + flats == trades_total`

#### Symbol reconciliation
- `sum(per_symbol.count) == trades_total`
- `sum(per_symbol.net_pnl) == total_net_pnl` within tolerance

#### Regime reconciliation
- `sum(per_regime.count) == trades_total`
- `sum(per_regime.net_pnl) == total_net_pnl` within tolerance

#### Exit reconciliation
- `sum(per_exit_type.count) == trades_total`
- `sum(per_exit_type.net_pnl) == total_net_pnl` within tolerance

#### Recent-window reconciliation
- recent trades used by learning trend must be a subset of canonical closed trades
- if subset empty, print `N/A`, not zero

### Required log

Every render cycle or every N cycles:

```python
[V10.13x.1 RECON]
counts_ok=...
symbol_ok=...
regime_ok=...
exit_ok=...
recent_ok=...
status=OK|MISMATCH
```

If mismatch occurs, include exact deltas.

Example:

```python
[V10.13x.1 RECON] status=MISMATCH total=100 symbol_sum=19 regime_sum=19 exit_sum=100 pnl_total=0.00000000 pnl_symbol=0.00016255
```

---

## 4. Add source tags to each rendered section

Internally, every major render block must know what source it used.

### Example source tags

- `canonical_closed_trades`
- `canonical_recent_window`
- `learning_monitor_state`
- `legacy_cache`
- `unavailable`

### Required debug log

For each major section, log one compact line:

```python
[V10.13x.1 SRC] header=canonical_closed_trades symbols=canonical_closed_trades regimes=canonical_closed_trades recent=canonical_recent_window calibration=canonical_recent_window
```

This is critical for finding hidden legacy branches.

---

## 5. Repair recent-window logic

The current `Poslednich 0` / `WR=0.0%` behavior is almost certainly a filter bug or a stale source bug.

### Required fix

Implement a dedicated recent-window function that derives strictly from canonical closed trades.

Example:

```python
def compute_recent_window_stats(closed_trades, window=24):
    decisive = [t for t in closed_trades if t["outcome"] in ("WIN", "LOSS")]
    recent = decisive[-window:]
    if not recent:
        return {
            "known": False,
            "window": 0,
            "wr": None,
            "avg_ev": None,
        }
    wins = sum(1 for t in recent if t["outcome"] == "WIN")
    return {
        "known": True,
        "window": len(recent),
        "wr": wins / len(recent),
        "avg_ev": sum(t.get("ev_final", 0.0) for t in recent) / len(recent),
    }
```

### Output rule

- If no recent decisive trades: `N/A`
- Never show `0` unless there are truly zero-valued valid stats

Use plain Czech, for example:

- `Poslednich N/A  (zadne rozhodujici obchody)`
- `Trend uceni N/A  (nedostatek recent dat)`

---

## 6. Repair total PnL display

The dashboard total PnL must come from canonical closed-trade aggregation only.

It must **not** come from:

- live equity drift
- open-position unrealized PnL
- stale dashboard cache
- execution engine fallback

### Required behavior

Display closed-trade PnL explicitly as closed-trade PnL.

If open PnL is also shown, it must be a separate metric, clearly labeled.

Example:

- `Zisk (uzavrene obchody)`
- `Open PnL (otevrene pozice)`

Do not merge them implicitly.

---

## 7. Gate calibration text on real availability

Do not display:

- `KALIBROVAN ✓`
- `dobre`
- `odkalibrovan`
- `SBÍRÁ DATA...`

unless the underlying recent-window and calibration inputs are actually valid.

### Required rule

Calibration block must be based on explicit known/unknown state.

Example:

```python
if not recent_stats["known"]:
    calibration_line = "Kalibrace p    N/A  (chybi recent rozhodujici obchody)"
```

### Forbidden

Any combination like:

- `KALIBROVAN ✓`
- `WR=0.0%`
- `Poslednich 0`
- `odchylka 49.8pp`

when recent truth is unresolved.

---

## 8. Keep LM_CLOSE visible and useful

The log confirms `[V10.13w LM_CLOSE]` is visible now. Preserve that.

But add one canonical economic summary path so close events can be reconciled with dashboard totals.

### Requirement

Each close event should carry enough info for canonical accounting:

- symbol
- regime
- direction
- close_reason
- gross_pnl
- fee
- slip
- net_pnl
- outcome
- closed_at

Do not rely on inferred/secondary reconstruction if direct values exist.

---

## 9. Exit attribution must become economic, not only count-based

The current section still shows mostly counts.

Required next stage inside this patch:

For each exit type, compute:

- count
- wins
- losses
- flats
- net_pnl
- avg_pnl
- pct_of_total_trades
- pct_of_total_net_pnl

### Example target output

```text
SCRATCH_EXIT   80  WR 62%  net +0.000081  avg +0.0000010  79% trades  43% pnl
PARTIAL_TP_25   9  WR 100% net +0.000054  avg +0.0000060   9% trades  29% pnl
```

If not enough data, print `N/A`, not zeros.

---

## 10. One user-facing learning block per cycle

Do not repeat the same learning diagnosis multiple times in one cycle.

Required:

- one consolidated human-readable block
- optional machine logs separately
- no duplicate `[!] LEARNING:` spam in the same cycle

---

## Acceptance checklist

Mark every item explicitly.

### Truth reconciliation

- [ ] `wins + losses + flats == trades_total`
- [ ] `sum(per_symbol.count) == trades_total`
- [ ] `sum(per_regime.count) == trades_total`
- [ ] `sum(per_exit_type.count) == trades_total`
- [ ] `sum(per_symbol.net_pnl) == total_net_pnl`
- [ ] `sum(per_regime.net_pnl) == total_net_pnl`
- [ ] `sum(per_exit_type.net_pnl) == total_net_pnl`

### Dashboard truth

- [ ] Header uses canonical closed-trade source
- [ ] Per-symbol block uses canonical closed-trade source
- [ ] Per-regime block uses canonical closed-trade source
- [ ] Exit block uses canonical closed-trade source
- [ ] Recent trend uses canonical recent-window source
- [ ] Calibration block no longer prints fake zeros

### Fallback suppression

- [ ] No numeric zero printed when data is unknown
- [ ] Unknown values render as `N/A`
- [ ] Missing source logs warning with reason

### Logging

- [ ] `[V10.13x.1 RECON]` visible
- [ ] `[V10.13x.1 SRC]` visible
- [ ] `[V10.13w LM_CLOSE]` still visible
- [ ] No duplicate learning block spam per cycle

### User-visible proof

- [ ] No output like `Obchody 100 (OK 0 X 0 ~ 100)` when symbol breakdown disagrees
- [ ] No `WR_canonical N/A` when decisive trades clearly exist
- [ ] No total PnL zero while per-symbol PnL is non-zero
- [ ] No `Poslednich 0` unless recent decisive set is truly empty

---

## Required deliverables

Return all of the following:

1. short root-cause summary
2. exact files changed
3. patch diff or full changed functions
4. explanation of each bug fixed
5. sample expected dashboard output after patch
6. sample expected reconciliation logs
7. note of any unresolved ambiguity

---

## Expected output example after fix

Example only; exact numbers will differ.

```text
Obchody    100  (OK 19  X 3  ~ 78)
WR_canonical     86.4%  (22 rozhodujicich obchodu, bez flat)
Zisk (uzavrene)  +0.00016255
Drawdown         0.00053148
Profit Factor    3.41x
Expectancy       +0.00000163

VYSLEDKY PODLE TYPU UZAVRENI
SCRATCH_EXIT  80  WR 65%  net +0.000081  avg +0.0000010
PARTIAL_TP_25 9   WR 100% net +0.000054  avg +0.0000060

Trend uceni    STABILNI
Poslednich 22    81.8%  vs prumer 86.4%  (-4.6%)
Kalibrace p      p=49.8%  WR=86.4%  odchylka 36.6pp  odkalibrovano
```

And logs:

```text
[V10.13x.1 SRC] header=canonical_closed_trades symbols=canonical_closed_trades regimes=canonical_closed_trades exits=canonical_closed_trades recent=canonical_recent_window calibration=canonical_recent_window
[V10.13x.1 RECON] counts_ok=True symbol_ok=True regime_ok=True exit_ok=True recent_ok=True status=OK
```

---

## Hard rules

- Do not change trading behavior.
- Do not change entry/exit thresholds.
- Do not change EV formulas.
- Do not change risk engine behavior.
- Do not hide mismatch.
- Do not print fake zeros.
- Prefer `N/A` over fabricated certainty.
- Prefer loud mismatch logs over silent wrong dashboard output.

---

## Final instruction

Implement **V10.13x.1 Dashboard Truth Patch** exactly for truth recovery and observability.

Priority order:

1. canonical truth
2. reconciliation
3. fallback suppression
4. recent-window repair
5. calibration truth
6. exit economics
7. deduplicated learning output

If a metric cannot be made truthful in this patch, mark it clearly as `N/A` and log why.
