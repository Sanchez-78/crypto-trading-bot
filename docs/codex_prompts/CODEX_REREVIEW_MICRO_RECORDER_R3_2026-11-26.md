# Re-review sběrače order booku a likvidací, rev. 3 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_micro_recorder_r3.md`.

Verdikt:
- **A:** `stop-tick`. APPROVE / CHANGES_REQUIRED.
- **B:** `preflight` + `install`. APPROVE_TO_DEPLOY / CHANGES_REQUIRED.

Navazuje na `_workspace/2026-11-26_codex_rereview_micro_recorder_r2.md`.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` (rev. 3) | `afbbb5c8d75cbc5e4c6fec231175440a84833257c14c7359f8f967d9203ec361` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `cbd066a0d93e8f97b6a44c7f017d90056b76c9d493a545e434c818ed2d54b7a6` |
| `tests/test_deploy_micro_recorder_script.py` (17 testů) | `58573571c407a5095d5e3ffa72d01724a6474135e6281b8832d9420d8b17a527` |
| `scripts/research/micro_recorder.py` = release kopie (beze změny) | `252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_micro_recorder.py` (10 testů, beze změny) | `750f5c0acded3c599cd3e5c66bfa7e2cdb4f449ae8925e25c25c9d8e8e532f8b` |

## Opravy

- **A, `stop-tick` jen v ověřeném stavu.** Před jakýmkoli zápisem musí platit všechny podmínky:
  - `is-active` = `active`;
  - platný `MainPID`;
  - `/proc/<pid>/cmdline` obsahuje `tick_recorder.py`;
  - `held_tick_db_fd()` najde FD, jehož `readlink` je **přesně**
    `/opt/cryptomaster/local_learning_storage/tick_l1.sqlite (deleted)`.

  Jinak `FAIL` bez `disable` a bez forenzního adresáře. Velikost drženého inode se bere přes
  `stat -L` na nalezeném FD, ne natvrdo na fd 3. Testy: neaktivní služba, cizí proces, opravená
  (nesmazaná) DB, vždy bez volání `disable`.
- **B1, pevné cíle.**
  - Produkce: `UNIT_DIR`, `APP_DIR`, `DATA_DIR`, `PY`, `MEMINFO`, `TICK_LOG`, `FORENSICS_ROOT`,
    `CHECK_WAIT` a `PROC_ROOT` v prostředí znamenají `FAIL`. Povolené jsou jen s
    `MICRO_DEPLOY_TEST_MODE=1`.
  - Preflight ověří, že unit obsahuje přesně
    `ExecStart=/usr/bin/python3 -I /opt/cryptomaster-micro/micro_recorder.py --out /var/lib/cryptomaster-micro`
    a `StateDirectory=cryptomaster-micro`, a že v produkci cíle skriptu odpovídají těmto
    konstantám.
  - Test: odmítnutí přepsání bez testovacího režimu.
- **B2, preflight bez zápisu.** Kontrola syntaxe je `compile()` v paměti s `-I -B`, bez
  `py_compile`. Test porovná seznam souborů release adresáře před a po preflightu.
- **B3, rollback větve a úklid.**
  - `place()` smaže dočasný soubor při selhání `cp`, `chmod`, `chown`, pinu i `mv`.
  - Rollback uklidí `.micro.*` v cílových adresářích.
  - Testy: selhání `systemd-analyze verify`, selhání `enable --now` (služba v napodobenině běží,
    takže jde o částečný úspěch) a selhání `chown`. Ve všech případech `ROLLBACK_OK`, žádné
    nainstalované soubory a žádné `.micro.*`.
- **Mutace:** vypnutá kontrola cmdline, návrat `py_compile` a vypnutá kontrola přepsání zachytí
  vždy aspoň 1 test.

Lokálně: 17 + 10 testů prošlo, `PROTECTED_SAME` a v release adresáři není `__pycache__`.

**Ověř:**
- Jsou A a B uzavřené?
- Platí, že fáze zůstávají oddělené? `stop-tick` se při neúspěchu instalace nevrací.

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
(Git Bash v PATH) a `protected_sha.py` před a po.
