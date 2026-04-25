# V10.13x — Analýza logů z 2026-04-25 07:57 UTC

## Shrnutí

Nový dashboard už **nevypadá rozbitě jako dřív**. Hlavní metriky se teď chovají mnohem konzistentněji:

- `Obchody 500 (OK 91 X 27 ~ 382)` se sčítají správně
- per-symbol počty dávají `CELKEM 500`
- jsou vidět ekonomické exit statistiky
- recent trend i calibration block už nejsou nulové fallback nesmysly

To je zlepšení.

Současně ale log ukazuje, že systém má teď jiný, závažnější problém:

- **winrate rozhodujících obchodů je vysoký (`77.1%`)**
- ale **celkový uzavřený PnL je záporný (`-0.00095045`)**
- dominantní exit typ je **`SCRATCH_EXIT` = 382 obchodů = 76 % všech obchodů**
- `SCRATCH_EXIT` je ekonomicky silně ztrátový: `net -0.00142026`
- learning health je téměř mrtvý: `Health: 0.001 [BAD]`
- edge i convergence jsou prakticky nulové

Tj. **metrics reconciliation se zjevně zlepšila, ale obchodní ekonomika a learning convergence jsou stále špatné**.

---

## Co log potvrzuje jako opravené

## 1. Count reconciliation vypadá správně

Dashboard:

- `Obchody 500 (OK 91 X 27 ~ 382)`

Součet:

- `91 + 27 + 382 = 500`

To je správně.

Také per-symbol sekce:

- BTC 121
- ETH 82
- ADA 47
- BNB 87
- DOT 41
- SOL 77
- XRP 45

Součet:

- `121 + 82 + 47 + 87 + 41 + 77 + 45 = 500`

To také sedí.

**Závěr:** count truth layer je pravděpodobně už výrazně lepší než dříve.

---

## 2. Exit attribution už je ekonomický, ne jen count-based

V logu je:

- `PARTIAL_TP_25 63 ... net +0.00059068`
- `wall_exit 1 ... net +0.00002412`
- `MICRO_TP 6 ... net +0.00002037`
- `replaced 45 ... net -0.00007563`
- `EARLY_STOP 3 ... net -0.00008973`
- `SCRATCH_EXIT 382 ... net -0.00142026`

To je přesně ten typ výstupu, který dřív chyběl.

**Závěr:** exit attribution je už použitelný pro rozhodování.

---

## 3. Recent trend už není zjevný fake fallback

Log ukazuje:

- `Trend uceni ZLEPŠUJE SE`
- `Poslednich 24 83.3% vs prumer 77.1% (+6.2%)`

To už nepůsobí jako starý fallback `Poslednich 0 / WR 0.0%`.

**Závěr:** recent-window blok je pravděpodobně napojený lépe než dřív.

---

## Co je teď hlavní problém

## 1. Vysoký WR, ale záporný PnL

To je nejdůležitější zjištění.

Dashboard říká:

- `WR_canonical 77.1%`
- `Zisk (uzavrene) -0.00095045`
- `Profit Factor 0.60x`

To znamená:

- většina rozhodujících obchodů končí jako win
- ale velikost zisků je menší než velikost ztrát a/nebo flat/scratch flow dlouhodobě krvácí

To není kosmetický problém dashboardu. To je **ekonomický problém exit architektury**.

---

## 2. SCRATCH_EXIT je dominantní a ničí ekonomiku

Nejdůležitější čísla:

- `SCRATCH_EXIT 382`
- to je `76% obch`
- `net -0.00142026`
- `avg -0.00000372`

Pozitivní exit typy:

- `PARTIAL_TP_25 net +0.00059068`
- `MICRO_TP net +0.00002037`
- `wall_exit net +0.00002412`

Negativní dominance scratch exitů je větší než zisky z pozitivních exitů.

### Praktický význam

Bot často:
- vstoupí správně nebo téměř správně
- ale neudrží pohyb dost dlouho
- nebo zavře trade příliš brzo / příliš často / příliš defenzivně
- a fees/slippage z mikro-close logiky sežerou edge

**Závěr:** hlavní problém už není “co dashboard ukazuje”, ale **že exit engine monetizuje edge velmi špatně**.

---

## 3. Learning health je téměř nulový

Log:

- `Health: 0.001 [BAD]`
- `Edge: 0.000`
- `Conv: 0.000`
- `Pairs: 13`
- `Trades: 108`

Současně ale ve snapshotu jsou místy vidět nenulové WR a někde i lehce nenulová `conv`, třeba:

- `BTCUSDT_BULL_TREND conv: 0.005`
- `SOLUSDT_BULL_TREND conv: 0.022`

To znamená, že dashboard health je extrémně přísný nebo skoro “dead by construction”.

### Pravděpodobné vysvětlení

Health formula je momentálně příliš penalizační vůči:
- nízkému EV
- nízké convergence
- vysokému podílu scratch flow
- malé robustnosti across pairs

A/nebo stále dává skoro nulový output i když některé pair/regime segmenty už mají signál.

**Závěr:** learning block sice vypadá transparentněji, ale **health formula je prakticky neinformativní**, protože skoro vše komprimuje k nule.

---

## 4. Stále je vidět duplicate human summary

Bloky se opakují po krátkých intervalech téměř celé znovu:

- dashboard
- execution engine
- learning monitor
- exit audit

To nemusí být bug, ale pro čitelnost je to stále dost hlučné.

Navíc některé warningy se lámou doprostřed řádků, např.:

- `Rezim trhu ... (77%)WARNING:root:on_price(ETHUSDT)...`
- `pullback [####--------] 34% -WARNING:root:on_price(BTCUSDT)...`

**Závěr:** log formatting / flushing je stále nečistý.

---

## 5. Forced / soft-bootstrap trading stále tlačí slabé obchody

V logu jsou vidět průchody typu:

- `FORCED_EXPLORE`
- `FAST_FAIL_SOFT`
- `SCORE_THRESHOLD bootstrap active`
- `OFI_SOFT_BOOTSTRAP`
- `decision=TAKE ... af=0.35`

To může být v bootstrapu v pořádku, ale v kombinaci s:
- vysokým scratch podílem
- záporným total PnL
- nulovým learning health

to vypadá, že bootstrap režim produkuje **mnoho málo hodnotných obchodů**.

---

## Nejpravděpodobnější interpretační závěr

V10.13x zřejmě spravil **pravdu v dashboardu**, ale tím jen odkryl realitu:

1. obchodní systém má hodně flat/scratch flow
2. rozhodující winrate vypadá dobře, ale neodpovídá skutečné ekonomice
3. exit monetization je slabá
4. learning layer zatím neumí proměnit data v robustní edge
5. bootstrap/forced flow možná generuje příliš mnoho slabých vstupů

---

## Priority — co dělat dál

## Priorita 1 — SCRATCH_EXIT audit a omezení
Nejdůležitější další krok.

### Cíl
Zjistit, proč je `SCRATCH_EXIT`:
- tak častý
- tak ztrátový
- a proč tvoří 76 % všech exitů

### Co přesně zjistit
Pro scratch exit vytáhnout rozpad podle:

- symbol
- regime
- hold time
- pnl bucket
- MFE/MAE před uzavřením
- fee/slippage impact
- důvod aktivace scratch close
- kolik scratch exitů bylo po pozitivním excursion
- kolik scratch exitů bylo uzavřeno téměř na BE, ale po costech do mínusu

---

## Priorita 2 — expectancy decomposition
Současný dashboard ukazuje:

- `WR_canonical 77.1%`
- `Profit Factor 0.60x`
- `Expectancy +0.00000398`

To je podezřelé vedle záporného uzavřeného PnL.

### Nutné ověřit
Zda expectancy:
- počítá decisive-only subset
- ignoruje flats
- nebo je jinak scope-odlišná od `Zisk (uzavrene)`

### Co doplnit
Přidat explicitně 3 samostatné expectancy:

- `Expectancy_all_closed`
- `Expectancy_decisive_only`
- `Expectancy_by_exit_type`

Dokud tohle nebude oddělené, bude uživatel přirozeně zmatený.

---

## Priorita 3 — health decomposition 2.0
Aktuální health:

- `0.001 [BAD]`

je příliš komprimovaná, prakticky k ničemu.

### Doporučení
Přestat zobrazovat jen:

- `Edge`
- `Conv`

a rozšířit to na:

- edge_strength
- convergence
- calibration
- stability_recent_vs_longterm
- breadth_of_pairs
- exit_quality
- scratch_penalty
- bootstrap_penalty

### Cíl
Aby šlo odpovědět:
“health je nízká hlavně kvůli scratch penalty a slabému breadth, ne kvůli úplně nulové edge.”

---

## Priorita 4 — bootstrap discipline
V logu je stále hodně:

- `FORCED_EXPLORE`
- `FAST_FAIL_SOFT`
- `bootstrap active`
- `af=0.35`

### Doporučení
Pokud je `SCRATCH_EXIT` ekonomicky ztrátový a health ~0, tak bootstrap by měl být přísnější v jednom z těchto bodů:

- méně forced explore vstupů
- menší frequency cap na pár
- vyšší minimální expected hold quality
- tvrdší blok pro weak pairs with repeated scratch losses

---

## Priorita 5 — log cleanup
Doporučené úpravy:

- zabránit warningům zalamovat dashboard řádky
- oddělit human dashboard a async warnings
- netisknout celý dashboard tak často, pokud se nic zásadního nezměnilo
- zkrátit repeating LM sections

---

## Doporučený konkrétní další patch

## V10.13x.2 — Scratch Economics & Health Decomposition

### Rozsah
Nechat trading behavior pokud možno beze změn v první fázi, jen přidat hlubší truth/debugging vrstvu.

### Obsah
1. `SCRATCH_EXIT forensic report`
   - count
   - net pnl
   - avg pnl
   - median pnl
   - avg hold time
   - avg MFE before scratch
   - avg MAE before scratch
   - by symbol
   - by regime

2. `Expectancy scope split`
   - all closed
   - decisive only
   - per symbol
   - per exit type

3. `Health decomposition v2`
   - edge
   - convergence
   - calibration
   - stability
   - breadth
   - exit_quality
   - scratch_penalty
   - bootstrap_penalty

4. `Scratch pressure alert`
   - warning if scratch share > 60%
   - warning if scratch net pnl < negative threshold
   - warning if scratch dominates losses

5. `Clean logging`
   - no mid-line warning corruption
   - one concise dashboard block
   - one concise learning block
   - machine logs separate

---

## Co bych nedělal jako další krok

Zatím bych **nedělal velký strategy rewrite**.

Ještě před tím je potřeba přesně vědět:

- jestli edge umí vznikat, ale zabíjí ho exits
- nebo jestli edge sám o sobě neexistuje
- nebo jestli bootstrap flow kontaminuje statistiky

Teď už máme dost lepší truth layer, takže další krok má být **ekonomická pitva scratch/exit/health**, ne slepé přepisování celé strategie.

---

## Finální doporučení

### Stav
V10.13x je užitečný, protože odkryl pravdu.

### Hlavní problém
Ne dashboard reconciliation, ale:

- **exit economics**
- **scratch dominance**
- **health formula opacity / dead compression**

### Další nejlepší krok
Implementovat:

**V10.13x.2 — Scratch Economics & Health Decomposition**

v tomto pořadí:

1. scratch forensic analytics
2. expectancy scope split
3. health decomposition v2
4. scratch pressure alerts
5. log cleanup

---

## Krátký verdict

**Ano — metrics vrstva je lepší.**  
**Ne — systém ještě není ekonomicky zdravý.**  
**Další patch má cílit na SCRATCH_EXIT a health decomposition, ne na další dashboard kosmetiku.**
