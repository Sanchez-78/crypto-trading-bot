# Release „exit-taxonomy“ — připnutý čtyřsouborový artefakt dashboardu (2026-11-25)

Jen prezentace (dashboard/API). Obchodní logika, bot, TP/SL, náklady ani REAL se nemění.

## Artefakt

- `preimage/`: skutečné bajty ze serveru (`scp`, jen čtení), 2026-11-25 ~07:05 UTC.
- `postimage/`: preimage + reviewovaný diff (`build_artifact.py`).
  - Nezměněné řádky mají přesné serverové bajty; živé soubory mísí CRLF a LF.
  - `postimage` po normalizaci EOL = lokální pracovní kopie.
- Diffy: `*.py.diff`. Hashe: `MANIFEST.json`.

| Soubor | preimage SHA-256 | postimage SHA-256 |
|---|---|---|
| `src/services/dashboard_web.py` | `df8b5041…e02e` | `2446e0c1…f21e` |
| `src/services/dashboard_read_model.py` | `12c3e91c…680c` | `31ba1f98…7fe5` |
| `src/services/performance_epoch.py` | `b2b19bd9…62bd` | `58c560cc…d2e6` |
| `src/services/exit_taxonomy.py` | nový soubor | `590cd219…e94c` |

Všechny soubory: mód 644, vlastník `root:root` (stejně jako dnes). Dashboard běží
v `/opt/dashboard_venv` (Python 3.12.3) a `/opt/cryptomaster` má jen pro čtení.

## Přesný postup = `deploy_exit_taxonomy.sh` (re-review D1–D3, 2026-11-25)

Nástroje (LF):
- `deploy_exit_taxonomy.sh`: `567d7169e48321a202c6044248a37139be1bf51700eb4ee519a0b534360fba62`
  (verze po re-review D6/D7: journal je čistý jen při statusu `grep` = 1. Instalace jde jen
  z privátního připnutého stage (`pin_stage`). `write_file` ověří hash dočasné kopie proti pinu před
  `mv`, takže živá cesta dostane vždy jen PRE nebo POST bajty. Zápisy jsou v `install_files` a
  `rollback_files`.
  Předchozí verze po D4/D5: fail-closed journal, validovaný PID a HTTP kódy, pevný očekávaný
  profil 200/200, `absent()` odmítá i visící symlink, rollback nejdřív ověří všechny zálohy a stav
  živých cest. Ruční rollback přijme jen přesnou POST sadu, automatický jen kombinace PRE/POST.
  Testy: `tests/test_deploy_exit_taxonomy_script.py`);
- `verify_staging.py`: `bb6185e7b1fdc89879b960b8a181464b0f92def5911ee6b686184c7c7f0f8a10`.

Na serveru jsou nahrané v `/root/exit-taxonomy-20261125/` (+ `postimage/`) a spouští se jako root
odtud.

- **`preflight`** (nic nezapisuje do `/opt/cryptomaster`):
  - postimage = piny;
  - živé tři soubory = preimage piny, mód 644 `root:root`;
  - `exit_taxonomy.py` neexistuje;
  - pak D2 staging:
    1. `rsync` živého `src/` **bez** `__pycache__`, `*.pyc`, `*.pyo`, `*.sqlite*` a `*.db`
       do `stage-XXXXXX`;
    2. přes něj zkopírovat čtyři postimage;
    3. spustit `/opt/dashboard_venv/bin/python3 -I -B -X pycache_prefix=<prázdný adresář>
       verify_staging.py <stage>`.
  - `verify_staging.py`:
    - odmítne bytecode ve stage a neprázdný `pycache_prefix`;
    - před importem ověří SHA-256 a `compile()` přesně připnutých bajtů;
    - po importu ověří, že `__file__` všech čtyř modulů leží ve stage a má připnutý hash;
    - žádný modul `src.*` se nesmí načíst mimo stage;
    - `get_metrics()` jen pro čtení: součet devíti skupin = `total` = n, klíče degradované obálky,
      `get_recent_trades()` s novými poli;
    - **syntetický SELL fixture** → SHORT, záporný pohyb, skupina `tp`;
    - `direction(None)` = UNKNOWN;
    - HTML obsahuje `escapeHtml(exitText)`.
  - Výsledek musí být `STAGING_VERIFIED`, jinak skript skončí bez zápisu.
- **`install`:**
  1. Celý preflight.
  2. Záznam PID bota a profilu přístupu: lokální i veřejné HTTP kódy čtyř endpointů.
  3. Záloha do `/opt/cryptomaster_deploy_backups/exit-taxonomy-<UTC>/`: tři originály (ověřené
     hashe), značka ABSENT, profil a PID.
  4. **Znovu** `check_live_pre` těsně před prvním zápisem (D1). Při neshodě skončí bez zápisu
     a bez rollbacku cizí změny.
  5. Instalace **v pořadí** `exit_taxonomy.py` → `performance_epoch.py` → `dashboard_read_model.py`
     → `dashboard_web.py`. Každý soubor zvlášť: dočasný soubor ve stejném adresáři, `chmod 644`,
     `chown root:root`, `mv -f`.
  6. Kontrola všech čtyř hashů, módů a vlastníků **před restartem**.
  7. Restart jen `cryptomaster-dashboard` a čekání na `is-active` + HTTP 200.
  8. API smoke:
     - součet skupin = total = n;
     - `/api/trades/recent` má `direction`/`exit_label`;
     - `/` obsahuje `escapeHtml(exitText)`.
  9. Journal dashboardu bez `Traceback` od restartu, profil přístupu shodný, **PID bota beze
     změny** (zapsán před i po, D3).
  10. Při jakékoli chybě po prvním zápisu se spustí automatický rollback.
- **`rollback <záloha>`** (automaticky i ručně):
  1. Nejdřív se vrátí tři originály (atomicky), **až potom** se smaže nový modul (D1).
  2. Hashe = preimage a modul neexistuje.
  3. Restart jen dashboardu a pak D3 kontroly:
     - `is-active` a HTTP 200;
     - API smoke (platný JSON);
     - journal bez tracebacku;
     - profil přístupu = profil před instalací;
     - PID bota beze změny.
  4. Výsledek `ROLLBACK_OK`.

**Doložený preflight 2026-11-25 07:21:39 UTC** (jen čtení, `/opt/cryptomaster` beze změny,
`exit_taxonomy.py` stále neexistuje):
- `STAGING_VERIFIED`, Python 3.12.3;
- všechny čtyři moduly ze `stage-*`;
- epocha n = 575: `tp` 109, `sl` 195, `timeout` 105, `trailing_stop` 132, `signal_exit` 34, ostatní
  0, total 575;
- 10 posledních řádků má nová pole, SELL fixture = SHORT;
- `PREFLIGHT_OK bot_pid=3840326`, profil všech čtyř endpointů 200/200 (lokálně i veřejně).

## Původní stručný postup (nahrazen skriptem výše)

1. **Preflight na serveru:**
   - SHA-256 tří živých souborů = preimage;
   - `exit_taxonomy.py` neexistuje;
   - záznam módů a vlastníků.

   Při neshodě **STOP**.
2. **Záloha:** `/opt/cryptomaster_deploy_backups/exit-taxonomy-<UTC>/`, tři originály a
   `ABSENT` značka pro `exit_taxonomy.py`.
3. **Kontrola v dashboardovém prostředí před instalací:**
   - postimage do dočasného adresáře;
   - `/opt/dashboard_venv/bin/python3 -I -B -c` s `py_compile` všech čtyř;
   - import `dashboard_read_model` z kopie stromu s postimage;
   - `get_metrics()` jen pro čtení nad živou cache (`mode=ro`). Ověří se součet skupin = n a
     `direction` u SELL obchodu = SHORT.
4. **Instalace:**
   - každý soubor atomicky: dočasný soubor ve stejném adresáři, `chmod 644`,
     `chown root:root`, `mv`;
   - poté SHA-256 = postimage.
5. **Restart pouze** `systemctl restart cryptomaster-dashboard`. Bot (`cryptomaster.service`)
   se nerestartuje. Načtený `performance_epoch` v botu se nemění; jeho změna je jen agregace pro
   dashboard.
6. **Ověření:**
   - `systemctl is-active cryptomaster-dashboard`;
   - `curl localhost:5001/api/dashboard/metrics`: `exit_distribution.total` = n epochy a součet
     skupin = total;
   - `/api/trades/recent` obsahuje `direction`/`exit_label`;
   - HTML obsahuje `escapeHtml`;
   - journal dashboardu bez tracebacku;
   - `cryptomaster.service` PID beze změny.
7. **Rollback při jakékoli chybě:**
   - vrátit tři originály ze zálohy a smazat `exit_taxonomy.py`;
   - `systemctl restart cryptomaster-dashboard`;
   - ověřit preimage hashe.
