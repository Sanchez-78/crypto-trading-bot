# Nezávislé ověření oprav cost/learning review — 2026-11-10

Předmět: commit `43137334a3566c3a659f1dd6dad6ac5b11ee7fd0`, report 67 a aktuální
skript/testy. Codex pouze ověřuje; implementace nebyla změněna.

## Výsledek

**CHANGES_REQUIRED v omezeném rozsahu před použitím C1 části pro závěrečnou interpretaci.**
Hlavní oprava pořadí čtení funguje, aritmetika platných vstupů se nezměnila a existující
testy procházejí. Tvrzení, že všechny vstupní vady jsou uzavřené, je ale předčasné:
zbývají reprodukované mezery v konzistenci C1 a coverage a ztráta vstupní provenance mu.

| Původní nález | Ověření |
|---|---|
| F01, pořadí I/O | PASS pro ověřené větve; bez důvěryhodné reference se nečte C1 ani mu, při nefinálním výsledku se mu nečte |
| F02, původ a konzistence C1 | Výrazně opraveno: reference/manifest/hash/cutoff/počty/CI. Konzistence protokolu zůstává neúplná, viz R01 |
| F03, absence evidence jako OK | Opraveno chybějící coverage a hypotézy. Zbývá falešné OK při nulových/chybějících skutečných řádcích, viz R02 |
| F04, interval a n=0 | PASS: obrácené CI s n>0 se odmítne, n=0 vrací NO_DATA bez rozpočtů |

Nejde o nález v reálném výsledku C1. Skutečné C1 outcomes ani mu nebyly otevřeny.
Všechny nové negativní případy jsou syntetické. Nebyla nalezena cesta nástroje k
obchodním příkazům. Nálezy mají prioritu **P2: integrita offline výzkumného reportu**.

## R01 — F02 přijímá údaje, které nemohl vytvořit deklarovaný protokol

Místo: `scripts/research/cost_and_learning_review.py:297` (`verify_result`), zejména
ověření ID, skupin a `day_bootstrap`.

Přes veřejnou cestu `build()` s obsahově odpovídajícím syntetickým manifestem a jeho
explicitní referencí byly samostatně přijaty tyto rozpory:

| Změna syntetického vstupu | Skutečný výstup | Proč je to rozpor |
|---|---|---|
| `day_bootstrap.valid=0`, intervaly ponechány konečné | CONFIRMED; mu se přečte | `learner_replay.py:230` neposkytne konečné CI při méně než 90 % platných replikací z 2 000 |
| 28 bloků, poslední vstup cutoff + 5 dní | CONFIRMED; mu se přečte | V tomto konkrétním rozsahu se vejde nejvýše 21 různých 6h UTC bloků |
| `upper_n=520`, `lower_n=480`, n=1 000 | CONFIRMED; mu se přečte | `score()` dělí přesně `e > median` a `e <= median`; horní skupina nemůže být větší než polovina |
| Jedno ID je prázdný řetězec | CONFIRMED; mu se přečte | Chybějící ID odmítá vstupní adaptér původního evaluatoru |

Odkazy na autoritu: `src/services/learner_replay.py:160` (skupiny; pro konečné CI
alespoň pět členů v každé), `:214` (bootstrap), `:247` (fresh prefix a poslední vstup),
`scripts/research/learner_replay_report.py:44` (ID).

**Pozitivní fixture v nových testech není plně konzistentní.** `_c1()` na
`tests/test_cost_and_learning_review.py:51` má současně upper=520/1 000 a 28 bloků
za pět dní; případ n=1 137, upper=601 také přesahuje horní polovinu. Testy tak
schvalují výsledky, které současný evaluator nemůže vyprodukovat.

Nejde o obejití kryptografické shody: syntetický manifest odpovídá syntetickým bytům.
Hash prokazuje původ/shodu, nikoli vnitřní bezrozpornost. Právě tu má zdejší validátor
navíc kontrolovat. Toto rozlišení zachovat i ve finálním reportu.

Minimální oprava: validovat `valid` proti skutečnému počtu replikací a jeho minimálnímu
podílu, horní mez počtu bloků podle n a dostupného časového rozsahu, možné velikosti
mediánových skupin a neprázdnost ID. Neprovádět bootstrap, nový medián ani replay.
Pro platnou nerovnoměrnou fixture lze použít upper=480/lower=520 a 16 bloků za pět dní.
Obecná funkce `split_means()` může dál počítat libovolné platné váhy; omezení patří
do validace konkrétního protokolu C1.

## R02 — F03 nekontroluje skutečné počty a obsah mezer

Místo: `scripts/research/cost_and_learning_review.py:208` (`coverage_review`).

Validátor kontroluje `expected_rows`, `missing_rows` a pouze přítomnost položek
`missing_ranges`. Skutečné `rows` u futures/spot/metrics se vůbec nečtou.

Reprodukce nad kompletní syntetickou strukturou všech fází a sedmi symbolů:

- `expected_rows=100`, `rows=0`, `missing_rows=0`, `missing_ranges=[]` → **OK**;
- stejné údaje bez pole `rows` → **OK**;
- `expected_rows=100`, `missing_rows=101`, `missing_ranges=[{}]` → **PARTIAL**,
  přestože souhrn není konzistentní ani rozsah zdokumentovaný.

Původní producer `scripts/research/futures_flow_screen.py:448` ukládá skutečné rows,
expected/missing a rozsahy s `start_ms`, `end_exclusive_ms`, `count`. Není nutné
znovu číst tržní data, aby konzument ověřil jejich základní vzájemnou konzistenci.

Minimální oprava: kontrolovat skutečné rows, meze missing vůči expected, platnost
rozsahů a součet jejich count podle existujícího kontraktu. Chybějící doklad nesmí
být OK; nemožný počet nebo poškozený rozsah odmítnout. Nerovnat nepravidelný funding
minutové řadě. Přidat negativní testy na veřejné cestě build/CLI.

Skutečný zmrazený souhrn má správně PARTIAL. Tento nález nedokazuje jiný počet jeho
mezer; ukazuje, že nové prohlášení o kontrole vstupů je stále příliš silné.

## R03 — při opravě se z reportu ztratil hash mu i použité reference manifestu

Místo: `scripts/research/cost_and_learning_review.py:397` (`mu, _ = loader(...)`)
a `:468` (`inputs`). Původní nástroj hash mu ve výstupu měl.

Reprodukce: stejný platný syntetický C1 a manifest; první mu = −9 bps, druhé mu = +9 bps.
Oba vstupy mají správné binding fields. Výsledky skupin se změní:

```text
mu −9 → upper −6.92, lower −10.92 bps
mu +9 → upper +11.08, lower +7.08 bps
```

Přitom celý objekt `inputs` v obou výstupech zůstává totožný. Z reportu nelze zjistit,
který soubor mu byl použit. Výstup také neuchovává hash přijatého manifestu, přestože
je právě tento hash vstupní hranicí důvěry.

Report 67 poctivě přiznává, že vlastní původ mu zatím není ověřen. To je odlišná věc
od ztráty dostupné identity souboru. Minimální oprava je uložit hash skutečně přečtených
bytů mu a přijaté reference/manifestu. Hash mu počítat a vykazovat až po oprávněném
čtení; bez čtení `null`. Samotný hash nevydávat za důkaz správnosti výpočtu mu.
Přidat test: změna mu mění jeho input hash, identické byty dávají identický report.

## Co bylo nezávisle ověřeno

- Lokální HEAD, `main` a lokální reference `origin/main` ukazují na `4313733`.
  Commit má skutečně 21 souborů, všechny v popsaném rozsahu. Žádný nový síťový fetch
  ani ověření aktuálního remote serveru neproběhlo.
- Skript a testy nemají od tohoto commitu lokální diff.
- Cílená sada byla znovu spuštěna v izolované kopii: **85 PASS, 2,02 s**.
  JUnit: `_workspace/code_audit_20260921_iyx_jz2k_results.xml`.
- První pokus zablokoval sandbox při kopii do Temp, ještě před testy. Opakování
  po schválení použilo stejný runner, který kopíruje kód a blokuje externí síť.
- Přečtení již zmrazeného futures agregátu a aritmetické porovnání s původním
  cost reportem: **42/42 buněk přesně shodných**, C1=PENDING, coverage=PARTIAL.
- Coverage skutečného souhrnu: 28 rozsahů, 10 990 řádků v intervalech jednotlivých
  zdrojů. Nejde o 10 990 minut; metrics mají jiný interval.
- AST syntaxe skriptu i testů pro Python 3.12: PASS.
- Prošel jsem původní mutation script a výsledky 13 mutací. Mutace nebyly v tomto
  review znovu spuštěny; nezávislý důkaz nových mezer jsou vlastní syntetické reprodukce.
- SHA všech šesti chráněných runtime souborů, skriptu/testů, frozen souhrnu a reportů
  66/67 před/po shodné. Důkaz: `cost_review_verification_20261110/integrity.json`.

Příkazy a nové důkazy:

```text
rtk python -B _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short
rtk python -B _workspace/cost_review_verification_20261110/reproduce.py
_workspace/cost_review_verification_20261110/reproductions.json
```

## Navazující postup

Nejdřív úzké lokální opravy R01–R03 a regresní testy. Potom samostatný návrh a review
zápisu provenance při původním zmrazení C1. Serverový producer zde není implementován
ani schválen: nesmí dodatečně přepočítat experiment, číst průběžné outcomes, posunout
cutoff nebo restartovat bota. Nutno zachovat čas a identitu původního zmrazeného běhu;
pozdější čas spuštění reportu nesmí předstírat čas vyhodnocení C1.

Žádný zásah do bota/serveru, žádný deploy, restart, commit ani push. Nově vznikl jen
tento audit, syntetický reproduktor, jeho výstup, doklad integrity a JUnit z opakování.
