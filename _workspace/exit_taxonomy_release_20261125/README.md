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

## Postup (až po APPROVE re-review)

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
