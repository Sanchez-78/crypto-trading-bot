# Re-review nasazovacího kroku „exit-taxonomy“ po D1–D3 (Codex, 2026-11-25)

Jen audit. Report napiš česky do `_workspace/2026-11-25_codex_rereview_exit_taxonomy_deploy_step.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro spuštění `deploy_exit_taxonomy.sh install` na serveru.

Navazuje na `_workspace/2026-11-25_codex_rereview_exit_taxonomy.md`. Tam je kód i postimage schválený;
zbývaly mezery D1–D3 v postupu. Postimage ani kód se od té doby **nezměnily** (MANIFEST beze změny).

## Nové soubory v `_workspace/exit_taxonomy_release_20261125/`

- `deploy_exit_taxonomy.sh` (`9ef226d0…f0c4`), režimy `preflight` / `install` / `rollback <záloha>`.
- `verify_staging.py` (`bb6185e7…8a10`).
- `README.md`, sekce „Přesný postup“.

## Jak jsou řešené D1–D3

- **D1:**
  - pole `ORDER` instaluje `exit_taxonomy.py` jako první, pak `performance_epoch`, `read_model`
    a `web`;
  - rollback (`EXISTING`) nejdřív atomicky vrátí tři originály, až potom smaže nový modul;
  - `check_live_pre` (preimage hashe, mód/vlastník a absence modulu) běží v preflightu a **znovu
    těsně před prvním zápisem**; při neshodě skončí bez zápisu a bez rollbacku.
- **D2** (`stage_and_verify` + `verify_staging.py`):
  - `rsync` živého `src/` bez `__pycache__`, `.pyc`, `.pyo`, `sqlite` a `db`, překryv čtyř
    postimage;
  - interpret dashboardu s `-I -B -X pycache_prefix=<prázdný>`, cwd = stage;
  - skript odmítne bytecode ve stage, neprázdný prefix a chybějící `-I`/`-B`;
  - hash a `compile()` připnutých bajtů **před** importem;
  - **po** importu `__file__` ve stage, hash zdroje = pin a žádný `src.*` modul mimo stage;
  - `get_metrics()`/`get_recent_trades()` jen pro čtení, syntetický SELL fixture a `escapeHtml`
    v HTML;
  - po instalaci, ještě před restartem, se znovu kontrolují hashe, módy a vlastníci všech čtyř
    souborů.
- **D3:**
  - rollback ověřuje `is-active` + HTTP 200, API smoke (platný JSON), journal bez tracebacku a
    profil přístupu (lokální i veřejné kódy čtyř endpointů = stav před instalací);
  - PID bota se zapisuje před a po instalaci i rollbacku; změna PID je chyba;
  - restart dashboardu se nepočítá jako důkaz o botu.

## Doložený běh `preflight` na serveru (2026-11-25 07:21:39 UTC)

- Jen čtení: `/opt/cryptomaster` beze změny a `exit_taxonomy.py` stále neexistuje.
- Release nahraný do `/root/exit-taxonomy-20261125/`; hashe postimage na serveru odpovídají pinům.
- `STAGING_VERIFIED`, Python 3.12.3; moduly načtené z `/root/exit-taxonomy-20261125/stage-m8ZkgX/...`
  (stage po běhu smazána).
- Živá epocha n = 575, rozpad exitů:

  | Skupina | Počet |
  |---|---:|
  | tp | 109 |
  | sl | 195 |
  | timeout | 105 |
  | trailing_stop | 132 |
  | signal_exit | 34 |
  | scratch, stagnation, risk_exit, other | 0 |
  | **total** | **575** |

- SELL fixture = SHORT. `PREFLIGHT_OK bot_pid=3840326`.
- Profil všech čtyř endpointů 200/200 (lokálně i veřejně).

**Ověřit:**
- Jsou D1–D3 uzavřené?
- Je skript správný: pořadí, atomické zápisy, `set -uo pipefail` a návratové kódy, automatický
  rollback po prvním zápisu, žádný restart bota?
- Jde `install` spustit?

Bez SSH, nasazení a commitu. `bash -n` a čtení skriptu stačí; testy podle předchozího zadání.
