# Re-review sběrače order booku a likvidací, rev. 2 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_micro_recorder_r2.md`.

Verdikt pro dva samostatné kroky:
- **A:** `stop-tick`. APPROVE / CHANGES_REQUIRED.
- **B:** `preflight` + `install`. APPROVE_TO_DEPLOY / CHANGES_REQUIRED.

Navazuje na `_workspace/2026-11-26_codex_review_micro_recorder_design.md`.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` (rev. 2) | `f634f14c3ada32db6edd1f93a64720ca6b0483b59b500edcab0e69e96cc0db36` |
| `scripts/research/micro_recorder.py` (= kopie v release adresáři) | `252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `c5c0a9537342af75d80ec7d3f3829546e147132c03e1bfbc3caef17725abaf87` |
| `tests/test_micro_recorder.py` (10 testů) | `750f5c0acded3c599cd3e5c66bfa7e2cdb4f449ae8925e25c25c9d8e8e532f8b` |
| `tests/test_deploy_micro_recorder_script.py` (9 testů) | `ec296a36419fc492ed6f04958bbe9c7f93a3e111ac7bf2931f5302a5b148d551` |

## Opravy

1. **`forceOrder` je vzorek.**
   - Výstup se jmenuje `liq_sampled/`.
   - Docstring a návrh uvádějí, že Binance posílá nejvýš jednu událost na symbol za 1000 ms (od
     2026-04 tu největší). Jde tedy o neúplný proxy signál, ne o všechny likvidace.
   - `depth20` je popsán jako částečné snímky top 20 úrovní.
2. **Ztráta při nedostatku disku je v datech.**
   - `flush()` drží okno ztráty (`from_ms`, `to_ms` a počty řádků podle druhu) a po obnovení
     zápisu ho zapíše jako jeden řádek `gaps` s `kind=disk_skip`.
   - Značky mezer (`connect`, …) se mezitím neztratí, re-queue je omezené na `MAX_BUFFER`.
   - Bez dat se okno neotevře.
   - Proces při startu zapíše značku `start` (pid), takže díra po chybě zápisu nebo restartu
     končí dohledatelně. Návrh popisuje i případ restartu během nedostatku disku: díra je vidět
     jako chybějící sekundy a v journald.
   - Testy:
     - `test_low_disk_drops_data_but_records_the_loss_window_on_recovery` ověřuje přesné okno a
       počty, přežití značky `connect` a to, že se zahozená data neobnoví;
     - `test_low_disk_without_data_opens_no_loss_window`.
3. **Tick-recorder.**
   - Samostatná fáze `stop-tick`. Nejdřív forenzika do `/root/tick-recorder-forensics-<UTC>/`:
     stav, držený smazaný inode, velikost, SHA-256 a počet chyb logu, prvních 50 a posledních 200
     řádků, gzip kopie. Teprve pak `disable --now`.
   - **Log zůstává na místě.** Jeho smazání není v žádné fázi.
   - Test ověřuje nezměněný log, SHA-256 ve forenzice, archiv a volání `disable`.
4. **`aggTrade`** se nepřidává.
5. **Připnutý fázovaný skript** `deploy_micro_recorder.sh`
   (`stop-tick` | `preflight` | `install` | `verify` | `rollback`):
   - **piny:** obou release souborů;
   - **instalace:** temp kopie, ověření pinu, `mv`;
   - **rollback:** trap EXIT po prvním zápisu provede rollback při jakémkoli nenulovém exitu.
     Smaže jen soubory s pinem, cizí soubor nechá.
   - **kontroly:** `is-active`, `MemoryCurrent` < 128 MiB, journal bez chyb, soubor `gaps`, PID
     bota beze změny, dashboard 200.
   - **testy:** bash s nahrazenými příkazy. Mutace „rollback vypnutý“ zachytí 4 testy.

Lokálně: 10 + 9 testů prošlo a `PROTECTED_SAME`.

## Ověř

- Jsou nálezy 1–3 uzavřené?
- Je skript fail-closed? Zaměř se na:
  - pořadí fází;
  - trap a rollback;
  - kontrolu pinů na cíli;
  - chování, když `systemd-analyze verify` nebo `enable` selže.
- Lze nejdřív spustit A (`stop-tick`) a pak B?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
(s Git Bash v PATH) a `protected_sha.py` před a po.
