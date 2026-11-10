# Implementační zadání pro Claude: opravy auditu cost/learning review

Datum: 2026-11-10. Rozsah: lokální offline nástroj, jeho testy a dokumentace.

Implementuj nálezy F01–F04 z `_workspace/66_codex_cost_review_audit_20261110.md`.
Nezůstávej u návrhu: oprav existující implementaci, dolož regresní testy a napiš
report. Codex provedl audit; toto je implementační zadání pro Claude.

Výsledkem má být důvěryhodný konzument zmrazených výsledků. Toto zadání neslouží
k získání nového výsledku C1, změně strategie ani dosažení zisku úpravou reportu.

## 1. Rozsah a nepřekročitelné hranice

Pracuj v aktuálním pracovním stromu `C:\Projects\CryptoMaster_srv`.
Nevytvářej větev, worktree, klon ani samostatný projekt. Zachovej všechny cizí změny.
Shell příkazy spouštěj s prefixem `rtk` podle `C:\codex\RTK.md`.

Povolené změny:

- `scripts/research/cost_and_learning_review.py`;
- `tests/test_cost_and_learning_review.py`;
- stručné, datované erratum v `_workspace/65_codex_cost_and_learning_review.md`;
- nový implementační report `_workspace/67_cost_review_audit_fixes_20261110.md`;
- nové důkazy a testovací artefakty v `_workspace/cost_review_fixes_20261110/`.

Pokud cílový report/adresář již existuje, nepřepisuj cizí obsah; zvol rozlišující
suffix a uveď ho v závěru. Rozšiř stávající funkce, nevytvářej druhý evaluator nebo
obecný framework pro výzkum. Nové závislosti nejsou povoleny; kompatibilita Python 3.12.

V tomto úkolu neprováděj SSH, deploy, restart, commit, push, reset, stash ani clean.
Tento úzký rozsah platí i pro Claude bez ohledu na starší obecná provozní oprávnění.
Neměň AGENTS.md, provozní konfiguraci, core bota, P0, RiskGuard, Stonkfly, executor,
settlement, Firebase, databáze, stav učení ani obchodní parametry.

C1 zůstává naslepo. Neotvírej skutečné post-cutoff outcomes, jejich agregát `mu`,
ani průběžné lift/CI. Pro vývoj a testy používej syntetické C1 artefakty. Datum
16. listopadu samo o sobě není důkaz splnění podmínek experimentu. Toto zadání
neautorizuje závěrečné vyhodnocení C1 ani tehdy, když mezitím uplyne sedm dní.

Spotřebovaný futures HOLDOUT znovu nevyhodnocuj. Povolené je pouze načtení již
zmrazeného agregovaného `report.json` a aritmetika nad jeho existujícími statistikami.
Žádný nový bootstrap, trénování, hledání thresholdů, změna hypotéz ani výběr strategie.

## 2. Vstupní kontrola

Přečti aktuální `AGENTS.md`, `docs/OPERATING_STATE.md`, reporty 65 a 66, původní
`docs/codex_prompts/CODEX_POST_C1_COST_AND_LEARNING_REVIEW_2026-11-10.md`, skript a testy.
Pro přesný kontrakt C1 čti pouze zdrojový kód a předregistraci:

- `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`, včetně dodatků;
- `src/services/learner_replay.py`;
- `scripts/research/learner_replay_report.py`;
- dostupnou implementaci tvorby výzkumného manifestu, pokud je potřeba.

Tyto zdroje jsou pro tento úkol jen ke čtení. Neimportuj evaluator kvůli spuštění
vyhodnocení a nevytvářej nový skutečný `prereg_result.json`.

Zaznamenej HEAD, větev, stav pracovního stromu a výchozí diff povolených souborů.
Auditovaná verze skriptu měla SHA-256:

```text
dc4041064d9151c4b15ba0d115c224389a40b862aa54f9d1da8413f7d34ae0e1
```

Jiný hash není pokyn k návratu starší verze. Ověř současný obsah a zachovej novější
opravy. Nálezy jsou reprodukovány výhradně synteticky v:

```text
_workspace/cost_review_audit_20261110/reproduce.py
_workspace/cost_review_audit_20261110/reproductions.json
_workspace/cost_review_audit_20261110/integrity.json
```

Auditní důkazy a report 66 neměň. Jejich případy přenes do regresních testů.

## 3. F01 — pořadí I/O a ochrana slepoty

Současný `build()` načítá `mu_path` před kontrolou finálního C1. Při PENDING ho
načte a ignoruje; bez C1 ho načte ještě před chybou. To je porušení hranice čtení,
i když se samotná hodnota následně nevypíše.

Uprav tok takto:

```text
zmrazený futures souhrn → validace
volitelný důvěryhodný doklad C1 → kontrola původu a přípustnosti artefaktu
ověřený C1 artefakt → strukturální a protokolová konzistence
teprve potom volitelné mu → kontrola stejné hodnocené množiny a jednotek
report
```

Chybějící C1 znamená PENDING. Neověřený původ znamená NOT_VERIFIED. PENDING,
INSUFFICIENT_DATA ani neplatný nebo neověřený finální artefakt nesmí vést k otevření,
hashování či parsování mu. Kontrola po načtení souboru nestačí. Samotný `--c1-mu`
bez přípustného C1 musí být odmítnut ještě před čtením mu.

Bez požadavku na C1 musí dál fungovat čistě nákladový report. Při nedostatku důkazu
uveď přesný důvod; při poškozeném vstupu použij jednoznačnou chybu, žádné částečné
CONFIRMED. Zvol a zdokumentuj konzistentní chování CLI a návratové kódy.

Nahraď zavádějící bezpodmínečné `post_cutoff_outcomes_opened=false` a text
„Post-cutoff výsledky otevřeny: ne“. Rozlišuj alespoň:

- čtení raw post-cutoff obchodů: v tomto nástroji vždy zakázané;
- čtení zmrazeného C1 výsledku;
- čtení zmrazeného outcome agregátu mu.

Příznaky musí odpovídat provedenému I/O, i pokud se načtený vstup následně zamítne.
Do chybových zpráv nevypisuj outcome hodnoty zamítnutého vstupu. JSON a Markdown
musí vyjadřovat stejný stav; větve PENDING/NOT_VERIFIED nesmějí vyvolat KeyError.

## 4. F02 — ověření dodaného C1, nikoli nový statistický test

Řetězec `CONTRARIAN_CONFIRMED` a nově vypočtený hash nejsou důkaz původu výsledku.
Nejdřív definuj malý explicitní kontrakt pro důvěryhodný manifest/provenanci a jeho
vazbu na dodaný artefakt. Využij skutečný existující formát, pokud nese potřebné údaje.

CLI může přijmout explicitní manifest a nezávisle známý očekávaný hash/protokol,
pokud dosavadní rozhraní nestačí. Zdokumentuj, odkud pochází důvěryhodná reference:
schválený zmrazený běh/předregistrace, ne výsledek, který se právě ověřuje.
Manifest vytvořený automaticky z neověřeného vstupu by problém neřešil. Není potřeba
PKI, online služba ani nový registr; hash prokazuje shodu s důvěryhodnou referencí,
nikoli pravdivost libovolného obsahu. Bez této reference stav NOT_VERIFIED.

Pokud chybí důvěryhodný doklad, neotvírej volitelný skutečný C1 artefakt „jen pro
zjištění verdiktu“. Čti nejdřív doklad. Následnou kontrolu hashe prováděj nad stejnými
byty, které parsuješ, bez druhého načtení mezi ověřením a použitím.

Kontroluj zejména:

- podporovanou verzi schématu/protokolu a hypotézu `C1_contrarian`;
- hash výsledku proti referenci a vazbu na původní běh;
- cutoff proti předregistraci, ne proti kopii stejného pole z nedůvěryhodného vstupu;
- neprázdná, unikátní a typově platná `scored_trade_ids`;
- celočíselné počty bez bool: `upper_n > 0`, `lower_n > 0`, součet rovný počtu ID;
- shodu dalších deklarovaných počtů s jejich skutečnou sémantikou;
- konečný lift, úplné konečné meze Welch i bootstrap CI a `lower <= upper`;
- minimální počet bloků a dostupné důkazy časových podmínek;
- vazbu mu na tentýž výsledek, hodnocenou množinu, cutoff a jednotky/bázi nákladů.

Aktuální protokol podle auditu požaduje nejméně 1 000 čerstvých obchodů, nejméně
16 různých 6h UTC bloků ve stejném hodnoceném prefixu, nejméně 7 × 24 hodin od cutoffu
a nejméně 6 hodin od posledního hodnoceného vstupu. Ověř přesné hodnoty v autoritě.
Prefix může mít více než 1 000 obchodů; nezaváděj chybnou podmínku `n == 1000`.
Zaokrouhlené `days_elapsed=7.00` samo nedokládá splnění časové podmínky.

Nereprodukuj výběr prefixu, medián, Welch test ani bootstrap. Validuj konzistenci
dodaného výsledku a jeho doložený původ; původní finální verdikt nepřepočítávej ani
neměň. Pokud stávající formát neobsahuje dostatek důkazů, uveď konkrétně chybějící
pole a nech C1 NOT_VERIFIED. Nedoplňuj metadata odhadem a neměň frozen evaluator,
aby starý soubor prošel. Podporu ověřeného rozhraní dokonči syntetickým fixture.

Nahraď neplatnou pozitivní fixture, která obsahuje tři ID proti počtům 520 + 480.
Nová musí mít konzistentní ID, počty, časy, bloky, intervaly a provenanci. Otestuj
všechny tři původní finální verdikty a také platný prefix delší než 1 000.

Hashování seznamu ID má mít explicitní stabilní konvenci. Neměň ji potichu; při
změně verzuj kontrakt. Shoda seznamu ID sama nenahrazuje vazbu na autoritativní běh.
Nepředpokládej stejně velké skupiny: nadále používej skutečné
`q = upper_n / (upper_n + lower_n)`.

## 5. F03 — chybějící coverage není nulová coverage gap

Tři bloky s `statistics: {}` dnes vedou k prázdné tabulce a stavu dat OK. Oprav
validaci skutečného frozen formátu a odděl existenci statistik od úplnosti pokrytí.

- Podporované fáze jsou TRAIN/TEST/HOLDOUT, hypotézy H1–H7, targety r15/tpsl.
- Ověř očekávaný universe a coverage strukturu podle původního kontraktu screenu.
- Chybějící coverage, chybějící zdroj/symbol nebo prázdná evidence nesmějí znamenat OK.
- Dokumentované mezery znamenají PARTIAL; nedoložené pokrytí NOT_VERIFIED.
- OK vyžaduje pozitivně doložené pokrytí, nikoli `get(..., [])`.
- Dokumentovaný dílčí/NO_DATA výsledek zachovej jako explicitní stav; neodvozuj z něj
  nulu ani nevyrob ekonomickou statistiku. Syntakticky poškozený formát odmítni.
- Počet missing ranges není počet chybějících minut; správně pojmenuj obě veličiny.
- Nevyvozuj minutové mezery z nepravidelného funding kalendáře, pokud to původní
  coverage kontrakt nedefinuje.

Počet n je v původním reportu na úrovni hypotézy. Vnořený target ho nesmí přepsat
jinou hodnotou. Případný rozpor odmítni; oprav fixture podle skutečného schématu.

## 6. F04 — intervaly a nulový vzorek

`sensitivity()` musí odmítnout obrácený interval. Při n=0 vrať explicitní NO_DATA
bez rozpočtů/odhadů, nebo srozumitelnou chybu podle zdokumentovaného kontraktu.
Nikdy kladný „konzervativní rozpočet“ z neplatného intervalu či prázdného vzorku.

Kontroluj typy, NaN/Infinity, booleany a potřebné jednotky. Percentilový interval
nemusí obsahovat bodový průměr: takovou podmínku nepřidávej.

Pro platné frozen vstupy zachovej přesně dosavadní aritmetiku:

```text
gross_CI = existující CI net9 + 9 bps
net(c) = gross - c
CI_net(c) = gross_CI - c
cost_budget = gross - 3 bps
conservative_budget = gross_CI.lower - 3 bps
```

Scénáře 0/9/15/18/20 bps ani rezervu 3 bps neměň. Fixní posun intervalu je odvození,
ne nový statistický test. Z agregovaného průměru nevyráběj WR, PF ani drawdown.
Kladný lift nebo bodový odhad skupiny stále nesmějí nastavit profitability=PASS
nebo schválit nasazení. Neměň produkční cost model ani skutečné vyúčtování.

## 7. Regresní testy a průkaz opravy

Testy musí zachytit původní vady na veřejné cestě nástroje, nejen uvnitř pomocných
funkcí. Používej `tmp_path`, syntetická data a injekci/spies na file I/O.

Minimální pokrytí:

| Oblast | Povinné případy |
|---|---|
| F01 | mu se vůbec nečte při chybějícím C1, PENDING, INSUFFICIENT_DATA, chybějící důvěryhodné referenci, mismatch a neplatném final; API i CLI |
| F01 | přístup k obsahu/hashování mu vyvolá v testu sentinel chybu; po validním C1 je správné pořadí čtení; JSON/Markdown pravdivě vykazují expozici |
| F02 | jiný cutoff/hash/protokol, duplicitní či prázdná ID, neplatné počty/součty, chybějící CI, málo bloků, nedoložené nebo nedostatečné časové podmínky |
| F02 | konzistentní synthetic final, každý ze tří verdiktů, n > 1000, nestejně velké skupiny, jiné mu ID/provenance/jednotky |
| F03 | prázdné statistics, chybějící coverage, chybějící fáze/hypotéza/target/symbol/zdroj, doložené mezery, doložené kompletní pokrytí, konfliktní n |
| F04 | n=0, záporné a necelé n, bool, NaN/Infinity, obrácené CI; platný interval mimo bodový průměr zůstává přípustný |
| Regrese | determinismus, původní aritmetika, zákaz přepsání vstupů/výstupů, žádné runtime/DB/Firebase/síťové importy, profitability nikdy automaticky PASS |

Každý F01–F04 dolož testem, který původní vadu zachytí. Ověř to cílenou mutací
v izolované kopii nebo bezpečným během proti zachované původní implementaci.
Selhání kvůli nekompatibilnímu API/importu není důkaz zachycení vady. Nevracej
vadný kód do hlavního pracovního stromu. Nevylepšuj auditní reprodukce tak, aby
zakryly původní problém.

Spusť pouze cílený soubor a validaci syntaxe pro Python 3.12. Existující izolovaný
runner lze použít po ověření jeho současného chování:

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short
```

Dosavadní audit měl 16 PASS; počet nových testů předem nevymýšlej. Původní testy
nemazat za účelem zeleného výsledku. Neplatné fixtures oprav a změny zdůvodni.
Celou sadu `tests/` nespouštěj.

Před testy a po nich porovnej SHA-256 šesti chráněných souborů, pokud existují:

```text
local_learning_storage/cache.sqlite
data/paper_open_positions.json
server_local_backups/paper_adaptive_learning_state.json
server_local_backups/learning_state_phase1.json
runtime/v5_quota_usage.sqlite
src/runtime/v5_quota_usage.sqlite
```

Hashování je kontrola integrity, ne povolení parsovat jejich obsah. Rozdíl je
incident: zastav práci a nahlas ho, neobnovuj soubor potichu. Chybějící soubor
zaznamenej, nevytvářej ho.

Nakonec proveď smoke test pouze nad existujícím zmrazeným futures souhrnem:

```text
rtk python -B scripts/research/cost_and_learning_review.py --futures-report _workspace/futures_flow_20261109/screen/report.json --out _workspace/cost_review_fixes_20261110/frozen_smoke
```

Bez `--c1-result` a bez `--c1-mu`. Výstupní adresář musí být nový. Dolož, že se
aritmetické hodnoty 7 × 3 × 2 = 42 platných buněk nezměnily proti původnímu výstupu.
Změna statusů, schématu či provenance po opravě je očekávaná a musí být vysvětlená.
Pokud souhrn není lokálně dostupný, nedownloaduj ho: uveď NOT_RUN a pokračuj testy
syntetického kontraktu. Hash frozen souhrnu i auditních důkazů před/po musí zůstat stejný.

## 8. Úzká dokumentační oprava

Do reportu 65 přidej datované erratum s odkazem na nezměněný audit 66 a nový report 67.
Původní historické výsledky nepřepisuj. Oprav rozsah tvrzení o ochraně C1 a validaci.
Stručně doplň již doložené interpretační výhrady:

1. Stejné maker/taker fee na spotu dokládá absenci úspory na poplatku, nikoli
   nemožnost rozdílu fill cen; stále chybí důkaz kladné maker ekonomiky.
2. Spot shadow data neprokazují futures fill rate, frontu ani adverse selection.
3. WR v core kontraktu a futures screenu mají odlišnou definici. Ověř ji čtením
   zdrojů, pojmenuj rozdíl; nic nepřepočítávej ani neměň během C1.
4. Budoucí C2 potřebuje předem definovat jmenovatel primární metriky, analýzu podle
   původní randomizace, nepřijaté příležitosti a sdílenou kapacitu portfolia.
   Odmítnuté kandidáty nesmějí být vydávány za obchody.

Toto není zadání k novému maker screeningu, spuštění C2 ani přepisu jejich protokolů.
Neaktualizuj fee sazby odhadem; známé sazby jsou datované scénáře, nikoli ověřený tier účtu.

## 9. Předání a definition of done

Po každém logickém celku zkontroluj diff. Na konci porovnej finální změny s výchozím
stavem, nikoli jen s HEAD, protože pracovní strom obsahuje nesouvisející práci.

Report musí obsahovat:

- tabulku F01–F04: příčina, soubor/funkce, oprava, test, PASS/FAIL/NOT_VERIFIED;
- přesný kontrakt provenance a jeho hranici důvěry, požadovaná metadata a chování
  u starších artefaktů, které je nemají;
- skutečný počet testů a výsledek mutací, příkazy a odkazy na důkazy;
- výsledek smoke testu a porovnání 42 buněk;
- SHA před/po chráněných dat, frozen souhrnu a důkazů;
- příklady CLI pro režim bez C1 a ověřený syntetický final včetně případných nových
  parametrů; neuváděj příkaz, který nyní otevře skutečné C1 outcomes;
- přehled změněných souborů a zbývajících omezení.

Hotovo znamená, že čtyři vady jsou opravené a regresně doložené, validní nákladová
aritmetika zůstala stejná a neověřený C1 nemůže odemknout čtení mu. Absence skutečného
finálního C1 není důvod číst průběžná data: konec úkolu může mít reálný C1 PENDING
a plně otestovanou větev final na syntetických datech.

Výslovně dolož: žádné skutečné C1 outcomes otevřeny, žádné nové vyhodnocení HOLDOUT,
žádná změna bota/serveru/runtime dat, žádný deploy/restart/commit/push. Nic z těchto
oprav samo o sobě není důkaz edge, ziskovosti ani potvrzení učící hypotézy.
