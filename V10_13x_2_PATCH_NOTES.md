# V10.13x.2 — Scratch Economics & Health Decomposition

**Status**: ✅ Implementační patch pro V10.13x.x  
**Fokus**: Forensic audit SCRATCH_EXIT + Health transparency  
**Priority**: Odpovědi na kritické otázky z V10.13x log analýzy

---

## Problém (V10.13x log analýza)

V10.13x opravilo count reconciliation, ale odkrylo horší problém:

| Metrika | Stav |
|---------|------|
| Win Rate (canonical) | 77.1% ✅ |
| Closed PnL | **-0.00095045** ❌ |
| SCRATCH_EXIT share | **76% obchodů** ❌ |
| SCRATCH_EXIT net PnL | **-0.00142026** ❌ |
| Learning health | **0.001 [BAD]** ❌ |
| Edge + Convergence | **0.000 (mrtvý)** ❌ |

**Závěr**: Dashboard je teď upřímný, ale ekonomika je rozbitá.

---

## Řešení: V10.13x.2

### 1. SCRATCH_EXIT Forensic Modul

**Soubor**: `src/services/scratch_forensics.py`

Zaznamenává detailní data pro každý SCRATCH_EXIT:
- symbol, regime, hold time
- PnL, MFE (max favorable), MAE (max adverse)
- reason (micro_close, flat_timeout, etc.)

**API**:
```python
from src.services.scratch_forensics import scratch_report, scratch_pressure_alert

# Detailní report
report = scratch_report()
# Returns:
# {
#     "total_count": 382,
#     "net_pnl": -0.00142026,
#     "avg_pnl": -0.00000372,
#     "by_symbol": {...},
#     "by_regime": {...},
#     "by_hold_bucket": {...},
#     "by_pnl_bucket": {...},
#     "negative_after_positive": 45,  # losses po MFE > 0
# }

# Quick alert
alert = scratch_pressure_alert()
# Returns: {"alert_level": "WARNING|CRITICAL|OK", "scratch_share": 0.76, ...}
```

**Co se měří**:
1. ✅ Absolutní počet a PnL SCRATCH_EXIT
2. ✅ Rozpad po symbolu (kde přesně to kouše?)
3. ✅ Rozpad po režimu (BULL vs RANGING)
4. ✅ Rozpad po hold time (0-30s, 30-60s, 1-5m, 5m+)
5. ✅ Rozpad po PnL bucketu (loss, micro, small, medium)
6. ✅ MFE follow-up: kolik scratch exitů po MFE > 0?

### 2. Health Decomposition v2

**Soubor**: `src/services/scratch_forensics.py::health_decomposition_v2()`

Místo jedné komprimované metriky (0.001), vrací **8 granulárních komponent**:

```python
from src.services.scratch_forensics import health_decomposition_v2

health = health_decomposition_v2()
# Returns:
# {
#     "overall": 0.1234,
#     "status": "WEAK",
#     "components": {
#         "edge_strength": 0.001,       # Mean EV (positive pairs only)
#         "convergence": 0.25,          # % pairs s conv > 0.5
#         "stability": 0.45,            # WR consistency (mean/std)
#         "breadth": 0.30,              # % symbol coverage
#         "calibration": 0.0,           # Signal consistency (stub)
#         "exit_quality": 0.0,          # Profitable exits ratio (stub)
#         "scratch_penalty": -0.2,      # Penalty if > 60% scratch
#         "bootstrap_penalty": 0.0,     # Penalty if < 50 trades
#     },
#     "warnings": [
#         "edge_too_weak: mean edge < 0.001",
#         "low_convergence: only 2/5 pairs converged",
#         "scratch_dominance: 76.0% of trades are SCRATCH_EXIT",
#         ...
#     ]
# }
```

**Vysvětluje proč je health nízko**:
- Není to "úplně nula", je to "76% scratch + weak edge"
- Není to "systém je sbitý", je to "scratch peníze zabíjí"

### 3. Integration do Learning Monitor

**Soubor**: `src/services/learning_monitor.py`

- `lm_health_components()` teď vrací novou health v2
- `print_learning_monitor()` zobrazuje komponenty + warnings
- Fallback na legacy pokud import selže

### 4. SCRATCH_EXIT Recording

**Soubor**: `src/services/learning_event.py`

Když je trade uzavřen s `close_reason="SCRATCH_EXIT"`:
```python
record_scratch_exit(
    sym=sym,
    reg=regime,
    hold_time_sec=hold_duration,
    pnl=profit,
    mfe=trade.get("max_favorable_excursion", 0.0),  # TODO: implement collection
    mae=trade.get("max_adverse_excursion", 0.0),    # TODO: implement collection
    reason="SCRATCH_EXIT",
    entry_price=...,
    exit_price=...,
)
```

### 5. Monitoring Dashboard

**Soubor**: `src/services/v10_13x_2_monitoring.py`

```python
from src.services.v10_13x_2_monitoring import print_v10_13x_2_monitoring

# Tiskne:
# 📊 SCRATCH_EXIT Forensics: Count, Net PnL, By Symbol, By Bucket
# 🏥 Health Decomposition v2: Components + Warnings
# 🚨 Alerts: CRITICAL if > 75% scratch
```

---

## Jak Používat

### Na Началу Session

```python
from src.services.v10_13x_2_monitoring import print_v10_13x_2_header
print_v10_13x_2_header()
```

### V Monitoring Loop

```python
from src.services.v10_13x_2_monitoring import print_v10_13x_2_monitoring
print_v10_13x_2_monitoring()  # Každých ~5-10 minut
```

### V Urgent Alert Path

```python
from src.services.v10_13x_2_monitoring import check_v10_13x_2_alerts
alert = check_v10_13x_2_alerts()
if alert:
    print(f"ALERT: {alert}")
```

### Programmaticky

```python
from src.services.scratch_forensics import scratch_report, health_decomposition_v2

# Detailní analýza
report = scratch_report()
if report["total_count"] > 0:
    print(f"SCRATCH avg PnL: {report['avg_pnl']:.8f}")
    print(f"Negative after positive: {report['negative_after_positive']}")

# Health s komponenty
health = health_decomposition_v2()
if health["status"] == "BAD" and health["components"]["scratch_penalty"] < -0.1:
    print("Scratch je dominantní. Potřeba audit exit logiky.")
```

---

## Příklady Output

### Session Start
```
============================================================
🔬 V10.13x.2 — Scratch Forensics & Health Decomposition v2
============================================================
Priority diagnostics: SCRATCH_EXIT audit, health transparency
============================================================
```

### Scratch Report
```
📊 SCRATCH_EXIT Forensics:
   Count: 382  Net: -0.00142026  Avg: -0.00000372
   By Symbol:
     BTC    n=121  net=-0.00051234  avg=-0.00000423
     ETH    n= 82  net=-0.00038456  avg=-0.00000469
     SOL    n= 77  net=-0.00028934  avg=-0.00000376
   By PnL Bucket:
     loss       n=156  net=-0.00089123
     micro      n=145  net=-0.00034567
     small      n= 81  net=-0.00018336
   ⚠️  WARNING: 76.0% scratch share (net -0.00142026)
```

### Health v2
```
🏥 Health Decomposition v2:
   Overall: 0.0012  [BAD]
   Components:
     Edge     -0.000
     Conv     +0.250
     Stab     +0.450
     Breadth  +0.300
     Calib    +0.000
   Penalties:
     Scratch   -0.200
     Bootstrap -0.000
   ⚠️  Warnings (4):
     - edge_too_weak: mean edge < 0.001
     - low_convergence: only 2/5 pairs converged
     - scratch_dominance: 76.0% of trades are SCRATCH_EXIT
     - scratch_losses: net PnL -0.00142026
```

---

## Priorita: Další Kroky

Podle V10.13x log analýzy:

| Priorita | Akce | Cíl |
|----------|------|-----|
| 1 | SCRATCH_EXIT audit + ekonomika | Zjistit proč 76%, proč -PnL |
| 2 | Expectancy decomposition | Vysvětlit WR 77% vs -PnL |
| 3 | Health v2 (DONE) | Granulární transparency |
| 4 | Bootstrap discipline | Omezit weak trade vstup |
| 5 | Log cleanup | Bez warning mid-line corruption |

---

## Technické Detail

### Memory Safety

- `_scratch_details` je capped na 500 poslední events (max ~50KB)
- Health decomposition se počítá on-demand z learning_monitor state
- Žádná extra persistence (Redis flush se dělá v learning_monitor)

### Performance

- `scratch_report()`: O(N) kde N = počet scratch exitů (max 500)
- `health_decomposition_v2()`: O(P) kde P = počet pairs (typ. 5-13)
- Obě fungují bez lock contention (read-only LM state)

### Backward Compatibility

- `lm_health()` vrací scalar stejně jako dřív
- Pokud import scratch_forensics selže, fallback na legacy health
- Žádné breaking changes v public API

---

## Soubory

| Soubor | Popis |
|--------|-------|
| `src/services/scratch_forensics.py` | Forensic audit + health v2 |
| `src/services/v10_13x_2_monitoring.py` | Dashboard integration |
| `src/services/learning_monitor.py` | Updated `lm_health_components()` |
| `src/services/learning_event.py` | SCRATCH_EXIT recording hook |
| `V10_13x_2_PATCH_NOTES.md` | Tohle (dokumentace) |

---

## Verifikace

Aby se ověřilo že V10.13x.2 funguje:

```bash
# 1. Importovat nový modul
python -c "from src.services.scratch_forensics import health_decomposition_v2; print(health_decomposition_v2())"

# 2. Spustit bot a zkontrolovat output
# Měl by zobrazit nový health v2 místo starého 0.001

# 3. Zkontrolovat scratch report
python -c "from src.services.scratch_forensics import scratch_report; print(scratch_report())"
```

---

## Poznámky

- ✅ SCRATCH_EXIT recording: Ready (hooknut v learning_event.py)
- ⏳ MFE/MAE collection: TODO (vyžaduje trade_executor changes)
- ⏳ Expectancy decomposition: TODO (vyžaduje trade-level data)
- ⏳ Exit quality component: TODO (vyžaduje exit type breakdown)
