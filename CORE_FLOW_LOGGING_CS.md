# V10.13k: Duální Systém Logování — CORE FLOW vs DIAGNOSTIKA (Česky)

## Vyřešený Problém

**Předtím:** Logy byly tak složité, že skutečné obchodní/učící signály byly skryté v hluku.
- Throttle logy (HBLOCK, EXPLORE_SKIP)
- Ověření stavu
- Kontroly kapacity
- Omezování frekvence
- Technické detaily

**Výsledek:** Těžko vidět, co bot skutečně dělá — obchody se otevírají/zavírají, učení se aktualizuje.

---

## Řešení: Dvě Proudy Logování

### CORE FLOW (Co Bot Dělá)
**Jasné, barevné, prominentní**
- ✅ **VSTUP** — Signál přijat, obchod otevřen (ZELENÁ)
- ✅ **VÝSTUP** — Obchod zavřen, výsledek (PURPUROVÁ)
- 📚 **UČENÍ** — LM stav aktualizován (CYAN)
- ⚠️ **CHYBA** — Neshody, selhání (ČERVENÁ)
- 📊 **ATRIBUCE** — Proč obchody ztrácely (ŽLUTÁ)

### DIAGNOSTIKA (Proč/Jak Funguje)
**Tmavé, skryté, technické**
- Potlačení Throttle (HBLOCK, EXPLORE_SKIP)
- Kontroly limitu kapacity (probe_cap_rate, probe_cap_total)
- Ověření stavu (detekce neshody)
- Vnitřní počitadla a příznaky
- (Skryté v základu — viditelné jen při explicitní aktivaci)

---

## Použití

### V Kódu: Použij Core Flow Logger

```python
from src.services.core_flow_logging_cs import (
    log_vstup_obchodu,
    log_vystup_obchodu,
    log_aktualizace_uceni,
    log_chyba,
    log_atribuce,
    log_diag,
)

# Zaloguj vstup obchodu (CORE FLOW, viditelné)
log_vstup_obchodu(
    symbol="ETHUSDT",
    strana="KOUPIT",
    cena=1800.0,
    bucket="C_WEAK_EV_TRAIN",
    zdroj="PAPIROVY_TRENING",
    ev=0.05,
    spolehlivost=0.85
)

# Zaloguj výstup obchodu (CORE FLOW, viditelné)
log_vystup_obchodu(
    symbol="ETHUSDT",
    trade_id="trade_123",
    vysledek="ZISK",
    pnl_pct=0.8,
    bucket="C_WEAK_EV_TRAIN",
    duvod="DOSAZENY_CIL",
    mfe_pct=1.2
)

# Zaloguj aktualizaci učení (CORE FLOW, viditelné)
log_aktualizace_uceni(
    obchody_v_lm=15,
    spolehlivost_kalibrace=0.72,
    dominantni_atribuce="POPLATEK_DOMINUJE_POHYB",
    pocet_aktualizaci=3
)

# Zaloguj chybu (CORE FLOW, ČERVENÁ, viditelné)
log_chyba(
    typ_chyby="KVALITA_VYSTUP_CHYBEJICI",
    zprava="Obchod zavřen ale žádný log kvalitního výstupu",
    trade_id="trade_123",
    symbol="ETHUSDT"
)

# Zaloguj atribuci (CORE FLOW, ŽLUTÁ, viditelné)
log_atribuce(
    trade_id="trade_123",
    symbol="ETHUSDT",
    atribuce="POPLATEK_DOMINUJE_POHYB",
    ztrata_pct=-0.3,
    poplatek_pct=0.05
)

# Zaloguj technickou detail (DIAGNOSTIKA, TMAVÁ, skryté v základu)
log_diag(
    "Kontrola Throttle prošla",
    symbol="ETHUSDT",
    klic_throttle=("HBLOCK", "ETHUSDT", "SOFT"),
    uplynulo_s=15.2
)
```

### Z Logů: Prohlídej s Core Flow Viewer

**Jednoduché použití:**
```bash
bash scripts/p11ak_core_flow_viewer_cs.sh
```

**S časovým oknem:**
```bash
bash scripts/p11ak_core_flow_viewer_cs.sh --since "60 min ago"
```

**Vypni barvy (pro export do souboru):**
```bash
bash scripts/p11ak_core_flow_viewer_cs.sh --color off > core_flow_2026-05-18.txt
```

### Příklad Výstupu

```
============================================================
PROHLÍŽEČ CORE FLOW LOGŮ
============================================================
PID: 12345
Od: 1 hodina ago

=== CORE FLOW: Obchody a Učení ===

→ VSTUPY:
  ✓ ETHUSDT bucket=C_WEAK_EV_TRAIN ev=+0.0523
  ✓ LTCUSDT bucket=C_WEAK_EV_TRAIN ev=+0.0312
  ✓ ETHUSDT bucket=C_NEG_EV_SONDA ev=-0.0045

← VÝSTUPY:
  ✓ ETHUSDT vysledek=ZISK pnl=+0.80% duvod=DOSAZENY_CIL
  ✓ LTCUSDT vysledek=ZTRATA pnl=-0.25% duvod=TIMEOUT
  ✓ ETHUSDT vysledek=ZTRATA pnl=-0.12% duvod=STOP_ZTRATA

📚 AKTUALIZACE UČENÍ:
  ✓ LM obchody=15
  ✓ LM obchody=16
  ✓ LM obchody=17

⚠️  CHYBY A NESHODY:
  Žádné

=== DIAGNOSTIKA: Technické Detaily ===

Počitadla (posledních 60 minut):
  PAPIROVY_VSTUP:            18
  PAPIROVY_VYSTUP:           16
  PAPIROVY_NEG_EV_SONDA:     2
  LM_STAV_AKTUALIZACE:       16
  ODMITNUT:                  142
  PRESKOCENO:                89

Tlumené/Diagnostické Logy (skryté):
  Použij 'journalctl' přímo pro HBLOCK, EXPLORE_SKIP, atd.

============================================================
```

---

## Mapy Barev

| Signál | Barva | Kód | Význam |
|--------|-------|-----|--------|
| VSTUP | 🟢 ZELENÁ | `\033[92m` | Obchod otevřen, signál přijat |
| VÝSTUP | 🟣 PURPUROVÁ | `\033[95m` | Obchod zavřen, pozice vyřešena |
| UČENÍ | 🔵 CYAN | `\033[96m` | LM aktualizován, kalibrace pokročila |
| CHYBA | 🔴 ČERVENÁ | `\033[91m` | Neshoda, selhání, nekonzistence |
| ATRIBUCE | 🟡 ŽLUTÁ | `\033[93m` | Analýza atribuce, důvod ztráty |
| INFO | 🔷 MODRÁ | `\033[94m` | Obecná informace |
| DIAG | ⚫ TMAVÁ | `\033[2m` | Technická detail, skryta |

---

## Monitorovací Pracovní Postup

### Během Vývoje

```bash
# Sleduj CORE FLOW v reálném čase (přeskoč hluk)
bash scripts/p11ak_core_flow_viewer_cs.sh --since "10 min ago"

# Porovnej před/po změnami
bash scripts/p11ak_core_flow_viewer_cs.sh --color off > pred.txt
# [udělej změny]
bash scripts/p11ak_core_flow_viewer_cs.sh --color off > po.txt
diff pred.txt po.txt
```

### Po Nasazení Validace

```bash
# Zkontroluj, že se obchody otevírají (CORE FLOW by mělo být viditelné)
bash scripts/p11ak_core_flow_viewer_cs.sh --since "30 min ago" | grep "VSTUPY"

# Ověř, že se učení děje
bash scripts/p11ak_core_flow_viewer_cs.sh --since "30 min ago" | grep "UCENI"

# Zkontroluj chyby
bash scripts/p11ak_core_flow_viewer_cs.sh --since "30 min ago" | grep "CHYBA"
```

### Diagnostika (Když je potřeba)

```bash
# Úplný journalctl pro technické ladění
journalctl -u cryptomaster --since "30 min ago" -n 500 | grep "HBLOCK\|EXPLORE_SKIP\|sonda_limit"

# Analyzuj specifické throttle důvody
journalctl -u cryptomaster | grep "PAPIROVY_PRUZKUM_PRESKOC" | tail -20
```

---

## Principy Designu

1. **CORE FLOW je primární** — Co je důležité, je co bot dělá (obchody, učení, chyby)
2. **DIAGNOSTIKA je sekundární** — Proč to funguje je technické, skryté v základu
3. **Barva je sémantická** — Stejný typ signálu má vždy stejnou barvu
4. **Skryté v designu** — Hluk je potlačen; spusť `journalctl` pokud potřebuješ detaily
5. **Snadný přechod** — Existující `log.info()` volání stále fungují, ale `log_vstup_obchodu()` je jasnější

---

## Soubory

- `src/services/core_flow_logging_cs.py` — Modul logování s barevným kódováním (česká verze)
- `scripts/p11ak_core_flow_viewer_cs.sh` — Prohlížeč logů který zvýrazňuje CORE FLOW (česká verze)
- `scripts/p11ag_quality_audit_cs.sh` — Audit skriptu s českou terminologií
- `CORE_FLOW_LOGGING_CS.md` — Úplný průvodce integrací + příklady (tohle)
