# Nezávislé re-review produceru původu C1 — 2026-11-11

**Verdikt: CHANGES_REQUIRED.** Commit `c81cf2f8ad4acd083eeb7d7583df1ccc4b9a4ced` opravuje běžné aliasy cest (B1), injekci přes run ID (B2) a pořadí synchronizačních zápisů (B3). B1 však stále propouští hardlinkový alias na dočasný soubor výsledku. Synteticky jsem vytvořil finální výsledek bez řádky `PROVENANCE` v logu. Před nasazením produceru je nutné tento případ opravit a znovu zkontrolovat.

## Rozsah a podklady

- Review podle `docs/codex_prompts/CODEX_REVIEW_C1_PROVENANCE_FIX2_2026-11-11.md`; porovnání `efc3447..c81cf2f`. Poslední commit měnící producer je `c81cf2f`.
- Čtení pouze kódu, testů a syntetických dat. Žádné skutečné post-cutoff výsledky C1 jsem neotevřel. Bez SSH, nasazení, restartu, commitu či pushe.
- Změny tohoto review jsou jen tento report a `_workspace/c1_provenance_fix2_review_20261111/`. Pracovní strom obsahoval již před review řadu nesouvisejících změn; soubory produceru, runneru, evaluatoru a jejich testů zůstaly beze změny.

## Nález

**P1 — Hardlink na `prereg_result.json.tmp` zničí jedinou referenci.** `scripts/research/learner_replay_report.py:156–161` porovnává `Path.resolve()`, což rozpozná relativní cesty a symlinky, ale nikoli dva názvy téhož inode. Log a dočasný soubor výsledku mohou mít různé vyřešené cesty a přesto být hardlinky. Následně `_append_reference` zapíše a synchronizuje řádku do logu (`:138–147`), ale `_write_frozen` otevře hardlinkovaný `.tmp` v režimu `wb` (`:126–135`), čímž stejný soubor zkrátí a přepíše. Po přejmenování (`:193–195`) existuje finální výsledek, ale log řádku ztratil. `fsync` tento logický problém neřeší.

Reprodukce je v [hardlink_probe.py](c1_provenance_fix2_review_20261111/hardlink_probe.py) a její výstup v [hardlink_reproduction.json](c1_provenance_fix2_review_20261111/hardlink_reproduction.json). Syntetický evaluator vrací pouze konečný verdikt a cutoff `123`; nečte botova data. Reprodukce na Windows skutečně použila `os.link(log, result.tmp)` a získala:

```text
different_resolved_paths = true
same_existing_file = true
result_exists = true
manifest_exists = true
provenance_line_in_log = false
log_equals_result = true
```

Stejnou validaci volá i CLI před evaluací (`:214–219`), takže hardlink propustí také tam. Oprava má kromě `resolve()` použít `os.path.samefile`/`Path.samefile` pro všechny existující dvojice log versus výsledek, manifest a oba `.tmp`. Chyby zjišťování identity mimo neexistující soubory mají skončit bezpečně chybou, ne být tiše ignorovány. Doplnit test hardlinku na výsledné `.tmp` pro knihovnu i CLI: zamítnutí před evaluací a beze změny logu, manifestu a výsledku. U serverových cest v `$BASE` je hardlink zatím **nedoložený**; tato reprodukce prokazuje vadu ochrany, nikoli aktuální poškození C1. Samotné ověření nepřítomnosti hardlinku na serveru by neodstranilo vadu obecného kontraktu produceru.

## Ostatní výsledky

- **B1 — běžné aliasy: PASS.** `resolve()` pokrývá relativní cesty, symlinky a aliasy výsledku, manifestu a jejich `.tmp`. Stávající testy toto ověřují. Symlinkový test na Windows přeskočil kvůli oprávnění, takže tento konkrétní případ je na hostu stále **NOT_VERIFIED**. Nejde o další nález nad rámec hardlinku.
- **B2 — PASS.** `RUN_ID_PATTERN.fullmatch` (`:110–112`, `:150–155`) odmítá whitespace, řídicí znaky, ne-ASCII, prázdné ID a délku nad 64. Serverové `%Y%m%dT%H%M%SZ` vyhovuje. CLI kontroluje před načtením dat a evaluací. Nová řádka ani oddělovače polí nejdou do logu propašovat přes ID.
- **B3 — pořadí zápisů v kódu PASS, odolnost při výpadku hosta NOT_VERIFIED.** `_write_frozen` synchronizuje obsah před `replace` a na POSIX adresář po něm (`:115–135`). `_append_reference` synchronizuje log a při prvním vytvoření také jeho adresář (`:138–147`). Při normální cestě je pořadí manifest → reference → výsledek (`:189–195`). Na Linuxu s filesystémem respektujícím `fsync` a bez aliasu z nálezu P1 by hotový marker výsledku měl mít trvale zapsaný manifest a referenci. Skutečný pád hosta, hardware, filesystém Hetzneru ani POSIX synchronizace adresáře nebyly na této Windows stanici ověřeny. `fsync` adresáře je na Windows záměrně no-op.
- **Evaluator, slepota, A1/A2: PASS v rozsahu diffu a cílených testů.** `src/services/learner_replay.py`, `deploy/research_eval/run_eval.sh` a `scripts/research/cost_and_learning_review.py` se mezi `efc3447` a `c81cf2f` nezměnily. Producent vyžaduje `run_id` a `provenance_log` pro zmrazení, zapisuje referenci před výsledkem a CLI odmítá vadné parametry před načtením a evaluací. Dosavadní testy slepoty prošly. Skutečný verdikt C1 nebyl otevřen ani nově přepočten.

## Ověření a integrita

| Kontrola | Výsledek |
|---|---|
| `rtk python -B _workspace/code_audit_20260921_runner.py tests/test_replay_blinding.py tests/test_learner_replay.py tests/test_cost_and_learning_review.py -q --tb=short` | **171 passed, 1 skipped**, 121,46 s; [JUnit](c1_provenance_fix2_review_20261111/targeted_tests_results.xml). Runner vytvořil izolovaný code-only snapshot, nikoli kopii runtime SQLite. |
| `rtk python -B _workspace/c1_provenance_fix2_review_20261111/hardlink_probe.py` | **Vada reprodukována**, viz výše. |
| Python AST produceru, `git diff --check efc3447 c81cf2f` | PASS. |
| SHA-256 šesti chráněných runtime souborů před a po cílených testech | **6/6 beze změny**; [porovnání](c1_provenance_fix2_review_20261111/runtime_sha_comparison.json). |

Claudeových 12/12 mutačních výsledků jsem nezávisle neopakoval. V tomto review jsou nové syntetické důkazy hardlinku a nezávisle spuštěné cílené testy.

## Přednasazovací syntetický preflight po opravě

Na Linux serveru, bez dotyku reálných C1 souborů, v dočasném adresáři vytvořit `result = tmp/prereg_result.json`, `log = tmp/verdict.log`, `log.symlink_to(result)` a ověřit, že `validate_freeze_inputs(result, "20261116T174700Z", log)` skončí `ValueError` a `result` nevznikne. Pak v novém dočasném adresáři vytvořit prázdný `log`, `os.link(log, tmp/prereg_result.json.tmp)` a požadovat stejnou chybu ještě před evaluací. Nakonec synteticky zmrazit normální různé cesty a ověřit hash manifestu, hash výsledku a jedinou referenci v logu. Systémový `fsync` a chování při skutečném výpadku tím zůstávají samostatně neověřené.

**Rozhodnutí pro nasazení:** současný commit nenasazovat jako uzavřenou opravu B1–B3. Po opravě hardlinkového aliasu zopakovat cílené testy, syntetické preflighty a porovnání SHA runtime souborů.
