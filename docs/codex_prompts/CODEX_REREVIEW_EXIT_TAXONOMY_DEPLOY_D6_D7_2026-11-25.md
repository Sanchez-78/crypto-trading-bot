# Cílené re-review nasazovacího skriptu „exit-taxonomy“ po D6/D7 (Codex, 2026-11-25)

Jen audit. Report napiš česky do `_workspace/2026-11-25_codex_rereview_exit_taxonomy_d6_d7.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro `deploy_exit_taxonomy.sh install`.

Navazuje na `_workspace/2026-11-25_codex_rereview_exit_taxonomy_d4_d5.md`. Kód exitů, postimage a
`verify_staging.py` se nezměnily. Změněné soubory:
- `_workspace/exit_taxonomy_release_20261125/deploy_exit_taxonomy.sh`
  (`567d7169e48321a202c6044248a37139be1bf51700eb4ee519a0b534360fba62`);
- `tests/test_deploy_exit_taxonomy_script.py`
  (`b37a831337e2a18a8fad8f09a949f2b9ecbed9ea52c7a6d0b1874fd9cf5dec7e`).

## Opravy

- **D6:** `journal_clean_since` po kontrole `journalctl` spustí `grep -q` nad hotovým souborem a
  status zachytí zvlášť.
  - `rm -f` při chybě vrací neúspěch.
  - Úspěch je **jen** status `grep` = 1 (nenalezeno). 0 (Traceback) i >1 (chyba čtení) jsou
    neúspěch.
- **D7:**
  - `pin_stage()` jednou zkopíruje postimage do privátního `mktemp -d` (chmod 700) a ověří všechny
    čtyři hashe. Při neshodě skončí bez zápisu.
  - `main install` instaluje **jen** z tohoto stage přes `install_files()` a po instalaci stage
    smaže.
  - `write_file(src, dst, expected_sha)` ověří hash **dočasné kopie** proti pinu před
    `chmod`/`chown`/`mv`. Při neshodě kopii smaže a živou cestu nechá beze změny.
  - Totéž platí pro rollback s PRE piny.
  - Živá cesta tak dostane vždy jen PRE nebo POST bajty, a automatický rollback (`rollback_state_ok
    auto` = směs PRE/POST) proto po částečné instalaci vždy projde.
  - Zápisy jsou ve funkcích `install_files` a `rollback_files` (gate → obnova → hashe), služby
    kontroluje `do_rollback`.

## Testy

- Nové testy:
  - `test_grep_error_is_not_a_clean_journal` (`grep` status 2, 0, 1);
  - `test_pin_stage_refuses_an_artifact_changed_after_preflight`;
  - `test_write_file_never_renames_unpinned_bytes` (živý soubor beze změny, dočasná kopie smazaná);
  - `test_partial_install_with_a_bad_file_rolls_back_to_pre`: tvůj scénář, třetí soubor v ORDER
    změněný → `install_rc=1`, automatický rollback rc 0, LIVE přesně PRE a nový modul smazaný;
  - `test_full_install_then_manual_rollback_round_trip`.
- Lokálně: 54 passed, 1 skipped (symlink na Windows), `PROTECTED_SAME`.
- Devět mutací zachytí aspoň jeden test: stará pipeline, D6 `grep` chyba přijata, D7 dočasná kopie
  neověřena, D7 stage neověřen, prázdný journal, PID, `000`, zálohy a stav rollbacku.

**Linux na serveru** (2026-11-25 07:58 UTC). Dočasný strom pod `/root/exit-taxonomy-20261125/`
s kopiemi živých souborů; `/opt` beze změny. Skutečný `chown` jako root.
- `grep` status 2 → rc 1; `pin_stage` → rc 0.
- Změněný `dashboard_read_model` ve stage:
  - „temp copy … != pin, live untouched“, `install_rc=1`;
  - LIVE = PRE (`web`, `read_model`) + POST (`exit_taxonomy`, `performance_epoch`);
  - automatický rollback rc 0.
- Plná instalace rc 0, všechny soubory 644 `root:root`. Ruční rollback rc 0, zůstanou jen tři
  originály a žádné dočasné soubory.
- `preflight` → `STAGING_VERIFIED`, `PREFLIGHT_OK bot_pid=3840326`, profil 200/200.
- Produkční hashe = preimage (`df8b5041`, `12c3e91c`, `b2b19bd9`) a `exit_taxonomy.py` neexistuje.

**Ověřit:**
- Jsou D6 a D7 uzavřené?
- Platí nyní „automatický rollback při každé chybě po prvním zápisu“?
- Jde spustit `install`?

Bez SSH, nasazení a commitu. Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_deploy_exit_taxonomy_script.py tests/test_exit_taxonomy.py`
(s Git Bash v PATH) a `protected_sha.py` před a po.
