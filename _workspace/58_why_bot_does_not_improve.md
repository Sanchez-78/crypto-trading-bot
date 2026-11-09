# Proč se robot nezlepšuje — vyhodnocení strategií a učení (2026-11-09)

> **Errata (externí audit `_workspace/59_…`, 2026-11-09):**
> - „Robot se nemá z čeho učit / učení nemůže fungovat / signály nemají žádnou
>   předpovědní hodnotu“ — **příliš silné**. Data ukazují jen, že přínos současného
>   filtru **nebyl prokázán** a souhrnný hrubý pohyb je statisticky nerozlišitelný od nuly.
>   Nulový souhrn nevylučuje užitečný výběr (opačně orientované, rozlišitelné podskupiny).
> - „Všechny intervaly hrubého pohybu obsahují 0“ — **nepravda**: `sideways_mean_reversion_v1`
>   BUY −8,31 bps [−16,40; −0,21], BTCUSDT +2,35 [+0,06; +4,64]. Po mnoha prohlížených
>   podskupinách to není objev, ale tvrzení bylo chybné.
> - „Přesně nula“ — správně „+0,02 ± 1,34 bps“. Hrubý pohyb je z paper cen (vstup přes
>   spread, výstup na midpointu), není to čistý mid-to-mid signál.
> - Report míchá snapshoty 913/915 obchodů; reprodukovatelný snapshot je
>   `docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json`.
> - Sekce „Autonomní smyčka“ (S3, termín 30. 11.) je zrušena — viz `docs/OPERATING_STATE.md`.

Data: `closed_trades` epochy od 2026-09-25 (server, read-only export), 913–915 obchodů,
report `/opt/cryptomaster_research/latest/report.md` z 2026-11-09 05:47 UTC.
Náklady v paper modelu: 9 bps na obchod (fee 0,08 % + slippage 0,01 %).

## Shrnutí

**Robot se nezlepšuje, protože se nemá z čeho učit.** Vstupní signály nemají žádnou
předpovědní hodnotu. Hrubý pohyb ceny po vstupu (před poplatky) je za 915 obchodů
**+0,02 ± 1,34 bps**, tedy přesně nula. Čistý výsledek −8,98 bps je přesně cena
poplatků (9,00 bps). Učení umí jen vybírat mezi kandidáty; když jsou všichni kandidáti
v průměru nulový náhodný pohyb mínus poplatek, žádný výběr nevytvoří zisk.

## Důkazy

| Test | Výsledek | Co to znamená |
|---|---|---|
| Hrubý pohyb po vstupu, celkem | +0,02 ± 1,34 bps (n=915) | signál nepředpovídá směr |
| Čistý výsledek | −8,98 ± 1,34 bps | = −náklad 9,00 bps |
| MFE ≥ 10 bps / MAE ≤ −10 bps | 51,5 % / 52,5 % | symetrické — chování náhodné procházky |
| Predikce hrubého pohybu vs. realita | Pearson 0,05, Spearman −0,08 (n=807) | model pohybu nemá informaci |
| Nejvyšší kvintil predikce (14 bps) | realita −1,1 bps | vysoká predikce neznamená velký pohyb |
| Zdroj × směr (10 skupin) | všechny intervaly hrubého pohybu obsahují 0 | žádná strategie ani směr nemá výhodu |
| Symboly (BTC, ETH, SOL, ADA) | hrubý pohyb −2,5 až +2,4, vše v šumu | žádný symbol nemá výhodu |
| Režimy (SIDEWAYS/BULL/BEAR) | −0,6 / +0,4 / +0,7 bps | klasifikace režimu nepřidává informaci |
| Kontexty učení s n ≥ 20 | 17, žádný s dolní mezí čistého výsledku > 0 | není co objevit |
| Stabilita kontextů (první vs. druhá polovina) | r = **−0,34** (17 kontextů) | co se učení naučí z minulosti, v budoucnu neplatí — honí šum |
| ADAPTIVE vs CONTROL | +1,46 bps, 95% CI [−1,36; +4,28] (n=354/340) | výběr nemá prokázaný účinek |
| ADAPTIVE podle pravděpodobnosti vstupu | Q1 (p 0,16–0,26) −4,7; Q4 (p 0,33–0,52) −7,3 bps | vyšší důvěra učení ≠ lepší výsledek |
| Týdenní vývoj ADAPTIVE | W43 −9,5 → W44 −7,2 → W45 −7,3 bps | žádný trend zlepšování |

## Proč učení nemůže fungovat (mechanismus, `paper_source_learning.py:242-298`)

1. **Učení jen filtruje.** Nemění směr, výstupy ani velikost; pouze pouští či drží
   kandidáty, které vytvořily strategie. Když kandidáti nemají hrubý edge, filtr
   ho nemůže vyrobit — maximálně vybrat podmnožinu, která má štěstí.
2. **Pravděpodobnost je pro všechny skoro stejná.** `p = sigmoid(průměr / 10 bps)`
   v mezích 0,1–0,9. Všechny kontexty mají průměr kolem −9 bps → p ≈ 0,29.
   ADAPTIVE je tak prakticky náhodný vzorek ~30 % kandidátů; proto rozdíl proti
   CONTROL je jen ~1,5 bps a statisticky nerozlišitelný.
3. **Krátká paměť honí šum.** Poločas 16 uzavřených obchodů a 36 kontextů s mediánem
   19 obchodů. Při SD ~19 bps na obchod je chyba průměru kontextu ~4–5 bps, tedy
   víc než jakýkoli reálný rozdíl. Záporná stabilita kontextů (r = −0,34) to potvrzuje.
4. **Poplatek je pevný, signál nulový.** Při nulovém driftu je očekávaný čistý výsledek
   −náklad bez ohledu na TP/SL geometrii (potvrzeno i dřívějším grid-searchem).
   Geometrie mění jen rozdělení výsledků (36 % TP/SL poměr vs. break-even 55 %), ne průměr.

## Co z toho plyne

- Další ladění učení, prahů, TP/SL, režimů nebo symbolů na **stávajících** signálech
  cíl (WR > 50 %, kladné P/L) nepřinese. To je stejný závěr jako dřívější výzkum
  (`RESEARCH_COSTWALL_FINDINGS.md`, `RESEARCH_M5_COST_ARITHMETIC.md`): 10 rodin
  strategií bez OOS edge.
- Paper náklad 9 bps je navíc **optimistický**: reálný Binance spot taker je ~10 bps
  na stranu (s BNB ~7,5), tj. 15–20 bps na obchod. Reálně by ztráta byla ~−15 bps/obchod.
- Aby cíl byl vůbec možný, je potřeba **nový zdroj informace** s hrubým edgem
  > ~15 bps na obchod na horizontu, kde náklad nehraje roli — to je výzkum nové
  strategie (data, horizont, trh), nikoli úprava učení. Je to rozhodnutí operátora.

## Autonomní smyčka

- `DECISION_READY` vznikl 2026-10-28 17:47 UTC: `ADAPTIVE_NO_EDGE, CONTROL_NO_EDGE,
  SELECTION_EFFECT_NOT_SHOWN` → pravidlo S1.3 → S2. Denní cron v sezení neběžel
  (sezení bylo zavřené), proto přechod proběhl až 2026-11-09.
- S2 = `PAPER_COST_EXPLORATION_ENABLED=false`: bot přestane platit za průzkumné vstupy
  se záporným modelovaným edgem. Dle dat před 23. 10. lze čekat jen několik obchodů denně.
- Další krok podle pravidel: S3 (stop pravidlo) při `STOP_NO_EDGE` na obchodech po přechodu,
  nejpozději 2026-11-30.
