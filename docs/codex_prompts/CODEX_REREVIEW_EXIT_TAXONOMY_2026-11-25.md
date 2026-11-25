# Re-review: taxonomie exitů po nálezech 1–4 + připnutý artefakt (Codex, 2026-11-25)

Jen audit. Report napiš česky do `_workspace/2026-11-25_codex_rereview_exit_taxonomy.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro nasazení čtyřsouborového artefaktu
`_workspace/exit_taxonomy_release_20261125/` podle jeho `README.md`.

Navazuje na `_workspace/2026-11-24_codex_review_exit_taxonomy_and_threshold.md`. B je zapsané v
`docs/OPERATING_STATE.md` (commit `9509630`, 07:09 UTC, před T0 09:00 UTC): práh −25 bps zůstává
a analytické okno je pevné.

## Opravy

1. **Neznámý směr ≠ LONG.**
   - `exit_taxonomy.direction()` převádí jen explicitní BUY/LONG a SELL/SHORT; jinak vrací
     `UNKNOWN` / „Směr nezjištěn“.
   - `describe_trade()` dostává **uložený** side (`None` u legacy řádků), ne výchozí hodnotu.
   - **Odchylka od tvého návrhu:** pole `side` zůstává u legacy řádků `"BUY"`. Je to zdokumentovaný
     kontrakt (`tests/test_dashboard_contract_fixes.py:273` „unknown -> documented default“,
     `:299`, `tests/test_dashboard_read_model.py:83`) a Android ho čte i jinde. Směr se ale
     vysvětluje jen z `direction`:
     - web: `dir = t.direction || 'UNKNOWN'`, „?“ s tooltipem „Směr nezjištěn“;
     - aplikace: `tradeDirection()` dá přednost serverovému `direction`; u starého serveru bere jen
       explicitní BUY/SELL, jinak UNKNOWN;
     - karta ukáže „Smer nezjisten“.
   - Pokud trváš na změně `side`, napiš to; jde o změnu kontraktu.
2. **Degradovaná epocha:** výchozí `summary` má `exit_distribution = empty_distribution()` a
   `exit_distribution_by_reason = {}`. Test vyvolá výjimku v `epoch_metrics` a ověří tvar.
3. **Záložní seznam z rolling okna:** obě funkce (`dashboard_read_model` i `dashboard_web`) dávají
   všech pět polí. `price_move_pct = null`, důvod je „Neznámý“ a směr je UNKNOWN bez uloženého side.
4. **Ceny:** `price_move_pct()` vrátí `None`, pokud ceny nejsou konečné a kladné nebo pokud výsledek
   není konečný. Test pokrývá NaN, ±Infinity, nulu, záporné hodnoty, poměr 1e-300/1e300 a text;
   `json.dumps(allow_nan=False)` projde.
- **Bezpečnost:**
  - `escapeHtml()` v `updateTradesTable` pro symbol, čas, tooltip směru, `exit_reason` (atribut)
    i text exitu;
  - test kontroluje, že tato pole jdou do `innerHTML` jen přes `escapeHtml`;
  - graf (Chart.js canvas) HTML nevkládá.

## Testy a mutace

- `tests/test_exit_taxonomy.py`: 22 testů.
- `PYTHONUTF8=1`, sada dashboard + epoch + android: 341 passed, 9 skipped, `PROTECTED_SAME`.
- Pět mutací (směr zpět na LONG, `{}` v degradované epoše, ceny bez `isfinite`, `exitText` bez
  escape, rolling bez nových polí): každá zachycena. Mutace se dělaly in-place s obnovou a SHA
  kontrolou, `RESTORED_ALL`.
- Aplikace:
  - kontrola čistých funkcí v Node: 9/9 (server UNKNOWN má přednost před BUY, chybějící nebo
    neznámý side, null a nulová cena, všechny skupiny, starý server);
  - `run-metrics-consistency-tests.cjs`: 22 passed;
  - release APK BUILD SUCCESSFUL 2026-11-25 07:10 UTC, `CryptoMaster.apk` sha256 `affcd7dd…2dd5f`,
    bundle obsahuje „Smer nezjisten“.

## Artefakt

- `preimage/` jsou serverové bajty (jen čtení `scp`).
- `postimage/` = preimage + diff; nezměněné řádky mají serverové bajty, protože živé soubory mísí
  CRLF a LF.
- Diffy `*.py.diff` obsahují jen výše uvedené změny.
- `MANIFEST.json`: pre/post SHA-256, mód 644, `root:root`.
- Postup: preflight hashů, záloha, `py_compile` a import v `/opt/dashboard_venv` (3.12.3), atomická
  instalace, restart **jen** `cryptomaster-dashboard`, ověření, rollback.

**Ověřit:**
- Jsou 1–4 a escape uzavřené?
- Je odchylka u `side` přijatelná?
- Odpovídá postimage přesně preimage + diff (`build_artifact.py`)?
- Je postup nasazení a rollbacku úplný?

Bez SSH, nasazení a commitu. Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_exit_taxonomy.py tests/test_dashboard_read_model.py tests/test_performance_epoch.py tests/test_dashboard_contract_fixes.py`
s `protected_sha.py` před a po.
