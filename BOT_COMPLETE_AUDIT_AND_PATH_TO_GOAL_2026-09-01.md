# CryptoMaster HF-Quant 5.0 — Kompletní audit stavu a návrh cesty k cíli

**Datum:** 2026-09-01
**Cíl projektu:** Win Rate > 50 % **A** kladné paper P&L, poctivě (bez metric-gamingu)
**Aktuální stav cíle:** **NESPLNĚN** (WR posledních 100: 21–25 %, lifetime PF 0,667, lifetime expectancy záporná)
**Bot v provozu:** ~6 měsíců (ne roky), paper-only, REAL trading = absolutní NO-GO

---

## 0. Shrnutí pro netrpělivé

Cíl není splněn a **hlavní příčina není bug** — je to strukturální: naprostá většina obchodů (v posledních 24h ~66 %) pochází z **záměrně nízko/negativně-EV explorativních bucketů** (learning/discovery mechanismy, ne "opravdová" strategie), a proto jakékoli agregátní číslo dominuje jejich výkon, ne výkon skutečné strategie.

Když se podívám ODDĚLENĚ na `A_STRICT_TAKE` (jediný bucket, který reprezentuje "opravdovou" vysoko-konvikční strategii), obraz je **výrazně lepší**: WR ~49 %, PF ~1,19, kladné P&L (+33,7 % lifetime) — blízko cíli, ne od cíle vzdáleno. Problém je, že tento bucket dnes tvoří jen ~1 % denního objemu obchodů — zbytek je exploration, který byl navržen tak, aby NEBYL ziskový (je to nástroj na sběr dat, ne na vydělávání).

**Návrh řešení níže (sekce 6) má dvě nezávislé linie:** (A) opravit MĚŘENÍ cíle, aby nebylo systematicky zkreslené explorativními bucket, a (B) posílit reálnou generaci `A_STRICT_TAKE` kandidátů, aby netvořili jen 1 % objemu.

---

## 1. Co bylo tuto monitorovací session opraveno (NENÍ příčina nesplnění cíle)

Rozsáhlá autonomní monitorovací smyčka (100+ cyklů) odhalila a opravila řadu reálných provozních chyb. Žádná z nich sama o sobě nevysvětluje, proč WR < 50 % — jde o infrastrukturní/spolehlivostní problémy, které bránily botovi fungovat *jak bylo navrženo*, ne problémy se samotnou obchodní logikou:

| Datum | Nález | Dopad |
|---|---|---|
| 2026-08-19/24 | Duplicitní přijímání paper-obchodů (2 nezávislé bugy) | Zkreslovalo statistiky, ne edge |
| 2026-08-19 | Admission deadlock (~17,5h) | Bot 17,5h nepřijímal obchody |
| 2026-08-17 | SKIP_SCORE_HARD bypass discovery | 66h+ tichý výpadek |
| 2026-08-18 | Ztráta atribuce uzavřených obchodů při zápisu | Historická data bez bucket/source |
| 2026-08-26–31 | Nadměrný zápis do Firestore (audit trail) | Riziko vyčerpání kvóty, ne edge |
| 2026-08-31 | `C_NEG_EV_PROBE` self-blocking (~90+ min výpadek) | Recovery-mechanismus byl sám nefunkční |
| 2026-09-01 | Dashboard: chybějící timestamp u obchodů | Kosmetická chyba zobrazení |
| 2026-09-01 | `EMERGENCY_MONITOR`: strukturální falešné poplachy (log-window příliš malé okno vůči reálnému throughputu) | Zavádějící monitoring, ne edge |

**Závěr:** Bot je dnes provozně mnohem spolehlivější než na začátku této série, ale **žádná z těchto oprav nezměnila fakt, že WR zůstává pod 50 %.** To je silný signál, že příčina je jinde — viz sekce 2–3.

---

## 2. Proč cíl není splněn — hlavní zjištění (live data, 2026-09-01 08:00 UTC)

### 2.1 Agregátní čísla vypadají špatně

```
recent_100 (posledních 100 obchodů): WR 23,0 %, PF 0,581 (pct), net P&L -2,86 %
lifetime (14 792 obchodů):           PF 0,667, expectancy -0,0282, WR structurally <50%
exit_distribution (lifetime):        TIMEOUT 74 %, SL 15 %, TP 11 %, scratch/stagnation 0 %
```

TIMEOUT-dominance byla už dřív (2026-08-25, `_workspace/43_...md`) nezávisle potvrzena jako **"no edge, not geometry"** — TIMEOUT obchody mají v průměru jen +7,8bp max-favorable-move proti 35-47bp TP zóně. Není to chyba nastavení TP/SL, je to chybějící směrový edge ve většině kandidátů.

### 2.2 Ale agregát je zavádějící — bucket-level rozklad (živá data, posledních 24h)

```
bucket                        n(24h)   WR      net_pnl_pct(24h)
PAPER_STARVATION_DISCOVERY    459      41,6%   -13,01
C_WEAK_EV_TRAIN                181      48,1%    -3,35
None (netagováno)               44      29,5%    -4,10
A_STRICT_TAKE                    7      57,1%    +0,16
P0_8_PLUS_EVIDENCE_COLLECTION     3      33,3%    -0,43
```

**`A_STRICT_TAKE` — jediný bucket navržený jako "opravdová" vysoko-konvikční strategie — je aktuálně jen ~1 % denního objemu obchodů** (7 z 694 za 24h). `PAPER_STARVATION_DISCOVERY` (explorativní, cíleně nízko/nulo-EV recovery-mechanismus) tvoří **66 %** objemu. Zbytek jsou další explorativní/tréninkové buckety (`C_WEAK_EV_TRAIN`, `D_NEG_EV_CONTROL`), z nichž `D_NEG_EV_CONTROL` je doslova **kontrolní skupina s negativním EV** — navržená tak, aby byla nezisková, jako baseline pro porovnání.

**To znamená: agregátní "WR posledních 100 obchodů", které dashboard hlásí jako headline číslo, měří převážně výkon mechanismů, které NIKDY neměly být ziskové.** Cíl "WR>50% a kladné P&L" byl formulován pro bota jako celek, ale bot dnes z >90 % obchoduje v režimech, které jsou EXPLICITNĚ navržené tak, aby nevydělávaly (sbírají data / testují starvation-recovery / slouží jako kontrolní skupina).

### 2.3 A_STRICT_TAKE (lifetime, 1 665 obchodů) — nejslibnější signál v celém systému

```
WR:              48,8 % (posledních 200: 49,0 %)
PF:               1,191  (gross_win 210,3 vs gross_loss 176,6)
Net P&L:         +33,71 % lifetime  (posledních 200: +8,25 %)
Exit rozklad:    TIMEOUT 850 (avg +0,172%), SL 603 (avg -0,255%), TP 212 (avg +0,196%)
```

Zajímavé: na rozdíl od celkového systému, kde jsou TIMEOUT obchody v průměru mírně ztrátové, jsou zde TIMEOUT obchody **v průměru ziskové** (+0,172 %). To naznačuje, že `A_STRICT_TAKE`'s admission-kritéria filtrují kandidáty s reálným směrovým momentem, ne šum.

**Rozklad podle symbolu ukazuje, že edge je koncentrovaný:**

```
symbol     n      WR      net_pnl_pct
SOLUSDT    858    54,1%    +34,34   <- prakticky celý zisk
ETHUSDT    429    47,8%     -2,82
ADAUSDT    378    37,8%     +2,19
```

`A_STRICT_TAKE` je blízko cíli (WR 49 % vs. 50 %, kladné P&L), ale (a) je to jen zlomek objemu, (b) edge je z velké části tažen jedním symbolem (SOLUSDT), ne rovnoměrně rozložený.

### 2.4 Neobjasněná mezera: bucket=None (32 % lifetime objemu, 44/694 = 6,3 % za 24h)

`bucket=None` tvoří **4 369 z 13 587 obchodů (32,2 %) za celou historii** — druhá největší kategorie po `PAPER_STARVATION_DISCOVERY`. `paper_source` rozklad: 3 607 zcela netagováno, 762 označeno `paper_evidence_collection`. Tato mezera byla poprvé zaznamenána 2026-08-31 (`_workspace/50_...md`, nález #1) jako "not yet traced" a **od té doby nebyla vyšetřena**. Vzhledem k velikosti (téměř třetina veškeré historie) je to nejvýznamnější dosud neprozkoumaná otevřená otázka v datech.

---

## 3. Výzkumný oblouk — co bylo zkoušeno jako alternativa (mimo živý bot)

Paralelně s provozní údržbou probíhal od 2026-07 rozsáhlý výzkum nových signálních tříd, s nezávislým "externím auditorem" (adversariální LLM-review persona) potvrzujícím/vyvracejícím každý nález:

| Signální třída | Výsledek | Zdroj |
|---|---|---|
| DEV_FADE (mikrostruktura, sekundové) | RETIRED — cost wall (~18bp taker vs ~2bp gross edge) | Kolo 6 audit, 2026-07-19 |
| 6 dalších second-scale rodin | Všechny selhaly na cost-wall | `RESEARCH_COSTWALL_FINDINGS.md` |
| Long-horizon momentum/reversion (tsmom, MA, donchian, xsec) | REFUTED — 2024 bull-market beta, ne alfa (CI přes nulu, zisk jen v 2024, jen v UP trhu) | `RESEARCH_LONGHORIZON_FINDINGS.md` |
| Delta-neutral funding-carry (long spot/short perp) | **NO-GO** — tvrdý FAIL na ≥200-fill prahu (efektivní N≈7,8), market-neutralita se hroutí pod realistickými fills (−30/−102bp v down-marketu), magnitude ~0,7-1,3%/rok (kolem risk-free) | Kolo 9 audit, 2026-08-24, `EXTERNAL_AUDIT_v9_COMPLETE_PACKAGE.md` |
| Funding-carry, extended 2021/22 historie | **PROBÍHÁ** (Kolo 10, spuštěno 2026-09-01, ještě nedokončeno) | `CLAUDE_EXTERNAL_AUDIT_KOLO10_PROMPT_2026-09-01.md` |

**Souhrnný závěr auditora (kolo 6-9):** deset price-only rodin vyčerpáno, jedna alternativní informační třída (funding) také odmítnuta (i když ne definitivně mrtvá). Auditor sám navrhl zbývající kandidáty (viz `RESEARCH_PIVOT_CHARTER.md`): (a) delší horizonty s většími pohyby, (b) funding/basis/carry (vyzkoušeno, NO-GO), (c) event/regime-conditioned obchodování (validované RANGING režimy apod.) — **tato třetí možnost nebyla dosud vůbec prozkoumána.**

---

## 4. Co NENÍ vysvětlením (vyloučeno evidencí)

- **Není to TP/SL geometrie** — grid-search (cyklus 23) i MFE/MAE analýza (cyklus 43) nezávisle potvrdily, že žádná geometrie na současné signální cestě není zisková; problém je v samotném signálu, ne v exit-parametrech.
- **Není to (jen) bug v admission logice** — i po opravě duplicit, deadlocku, C_NEG_EV_PROBE stallu zůstává agregátní WR ve stejném pásmu (21–25 %).
- **Není to nedostatek dat/objemu** — 14 792 obchodů je solidní vzorek na úrovni celého systému (byť ne na úrovni jednotlivých úzkých bucketů).
- **Není to (jen) trh v daném období** — long-horizon research explicitně ukázal, že i price-only edge, který VYPADAL dobře, byl jen 2024 bull-market beta; přítomný stav (2025-26) je jiný režim.

---

## 5. Otevřené, dosud nezodpovězené otázky

1. **Bucket=None (32 % lifetime)** — co přesně tyto obchody reprezentují? Legacy admission cesta? Nesprávně tagovaná `A_STRICT_TAKE` podmnožina? Nutná dedikovaná forenzní analýza.
2. **Proč A_STRICT_TAKE generuje tak málo kandidátů** (1 % denního objemu)? Je admission-práh příliš přísný, nebo trh skutečně nabízí tak málo vysoko-konvikčních příležitostí? Pokud je to admission-práh, jeho uvolnění (opatrně, s zachováním kvality) by mohlo zvýšit podíl ziskové strategie na celkovém mixu.
3. **Proč SOLUSDT funguje a ETHUSDT/ADAUSDT ne** v rámci `A_STRICT_TAKE`? Je to specifikum symbolu (likvidita, volatilita), nebo náhoda malého vzorku?
4. **Je "WR>50% pro celého bota" správná formulace cíle**, když >90 % objemu jsou záměrně explorativní/kontrolní obchody? (Přesná analogie k otázce, kterou položil externí auditor u funding-carry: "market-neutral cash-enhancement yield" vs. skutečný cíl — zde: "blended WR přes explorativní mix" vs. skutečný cíl.)
5. **Kolo 10 výsledek** (extended funding-carry historie) — čeká se, ale i pozitivní výsledek podle auditorova vlastního kola-9 verdiktu neopraví magnitude/market-neutralitu problémy, takže pravděpodobně nezmění celkový obraz.

---

## 6. Návrh cesty k cíli — prioritizovaný akční plán

### Linie A — Oprava MĚŘENÍ cíle (rychlé, nízké riziko, žádná změna obchodní logiky)

**A1. Přidat "real-signal" WR/PF metriku vedle blended metriky.** Dashboard by měl vedle stávajícího `recent_100` blended WR zobrazovat i WR/PF pouze pro `A_STRICT_TAKE` (a případně další buckety, které nejsou explicitně explorativní/kontrolní). To nezmění obchodní logiku, jen odhalí, že bot **už dnes má** blízko-cílovou strategii, jen zastřenou explorativním objemem. Nízké riziko, vysoká transparentní hodnota — analogické tomu, jak `deploy-verify-agent` musel odlišit "incident vyřešen restartem" od "incident vyřešen opravou" u C_NEG_EV_PROBE.

**A2. Vyšetřit a vysvětlit `bucket=None` (32 % historie).** Dokud nevíme, co tato kategorie reprezentuje, nemůžeme s jistotou tvrdit, že současný mix je "66 % explorace + 1 % real signal" — mohla by v sobě skrývat další reálné obchody. Toto je nejlevnější příští krok s potenciálně největším dopadem na pochopení skutečného stavu.

### Linie B — Posílení reálné strategie (střední riziko, vyžaduje evidence-based-patch-orchestrator workflow)

**B1. Prošetřit, proč A_STRICT_TAKE generuje jen ~1 % objemu.** Pokud je to admission-práh (EV/score threshold), zvážit opatrné uvolnění s A/B-style porovnáním WR/PF před a po, přesně podle stávající harness disciplíny (žádný patch bez evidence, žádné nasazení bez review).

**B2. Prošetřit SOLUSDT-specifický edge v A_STRICT_TAKE.** Pokud je edge skutečně symbol-specifický (ne náhoda), zvážit zvýšení position-sizingu/frekvence pro SOLUSDT v rámci A_STRICT_TAKE, s patřičnou opatrností k single-symbol-koncentraci (RESEARCH_PIVOT_CHARTER's "no symbol > 50% of profit" princip by se měl aplikovat i tady).

**B3. Zvážit snížení objemového podílu `PAPER_STARVATION_DISCOVERY`** pokud jeho primární funkce (recovery ze starvation) už není tak potřebná díky dnešní lepší spolehlivosti admission logiky (mnoho blokujících bugů bylo opraveno). Vyžaduje opatrnou evidenci, že to nezvýší riziko nového starvation stavu.

### Linie C — Nová signální třída (vyšší riziko/úsilí, dlouhodobé)

**C1. Počkat na Kolo 10** (extended funding-carry historie) — v běhu, výsledek očekáván brzy. I při pozitivním výsledku pravděpodobně **nezmění** kolo-9 NO-GO (magnitude a market-neutralita problémy přetrvávají nezávisle na velikosti vzorku), ale stojí za dokončení pro úplnost evidence.

**C2. Prozkoumat auditorem navrženou, dosud netestovanou třetí cestu: event/regime-conditioned obchodování** (např. fader omezený na validované RANGING režimy) — vyžaduje stejnou rigorózní evidence-bar disciplínu jako funding-carry (executable fills, purged walk-forward, block bootstrap, GO-scorecard) před jakoukoli implementací infrastruktury.

### Doporučené pořadí

```
1. A2 (bucket=None forenzika)       — nejlevnější, může změnit celý obraz
2. A1 (real-signal metrika)          — transparentnost, žádné riziko
3. B1 (A_STRICT_TAKE admission)      — přímý, evidence-based pokus zvýšit podíl ziskové strategie
4. B2 (SOLUSDT koncentrace)          — navazuje na B1's zjištění
5. C1 (čekat na Kolo 10)             — již běží paralelně, nevyžaduje aktivní práci
6. B3 (snížit starvation-discovery)  — až po B1/B2, aby nedošlo k novému stall riziku
7. C2 (nová signální třída)          — nejnákladnější, jen pokud A/B linie nestačí
```

Real trading zůstává absolutní NO-GO nezávisle na jakémkoli kroku výše.

---

*Sestaveno na základě živých dat (2026-09-01 08:00 UTC), `_workspace/monitoring_progress.json` (199+ cyklů), `_workspace/43_timeout_dominance_no_edge_confirmation.md`, `_workspace/50_c_neg_ev_probe_self_blocking_stall.md`, `EXTERNAL_AUDIT_v9_COMPLETE_PACKAGE.md`, `RESEARCH_PIVOT_CHARTER.md`, a přímými SQL dotazy proti `local_learning_storage/cache.sqlite` na produkčním serveru.*
