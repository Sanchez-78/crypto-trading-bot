# Strategie a učení — lokální implementační report, 2026-10-07

Zadání: `docs/codex_prompts/CODEX_STRATEGY_LEARNING_TASKS_2026-10-02.md`.
Úkoly 1–4 jsou implementované v lokálním pracovním stromu. Nasazení a zapnutí
nového příznaku nebylo provedeno. Testy kódu nejsou důkaz ekonomického edge.

Výchozí HEAD: `d14bddb4c33a7a8a831b2e9ff7944d7f23be4699`, větev `main`.
Strom byl již před zadáním rozsáhle změněný; tyto změny jsou zachovány.
Referencí pro tento report je **stav před úkolem**, nikoli čistý Git HEAD.

## A. Ověření nálezů před implementací

Čísla řádků v této tabulce odpovídají výchozímu stavu fáze A. Podrobnosti a
aritmetika: `strategy-learning-phase-a-20261007.md` a
`strategy-learning-phase-a-arithmetic-20261007.json` v tomto adresáři.

| Nález | Stav | Důkaz a přesné omezení |
|---|---|---|
| N1 | CONFIRMED | `src/services/signal_router.py:227`: statistika jen mimo evidence-only; `src/services/p0_8_plus_shadow_evaluator.py:279`: bez closed_trades; `src/services/paper_trade_executor.py:1861`: převzetí admission pro P0.8+. Chybělo statistické stop pravidlo. Existující cost/risk limity stále platily, tedy „neomezeně“ pouze ve smyslu evidence budgetu. |
| N2 | CONFIRMED | `src/services/p0_8_plus_live_pipeline.py:194`: gross zlomek; `src/services/paper_trade_executor.py:2255`, `:2282`: predikce na pozici; `src/services/local_persistent_cache.py:115`, `:321`: chybějící sloupce/projekce. |
| N3 | CONFIRMED, pouze kontext | `src/services/paper_trade_executor.py:2131` vezme geometrii, `:2164` ji explicitní env TP přepíše. Soubory modulů `mean_reversion_exit_v1` a `dynamic_breakout_exit_v1` nenalezeny. Bez změny. |
| N4 | REFUTED v tvrzení „segment_weights čte jen sampler“ | Čte je i sama adaptive vrstva: `src/services/paper_adaptive_learning.py:1025`, `:1222`. Ostatní dílčí části CONFIRMED: výchozí režimy `:95` bez SIDEWAYS, skip `:849`, rozšíření TP při nízkém WR `:888`; sampler má odstraněné entry API (`src/services/paper_training_sampler.py:1`, dokumentuje 21. září). Z toho nelze dovodit živý vliv vah na aktuální vstupy. Navazující zásah do N4 není zadán a nebyl proveden. |
| N5 | NOT_VERIFIED jako aktuální náklad účtu/venue | Historický `RESEARCH_M5_COST_ARITHMETIC.md:18` řeší spot VIP0+BNB; neověřuje aktuální účet nebo derivátový venue. `src/services/paper_trade_executor.py:148` má env-driven náklady a defaults 15+3 bps. 9 bps v dodaném exportu je historický scénář, nikoli univerzální default. Report 9→15 označuje jako aproximaci. |

Dosažitelnost aktuální cesty byla ověřena od `start.py:48` přes
`bot2/main.py:1718`, `p0_8_plus_live_pipeline.py:355`, evaluator a broker.
Jméno modulu samo o sobě nebylo považováno za důkaz živého zapojení.

Přepočet 82 řádků souhlasí s tabulkami zadání v rámci zaokrouhlení:
WIN/LOSS/FLAT 28/52/2, SL/TP/TIMEOUT 44/26/12, vše SIDEWAYS.
Mean/SD celkem −10,634756/28,792798 bps; mean reversion n=57,
mean −11,798421, upper −5,636768; breakout n=25, mean −7,981600,
upper +2,005055. MFE≥20:45, MAE≤−20:46.

## B. Změny po úkolech

| Úkol | Soubor | Změna a dopad |
|---|---|---|
| 1 | `src/services/evidence_budget.py` (nový) | Čisté immutable rozhodnutí; výběrová SD, pořadí stop pravidel, konečné numerické hodnoty, neplatná historie/policy fail-closed. Žádné I/O ani oprávnění k execution. |
| 1 | `tests/test_evidence_budget.py` (nový) | Hranice min/max a nulových mezí, neplatné vstupy, přetečení, determinismus, skutečný JSON. |
| 2 | `src/services/strategy_contracts.py:155` | Nový kód `P0_REJECT_EVIDENCE_BUDGET`. |
| 2 | `src/services/signal_router.py:73`, `:249` | Volitelná injekce; pouze evidence admission, před riskem. Odmítnutí, neplatný výsledek i výjimka uzavřou cestu. Strict-EV a dřívější rejekce zachovány. |
| 2 | `src/services/p0_8_plus_shadow_evaluator.py:89`, `:331` | SQLite mode=ro, source/epoch filtr, cache 60 s, invalidace identity DB/epochy/prahů, log 300 s/source. Callback jen při explicitním příznaku. |
| 2 | `tests/test_signal_router.py`, `tests/test_p0_8_plus_shadow_evaluator.py` | OFF equivalence, risk ordering, fail-closed, strict/early reject, temp SQLite, epoch, cache, chyby a konfigurace. Bypass testy nezměněny. |
| 3 | `src/services/local_persistent_cache.py:129`, `:290` | Dva nullable sloupce a zápis zlomků ×10000 jen pro přesný explore_bucket P0.8+. Neplatné/chybějící hodnoty NULL, staré řádky NULL, bez backfillu. |
| 3 | `tests/test_local_persistent_cache_attribution.py` | Jednotky, nesprávný bucket, chybějící/nonfinite data, nula versus NULL, staré schéma a idempotence. |
| 4 | `scripts/research/p0_8_plus_epoch_report.py` (nový) | Read-only DB/JSON CLI; skupiny a celek, denní bootstrap, stop rozhodnutí, bariéry, exkurze, gross kalibrace, explicitní nákladová aproximace. Výstupy jen pod --out. |
| 4 | `tests/test_p0_8_plus_epoch_report.py` (nový) | Skutečný JSON, temp DB, mode=ro, entry filtr, LONG/SHORT matematika, NULL/NO_DATA, bootstrap, neplatná data a ochrana vstupu. |
| Dokumentace | `src/services/LOGIC.md` | Konfigurace, matematika, integrace, startup podmínka a omezení reportu. |

Nové chování je výchozí **OFF**: `PAPER_EVIDENCE_STOP_RULE_ENABLED=false`.
Akceptované true hodnoty: `1`, `true`, `yes`, `on` po strip/lower.
`PAPER_EVIDENCE_STOP_MIN_N/MAX_N` default 40/150; neplatná konfigurace
se vrací k defaultům. P0 strict prahy a ekonomika ostatních strategií se nemění.

Reader záměrně neimportuje `local_persistent_cache`, protože tento import
inicializuje a zapisuje DB. Použije již načtený kanonický modul. Není-li ještě
inicializovaný normálním startupem, při zapnutém příznaku vrací INVALID_HISTORY.
Po dostupnosti modulu další volání opět normálně čte; žádná náhradní DB nevzniká.
Garantované pořadí jeho inicializace před prvním tickem nebylo prokázáno.

Počet dodatečně přijatých obchodů během 60s cache intervalu není touto změnou
nulový; jde o periodické stop pravidlo, nikoli transakční limit přesného n.
CONTINUE nedává strict-EV ani readiness. Celkový souhrn v offline reportu není
živý globální stop gate; živá kontrola je podle learning_source.

Net predikce zůstává zdola oříznutá nulou existující pipeline. Realizovaný gross
v reportu je side-aware návratnost entry/exit ceny; není odhadován jako net+9.
Kalibrace používá pouze páry s oběma platnými hodnotami.

## C. Další nálezy

1. Predikce se neztrácejí nutně ze všech úložišť: durable close journal ukládá
   celý position/closed JSON (`src/services/paper_close_journal.py:96`, `:113`).
   N2 se vztahuje ke canonical closed_trades projekci. Pokrytí historických
   predikcí journalem nebylo ověřeno; žádný backfill.
2. Nezávislá kontrola úkolu 1 odhalila overflow `math.isfinite(z)` u obřího
   integer z. Opraven převodem v try; nový test `z=10**1000` prochází.
3. Write-on-import cache vyžaduje izolaci testů a výše uvedený startup guard.
   Tento historický import-time design se mimo zadání nepřepisoval.
4. Předchozí provozní práce má otevřený incident Stonkfly SQLITE_BUSY a diskové
   kapacity; nepatří k těmto čtyřem lokálním úkolům. Viz samostatný
   `docs/remediation/STONKFLY_LIVE_2026-10-02.md`, handoff 7. října.
   Prvních 30 minut předchozí validace prošlo, pozdější inference se zastavila;
   dlouhodobá stabilita nebyla prohlášena za vyřešenou.
5. Nezávislé review úkolu 4 zachytilo přepis cizího inode přes hardlink výstupu
   a rozdílnou normalizaci neplatného outcome v celkových/dílčích součtech.
   Opraveno atomickým nahrazením výstupu z temp souboru uvnitř --out a společnou
   funkcí `_outcome`; dvě nové regrese procházejí. Následné read-only review
   úkolů 2–4: **APPROVE**, reviewer `/root/dashboard_service`.

## D. Ověření a přesné příkazy

Testy běžely přes `_workspace/code_audit_20260921_runner.py` v dočasné kopii
obsahující pouze kód/dokumentaci a explicitní neměnný evidence JSON. Runner
zakazuje externí síť, nastavuje PAPER a REAL OFF a spouští pytest s
`-p no:cacheprovider`, bez bytecode a automatických pluginů. Původní runtime
data se do kopie nekopírují. Nové DB fixtures používají tmp_path; historické
import-time inicializace mohly vytvořit pouze disposable snapshot DB.

Baseline příkaz:

```text
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_signal_router.py tests/test_signal_router_bypass.py tests/test_cost_model.py tests/test_p0_segment_ev_gate.py tests/test_p0_8_plus_shadow_evaluator.py tests/test_p0_8_plus_shadow_evaluator_bypass.py tests/test_p0_8_plus_live_pipeline.py tests/test_p0_8_plus_config_validation.py tests/test_p0_8_plus_document_invariants.py tests/test_strategy_sideways_mean_reversion_v1.py tests/test_strategy_sideways_mean_reversion_v1_bypass.py tests/test_strategy_volatility_breakout_v1.py tests/test_strategy_trend_cost_aware_v1.py tests/test_local_persistent_cache_attribution.py
```

Konečná rozšířená sada:

```text
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_signal_router.py tests/test_signal_router_bypass.py tests/test_cost_model.py tests/test_p0_segment_ev_gate.py tests/test_p0_8_plus_shadow_evaluator.py tests/test_p0_8_plus_shadow_evaluator_bypass.py tests/test_p0_8_plus_live_pipeline.py tests/test_p0_8_plus_config_validation.py tests/test_p0_8_plus_document_invariants.py tests/test_strategy_sideways_mean_reversion_v1.py tests/test_strategy_sideways_mean_reversion_v1_bypass.py tests/test_strategy_volatility_breakout_v1.py tests/test_strategy_trend_cost_aware_v1.py tests/test_local_persistent_cache_attribution.py tests/test_evidence_budget.py tests/test_p0_8_plus_epoch_report.py
```

| Běh | PASS | FAIL | SKIP | JUnit v _workspace |
|---|---:|---:|---:|---|
| Baseline, 14 souborů | 311 | 0 | 0 | `code_audit_20260921_oyr4f0ke_results.xml` |
| Úkol 1 po numeric review | 30 | 0 | 0 | `code_audit_20260921_vlaawhd6_results.xml` |
| Úkol 2, router/evaluator + oba bypass soubory | 97 | 0 | 0 | `code_audit_20260921_zgkzgfv2_results.xml` |
| Úkol 3, attribution | 24 | 0 | 0 | `code_audit_20260921_kng91f43_results.xml` |
| Úkol 4 po review, report | 16 | 0 | 0 | `code_audit_20260921_u9fhcben_results.xml` |
| Sada před finálním review | 403 | 0 | 0 | `code_audit_20260921_vmrb4q3s_results.xml` |
| Konečná sada po opravách, 16 souborů | 405 | 0 | 0 | `code_audit_20260921_widblx8h_results.xml` |

Baseline 16,30 s, konečná sada 14,59 s. Oba běhy mají stejných 12 existujících
utcnow deprecation warningů. Čas testů není performance měření živého bota.

Cílené příkazy:

```text
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_evidence_budget.py
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_signal_router.py tests/test_signal_router_bypass.py tests/test_p0_8_plus_shadow_evaluator.py tests/test_p0_8_plus_shadow_evaluator_bypass.py
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_local_persistent_cache_attribution.py
rtk python _workspace/code_audit_20260921_runner.py -q tests/test_p0_8_plus_epoch_report.py
rtk python _workspace/strategy_learning_guard_20261007.py verify
rtk python _workspace/strategy_learning_diff_20261007.py
rtk python -B scripts/research/p0_8_plus_epoch_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades.json --out _workspace/strategy-learning-epoch-report-20261007
```

Vývojové neúspěšné běhy nezamlčujeme: úkol 1 měl jeden chybný testovací
předpoklad o rozsahu overflow (opraveno na ±1,7e308); úkol 2 měl testovací
wrapper se jménem argumentu `uri`, kolidující s keyword `uri=True`
(1 FAIL/96 PASS, opraveno na `database`). Konečné sady jsou zelené.

### Mutační kontroly

```text
rtk python _workspace/strategy_learning_mutation_20261007.py 1
rtk python _workspace/strategy_learning_mutation_20261007.py 2
```

| Mutace | Výsledek | Příklady testů, které ji zachytily |
|---|---|---|
| Úkol 1: `upper < 0` → `upper > 0` | 6 FAIL, 23 PASS, 0 SKIP; mutace zachycena | `test_ordered_boundaries`, `test_exact_zero_bounds_use_strict_upper_and_inclusive_lower`, `test_supplied_epoch_evidence_stops_mean_reversion_but_not_cold_breakout` |
| Úkol 2: fail-closed výsledek výjimky nahrazen povolením | 6 FAIL, 28 PASS, 0 SKIP; mutace zachycena | `test_budget_exception_fails_closed_before_risk`, všech 5 variant `test_invalid_budget_return_fails_closed` |

Obě mutace obnoveny byte-for-byte v finally; následná konečná sada testovala
původní korektní kód. První mutace předcházela přidání 30. testu na obří z.
Logy: `strategy-learning-mutation-task1-20261007.txt` a `task2` analogicky.
Sandbox nejdříve zablokoval Temp u obou mutací; tyto infrastrukturní chyby
nebyly započítány jako zachycení mutace. Opakování s povoleným přístupem
prokázala skutečná assertion selhání.

Syntaxe: `ast.parse(..., feature_version=(3,12))` PASS pro všech 11 měněných
Python souborů; běhy byly na Windows/Python 3.14.3. Linux/Python 3.12 execution
NOT_RUN. `git diff --check` pro měněné soubory PASS.

## E. Zachování dat a rozsahu

`strategy-learning-baseline-20261007.json` obsahuje výchozí SHA-256 šesti
požadovaných runtime cest a 63 chráněných souborů. Opakované kontroly během
práce i po konečné sadě: `{"runtime": [], "protected": []}`.
Žádný nový rozdíl. Nepřítomný runtime soubor se porovnává jako nepřítomný.

Oba bypass testovací soubory navíc byte-for-byte souhlasí s baseline kopií.
Samotný git status stále ukazuje staré M/D položky chráněných souborů;
doslovně prázdný status by vyžadoval zahodit cizí práci. Akceptace je proto
doložena nulovým **novým** rozdílem oproti zachycenému výchozímu stavu.

PAPER/REAL konfigurace, exekutor, cost model, P0 prahy, strategie,
Stonkfly, učení, služby a workflows nebyly v tomto zadání změněny.
Nebyla vytvořena větev, commit, deployment ani služba.

## F. Rollback hranice

Inkrementální review patche vůči baseline jsou
`strategy-learning-task1-20261007.patch` až `task4` a `taskdocs`.
Nevracejí starší uživatelské změny; nejsou diffem vůči Git HEAD.

- Úkol 1: nový čistý modul a jeho test. Před odebráním modulu nejprve odebrat
  závislé zapojení úkolu 2 a import reportu úkolu 4. Není samostatně odstranitelný
  za současného ponechání importujících komponent.
- Úkol 2: pouze nová konstanta, callback blok, reader/cache/flag a nové testy.
  Pro provozní vypnutí stačí ponechat příznak OFF; změna serveru není součástí
  této práce. Zachovat starší úpravy routeru a evaluátoru.
- Úkol 3: jen dva sloupce ve schématu a dvě hodnoty INSERT + převod/testy.
  Pokud již někdy budou sloupce nasazeny, mohou po code rollbacku zůstat jako
  nepoužívané nullable sloupce; DB ani existující data se nemažou.
- Úkol 4: nový offline skript a test; bez vlivu na živé rozhodování.
  Vygenerované reporty jsou oddělené artefakty.
- Dokumentace: pouze nová sekce v LOGIC.md. Forenzní artefakty lze zachovat.

## G. NOT_RUN / NOT_VERIFIED a otevřené body

- SSH, deploy, restart, zapnutí flagu, zápis do runtime DB, backfill, commit,
  push a full `tests/`: **NOT_RUN**, výslovně mimo aktuální zadání.
- N3 geometrie, N4 přepojení učení, N5 změna fees, nové signály/strategie:
  **neimplementováno**, rozhodnutí operátora.
- Reálný výkon, SQL plán na rostoucí provozní DB, drift mezi dny, aktuální
  fee tier, živá startup dostupnost cache a budoucí kalibrace:
  **NOT_VERIFIED**. Denní bootstrap zde obsahuje jen 8 dnů.
- Ziskovost a WR>50 % nejsou tímto reportem doloženy ani deklarovány.
- Předchozí Stonkfly SQLITE_BUSY incident zůstává otevřený; aktuální zákaz
  přístupu na server a chráněný rozsah jej nyní neumožňují opravovat.

## H. Přesný výstup offline report.md

```markdown
# P0.8+ — popis evidence epochy

Popis dodaných dat; bez doporučení a bez závěru o edge.
Stop meze jsou orientační: obchody nejsou nezávislé.
Bootstrap: celé UTC dny podle exit_ts, 2000 replikací, pevný seed; málo dnů a závislost mezi dny omezují výklad.
Náklady 9→15 bps: aproximace net15 = net9 - 6, nikoli ověření aktuální sazby účtu.
Bez --since jsou zahrnuty všechny dodané řádky, automatický výběr epochy se neprovádí.
Chybějící predikce jsou NO_DATA; predicted net edge je v pipeline zdola oříznutý nulou.

Stav: OK

## Celkem

n=82; WIN/LOSS/FLAT=28/52/2
Čistý průměr -10.634756 bps; výběrová SD 28.792798 bps.
Denní bootstrap 95 %: [-17.057744, -5.245165] bps; UTC dnů=8.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -15.865252/-5.404260 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 44 | 0/44/0 | -35.156818 |
| TIMEOUT | 12 | 2/8/2 | -3.599167 |
| TP | 26 | 26/0/0 | 27.616923 |

Podíl TP/(TP+SL): 0.371429; driftless reference: 0.413582; realizovaný break-even: 0.560056.
Medián TP MFE=36.415800 bps (n=26), SL |MAE|=25.682950 bps (n=44).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 53/82 (0.646341) | 57/82 (0.695122) |
| 20 | 45/82 (0.548780) | 46/82 (0.560976) |
| 30 | 31/82 (0.378049) | 1/82 (0.012195) |
| 35 | 26/82 (0.317073) | 1/82 (0.012195) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: NO_DATA, n=0, chybí=82; predikce NO_DATA, realizace NO_DATA, bias (pred−real) NO_DATA, MAE NO_DATA bps.
Uložená net predikce: n=0, průměr NO_DATA bps; oříznutá nulou.
Aproximace nákladů: net při 9 bps -10.634756; net při 15 bps -16.634756 bps.

## sideways_mean_reversion_v1

n=57; WIN/LOSS/FLAT=18/37/2
Čistý průměr -11.798421 bps; výběrová SD 28.279306 bps.
Denní bootstrap 95 %: [-17.226571, -5.592300] bps; UTC dnů=8.
Stop pravidlo: STOP_NO_EDGE; allowed=False; dolní/horní mez -17.960074/-5.636768 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 31 | 0/31/0 | -35.356129 |
| TIMEOUT | 10 | 2/6/2 | -1.822000 |
| TP | 16 | 16/0/0 | 27.609375 |

Podíl TP/(TP+SL): 0.340426; driftless reference: 0.419293; realizovaný break-even: 0.561516.
Medián TP MFE=35.624450 bps (n=16), SL |MAE|=25.722200 bps (n=31).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 40/57 (0.701754) | 42/57 (0.736842) |
| 20 | 34/57 (0.596491) | 33/57 (0.578947) |
| 30 | 20/57 (0.350877) | 1/57 (0.017544) |
| 35 | 16/57 (0.280702) | 1/57 (0.017544) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: NO_DATA, n=0, chybí=57; predikce NO_DATA, realizace NO_DATA, bias (pred−real) NO_DATA, MAE NO_DATA bps.
Uložená net predikce: n=0, průměr NO_DATA bps; oříznutá nulou.
Aproximace nákladů: net při 9 bps -11.798421; net při 15 bps -17.798421 bps.

## volatility_breakout_v1

n=25; WIN/LOSS/FLAT=10/15/0
Čistý průměr -7.981600 bps; výběrová SD 30.354573 bps.
Denní bootstrap 95 %: [-19.764508, 5.323435] bps; UTC dnů=8.
Stop pravidlo: CONTINUE; allowed=True; dolní/horní mez -17.968255/2.005055 bps.

| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |
|---|---:|---|---:|
| SL | 13 | 0/13/0 | -34.681538 |
| TIMEOUT | 2 | 0/2/0 | -12.485000 |
| TP | 10 | 10/0/0 | 27.629000 |

Podíl TP/(TP+SL): 0.434783; driftless reference: 0.410772; realizovaný break-even: 0.556592.
Medián TP MFE=36.592800 bps (n=10), SL |MAE|=25.510200 bps (n=13).

| X bps | MFE ≥ X | MAE ≤ −X |
|---:|---|---|
| 10 | 13/25 (0.520000) | 15/25 (0.600000) |
| 20 | 11/25 (0.440000) | 13/25 (0.520000) |
| 30 | 11/25 (0.440000) | 0/25 (0.000000) |
| 35 | 10/25 (0.400000) | 0/25 (0.000000) |

Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.
Kalibrace hrubého pohybu: NO_DATA, n=0, chybí=25; predikce NO_DATA, realizace NO_DATA, bias (pred−real) NO_DATA, MAE NO_DATA bps.
Uložená net predikce: n=0, průměr NO_DATA bps; oříznutá nulou.
Aproximace nákladů: net při 9 bps -7.981600; net při 15 bps -13.981600 bps.

```
