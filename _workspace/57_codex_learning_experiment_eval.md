# Vyhodnocení PAPER učícího experimentu — 26. 10. 2026

Zadání `docs/codex_prompts/CODEX_LEARNING_EXPERIMENT_EVAL_2026-10-26.md`
odkazované aktuálním AGENTS.md je implementováno lokálně. Toto kolo neprovádí
SSH, deploy, restart, commit, změnu příznaků ani živého rozhodování.

Výchozí sada **240 PASS / 0 FAIL / 0 SKIP**; závěrečná sada s novými testy
**311 PASS / 0 FAIL / 0 SKIP**. Obě požadované mutace zachyceny. Chráněná
runtime data, oba evidence exporty, AGENTS.md a zakázané produkční soubory
jsou proti začátku tohoto kola beze změny.

Verdikt pro `paper_source_learning_v1`:
`ADAPTIVE_NO_EDGE`, `CONTROL_NO_EDGE`, `EFFECT_INSUFFICIENT_DATA`.
To jsou výstupy předem stanovených orientačních pravidel, nikoli důkaz
kauzálního účinku či obchodního oprávnění.

## Fáze A — ověření dat a nálezů

Zdrojem je výhradně dodaný read-only export
`docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261026.json`.
Má 267 řádků, net P/L −2,04447 USD, průměr −10,209588 bps, výběrovou SD
24,113591 bps a orientační meze [−12,637160; −7,782016] bps.
Výpočet před implementací: `_workspace/learning_eval_findings_20261026.py`,
výstup `_workspace/learning-eval-phase-a-20261026.json`.

| Nález | Stav | Důkaz a upřesnění |
|---|---|---|
| F1 — účinek adaptivního výběru neprokázán | CONFIRMED | ADAPTIVE n=59, −7,810000 bps; CONTROL n=68, −12,142941 bps. Rozdíl +4,332941, Welch SE × 1,96 interval [−2,172500; +10,838383]. Horní meze ramen −3,927704 / −8,303859 bps. Ani jedno rameno nemá n≥100. |
| F2 — placený průzkum bez vlastního limitu kumulativní ztráty | CONFIRMED | `paper_source_learning.py:90` povoluje research cost debit, `signal_router.py:261` jej přijímá přes stávající policy. `paper_learning_budget.py:20` a `:46` omezují počty/čas, nikoli sumu P/L. Trend probe predikce net −12,591624 / realizace −10,750595 bps, mean-reversion probe −7,238651 / −10,358868. Výjimka v zobecnění: breakout probe má +2,510961 predikci net a +0,267143 realizaci, n=7. |
| F3 — nadsazená a téměř nekorelovaná predikce | REFUTED v plošné formulaci | Nadsazení potvrzeno: legacy MR bias +20,690159 bps (n=8), legacy breakout +22,945817 (n=9). Ne všechny korelace jsou blízké nule: legacy MR Pearson −0,688226 a Spearman −0,761905; malé n. Probe MR Pearson +0,187902, trend −0,182982. Tato data nedokládají spolehlivou pozitivní prediktivní vazbu. |
| F4 — Stonkfly má jen 5 WARMUP obchodů | CONFIRMED | Pět tagů `paper_source_learning_stonkfly_v1`, všechny WARMUP, průměr −17,23 bps. ADAPTIVE/CONTROL obě n=0; nevkládají se do native ramen. |
| F5 — starý PaperAdaptiveLearning nedostává tyto closes | CONFIRMED | `paper_close_pipeline.py:42` neobsahuje `p0_8_plus_evidence_collection`; `paper_trade_executor.py:3414` vrací ineligible a `:3504` podmiňuje staré learning hooks. `:3265` je wrapper pro starý record_close. Nová `paper_source_learning.py:343` / `:378` čte vlastní canonical outcomes nezávisle; nejde o absenci veškerého učení. |
| F6 — 36 HARD_STOP_STRUCTURAL je počítáno jako LOSS | REFUTED | Export: n=36, průměr −1,035 bps, **24 FLAT / 4 WIN / 8 LOSS**. `paper_trade_executor.py:1339` klasifikuje net P/L přes `trade_metrics_contract.py:104`; neoznačuje automaticky všechny strukturální výstupy LOSS. Zachovány uložené outcome štítky. |
| F7 — stop a adaptive současně zakázané | CONFIRMED | `paper_source_learning.py:98`, výjimka `:111`; test `tests/test_paper_source_learning.py:47` obsahuje kombinaci stop=true/adaptive=true. Beze změny. |

Reference počtů, průměrů, SD, mezí a kalibračních Pearsonových korelací souhlasí
po zohlednění zaokrouhlení tabulky. Kalibrační reference v zadání má často jen
jedno desetinné místo; testy porovnávají plné přepočtené hodnoty s tolerancí
0,01 bps, korelace s tolerancí 0,05. Jediná věcná neshoda v reference nálezech
je F6; F2/F3 vyžadují uvedená omezení formulace.

### Další nálezy

1. Dosavadní offline report tvrdil, že každá net predikce je oříznutá nulou.
   To pro `_paper_probe_v2` již není pravda. Opravena pouze formulace offline
   výstupu, nikoli mapper nebo uložené hodnoty.
2. Pro experiment existuje šest UTC dnů v sjednocení ramen, jen čtyři společné.
   Společný denní bootstrap má 1 997 platných a 3 nedefinované replikace bez
   některého ramene z 2 000. Výsledný interval [−4,793048; +14,521322] bps také
   obsahuje nulu. Málo bloků a nestejné pokrytí omezují výklad; chybějící rameno
   se nenahrazuje nulou.
3. CONTROL je podíl kandidátů před adaptivním filtrem, nikoli simultánní portfolio.
   Prosté srovnání realizovaných obchodů má výběrová a časová omezení. Není to
   odhad výsledku neotevřených obchodů ani garantovaného dopadu na celkové P/L.

## Fáze B — implementace

| Soubor | Změna |
|---|---|
| `src/services/learning_experiment_verdict.py` — nový | Frozen dataclasses, čistý výpočet pravidel v předepsaném pořadí. SD n−1, arm z=1,645, Welch SE × z=1,96, default n=30/100. Neplatné hodnoty/parametry/numerický overflow → pouze INVALID_DATA. Žádné I/O nebo runtime importy. |
| `scripts/research/p0_8_plus_epoch_report.py` | Parser politiky s INVALID_TAG/NO_POLICY; oddělené source/profile/version/action skupiny; verdikt a společný denní bootstrap; bias/MAE/Pearson/Spearman a kvintily; UTC časová řada. Stávající CLI a atomické zápisy pod --out zachovány. |
| `tests/test_learning_experiment_verdict.py` — nový | 37 případů pro kódy, pořadí, prahy, nulovou SD, chybná data/parametry, přetečení, invarianci a reálných 59/68 výsledků. |
| `tests/test_p0_8_plus_epoch_report.py` | Přidáno 34 případů; původní testy ponechány byte-for-byte jako prefix souboru. Parser včetně duplicitních klíčů/NaN, segmentace, známé korelace, shody, hranice n, bootstrap, JSON --since a nový export. |
| `src/services/LOGIC.md:193` | Definice experimentu, jeho omezení, pravidla, zákaz ladění na evaluačních datech a příkaz. |

Parser používá pouze `policy_version`, `policy_action`, `policy_probability`.
Nejasné/duplicitní/poškozené tagy se počítají jednou za obchod jako INVALID_TAG,
nikdy jako CONTROL. Extra neural arrays se nevkládají do reportových skupin.
Nový export má OK=154, NO_POLICY=113, INVALID_TAG=0.

Kalibrační status je při méně než 5 párech NO_DATA; korelace a kvintily chybí.
Původní popisné průměry pod n=5 zůstávají kvůli starému výstupnímu kontraktu
a existujícímu testu dvou řádků. Poznámka ve výstupu to výslovně rozlišuje.
Spearman používá průměrná pořadí při shodách, kvintily hranice predikce bez
dělení shodných predikcí; mohou vzniknout prázdné kvintily s NULL průměrem.
Konstantní veličina má korelaci NULL, ne nulu.

`--since` pro JSON již existovalo; ověřeno novým CLI testem (inkluzivní filtr
entry_ts). Nebyla implementována duplicitní filtrační cesta.

## Testy, mutace a integrita

Výchozí běh před změnou (disposable code-only kopie, runtime data se nekopírují):

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_p0_8_plus_epoch_report.py tests/test_evidence_budget.py tests/test_paper_source_learning.py tests/test_paper_learning_budget.py tests/test_paper_neural_context.py tests/test_signal_router.py -q --tb=short
```

**240 PASS / 0 FAIL / 0 SKIP**, 12,81 s;
`_workspace/code_audit_20260921_kqz81nin_results.xml`.

Finální běh stejné sady + nový modul:

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_p0_8_plus_epoch_report.py tests/test_evidence_budget.py tests/test_paper_source_learning.py tests/test_paper_learning_budget.py tests/test_paper_neural_context.py tests/test_signal_router.py tests/test_learning_experiment_verdict.py -q --tb=short
```

**311 PASS / 0 FAIL / 0 SKIP**, 17,98 s;
`_workspace/code_audit_20260921_d9708rj2_results.xml`.
Oba běhy mají jednu stávající DeprecationWarning `datetime.utcnow()` z Firebase
modulu ve fixture neural lifecycle; nebyla opravována mimo rozsah zadání.
Meziběhy: 53 PASS pro nový verdikt + původní report; 309 PASS před posledním
zpřísněním parseru a dvěma přidanými případy. Počty běhů se nesčítají.

Mutace:

```text
rtk python _workspace/learning_eval_mutations_20261026.py
```

| Mutace | Výsledek | Zachycující test |
|---|---|---|
| Otočení upper<0 jen pro ADAPTIVE | Zachycena, 1 assertion failure, 0 errors | `test_real_evidence_has_no_edge_in_both_arms_and_insufficient_effect_samples` |
| Vynechání min_effect_n | Zachycena, 2 assertion failures, 0 errors | `test_effect_waits_until_both_arms_reach_threshold[99-100]` a `[100-99]` |

Čistá baseline mutací má 37 PASS. Mutace proběhly pouze v disposable kopii
`_workspace/learning-eval-mutations-77g20nap`; copy se v finally obnovuje,
kanonický modul se nemutoval a jeho hash je nezměněný. Záznam
`_workspace/learning-eval-mutations-20261026.json` obsahuje výsledky i cestu k logům/XML.
První vytvoření kopie selhalo na sandbox ACL před spuštěním testů; po schváleném
lokálním opakování prošlo. Nebyl to testový failure ani přístup na server.

Python 3.12 AST syntax čtyř Python souborů PASS; skutečné testy Python 3.14 Windows.
`git diff --check` pro upravené existující soubory PASS.
Ruff **NOT_RUN**: není nainstalován, nové dependencies se nepřidávaly.

Integrita:

```text
rtk python _workspace/learning_eval_audit_20261026.py before
rtk python _workspace/learning_eval_audit_20261026.py check
```

Baseline 538 souborů; výsledný scope přesně výše uvedených pět cest.
`_workspace/learning-eval-20261026-before/manifest.json` vs
`_workspace/learning-eval-20261026-integrity.json`: všech šest runtime SHA shodných,
evidence exporty a zakázané zdroje shodné. Předešlé stovky dirty změn jsou
zachované; absolutní git status je stále dirty, což není nová změna tohoto kola.
Aktuální úzký diff: `_workspace/learning-eval-20261026-scoped.patch`.
Celý git status/stat/diff uložen jako `learning-eval-final-git-*.txt`.

## Co zůstalo mimo rozsah

- **NOT_RUN:** SSH, deployment, restart, serverové testy, cloud reads/writes,
  celá historická test suite, nové market fetches.
- **NOT_CHANGED:** živé politiky, frekvenční budget, kumulativní loss budget,
  stop flag, TP/SL, REAL cesta, runtime DB, historické výsledky a learning state.
- **NOT_VERIFIED:** kauzální efekt výběru, ziskovost, budoucí výkon nebo účinek
  Stonkfly. Dodaná data a deskriptivní intervaly takový závěr neopravňují.
- Operátorská rozhodnutí v části 8 zadání se neimplementovala.

## Hranice rollbacku

1. Úkol 1: nový čistý modul a jeho nový test. Po úkolu 2 je report importuje;
   při vracení proto nejdříve vrátit reportovou integraci.
2. Úkol 2: vrátit pouze task-diff reportového skriptu a přidané testy proti
   `_workspace/learning-eval-20261026-before/`, nikoli proti Git HEAD.
   Staré uncommitted implementace reportu a testů musí zůstat zachované.
3. Úkol 3: odstranit pouze přidanou sekci LOGIC.md. Generované artefakty jsou
   offline výstupy; žádná DB migrace ani obnova runtime dat není potřebná.

## Generovaný report nad novým exportem — celý obsah

Příkaz (zápis pouze pod explicitní --out):

```text
rtk python -B scripts/research/p0_8_plus_epoch_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261026.json --out _workspace/learning-experiment-eval-20261026
```

Strojový výstup: `_workspace/learning-experiment-eval-20261026/report.json`.
Následuje úplný obsah `report.md` bez redakčních změn.

---

# P0.8+ — popis evidence epochy

Popis dodaných dat; bez doporučení a bez závěru o edge.
Stop meze jsou orientační: obchody nejsou nezávislé.
Bootstrap: celé UTC dny podle exit_ts, 2000 replikací, pevný seed; málo dnů a závislost mezi dny omezují výklad.
Náklady 9→15 bps: aproximace net15 = net9 - 6, nikoli ověření aktuální sazby účtu.
Bez --since jsou zahrnuty všechny dodané řádky, automatický výběr epochy se neprovádí.
Chybějící predikce jsou NO_DATA; legacy net predikce jsou oříznuté nulou, paper_probe_v2 zachovává znaménko.
Verdikt používá předem daná n>=30 pro rameno a n>=100 v obou ramenech pro efekt; žádné ladění na těchto datech.
CONTROL je náhodný podíl kandidátů, nikoli paralelní portfolio; intervaly nejsou kauzální důkaz.
Welchův standard error se zde násobí předepsaným z=1.96 (normální aproximace); ramena používají z=1.645.
Kalibrace: při n<5 NO_DATA pro rozšířenou diagnostiku; staré popisné průměry zůstávají. Shodné predikce se v kvintilech nedělí.

Stav: OK

## Celkem

n=267; WIN/LOSS/FLAT=59/161/47
Čistý průměr -10.209588 bps; výběrová SD 24.113591 bps.
Denní bootstrap 95 %: [-13.221382, -6.928830] bps; UTC dnů=23.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -12.637160/-7.782016 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| DYNAMIC_TARGET_EXIT | 7 | 7/0/0 | 26.978571 |
| HARD_STOP_STRUCTURAL | 36 | 4/8/24 | -1.035000 |
| HARD_STOP_VOLATILITY | 19 | 0/19/0 | -36.582105 |
| SL | 71 | 0/71/0 | -35.382676 |
| TIMEOUT | 91 | 8/60/23 | -8.757692 |
| TP | 40 | 40/0/0 | 29.862250 |
| TREND_INVALIDATED | 3 | 0/3/0 | -22.620000 |

Podíl TP/(TP+SL): 0.360360; driftless reference: 0.416002; realizovaný break-even: 0.542305.
Medián TP MFE=35.861500 bps (n=40), SL |MAE|=25.545400 bps (n=71).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 148/267 (0.554307) | 166/267 (0.621723) |
| 20 | 99/267 (0.370787) | 109/267 (0.408240) |
| 30 | 60/267 (0.224719) | 4/267 (0.014981) |
| 35 | 47/267 (0.176030) | 4/267 (0.014981) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=161, chybí=106; predikce 6.701135, realizace -0.745478, bias (pred−real) 7.446613, MAE 17.706294 bps.
Pearson=0.096023; Spearman=-0.056641.
Uložená net predikce: n=161, průměr -7.943316 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps -10.209588; net při 15 bps -16.209588 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 33 | 0.559632 | -1.411132 |
| 2 | 32 | 1.630503 | -2.260242 |
| 3 | 32 | 3.729266 | 0.833777 |
| 4 | 32 | 7.354572 | -6.679625 |
| 5 | 32 | 20.423626 | 5.810634 |

## sideways_mean_reversion_paper_probe_v2

n=53; WIN/LOSS/FLAT=6/35/12
Čistý průměr -10.358868 bps; výběrová SD 17.360192 bps.
Denní bootstrap 95 %: [-13.368095, -8.384062] bps; UTC dnů=4.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -14.281544/-6.436192 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 8 | 0/8/0 | -37.647500 |
| TIMEOUT | 41 | 2/27/12 | -8.652195 |
| TP | 4 | 4/0/0 | 26.725000 |

Podíl TP/(TP+SL): 0.333333; driftless reference: 0.415892; realizovaný break-even: 0.584838.
Medián TP MFE=35.477900 bps (n=4), SL |MAE|=25.260650 bps (n=8).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 22/53 (0.415094) | 29/53 (0.547170) |
| 20 | 11/53 (0.207547) | 11/53 (0.207547) |
| 30 | 6/53 (0.113208) | 1/53 (0.018868) |
| 35 | 4/53 (0.075472) | 1/53 (0.018868) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=53, chybí=0; predikce 7.167277, realizace -1.359733, bias (pred−real) 8.527011, MAE 14.849164 bps.
Pearson=0.187902; Spearman=0.080793.
Uložená net predikce: n=53, průměr -7.238651 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps -10.358868; net při 15 bps -16.358868 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 11 | 3.378825 | -3.737331 |
| 2 | 10 | 4.780164 | -0.107708 |
| 3 | 11 | 6.588829 | -5.890629 |
| 4 | 10 | 8.392692 | 0.238845 |
| 5 | 11 | 12.590269 | 2.957302 |

## sideways_mean_reversion_v1

n=81; WIN/LOSS/FLAT=23/52/6
Čistý průměr -13.076790 bps; výběrová SD 26.659744 bps.
Denní bootstrap 95 %: [-17.071316, -8.376941] bps; UTC dnů=15.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -17.949599/-8.203981 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 43 | 0/43/0 | -35.207674 |
| TIMEOUT | 20 | 5/9/6 | -1.978500 |
| TP | 18 | 18/0/0 | 27.460000 |

Podíl TP/(TP+SL): 0.295082; driftless reference: 0.419271; realizovaný break-even: 0.561816.
Medián TP MFE=35.547050 bps (n=18), SL |MAE|=25.664000 bps (n=43).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 54/81 (0.666667) | 60/81 (0.740741) |
| 20 | 43/81 (0.530864) | 48/81 (0.592593) |
| 30 | 25/81 (0.308642) | 1/81 (0.012346) |
| 35 | 18/81 (0.222222) | 1/81 (0.012346) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=8, chybí=73; predikce 19.524342, realizace -1.165817, bias (pred−real) 20.690159, MAE 27.156981 bps.
Pearson=-0.688226; Spearman=-0.761905.
Uložená net predikce: n=8, průměr 4.955240 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps -13.076790; net při 15 bps -19.076790 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 2 | 16.078720 | 16.568038 |
| 2 | 1 | 16.390658 | 35.025082 |
| 3 | 2 | 17.779204 | -8.118991 |
| 4 | 1 | 19.398410 | -7.184596 |
| 5 | 2 | 26.344909 | -27.032558 |

## trend_cost_aware_paper_probe_v2

n=84; WIN/LOSS/FLAT=12/46/26
Čistý průměr -10.750595 bps; výběrová SD 19.229264 bps.
Denní bootstrap 95 %: [-14.430000, -6.064615] bps; UTC dnů=4.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -14.201945/-7.299246 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| DYNAMIC_TARGET_EXIT | 7 | 7/0/0 | 26.978571 |
| HARD_STOP_STRUCTURAL | 36 | 4/8/24 | -1.035000 |
| HARD_STOP_VOLATILITY | 19 | 0/19/0 | -36.582105 |
| TIMEOUT | 19 | 1/16/2 | -15.353684 |
| TREND_INVALIDATED | 3 | 0/3/0 | -22.620000 |

Podíl TP/(TP+SL): NO_DATA; driftless reference: NO_DATA; realizovaný break-even: NO_DATA.
Medián TP MFE=NO_DATA bps (n=0), SL |MAE|=NO_DATA bps (n=0).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 39/84 (0.464286) | 47/84 (0.559524) |
| 20 | 19/84 (0.226190) | 27/84 (0.321429) |
| 30 | 9/84 (0.107143) | 2/84 (0.023810) |
| 35 | 7/84 (0.083333) | 2/84 (0.023810) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=84, chybí=0; predikce 1.841264, realizace -1.750582, bias (pred−real) 3.591846, MAE 15.432618 bps.
Pearson=-0.182982; Spearman=-0.097357.
Uložená net predikce: n=84, průměr -12.591624 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps -10.750595; net při 15 bps -16.750595 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 17 | 0.428201 | 3.813092 |
| 2 | 17 | 0.712612 | -6.351428 |
| 3 | 16 | 1.282060 | -0.710116 |
| 4 | 17 | 2.224809 | -1.525456 |
| 5 | 17 | 4.525742 | -3.917799 |

## volatility_breakout_paper_probe_v2

n=7; WIN/LOSS/FLAT=2/3/2
Čistý průměr 0.267143 bps; výběrová SD 21.315141 bps.
Denní bootstrap 95 %: [-6.673333, 14.302000] bps; UTC dnů=4.
Stop pravidlo: CONTINUE; allowed=True; dolní/horní mez -12.985580/13.519865 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 1 | 0/1/0 | -34.430000 |
| TIMEOUT | 4 | 0/2/2 | -4.015000 |
| TP | 2 | 2/0/0 | 26.180000 |

Podíl TP/(TP+SL): 0.666667; driftless reference: 0.419553; realizovaný break-even: 0.568058.
Medián TP MFE=35.178750 bps (n=2), SL |MAE|=25.427600 bps (n=1).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 6/7 (0.857143) | 4/7 (0.571429) |
| 20 | 5/7 (0.714286) | 2/7 (0.285714) |
| 30 | 3/7 (0.428571) | 0/7 (0.000000) |
| 35 | 2/7 (0.285714) | 0/7 (0.000000) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=7, chybí=0; predikce 19.727798, realizace 9.267160, bias (pred−real) 10.460638, MAE 19.565526 bps.
Pearson=0.324370; Spearman=0.535714.
Uložená net predikce: n=7, průměr 2.510961 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps 0.267143; net při 15 bps -5.732857 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 2 | 13.859516 | -13.928595 |
| 2 | 1 | 14.706865 | 35.128806 |
| 3 | 1 | 21.638551 | 3.485709 |
| 4 | 1 | 23.783570 | 35.228739 |
| 5 | 2 | 25.123285 | 9.442029 |

## volatility_breakout_v1

n=42; WIN/LOSS/FLAT=16/25/1
Čistý průměr -5.155714 bps; výběrová SD 33.564511 bps.
Denní bootstrap 95 %: [-17.152809, 9.677544] bps; UTC dnů=16.
Stop pravidlo: CONTINUE; allowed=True; dolní/horní mez -13.675361/3.363932 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 19 | 0/19/0 | -34.875263 |
| TIMEOUT | 7 | 0/6/1 | -13.551429 |
| TP | 16 | 16/0/0 | 33.809375 |

Podíl TP/(TP+SL): 0.457143; driftless reference: 0.411623; realizovaný break-even: 0.507759.
Medián TP MFE=36.622550 bps (n=16), SL |MAE|=25.620800 bps (n=19).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 27/42 (0.642857) | 26/42 (0.619048) |
| 20 | 21/42 (0.500000) | 21/42 (0.500000) |
| 30 | 17/42 (0.404762) | 0/42 (0.000000) |
| 35 | 16/42 (0.380952) | 0/42 (0.000000) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: OK, n=9, chybí=33; predikce 27.784626, realizace 4.838809, bias (pred−real) 22.945817, MAE 45.905916 bps.
Pearson=0.131714; Spearman=-0.133333.
Uložená net predikce: n=9, průměr 11.694697 bps; legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.
Aproximace nákladů: net při 9 bps -5.155714; net při 15 bps -11.155714 bps.

| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |
|---:|---:|---:|---:|
| 1 | 2 | 16.072434 | 0.123551 |
| 2 | 2 | 19.772468 | -23.239951 |
| 3 | 1 | 27.399563 | 84.915397 |
| 4 | 2 | 33.739224 | -26.951486 |
| 5 | 2 | 41.746908 | 29.384826 |

## Profily a přiřazení politiky

| Profil | n | Průměr net bps | SD bps |
|---|---:|---:|---:|
| paper_probe_v2 | 144 | -10.070833 | 18.676369 |
| v1 | 123 | -10.372033 | 29.306797 |

Policy tagy (počty obchodů): OK=154, NO_POLICY=113, INVALID_TAG=0

| Verze / akce | n | Průměr net bps | SD bps | Dolní / horní mez | Pravděpodobnost min / průměr / max |
|---|---:|---:|---:|---|---|
| NO_POLICY / NO_POLICY | 113 | -11.914513 | 27.630331 | -16.190268 / -7.638759 | NO_DATA / NO_DATA / NO_DATA |
| paper_source_learning_stonkfly_v1 / WARMUP | 5 | -17.230000 | 25.290990 | -35.835730 / 1.375730 | 1.000000 / 1.000000 / 1.000000 |
| paper_source_learning_v1 / ADAPTIVE | 59 | -7.810000 | 18.127951 | -11.692296 / -3.927704 | 0.159161 / 0.280660 / 0.483632 |
| paper_source_learning_v1 / CONTROL | 68 | -12.142941 | 19.244914 | -15.982023 / -8.303859 | 1.000000 / 1.000000 / 1.000000 |
| paper_source_learning_v1 / PROBE | 9 | -11.518889 | 20.559750 | -22.792485 / -0.245293 | 1.000000 / 1.000000 / 1.000000 |
| paper_source_learning_v1 / WARMUP | 13 | 7.439231 | 34.298572 | -8.209181 / 23.087643 | 1.000000 / 1.000000 / 1.000000 |

## Předem stanovený verdikt experimentu

### paper_source_learning_stonkfly_v1

EFFECT_INSUFFICIENT_DATA
ADAPTIVE n=0; CONTROL n=0.
Rozdíl ADAPTIVE−CONTROL: NO_DATA bps; Welch SE × 1,96 interval [NO_DATA, NO_DATA] bps.
Denní blokový bootstrap rozdílu: NO_DATA, [NO_DATA, NO_DATA] bps; dnů=0, společných=0, platných replikací=0/2000, vynechaných=0, omezené bloky=True.

### paper_source_learning_v1

ADAPTIVE_NO_EDGE, CONTROL_NO_EDGE, EFFECT_INSUFFICIENT_DATA
ADAPTIVE n=59; CONTROL n=68.
Rozdíl ADAPTIVE−CONTROL: 4.332941 bps; Welch SE × 1,96 interval [-2.172500, 10.838383] bps.
Denní blokový bootstrap rozdílu: OK, [-4.793048, 14.521322] bps; dnů=6, společných=4, platných replikací=1997/2000, vynechaných=3, omezené bloky=True.

## Časová řada podle UTC dne uzavření

| Den UTC | Akce | n | Průměr net bps |
|---|---|---:|---:|
| 2026-09-25 | CELKEM | 14 | -7.400000 |
| 2026-09-25 | NO_POLICY | 14 | -7.400000 |
| 2026-09-26 | CELKEM | 2 | -34.910000 |
| 2026-09-26 | NO_POLICY | 2 | -34.910000 |
| 2026-09-27 | CELKEM | 4 | -29.432500 |
| 2026-09-27 | NO_POLICY | 4 | -29.432500 |
| 2026-09-28 | CELKEM | 15 | 1.786667 |
| 2026-09-28 | NO_POLICY | 15 | 1.786667 |
| 2026-09-29 | CELKEM | 15 | -10.598000 |
| 2026-09-29 | NO_POLICY | 15 | -10.598000 |
| 2026-09-30 | CELKEM | 14 | -18.967857 |
| 2026-09-30 | NO_POLICY | 14 | -18.967857 |
| 2026-10-01 | CELKEM | 11 | -9.780909 |
| 2026-10-01 | NO_POLICY | 11 | -9.780909 |
| 2026-10-02 | CELKEM | 11 | -17.213636 |
| 2026-10-02 | NO_POLICY | 11 | -17.213636 |
| 2026-10-06 | CELKEM | 4 | -8.157500 |
| 2026-10-06 | NO_POLICY | 4 | -8.157500 |
| 2026-10-07 | CELKEM | 6 | -21.435000 |
| 2026-10-07 | NO_POLICY | 6 | -21.435000 |
| 2026-10-08 | CELKEM | 10 | -0.995000 |
| 2026-10-08 | NO_POLICY | 10 | -0.995000 |
| 2026-10-09 | CELKEM | 1 | -36.230000 |
| 2026-10-09 | NO_POLICY | 1 | -36.230000 |
| 2026-10-11 | CELKEM | 1 | -28.290000 |
| 2026-10-11 | NO_POLICY | 1 | -28.290000 |
| 2026-10-12 | CELKEM | 3 | -29.456667 |
| 2026-10-12 | NO_POLICY | 3 | -29.456667 |
| 2026-10-13 | CELKEM | 2 | -18.225000 |
| 2026-10-13 | NO_POLICY | 2 | -18.225000 |
| 2026-10-19 | CELKEM | 4 | 33.947500 |
| 2026-10-19 | CONTROL | 1 | -16.180000 |
| 2026-10-19 | WARMUP | 3 | 50.656667 |
| 2026-10-20 | CELKEM | 4 | -11.367500 |
| 2026-10-20 | CONTROL | 2 | -5.995000 |
| 2026-10-20 | WARMUP | 2 | -16.740000 |
| 2026-10-21 | CELKEM | 1 | -34.310000 |
| 2026-10-21 | PROBE | 1 | -34.310000 |
| 2026-10-22 | CELKEM | 1 | 14.570000 |
| 2026-10-22 | PROBE | 1 | 14.570000 |
| 2026-10-23 | CELKEM | 42 | -9.041905 |
| 2026-10-23 | ADAPTIVE | 12 | -13.895833 |
| 2026-10-23 | CONTROL | 21 | -6.460952 |
| 2026-10-23 | WARMUP | 9 | -8.592222 |
| 2026-10-24 | CELKEM | 47 | -9.694043 |
| 2026-10-24 | ADAPTIVE | 20 | -3.100000 |
| 2026-10-24 | CONTROL | 22 | -16.072727 |
| 2026-10-24 | PROBE | 2 | -14.115000 |
| 2026-10-24 | WARMUP | 3 | -3.930000 |
| 2026-10-25 | CELKEM | 41 | -14.424146 |
| 2026-10-25 | ADAPTIVE | 21 | -13.110952 |
| 2026-10-25 | CONTROL | 16 | -14.930000 |
| 2026-10-25 | PROBE | 3 | -19.456667 |
| 2026-10-25 | WARMUP | 1 | -18.810000 |
| 2026-10-26 | CELKEM | 14 | -1.673571 |
| 2026-10-26 | ADAPTIVE | 6 | 7.215000 |
| 2026-10-26 | CONTROL | 6 | -11.565000 |
| 2026-10-26 | PROBE | 2 | 1.335000 |
