# Náklady, učení a ziskovost: review a plán po C1 (2026-11-10)

> **Erratum (2026-11-10, po auditu `_workspace/66_codex_cost_review_audit_20261110.md`,
> opravy v `_workspace/67_cost_review_audit_fixes_20261110.md`; historická čísla níže beze změny):**
> - Tvrzení o ochraně C1 a validaci v sekci A3 byla silnější než implementace. Nástroj
>   načítal mu před kontrolou finálního C1 (F01), přijal libovolný řetězec CONFIRMED bez
>   doloženého původu (F02), vykázal chybějící coverage jako OK (F03) a z obráceného
>   intervalu nebo n = 0 vyráběl rozpočty (F04). Opraveno a regresně doloženo ve verzi
>   schématu 2. Nákladová aritmetika 42 buněk se nezměnila.
> - Skutečný `prereg_result.json` z dnešního serveru zůstane v nástroji NOT_VERIFIED: běh
>   nezapisuje manifest původu (`c1_provenance_v1`).
> - **Maker:** stejný maker/taker poplatek na spotu znamená jen to, že se neušetří na
>   poplatku. Nevylučuje rozdíl ve fill cenách (zachycení spreadu, adverse selection,
>   čekání, nevyplnění). Věta „maker má smysl jen na futures“ v C3 je přehnaná. Důkaz
>   kladné maker ekonomiky ale stále chybí.
> - **Shadow data:** spot shadow data neprokazují futures fill rate, frontu ani adverse
>   selection. Jsou jen orientační.
> - **WR:** `src/core/trade_metrics_contract.py:20-22` počítá WIN až při net > +0,05 p. b.
>   (+5 bps), pásmo ±5 bps je FLAT. Futures screen
>   (`scripts/research/futures_flow_screen.py:631-633`) bere WR jako net > 0. Nejde o
>   stejnou metriku. Během C1 se nic nepřepočítává ani nemění.
> - **C2:** před startem je nutné definovat jmenovatel primární metriky (analýza podle
>   původní randomizace příležitostí), nepřijaté příležitosti a sdílenou kapacitu
>   portfolia; net na fill se uvádí zvlášť. Odmítnutí kandidáti se nesmějí vydávat za
>   obchody. Osnova v C2 není hotový protokol ke spuštění.

Zadání: `docs/codex_prompts/CODEX_POST_C1_COST_AND_LEARNING_REVIEW_2026-11-10.md`.
Provedl Claude podle pokynu operátora („proveď vše, Codex pouze doporučuje“). Jde jen o
lokální práci: bot, server, konfigurace, runtime data ani C1 se neměnily. Žádný reset.

## Stav C1 (zdroj: slepý řádek `verdict.log`, 2026-11-10 05:47 UTC)

`prereg=PENDING`, `fresh_n=204/1000`, `days=0.93/7`, `prereg_result.json` neexistuje.
Podmínky z kódu (`src/services/learner_replay.py:66-78, 247-281`): ≥ 1 000 čerstvých
obchodů a pokrytí ≥ 16 různých 6h bloků (oboje splní stejný prefix), ≥ 7 dní od cutoffu
a ≥ 6 h od vstupu posledního hodnoceného obchodu. Datum 16. 11. je jen orientační.
**Fáze B neproběhla, protože C1 není zmrazené.** Žádná post-cutoff data jsem neotevřel.

## A1 Errata (doplněno do `RESEARCH_FUTURES_FLOW_FINDINGS.md`)

Mezery v pokrytí (28 rozsahů = 4 rozsahy × 7 symbolů; mezi nimi chybějící futures
2026-10-28 v HOLDOUT), NO_EDGE platí jen pro testované konfigurace, „17 rodin“ nejsou
nezávislé důkazy, +0,02 bps pochází z paper fill cen a WR_BE je dvoubodová aproximace.
V `docs/OPERATING_STATE.md` už je varování k formulaci „vyčerpané“ (commit `6061ceb`).

## A2 Mapa nákladů (ověřeno čtením kódu)

| Vrstva | Kde | Co obsahuje | Jednotka / strany |
|---|---|---|---|
| Admission (odhad) | `src/services/cost_model.py:268-319` (`evaluate_edge`) | taker fee vstup + výstup (`COST_MODEL_TAKER_FEE_BPS=4` na stranu), spread vstup + výstup (z bid/ask), skluz vstup + výstup, latence, funding (jen náklad, nikdy přínos) a nad tím uncertainty buffer 2 bps | bps, každá strana zvlášť |
| Paper settlement (realizace) | `src/services/paper_trade_executor.py:1287-1347` (`_calculate_pnl`) | gross = pohyb mezi fill cenami; odečte `PAPER_FEE_PCT` (komentář `:148` „round-trip“) a `PAPER_SLIPPAGE_PCT` jednou | frakce → % (0,0008 = 8 bps za celý obchod) |
| Fill ceny | vstup `p0_8_plus_live_pipeline.py:50-62` (long za ask, short za bid); výstup `market_stream.py:84-92` → `update_paper_positions` s **mid** | spread vstupu je v gross; spread výstupu chybí | — |
| Výzkumný screen | `scripts/research/futures_flow_screen.py` | fixní 9/18 bps round trip, futures 1m close/high/low | bps, round trip |

**Server (env):** `PAPER_FEE_PCT=0.0008`, `PAPER_SLIPPAGE_PCT=0.0001` → 9 bps za obchod;
`COST_MODEL_TAKER_FEE_BPS=4`, `COST_MODEL_SLIPPAGE_FLOOR_BPS=0.5`.

### Nálezy

1. **Dvojí započítání v settlementu nenalezeno.** Spread vstupu je v ceně, fee a skluz se
   odečítají jednou (`paper_trade_executor.py:1329-1333`).
2. **Settlement náklady podhodnocuje, nenadhodnocuje:**
   - výstup se plní na mid, takže chybí polovina spreadu výstupu (u majors řádově 0,1–1 bps,
     velikost NOT_VERIFIED, data o spreadu při výstupu se neukládají);
   - fee 4 bps za stranu je pod veřejným ceníkem. Spot VIP0 má 10 bps maker i taker
     (7,5 s BNB) [binance.com/en/fee/trading, 10. 11. 2026] a USDⓈ-M regular 2 maker / 5 taker
     (−10 % s BNB) [Binance FAQ 360033544231]. Cenový zdroj bota je spot (`market_stream.py:192`,
     `stream.binance.com`). Realistický taker round trip na spotu je 15–20 bps + spread, na
     futures ~9–10 bps + spread.
3. **Shorty na spotu:** bot otevírá SELL (short) nad spotovými cenami. Bez marže nebo futures to
   reálně nejde a marže má úrok, který model neobsahuje. NOT_VERIFIED, jaký produkt by se použil.
4. **Admission a settlement mají záměrně jinou sémantiku.** Admission je konzervativnější
   (počítá spread obou stran, latenci a buffer), settlement je realizace. Nejde o chybu a
   neslučuji je. Jejich rozdíl ale znamená, že `predicted_net_edge_bps` a realizovaný net
   nejsou přímo srovnatelné.
5. **Funding:** settlement ho nepočítá (spot), admission jen jako náklad. Pro horizont 15 min
   je to zanedbatelné, pokud pozice nepřekročí výplatu fundingu.

Core se v tomto úkolu neopravuje. Návrh po review je v sekci C.

### Citlivost na náklady (`_workspace/cost_and_learning_review_20261110/review.md`)

Jde o aritmetiku nad zmrazeným HOLDOUT, bez nového výpočtu. Bod zvratu (= gross)
H1–H7 je −0,23 až +0,88 bps. Rozpočet s rezervou +3 bps vychází záporný u všech: rezerva
nevychází ani při nulových nákladech. Z průměru nejde dopočítat WR při jiném nákladu, PF ani
drawdown. Přechod na maker by změnil i výběr a ceny fillů, takže ho nelze odvodit odečtením
menšího fee.

## A3 Nástroj

- `scripts/research/cost_and_learning_review.py`: konzument zmrazených vstupů (report.json
  futures screenu, volitelně zmrazený `prereg_result.json` a JSON s mu pro stejnou hodnocenou
  množinu). Neimportuje DB, executor, Firebase ani síť. Bez zmrazeného C1 vypíše PENDING.
  Odmítá NaN/Infinity, duplicitní klíče, poškozený JSON, neplatné n a přepsání vstupu i
  existujícího výstupu. Výsledek je deterministický (SHA vstupů a kódu, bez času).
- `tests/test_cost_and_learning_review.py`: 16 PASS (izolovaný runner). 8 mutací, z toho
  každá zachycena: C1 PENDING jako finální, q = 0,5, chybějící kontrola duplicitních klíčů,
  ziskovost = PASS, CI bez posunu, přepsání výstupu, „days“ místo 6h bloků, n z hypotézy.
  Syntaxe pro Python 3.12 je OK. Ruff NOT_RUN.
- Opakování: `python -B scripts/research/cost_and_learning_review.py --futures-report
  _workspace/futures_flow_20261109/screen/report.json --out <nový adresář>`.
  Po C1 přidat `--c1-result prereg_result.json`.
- SHA-256 šesti runtime souborů před a po: shodné. Futures skript, předregistrace a stage
  soubory nezměněny (git status čistý).

## Čtyři otázky (stav teď)

| Otázka | Stav |
|---|---|
| Jsou data použitelná? | PARTIAL: mezery jsou známé a reportované; v živém botu stale svíčky (viz C1 níže) |
| Umí learner lépe seřadit kandidáty? | PENDING (C1) |
| Má vybraná politika kladný net? | NOT_VERIFIED; živá data −9 bps/obchod |
| Je připravena změna bota? | NO |

## C. Plán po C1 (k review, nic se teď neaktivuje)

### C1 — kvalita dat (oprava cache)

Diff je hotový (`_workspace/63_…`, `_workspace/candle_refresh_20261109/task.diff`, 112 testů,
příznak vypnutý). Po zmrazeném C1:
1. nezávislé review přesného diffu (reviewer-agent nebo audit Codexem);
2. `deploy_bot_files.sh`: dva soubory a drop-in `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED=true`,
   záloha a rollback skriptem;
3. ověření se stejným jmenovatelem: `data_age_ms` < 90 000, nejvýš 1 fetch za symbol a minutu,
   podíl `REJECT_STALE_MARKET_DATA` a funnel počty před a po;
4. **nová kohorta** s vlastním časovým a verzovým markerem (`cohort_start_ms`, verze cache).
   Neslučuje se s C1 a vyšší počet obchodů se nevydává za účinek učení.

### C2 — replikace (jen při CONTRARIAN_CONFIRMED)

Osnova, neaktivní. Hypotézu a čísla doplnit až ze zmrazeného výsledku:
- jedna kauzální mapa score → přijetí s prahem z trailing dat do rozhodnutí (ne medián celé kohorty);
- randomizovaná alokace před výsledkem (např. 50 % politika / 50 % kontrola, stabilní
  hash decision ID), stejní kandidáti a stejná risk/execution cesta;
- oddělené jmenovatele: příležitosti, přijetí, fills, uzavřené obchody; vliv sdílené kapacity;
- primární metrika rozdíl net mezi rameny, nejmenší zajímavý účinek ≥ 3 bps, pevný konec,
  power odhad s 6h bloky, jediné vyhodnocení;
- zvlášť se reportuje kladný post-cost EV vybraného ramene. Lift ≠ zisk;
- zamítnutí kandidáti se nezapisují jako fiktivní obchody.

Při REFUTED / NOT_SHOWN: replikace se nedělá a nepřechází se automaticky na opak.

### C3 — další výzkum (nejvýš dvě možnosti, k rozhodnutí operátora)

1. **Zatím žádný nový signál** (doporučeno do C1): levné screeny jsou negativní a další grid
   search by jen zvyšoval počet testů.
2. **Ověření proveditelnosti maker execution před jakoukoli strategií:** spot maker = taker
   (10 bps), takže maker má smysl jen na futures (2 vs 5 bps). Rozhoduje fill rate, adverse
   selection a výnos od skutečného fillu, ne poplatek. Nejprve levný výpočet ze stávajících
   shadow dat (`shadow_excursion.sqlite`, dotyk midpointu není fill), bez nové pipeline.
   M5 memo (`RESEARCH_M5_COST_ARITHMETIC.md`) ukázalo hrubý zisk ~4 bps na fill, takže
   očekávání je nízké.

Placená data ani menší páry nejsou důkazem edge. Bez nového protokolu a souhlasu se nic nekupuje.

## NOT_VERIFIED

Spread při výstupu (neloguje se), skutečný fee tier účtu, produkt pro shorty, chování opravy
cache na serveru a C1 výsledek.
