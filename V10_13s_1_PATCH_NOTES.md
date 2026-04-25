# V10.13s.1 — Canonical State & Maturity Fix

**Status**: ✅ Implementace hotová  
**Fokus**: Opravit startup state mismatch  
**Priorita**: KRITICKÁ (blokuje všechna subsystémy)

---

## Problém (V10.13s Log Analysis)

V10.13s log ukazuje 4 různé počty obchodů zároveň:

```
[7/7a] Loaded 100 trades ✓
Bootstrap: 7467 obchodů
[V10.13x RECON] trades=500
completed_trades: 100
Maturity computed: trades=0 bootstrap=True cold_start=True
```

**Rozpor**: 100 vs 500 vs 7467 vs 0

To způsobuje:
- ❌ Maturity oracle vrací `trades=0` i když máme 100+ obchodů
- ❌ Bootstrap logika neví kterému číslu věřit
- ❌ Health a kalibrační rozhodnutí jsou na песчané podlaze
- ❌ Stale global state se detekuje až za běhu, ne v boot
- ❌ Žádný single source of truth

---

## Řešení: V10.13s.1

### 1. Canonical State Oracle

**Soubor**: `src/services/canonical_state.py`

Jedna funkce pro všechny: `get_canonical_state()`

```python
state = get_canonical_state()
# Returns:
# {
#     "trades_runtime": 100,           # Z learning_monitor
#     "trades_dashboard": 500,         # Z learning_event
#     "trades_historical_total": 7467, # Z Firebase (stale, warning!)
#     "trades_for_maturity": 100,      # AUTHORITATIVE
#     "source": "runtime",
#     "maturity": "live",
#     "bootstrap_active": False,
#     "state_consistent": True,
#     "warnings": [],
#     "ts": 1234567.89,
# }
```

**Priorita zdrojů** (v pořadí):
1. **Learning Monitor** (runtime, accurate) ← VÍTĚZ
2. **Learning Event** (dashboard reconciliation)
3. **Firebase** (historical, may be stale) — WARNING
4. NIKDY stale global state

**Procedura**:
1. Get runtime count z `learning_monitor.lm_count`
2. Get dashboard count z `learning_event.METRICS["trades"]`
3. Compare — if mismatch, log warning
4. Pick authoritative count (runtime if > 0, else dashboard)
5. Determine maturity (cold_start < 50, bootstrap < 100, live ≥ 100)
6. Return unified dict

**Cache**: 5 sekund (invaliduje se po state změnách)

### 2. Integration do Execution

**Soubor**: `src/services/execution.py`

Updated funkce:
- `bootstrap_mode()` — nyní používá `get_authoritative_trade_count()`
- `is_bootstrap()` — nyní používá `get_canonical_state()`

```python
# Dřív:
def is_bootstrap():
    return METRICS.get("trades", 0) < 100  # Která čísla věřit?

# Teď:
def is_bootstrap():
    return get_authoritative_trade_count() < 100  # Single truth
```

### API

Shortcut funkce pro běžné use cases:

```python
from src.services.canonical_state import (
    get_canonical_state,              # Full state dict
    get_authoritative_trade_count,    # Just count
    is_bootstrap_active,              # Is bootstrap?
    get_maturity,                     # "cold_start"|"bootstrap"|"live"
    print_canonical_state,            # Diagnostic print
    invalidate_cache,                 # Force recompute
)

# Příklady:
trade_count = get_authoritative_trade_count()  # 100
is_bootstrap = is_bootstrap_active()           # False
maturity = get_maturity()                      # "live"

# Full diagnostic
print_canonical_state()
# Output:
# [CANONICAL STATE]
#   Runtime:    100
#   Dashboard:  500
#   For Logic:  100  [live]
#   Consistent: False
#   Source:     runtime
#   Warnings:
#     - count_mismatch: runtime=100 vs dashboard=500
```

---

## Jak Funguje

### Algoritmus Consistency Check

```
1. Runtime trades = sum(learning_monitor.lm_count.values())
2. Dashboard trades = learning_event.METRICS["trades"]
3. Firebase trades = load_latest_state()["trade_count"]

4. state_consistent = abs(runtime - dashboard) <= 5
   (tolerance 5 trades pro race conditions)

5. Authoritative count:
   if runtime > 0:
       use runtime  (current session, most accurate)
   else:
       use dashboard  (fallback if runtime not ready)

6. Maturity determination:
   if count == 0:        "cold_start" + bootstrap=True
   if 0 < count < 50:    "bootstrap" + bootstrap=True
   if count >= 50:       "live" + bootstrap=False

7. Sanity check:
   if count > 0 and maturity == "cold_start":
       WARNING: maturity logic error
```

### Fallback na Starý Kod

Pokud `canonical_state` import selže:
```python
try:
    from src.services.canonical_state import get_authoritative_trade_count
    n = get_authoritative_trade_count()
except Exception:
    # Fallback na stary kod
    n = METRICS.get("trades", 0)
```

---

## Otestování

```bash
# 1. Import test
python -c "from src.services.canonical_state import get_canonical_state; print(get_canonical_state())"

# 2. Verify count is not 0 when data exists
python -c "
from src.services.canonical_state import get_authoritative_trade_count, get_maturity
c = get_authoritative_trade_count()
m = get_maturity()
print(f'Count: {c}, Maturity: {m}')
assert m != 'cold_start' or c == 0, 'Maturity bug: cold_start but trades > 0'
"

# 3. Verify consistency warning
python -c "
from src.services.canonical_state import get_canonical_state
s = get_canonical_state()
if s['warnings']:
    print(f'Warnings: {s[\"warnings\"]}')
"
```

---

## Impact

**Subsystémy které se mají aktualizovat**:

1. ✅ **execution.py** — Updated `bootstrap_mode()` + `is_bootstrap()`
2. ⏳ **learning.py** — Měl by používat canonical state pro thresholdy
3. ⏳ **risk_engine.py** — Měl by respektovat maturity
4. ⏳ **diagnostics.py** — Měl by zobrazovat canonical state
5. ⏳ **bot2/main.py** — Měl by invalidovat cache po state změnách

---

## Co NENÍ v Scope

- MFE/MAE collection (TO V10.13x.2)
- Expectancy decomposition (TODO V10.13x.2)
- SCRATCH_EXIT optimization (TODO V10.13s.2)
- Duplicate subscription fix (TODO V10.13s.1.1)

---

## Next Steps Podle V10.13s Log

| Priorita | Akce | Patch |
|----------|------|-------|
| 1 ✅ | Canonical state fix | V10.13s.1 |
| 2 | Duplicate subscription guard | V10.13s.1.1 |
| 3 | Firebase quota log severity | V10.13s.1.2 |
| 4 | SCRATCH_EXIT audit | V10.13s.2 |

---

## Soubory

| Soubor | Popis |
|--------|-------|
| `src/services/canonical_state.py` | Canonical state oracle (NEW) |
| `src/services/execution.py` | Updated bootstrap_mode + is_bootstrap |
| `V10_13s_1_PATCH_NOTES.md` | Tohle |

---

## Poznámky

- ✅ Canonical state Oracle: HOTOVO
- ✅ Integration do execution.py: HOTOVO
- ✅ Fallback logika: HOTOVO
- ⏳ Integration do ostatních subsystémů: TODO (lazy approach — jen podle potřeby)
- ⏳ Duplicate subscription fix: Hledání zdroje v logu (nebylo jasné kde se dělá)

V10.13s.1 je **foundation patch** — opravuje root cause. V10.13s.2 pak může dělat diagnostiku bez obav že budou čísla lživá.
