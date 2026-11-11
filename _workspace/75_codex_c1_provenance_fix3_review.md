# Nezávislé re-review hardlinkové opravy původu C1 — 2026-11-11

**Verdikt: APPROVE pro kód commitu `fb2faec29478d85fb7649983ab56706d6ae25559`.** Původní P1 z review 73 je opravený: `samefile` odmítá hardlinkový alias a zápis přes nově vytvořený `.tmp` sám o sobě už nezkrátí sdílený inode logu. Před nasazením zůstává nutný syntetický preflight na Linux serveru a kontrola skutečných cest a oprávnění; tyto hostitelské vlastnosti jsem lokálně nemohl potvrdit.

Review je podle `docs/codex_prompts/CODEX_REVIEW_C1_PROVENANCE_FIX3_2026-11-11.md`. Porovnal jsem `c81cf2f..fb2faec`, zkontroloval aktuální `run_eval.sh` a služby. Neotevřel jsem skutečné post-cutoff výsledky C1, nepřipojoval se na server a neměnil kód, testy ani runtime data. Výstupem jsou pouze tento report a `_workspace/c1_provenance_fix3_review_20261111/`.

## Ověřená oprava

- **B1 / hardlink: PASS.** `scripts/research/learner_replay_report.py:160–177` nejdřív porovnává vyřešené cesty a potom identitu existujících souborů pomocí `os.path.samefile`. `FileNotFoundError` znamená neexistující člen dvojice; jiné `OSError` se převádí na zamítnutí. Nezávisle jsem ověřil všechny čtyři cíle: finální výsledek, manifest a oba `.tmp`. Pro všechny byly vyřešené cesty různé, `samefile` bylo pravdivé a validace odmítla vstup bez změny logu. Vynucený `PermissionError` také skončil odmítnutím. Viz [syntetické kontroly](c1_provenance_fix3_review_20261111/synthetic_checks.json).
- **Původní reproduktor: PASS.** Přesná kopie `hardlink_probe.py` z review 73 skončila `ValueError` ve validaci ještě před zápisem. Log zůstal beze změny; výsledek ani manifest nevznikly. [Výsledek běhu kopie](c1_provenance_fix3_review_20261111/copied_probe_result.json). Původní důkazy review 73 jsem nepřepisoval.
- **Druhá ochrana samostatně: PASS.** Pro syntetický konečný verdikt jsem dočasně vypnul `validate_freeze_inputs` pouze v procesu testovacího skriptu a předem hardlinkoval `verdict.log` na `prereg_result.json.tmp`. `_write_frozen` v `scripts/research/learner_replay_report.py:126–139` staré jméno odstranil, vytvořil nový soubor s `xb`, synchronizoval obsah a zveřejnil výsledek přes `replace`. Log zachoval původní text i novou referenci; hash výsledku souhlasí s manifestem a hash manifestu s referencí. [Důkaz](c1_provenance_fix3_review_20261111/synthetic_checks.json).
- **Atomické zveřejnění a B3: PASS v rozsahu kódu a testů.** `unlink` + `xb` nijak nemění pořadí `flush`/`fsync` obsahu → `replace` → `fsync` adresáře. Manifest se zapisuje před synchronizovanou referencí v logu a výsledek až po ní (`:205–211`). Skutečný pád hosta a chování filesystému zůstávají **NOT_VERIFIED**. Na Windows je `_fsync_dir` no-op; serverový Linux musí projít preflightem.
- **B2, A1/A2, evaluator a slepota: PASS.** Regulární výraz run ID, povinné parametry zmrazení, pořadí reference před markerem a oddělení exploratory/pre-cutoff výsledků jsou beze změny. `src/services/learner_replay.py`, `deploy/research_eval/run_eval.sh` a `scripts/research/cost_and_learning_review.py` se v tomto commitu neměnily. Cílené regresní testy prošly; reálný verdikt C1 nebyl čten ani počítán.

## Omezení souběhu — P3, neblokuje tento commit

`xb` chrání **otevření** nového inode: pokud jiný proces vloží pod `.tmp` jméno dřív, otevření selže místo zápisu přes cizí inode. Po uzavření souboru však `_write_frozen` provede `tmp.replace(path)` podle **jména** (`scripts/research/learner_replay_report.py:137`). Proces, který smí do téhož adresáře zapisovat, může mezi uzavřením a `replace` jméno vyměnit. Syntetická injekce v [synthetic_checks.py](c1_provenance_fix3_review_20261111/synthetic_checks.py) tak zveřejnila jiný inode než ten, který producer zapsal a synchronizoval. Tím se neobnovuje původní chyba přepsání řádky logu; při běžné cestě by nesoulad hashů konzument odmítl. Jde o omezení při **cizím zapisujícím aktérovi**, nikoli o samovolný souběh v produceru.

Současný `deploy/research_eval/run_eval.sh:16–17` používá `flock` a tím serializuje své vlastní běhy; cesta ke zmrazení je v něm jedna (`:40–47`). Jiný proces s právem zápisu do `/opt/cryptomaster_research` tento zámek dodržovat nemusí. Skutečná práva a další zapisující procesy na serveru jsou **NOT_VERIFIED**. Před nasazením je proto nutné potvrdit, že chráněné jmenné prostory může měnit jen řízený evaluační běh; při opačném výsledku je potřeba vyřešit vlastnictví/adresářové oprávnění nebo sdílené zamykání. Předpis „druhá ochrana obstojí při libovolném souběhu“ by byl příliš silný.

## Testy a integrita

| Kontrola | Výsledek |
|---|---|
| `rtk python -B _workspace/code_audit_20260921_runner.py tests/test_replay_blinding.py tests/test_learner_replay.py tests/test_cost_and_learning_review.py -q --tb=short` | **177 passed, 1 skipped** (jen symlink test: Windows nedovoluje symlink); [JUnit](c1_provenance_fix3_review_20261111/targeted_tests_results.xml). Izolovaný snapshot obsahoval kód a dokumentaci, nikoli runtime SQLite. |
| Kopie původního `hardlink_probe.py` | Očekávané zamítnutí před zápisem; viz výše. |
| Nezávislé syntetické kontroly | 4/4 hardlinkové cíle zamítnuty, chyba identity zamítnuta, druhá ochrana samostatně úspěšná; vymezena souběhová hranice. |
| Python AST, `git diff --check c81cf2f fb2faec` | PASS. |
| SHA-256 šesti chráněných runtime souborů před/po testech | **6/6 beze změny**, [porovnání](c1_provenance_fix3_review_20261111/runtime_sha_comparison.json). |

Autorem uváděné 4/4 mutace jsem nezávisle neopakoval; vlastní syntetické kontroly nepřepisovaly zdrojový kód. Testy na této stanici běží pod Pythonem 3.14; kompatibilitu a `fsync` adresáře na serverovém Pythonu 3.12 je potřeba ověřit v preflightu.

## Nutný preflight před nasazením

1. V serverovém deployment balíku porovnat SHA-256 produceru a `run_eval.sh` s reviewovanými soubory. Ověřit Python 3.12 syntax, pevné argumenty `--run-id` a `--provenance-log`, a že skutečný `prereg_result.json` ještě neexistuje. **Nečíst post-cutoff outcomes.**
2. Zkontrolovat vlastnictví a oprávnění `/opt/cryptomaster_research`, skutečný typ a vyřešené cesty `verdict.log`, `prereg_result.json`, `prereg_provenance.json` a obou `.tmp`. Pro existující dvojice ověřit `samefile == false`; žádné nečekané symlinky/hardlinky. Potvrdit, že žádný další proces neupravuje tato jména mimo zámek evaluačního běhu.
3. Syntetické pokusy provést v novém dočasném adresáři **uvnitř stejného filesystemu** `/opt/cryptomaster_research`, nikdy na skutečných C1 souborech: symlink logu na výsledek, hardlink logu na výsledné `.tmp`, hardlink na manifestové `.tmp` a běžné zmrazení. Aliasové případy musí skončit před zápisem; běžný případ musí mít jednu referenci a hashe přesně odpovídající obsahu manifestu a výsledku. Zkontrolovat, že na Linuxu lze otevřít a synchronizovat rodičovský adresář.
4. Ve stejném syntetickém prostoru ověřit obnovu po selhání mezi manifestem a referencí a mezi referencí a výsledkem: bez finálního markeru smí zůstat osiřelý manifest/řádka, opakovaný běh musí vytvořit konzistentní finální trojici. Ověřit běh se serverovým Pythonem 3.12 a bez restartu bota. Skutečný výpadek hosta tím nebude simulován.

Toto review **není povolením k nasazení bez preflightu**. Pokud kontrola práv, aliasů, syntetického zmrazení nebo obnovy selže, nasazení zastavit a vrátit k opravě.
