# Externí audit — CryptoMaster HF-Quant 5.0 (kolo 6: OVĚŘ REFUTACI + verdikt o osudu DEV_FADE)

**Od:** provozovatel bota
**Předmět:** Nezávisle **potvrdit nebo vyvrátit** náš závěr, že DEV_FADE nemá při reálných nákladech životaschopnou execution cestu (taker ani maker) → vydat **GO / NO-GO na „retire DEV_FADE"**
**Datum:** 19. 7. 2026
**Auditovat @ commit:** `0e46810` (větev `main`)

---

## 0. Absolutní mantinel (beze změny)

**REAL trading = NO-GO.** Vše paper. Live objednávky vícenásobně gaté. Nesnižuj náklady, neměň edge jako vedlejší efekt, netiskni secrets, ke každému tvrzení `file:line` / artefakt. „Runtime ověřeno" jen po analýze **čerstvého** serverového artefaktu, ne z tohoto dokumentu.

**Klíčové: tuto refutaci postavil implementátor bota — nesmí si známkovat vlastní úkol.** Tvým úkolem je ji zkusit ROZBÍT, ne potvrdit z lásky.

---

## 1. Co se od kola 5 změnilo

Kolo 5 skončilo: DEV_FADE má záporné očekávání, vše `TIMEOUT`, E1–E4 zablokované chybějícími excursion daty. Od té doby:

| Krok | Co | PR | Gate |
|------|----|----|----|
| F8b recorder + integrace | observation-only 1s path + first-crossing do separátní sqlite, default-OFF, žádné trading side effects | #84 / #86 | reviewer APPROVE + trading-safety SAFE |
| E1–E4 analyzer | time-based walk-forward GO/NO-GO na (TP,SL) | #87 | reviewer APPROVE |
| Sběr dat spuštěn | `PAPER_DATA_COLLECTION_ONLY=1` → 0 nových pozic, jen záznam | ops #89–#91 | auto-rollback armed |
| **Maker-fill model** | **passive/maker execution + adverse selection, walk-forward OOS** | **#101** | **k auditu** |
| Read-only runner | `hetzner-run-maker-model.yml` — pull skriptu z origin/main do /tmp, běh proti shadow sqlite `mode=ro` | #101 | read-only |
| Dashboard scope tokens | additivní (lifetime vs recent), zrcadleno do degraded | #102 | 40/40 testů, contract-agent CAUTION (bez porušení) |

**Řetězec (vše merged):** … #87 (E1–E4) → #96/#98 (API outage fix + open unit + auto-rollback) → #100 (consult brief) → **#101 (maker model)** → #102 (scope tokens) → #103 (docs).

---

## 2. Připojení na server (read-only)

- **`hetzner-fetch-health.yml`** → artefakt `cryptomaster-health-<N>`: `closed_trades.csv` (plný řádkový dump), `shadow_collection_probe.txt` (počty + režimy), metriky. Poslední: `health-552` (server `d99aa5d4`, 08:31 UTC).
- **`hetzner-run-maker-model.yml`** → artefakt `maker-model-result-<N>`: JSON výstup modelu proti **plnému** `shadow_excursion.sqlite`. Poslední: `maker-model-result-1` (n=9305, 16:12 UTC).
- **`hetzner-export-shadow.yml`** → redukovaný read-only export shadow sqlite pro offline přepočet.

---

## 3. JÁDRO — ověř refutaci (metodika + data + čísla)

### 3.1 Metodika `scripts/maker_fill_model.py` (#101)
Model pracuje v **signed favorable-bps** prostoru (side-aware, viz `shadow_excursion_recorder.py`). Passive entry offset `E`: fill jen když path poprvně dosáhne `-E` (cena šla `E` proti), entry basis `-E`, drží do horizontu (passive **exit** se NEmodeluje → konzervativní). Unfilled = 0 P&L.

**Zkontroluj:**
1. Je „fill iff `min_low_bps <= -E`" korektní model passive fillu? Nepodhodnocuje/nenadhodnocuje fill rate (žádný queue-position / partial-fill model — je to zjednodušení; je přijatelné, nebo zásadní vada?).
2. Je **adverse-selection metrika** (filled-subset horizon F vs full-sample F) validní způsob, jak ukázat, že se plníš v horší podmnožině? Sedí znaménko a velikost (E=2 → −3.9 bp, E=4 → −4.8, E=6 → −6.2)?
3. Je **unconditional expectancy** (unfilled=0) správný způsob, jak započítat „minulé reverterů, které jsi pasivně nechytil"? Nebo to penalizuje passive nefér?
4. **Walk-forward:** train 60 % → výběr `E*` → **jediné** vyhodnocení na test 40 %. Je split bez leaku (řazeno dle `signal_ts_ms`)? Je výběr `E*` jediný stupeň volnosti (žádný jiný in-sample tuning)?
5. Sanity: `taker@18 == Fmean − 18` přesně (u nás −15.95 = 2.05 − 18)? ✅ lokálně i server-side — potvrď.

### 3.2 Data adequacy (jediná reálná slabina)
`maker-model-result-1`: **n=9305**, ale režim **97.6 % BULL_TREND** (9084), QUIET_RANGE 174, **RANGING jen 47**; symbol **94 % ETH**. Fader má mít *nejlepší* výsledek v RANGING — které je pod-vzorkované.
- **Zásadní otázka pro tebe:** je refutace („maker execution nepomáhá") **strukturální** (adverse selection u fade entry platí napříč režimy), nebo je to **artefakt jednorežimového vzorku**, který by se v RANGING mohl obrátit? Kolik RANGING obs bys vyžadoval, než bys refutaci přijal jako definitivní?

### 3.3 Čísla k potvrzení (z `maker-model-result-1`, přepočítej z dat)
- Taker: horizon F mean **+2.05 bp**, break-even taker **~2 bp**, −15.95 @18 bp.
- Best maker uncond expectancy dle nákladu: 0→+2.0 (E=0), 2→+0.005, **3→−0.21, 18→−0.99** — passive nikdy neporazí taker.
- Walk-forward OOS: test **−0.26 @3 bp, −0.09 i @0 bp**, −1.08 @18 bp → **NO-GO-OOS**.

---

## 4. Rozhodnutí, které máš vydat

**Jednu ze tří možností, s odůvodněním a `file:line`/artefakt důkazy:**

- **A) NO-GO potvrzeno → retire DEV_FADE.** Refutace je metodicky správná a dostatečně robustní i přes jednorežimový vzorek (adverse selection je strukturální). Doporuč zastavit DEV_FADE a hledat jinou třídu signálu.
- **B) NEROZHODNUTO → dosbírat.** Metodika OK, ale vzorek je nedostatečný (málo RANGING); specifikuj přesně kolik RANGING/BEAR obs a jak dlouho, než verdikt přijmeš.
- **C) REFUTACE VADNÁ.** Model má konkrétní chybu (uveď `file:line`) nebo chybí execution styl (např. chytřejší passive/aggressive hybrid, jiný horizont, cross-venue), který by ~2 bp hrubou hranu učinil obchodovatelnou. Popiš co konkrétně přepočítat.

**Nežádáme tě, abys vymyslel novou strategii** — žádáme tě posoudit, jestli **věřit této refutaci**. Rozhodnutí retire/pivot z tvého verdiktu plyne.

---

## 5. Mimo rozsah
- **REAL trading** — absolutní NO-GO bez ohledu na tento audit.
- **Bezpečnost/infra** — 5 kol hotovo (F1–F11, deploy gating, fail-closed real-order guardy). Neauditovat znovu, pokud nenajdeš regresi.
- **Learning loop** — downstream od signálu; neumí vyrobit hranu, kterou signál nemá (correct-gatuje na ~0 obchodů). Není předmětem.

## 6. Artefakty k předání
`STRATEGY_CONSULT_BRIEF.md` (§5b), `STRATEGY_EDGE_ANALYSIS.md` (oprava nahoře), `scripts/maker_fill_model.py`, `scripts/e1_e4_counterfactual.py`, `src/services/shadow_excursion_recorder.py` (schéma + bps sign policy), shadow export, `AUDIT_CHANGES_LOG.md` (2026-07-19 sekce).
