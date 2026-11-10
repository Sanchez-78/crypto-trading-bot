# Zadání pro Claude: uzavření nálezů R01–R03 z auditu 68

Implementuj tři zbývající opravy popsané v
`_workspace/68_codex_cost_review_verification_20261110.md`. Pracuj přímo v existujícím
offline nástroji a jeho testech. Dodej malý, přezkoumatelný diff a důkazy oprav.

## 1. Rozsah

Kořen: `C:\Projects\CryptoMaster_srv`. Dodrž aktuální `AGENTS.md` a `C:\codex\RTK.md`.
Implementaci provádí Claude; Codex provedl nezávislý audit.

Měnit smíš:

- `scripts/research/cost_and_learning_review.py`;
- `tests/test_cost_and_learning_review.py`;
- nový report `_workspace/69_cost_review_r01_r03_fixes_20261110.md`;
- nové důkazy v `_workspace/cost_review_r01_r03_fixes_20261110/`;
- krátký datovaný dodatek v reportu 67, který odkáže na audit 68 a report 69.

Již existující cílové artefakty nepřepisuj; při kolizi zvol nový suffix. Audit 68,
jeho reproduktor a původní důkazy zůstávají nezměněné. Zachovej nesouvisející změny
v pracovním stromu. Žádná nová větev, worktree, klon, závislost ani refaktoring mimo
příčiny R01–R03. Zachovej Python 3.12.

Toto zadání nepovoluje SSH, deploy, restart, commit, push, reset, stash ani clean.
Neimplementuj ani nenasazuj serverový producer manifestu. Neměň evaluator C1,
předregistraci, cutoff, parametry obchodování, cost model, core bota ani runtime data.

Skutečné post-cutoff outcomes C1 a jejich agregáty neotvírej. Veškeré C1 fixtures
musí být syntetické. Datum ani počet uplynulých dní nejsou oprávněním k jejich čtení.
Futures HOLDOUT znovu nevyhodnocuj; používat lze pouze hotový zmrazený souhrn.

## 2. Nejdřív ověř výchozí stav

Přečti audit 68, report 67, aktuální skript a testy. Pro přesné invarianty čti pouze
zdrojový kód `src/services/learner_replay.py`, `scripts/research/learner_replay_report.py`
a `scripts/research/futures_flow_screen.py`; nevolej jejich evaluátory.

Zaznamenej HEAD, větev, git status a výchozí diff povolených souborů. Audit vycházel
z commitu `43137334a3566c3a659f1dd6dad6ac5b11ee7fd0` a SHA skriptu:

```text
e8e882563fed907153db8c906d057219c7ef7a3d333270271574a6440ab0bd6e
```

Pokud se mezitím změnil, nevracej ho na starou verzi. Zjisti, které nálezy trvají.
Výchozí ověření: 85 PASS, 42 nákladových buněk shodných, runtime data nezměněná.
To jsou historické výsledky auditu, nikoli výsledky tohoto nového úkolu.

## 3. R01 — konzistence C1 artefaktu

Rozšiř `verify_result()` o levné kontroly údajů, které již artefakt obsahuje.
Nezaváděj druhý statistický evaluator. Ověř tyto podmínky proti současné autoritě:

1. `day_bootstrap.valid` je celé číslo, nikoli bool. Původní evaluator používá
   2 000 replikací a konečné CI vydává až při nejméně 90 % platných replikací.
   Pro finální výsledek tedy ověř `1800 <= valid <= 2000`.
2. Počet různých bloků je nejméně 16, nejvýše počet hodnocených obchodů a nejvýše
   počet možných 6h UTC bloků mezi cutoffem a posledním hodnoceným vstupem.
   Pro celočíselné ms a striktní `entry > cutoff` je horní mez:

   ```text
   block_ms = 6 * 3_600_000
   max_blocks = last_entry_ms // block_ms - (cutoff_ms + 1) // block_ms + 1
   ```

   Jde o nutnou podmínku, nikoli důkaz skutečné distribuce vstupů. Netvrď, že tím
   byly ověřeny timestampy všech obchodů.
3. Skupiny vznikají jako `estimate > median` a `estimate <= median`. Proto horní
   skupina nesmí překročit `floor(n / 2)`. Konečný výsledek současného `score()`
   navíc vyžaduje alespoň pět členů v každé skupině. Zachovej kontrolu jejich součtu.
4. ID nesmějí být prázdná ani duplicitní. Typy validuj podle podporovaného kontraktu;
   neopravuj chybné vstupy tichou konverzí nebo odstraňováním ID.

Počet bloků, replikací či velikosti skupin nesmí pocházet z libovolných nových
parametrů dodaných v ověřovaném souboru. Konstanty zdůvodni odkazy na protokol.
Manifest se nadále ověřuje proti nezávislé referenci; samotná správná SHA nemůže
omluvit vnitřně rozporný obsah.

Oprav pozitivní fixture: například n=1 000, upper=480, lower=520, 16 bloků a poslední
vstup cutoff + 5 dní. U n=1 137 může být upper=551/lower=586. Zachovej test delšího
prefixu a všech tří finálních verdiktů. Nevyžaduj n přesně 1 000 ani stejné skupiny.
Obecnou aritmetiku `split_means()` neomezuj pravidly specifickými pro C1.

Povinné negativní testy: valid=0/1799/2001, chybějící valid, bool, příliš mnoho bloků
pro časový rozsah nebo n, horní skupina větší než polovina, skupina menší než pět,
prázdné ID. Povinné pozitivní hranice: valid=1800 a 2000, přípustné bloky a skupiny.
Všechny zamítnuté finální C1 případy musí na cestě `build()` ponechat mu neotevřené;
použij sentinel/spying loader, který při jeho čtení test okamžitě shodí.

## 4. R02 — konzistence coverage

V `coverage_review()` validuj skutečné `rows`, očekávané počty i obsah rozsahů.
Opři se o kontrakt `source_coverage()` a normalizaci zdrojů, nikoli o domyšlené údaje.

Pro futures/spot/metrics:

- rows, expected_rows a missing_rows jsou nezáporná celá čísla bez bool;
- missing nesmí překročit expected;
- ověř vztah skutečných a chybějících řádků k očekávaným. Pokud kontrakt zaručuje
  unikátní timestampy na pravidelné mřížce, musí platit rows + missing = expected;
- každá mezera má platné start_ms, end_exclusive_ms a kladný count; konec je za
  začátkem, délka odpovídá count a intervalu zdroje;
- součet count odpovídá missing_rows; rozsahy se nepřekrývají ani neduplikují;
- futures/spot mají krok 1 minuta, metrics 5 minut. Funding nemá pravidelnou
  minutovou mřížku a tato pravidla se na něj nepřenášejí.

Chybějící doklad znamená NOT_VERIFIED, nikdy OK. Rozporné počty nebo poškozené
rozsahy odmítni jako neplatný vstup. Konzistentně chybějící data označ odpovídajícím
stavem PARTIAL/NO_DATA podle stávajícího kontraktu. Nulové expected nedokládá OK.
Neměň platné nákladové statistiky ani nedoplňuj rows výpočtem místo chybějícího důkazu.

Povinné testy na cestě build/CLI: chybějící rows; rows=0 při expected=100 a missing=0;
missing>expected; chybějící count; obrácený rozsah; nesoulad count s délkou; nesoulad
součtu rozsahů s missing; překryv/duplicitní rozsahy; bool/záporné počty. Doplň pozitivní
fixture s řádnou mezerou pro 1m i 5m data a zachovej nepravidelný funding.

## 5. R03 — zachovat identitu skutečně použitých vstupů

Přestaň zahazovat hash mu z loaderu. Ve výstupní provenanci uchovej:

- hash skutečně přečtených bytů mu;
- hash skutečně přečteného manifestu a důvěryhodnou referenci použitou k porovnání;
- dosavadní hash futures souhrnu, C1 výsledku, run ID a code hash.

Přijatý manifest a referenci lze sdružit, jen pokud je z výstupu jednoznačná jejich
ověřená shoda. Při nesouladu odliš pozorovaný hash od očekávaného; neoznač vstup jako
ověřený. Chybějící nebo nepřečtený vstup má hash null. Reference předaná operátorem
může existovat i bez čtení souboru; nesmí být vydávána za pozorovaný hash souboru.

Využij stejné byty jako parser. Kvůli vykázání hashe nepřidávej druhé čtení, a zejména
nikdy nehashuj mu před ověřením finálního C1. Zachovej dosavadní ochranu slepoty.
Samotná identita mu neověřuje jeho matematickou správnost ani autorství: tato hranice
důvěry zůstává v dokumentaci výslovná.

Testy: změna pouze mu změní jeho input hash; stejné byty a konfigurace dají identický
report; očekávaný hash manifestu je ve výstupu dohledatelný; ve větvích bez oprávnění
ke čtení je mu hash null a sentinel potvrzuje nulový počet přístupů. JSON a Markdown
nadále pravdivě popisují skutečné čtení a žádný výsledek automaticky neschvaluje obchodování.

## 6. Ověření bez dotyku C1

Pouze cílená sada, nikoli všechny testy repozitáře:

```text
rtk python -B _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short
```

Ověř syntaxi skriptu i testů přes AST pro Python 3.12 bez zápisu bytecode. Každý R01–R03
musí mít test zachycující původní vadu; ověř to cílenými mutacemi v izolované kopii.
Za úspěšné zachycení nepočítej selhání importu nebo nekompatibilní signatury.
Původní testy zachovej, neplatné fixtures oprav. Historický reproduktor auditu 68
nepřepisuj; po opravě je jeho odmítnutí vadného vstupu očekávané.

Před testy a po nich porovnej SHA šesti chráněných runtime souborů uvedených v AGENTS.md,
frozen futures souhrnu a auditních důkazů. Chybějící soubory nevytvářej. Rozdíl v
chráněných datech znamená zastavit práci a nahlásit incident, nikoli tichý návrat kopie.

Smoke test spusť pouze nad `_workspace/futures_flow_20261109/screen/report.json`,
bez C1 a mu, s novým výstupním adresářem v adresáři důkazů tohoto úkolu.
Neprováděj znovu simulaci ani bootstrap. Porovnej 42 buněk s původním zmrazeným
cost reportem: n, gross, CI, net ve všech scénářích a rozpočty zůstanou shodné.
Coverage skutečného souhrnu nadále PARTIAL: 28 rozsahů, 10 990 řádků v intervalech
zdrojů. Pokud nový validátor odmítne skutečný souhrn, nejdříve zkontroluj vlastní
interpretaci schématu; žádná výjimka podle hashe souboru nebo skryté oslabení kontroly.

## 7. Předání

Report 69 uvede pro R01–R03 příčinu, konkrétní změnu, test a PASS/FAIL/NOT_VERIFIED,
skutečné počty testů, mutace, porovnání 42 buněk, hash integritu, přehled diffu
a zbývající omezení. Rozliš nezávisle ověřené od převzatých historických výsledků.

Na konci zkontroluj git diff a status vůči výchozímu stavu úkolu. Žádné závěrečné
„vše opraveno“ bez důkazů pro všechny tři nálezy. Skutečný C1 má zůstat neotevřený;
jeho nepřítomnost není překážkou dokončení tohoto lokálního úkolu.

Zápis serverového manifestu je samostatná budoucí změna po review. Toto zadání ho
neautorizuje a nenahrazuje důkaz původního času zmrazení pozdějším časem reportování.
