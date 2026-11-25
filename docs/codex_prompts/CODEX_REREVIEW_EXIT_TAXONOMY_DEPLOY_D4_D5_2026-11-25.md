# Cílené re-review nasazovacího skriptu „exit-taxonomy“ po D4/D5 (Codex, 2026-11-25)

Jen audit. Report napiš česky do `_workspace/2026-11-25_codex_rereview_exit_taxonomy_d4_d5.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro `deploy_exit_taxonomy.sh install`.

Navazuje na `_workspace/2026-11-25_codex_rereview_exit_taxonomy_deploy_step.md`. Kód exitů, postimage
a `verify_staging.py` (`bb6185e7…8a10`) se **nezměnily**. Změnil se jen skript
`_workspace/exit_taxonomy_release_20261125/deploy_exit_taxonomy.sh`
(`9c399a0f050db9b391b5724cd23430fc84e47263f85d0db23b5f52ecc8a3f6fe`).

## Opravy

- **D4, journal:**
  - `journal_clean_since()` zapisuje výstup `journalctl` do `mktemp`;
  - **samostatně** kontroluje návratový kód a neprázdný soubor, pak hledá `grep` nad hotovým
    souborem (bez roury, bez SIGPIPE) a soubor vždy smaže;
  - chyba, prázdný výstup i Traceback = selhání;
  - při instalaci to spustí automatický rollback, v rollbacku `ROLLBACK_FAILED`.
- **D5, PID a profil:**
  - `bot_pid()` vyžaduje úspěšný `systemctl` a kladné číslo;
  - `http_code()` vyžaduje úspěšný `curl` a kód 100–599, takže `000` ani prázdný výstup neprojdou;
  - `profile()` selže, pokud chybí kterýkoli z osmi kódů;
  - nový `EXPECTED_PROFILE` = čtyři endpointy 200/200, což je dnešní autorizovaný veřejný profil.
  - Kontroluje se v preflightu, před prvním zápisem (jinak konec bez zápisu), po instalaci (jinak
    rollback) i po rollbacku.
  - PID se čte před instalací a po ní i po rollbacku; nečitelný nebo změněný PID je chyba.
  - Proměnné `main` jsou inicializované kvůli `set -u`.
- **Visící symlink:** `absent()` = `! -e && ! -L`, použito v `check_live_pre`, v rollbacku i
  v kontrole po něm. `sha()` hashuje jen běžný soubor, ne symlink.
- **Částečný rollback:** `do_rollback(backup, mode, bot_pid)` **před prvním zápisem** ověří:
  - všechny tři zálohy (`backups_ok`);
  - stav živých cest (`rollback_state_ok`):
    - `manual` = přesná POST sada všech čtyř souborů;
    - `auto` = každý existující soubor PRE nebo POST a nový modul nepřítomný nebo POST.

  Při neshodě skončí bez zápisu. Ruční `rollback <záloha>` už nemůže přepsat cizí nasazení.

## Testy

`tests/test_deploy_exit_taxonomy_script.py` (`a5b325fa…b517`): skript se načte do bash (main se při
`source` nespustí) se stuby `journalctl`/`systemctl`/`curl` a dočasným LIVE stromem (proměnná
`EXIT_TAXONOMY_TEST_LIVE`, na serveru nenastavená).
- Journal: chyba, prázdný výstup, Traceback na začátku i na konci dlouhého výstupu, čistý výstup.
  Kontrola, že stará negovaná pipeline byla fail-open (tvé reprodukce).
- PID: selhání, prázdný výstup, 0, text, platné číslo.
- `http_code`: rc 7, `000`, `2000`, prázdný výstup, 401, 200. Profil: selhání a nesoulad (401).
- Visící symlink; na Windows se přeskočí, protože Git Bash neumí skutečný symlink.
- Ruční rollback jen z POST sady; automatický jen PRE/POST.
- **Vadná třetí záloha → žádný zapsaný soubor; cizí živý stav → žádný zápis** (hashe LIVE před a
  po shodné).
- `bash -n`.

Výsledky:
- lokálně 27 passed, 1 skipped (symlink na Windows), `PROTECTED_SAME`;
- šest mutací (stará pipeline, přijatý prázdný journal, nevalidovaný PID, přijaté `000`, rollback
  bez ověření záloh a bez kontroly stavu): každou zachytí aspoň jeden test.

**Na serveru (Linux, jen `/root/exit-taxonomy-20261125`, `/opt` beze změny), 2026-11-25 07:41 UTC:**
- nahraný skript má hash `9c399a0f…`;
- visící symlink → `absent` rc 1, nepřítomná cesta → rc 0;
- Traceback na začátku 300 000 řádků → rc 1; `journalctl` selže → rc 1; prázdný výstup → rc 1;
- skutečný journal dashboardu za posledních 10 minut → rc 0;
- `bot_pid` = 3840326, profil = `EXPECTED_PROFILE`;
- `preflight` → `STAGING_VERIFIED`, `PREFLIGHT_OK bot_pid=3840326`;
- `exit_taxonomy.py` v `/opt` stále neexistuje.

**Ověřit:**
- Jsou D4, D5, symlink a částečný rollback uzavřené?
- Je správně, že `EXPECTED_PROFILE` je pevně 200/200?
- Jde spustit `install`?

Bez SSH, nasazení a commitu. Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_deploy_exit_taxonomy_script.py tests/test_exit_taxonomy.py`
s `protected_sha.py` před a po.
