# Sběrač order booku a likvidací pro výzkum: návrh a limity (Claude, 2026-11-26, rev. 4)

Rev. 2 zapracovává review `_workspace/2026-11-26_codex_review_micro_recorder_design.md`:
- likvidace jsou jen vzorek, výstup se jmenuje `liq_sampled`;
- ztráta dat při nedostatku disku se zapíše do `gaps`;
- vypnutí tick-recorderu je samostatná fáze a log se nemaže;
- `aggTrade` se nepřidává;
- přidán připnutý fázovaný nasazovací skript.

Rev. 3 zapracovává re-review `_workspace/2026-11-26_codex_rereview_micro_recorder_r2.md`:
- `stop-tick` vypne službu jen v přesně ověřeném rozbitém stavu: unit `active`, platný MainPID, cmdline obsahuje `tick_recorder.py` a některý FD odkazuje přesně na `…/tick_l1.sqlite (deleted)`. Jinak skončí `FAIL` bez `disable` a bez forenziky.
- Cesty a interpret jsou v produkci pevné. Proměnné `UNIT_DIR`, `APP_DIR`, `DATA_DIR`, `PY`, `MEMINFO`, `TICK_LOG`, `FORENSICS_ROOT`, `CHECK_WAIT` a `PROC_ROOT` se přijmou jen s `MICRO_DEPLOY_TEST_MODE=1`, jinak `FAIL`. Preflight navíc ověří, že unit má přesně `ExecStart=/usr/bin/python3 -I /opt/cryptomaster-micro/micro_recorder.py --out /var/lib/cryptomaster-micro` a `StateDirectory=cryptomaster-micro`.
- Preflight nic nezapisuje: kontrola syntaxe přes `compile()` v paměti s `-B`, bez `py_compile` a `__pycache__`.
- `place()` při chybě `cp`, `chmod`, `chown`, pinu nebo `mv` smaže dočasný soubor. Rollback navíc uklidí `.micro.*` v cílových adresářích.
- Nové testy:
  - `stop-tick` odmítne neaktivní službu, cizí proces a opravenou (nesmazanou) DB;
  - produkční režim odmítne přepsání cest;
  - preflight nic nezapíše;
  - rollback a úklid při selhání `systemd-analyze verify`, `enable --now` (služba běží, enable selže) a `chown`.
- Celkem 17 testů skriptu. Mutace (vypnutá kontrola cmdline, návrat `py_compile`, vypnutá kontrola přepsání) zachytí vždy aspoň 1 test.

Rev. 4 zapracovává `_workspace/2026-11-26_codex_rereview_micro_recorder_r3.md`:
- `stop-tick` **těsně před `disable`** znovu volá `verify_tick_state()`. Musí sedět stejný PID, cmdline a FD na přesný smazaný inode, jinak `FAIL` bez vypnutí.
- Rollback maže jen dočasné soubory vytvořené tímto během (pole `TEMPS`), cizí `.micro.*` nechá.
- `check_target_dirs` (v preflightu i po `mkdir` v instalaci) odmítne cílové cesty se symlinkem (`realpath -m` ≠ `realpath -m -s`). V produkci navíc kanonické cesty musí být `/opt/cryptomaster-micro` a `/etc/systemd/system`.
- Umístění souboru je bez přepsání: hard link `ln tmp dst` selže, když cíl mezitím vznikl. Pak se nic nepřepíše a proběhne rollback, který cizí cíl nechá (není připnutý).
- Nové testy: změna PID během forenziky, cizí `.micro.*` přežije rollback, cíl vzniklý po preflightu se nepřepíše.
- Test se symlinkem se na Windows přeskočí. Logika `realpath` i odmítnutí `ln` nad existujícím cílem jsou ověřené na Linuxu serveru v dočasném `/tmp` adresáři (hned smazán): symlink `HAS_SYMLINK`, čistá cesta `clean`, `ln refused existing dst`.
- Mutace (bez opakovaného ověření, úklid globem, `mv -f`) zachytí každá 1 test.
- Celkem 21 testů skriptu (20 prošlo, 1 přeskočen na Windows) a 10 testů sběrače.

Krok 2 z doporučení C (Codex `_workspace/2026-11-26_codex_review_event_screen_result.md` a následná
zpráva):
- **Krok 1:** měřicí okno doběhne do 2026-12-02 09:00 UTC beze změny.
- **Krok 2:** samostatně připravit sběr nové informační třídy. Nasadit až po schválení.

Sběrač **neobchoduje** a neimportuje kód bota. Nečte `.env`, Firebase ani runtime DB. Nic
neposílá ven, jen přijímá veřejný stream Binance.

Data samotná zisk neprokazují. Využijí se až v samostatném, předem zapsaném screeningu po nasbírání
(cíl ≥ 6 týdnů).

## Nález: stávající `tick-recorder.service` je od 10. 7. 2026 nefunkční

Zjištěno jen čtením, 2026-11-26:

- **Stav služby:** `active` od 2026-07-09, 0 restartů, RSS 115 MB, 120 otevřených FD (eventpoll
  roste). Skript `/opt/cryptomaster/tick_recorder.py` na disku už neexistuje, proces běží ze
  staré kopie v paměti.
- **Smazaná DB:** cílová `/opt/cryptomaster/local_learning_storage/tick_l1.sqlite` je smazaná, ale
  proces ji drží otevřenou (`fd 3 → … (deleted)`). Zabírá tak 1 271 099 392 B disku (mtime
  2026-07-10 06:39). Každý flush končí chybou `attempt to write a readonly database`.
- **Log:** `/tmp/tick_recorder.log` má 282 MB a 6 007 506 těchto chyb.
- **Důsledek:** L1 data pro maker-fill výzkum se 4,5 měsíce nesbírají.
- **Návrh v rámci nasazení:**
  1. `systemctl disable --now tick-recorder.service`. Uvolní se 115 MB RAM a 1,27 GB disku (smazaný
     inode) a zastaví se růst logu.
  2. Smazat `/tmp/tick_recorder.log`.
  3. Unit soubor ponechat kvůli dohledatelnosti.

  Nový sběrač bude mít i L1 (bid1/ask1/qty každou sekundu), takže starý nenahrazovat opravou.

## Co se sbírá

Jedno kombinované websocket spojení na `wss://fstream.binance.com/stream`. Symboly: BTC, ETH, SOL,
ADA, BNB, DOT, XRP (USDT perp).

| stream | výstup | řádek |
|---|---|---|
| `<sym>@depth20@500ms` | `book/YYYY-MM-DD.csv.gz` | 1 na symbol a sekundu (poslední snímek dané sekundy) |
| `<sym>@forceOrder` | `liq_sampled/YYYY-MM-DD.csv.gz` | 1 na **přijatou** událost. Binance posílá nejvýš 1 událost na symbol za 1000 ms (od 2026-04 tu největší v intervalu), takže **nejde o všechny likvidace**, jen o vzorkovaný proxy signál. |
| — | `gaps/YYYY-MM-DD.csv.gz` | `start` (pid), `connect`, `disconnect`, `dropped_rows`, `disk_skip`. Výzkum vyloučí sekundy v mezerách. |

**Pole order booku:**
- `ts_s`, `event_ms`, `updates` (počet snímků v sekundě);
- `bid1`, `ask1`, `spread_bps`, `bid1_qty`, `ask1_qty`;
- notional na každé straně do 5/10/25 bps od mid, notional celých 20 úrovní;
- `bid_range_bps` a `ask_range_bps` (kam 20 úrovní sahá, tedy pokrytí pásem);
- `imbalance_10bps`.

Jde o částečné snímky top 20 úrovní (`depth20`), ne o rekonstruovanou úplnou knihu. Prázdná nebo překřížená kniha se nezapíše. Neplatná čísla se zahodí.

**Evidence výpadků:**
- Chyba zápisu vede na exit 3 a restart. Díra v datech pak končí řádkem `start`, další stopa je v journald.
- Při restartu během nedostatku disku se okno ztráty v paměti ztratí. Díra je ale vidět jako chybějící sekundy mezi posledním řádkem a `start` a v journald (rate-limited hláška).
- Neúplný poslední gzip člen po pádu musí čtečka tolerovat (číst po členech a zachytit `EOFError`).

**Pole likvidací:** čas, symbol, strana, typ, stav, cena, průměrná cena, množství, plněno,
notional.

## Limity (fail-closed)

| limit | hodnota | kde |
|---|---|---|
| paměť | `MemoryHigh=96M`, `MemoryMax=128M`, `MemorySwapMax=0` | systemd unit |
| CPU | `CPUQuota=20%`, `Nice=10`, `IOSchedulingClass=idle`, `TasksMax=16` | unit |
| buffer | max 50 000 řádků na druh mezi flushi. Nadbytek se zahodí a zapíše jako `dropped_rows`. | `MAX_BUFFER` |
| zápis | flush 1× za 60 s (jeden gzip člen + `fsync`). Chyba zápisu → exit 3 → systemd restart (max 10 za 10 min). | `FLUSH_SECONDS`, `run()` |
| disk | při volném místě < 5 GiB se **datové** řádky nezapisují. Ztráta se drží jako okno (`from_ms`, `to_ms`, počty řádků podle druhu). Po obnovení zápisu jde do `gaps` jeden řádek `disk_skip`. Značky mezer se mezitím drží v bufferu (strop 50 000) a zapíšou se. Log max 1× za 5 min. | `MIN_FREE_BYTES`, `flush()` |
| retence | soubory > 120 dní a nad 4 GiB celkem se mažou od nejstarších (nikdy dnešní). Kontrola 1× za hodinu. | `prune()` |
| logy | jen journald, rate-limit (aplikace 1 řádek za 5 min na druh chyby, journald 20 za 60 s). Žádný `/tmp` log. | unit, `_rate_log` |
| izolace | `DynamicUser`, `StateDirectory=cryptomaster-micro`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, `RestrictAddressFamilies` | unit |

**Změřeno lokálně** (2026-11-26, 185 s proti živému Binance streamu, jen na PC):
- 1 900 zpráv, 1 011 řádků order booku;
- **≈ 26 MB za den** (gzip, při flush 30 s);
- likvidace 0 (ve 3 min běžné);
- špička Python heapu 1,2 MB.

Odhad na serveru:
- **disk** ~0,8 GB za 30 dní, limit 4 GiB vydrží ~150 dní (retence 120 dní platí dřív);
- **RAM** proces ~30–50 MB (interpret + websocket-client), strop 128 MB;
- **CPU:** ~10 zpráv za s, JSON a pár součtů.

Server má dnes `available` ~2,2 GB a 15 GB volného disku. Po vypnutí tick-recorderu přibude
~115 MB RAM a 1,27 GB disku.

## Kód a testy

- Kód: `scripts/research/micro_recorder.py`. Na serveru jako `/opt/cryptomaster-micro/micro_recorder.py`,
  mimo strom bota.
- Závislosti: stdlib a `websocket-client` 1.9.0, který je už v systémovém `/usr/bin/python3`
  (ověřeno čtením).
- Testy: `tests/test_micro_recorder.py` (10 testů), bez sítě:
  - výpočet pásem, nerovnováhy a pokrytí;
  - parsování likvidací;
  - 1 řádek za sekundu s posledním snímkem a počtem aktualizací;
  - neuzavření běžící sekundy;
  - jedna hlavička přes víc gzip členů;
  - strop bufferu a záznam do `gaps`;
  - disková pojistka: okno ztráty `disk_skip` zapsané po obnovení, značky mezer přežijí,
    zahozená data se neobnoví, rate-limit logu;
  - bez dat se okno ztráty neotevře;
  - retence podle stáří a velikosti, nikdy dnešní soubor;
  - směrování streamů.
- Unit: `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service`.

## Postup nasazení (až po APPROVE): `_workspace/micro_recorder_release/deploy_micro_recorder.sh`

Skript má připnuté hashe `micro_recorder.py` a unitu. Fáze se spouštějí odděleně a každá končí
značkou OK nebo `FAIL`.

1. **`stop-tick`** (samostatná fáze, nezávislá na instalaci):
   - forenzní záznam do `/root/tick-recorder-forensics-<UTC>/` (`umask 077`):
     - stav služby a držený smazaný inode;
     - velikost, SHA-256 a počet chyb logu;
     - prvních 50 a posledních 200 řádků;
     - gzip kopie logu;
   - `systemctl disable --now tick-recorder.service`;
   - kontroly: neaktivní, PID bota beze změny, volné místo před a po, **log zůstává na místě**;
   - smazání logu není součástí žádné fáze.
2. **`preflight`** (jen čtení):
   - piny release souborů;
   - `python3 -I -c "import websocket"` a `py_compile`;
   - cílový unit i skript ještě neexistují;
   - volný disk ≥ 6 GiB a `MemAvailable` ≥ 1 GiB;
   - platný PID bota.
3. **`install`:** preflight a poté:
   - cílová cesta dostane jen připnuté bajty (dočasná kopie, ověření pinu, `chmod`, `chown`, `mv`);
   - `daemon-reload`, `systemd-analyze verify`, `enable --now`;
   - po 120 s kontroly:
     - `is-active`;
     - `MemoryCurrent` < 128 MiB;
     - journal bez `Traceback` a `write failed`;
     - existuje soubor `gaps`;
     - PID bota beze změny;
     - dashboard 200.
   - **Každý nenulový exit po prvním zápisu** spustí automatický rollback (trap EXIT).
4. **`verify`** (po 10 min a po 24 h): kontroly z bodu 3, čitelné řádky `book` a `gaps`, `du`.
5. **`rollback`:**
   - `disable --now`;
   - smaže **jen soubory s připnutým hashem** (cizí soubor nechá a vypíše varování);
   - `daemon-reload`;
   - data ve `/var/lib/cryptomaster-micro` zůstávají;
   - tick-recorder se neobnovuje, protože byl nefunkční.

Testy skriptu: `tests/test_deploy_micro_recorder_script.py` (21 testů, bash s nahrazenými
`systemctl`, `curl`, `df`, `journalctl`):
- piny odpovídají release souborům;
- preflight odmítne změněný skript;
- úspěšná instalace;
- rollback při 4 typech selhání kontrol (neaktivní, paměť, journal, HTTP);
- rollback nechá cizí unit;
- `stop-tick` archivuje forenziku a log nechá beze změny.

Mutace „rollback vypnutý“ zachytí 4 testy. Testy sběrače: `tests/test_micro_recorder.py` (10 testů,
včetně okna ztráty při nedostatku disku).

Bot (`cryptomaster.service`) se nerestartuje a jeho nastavení se nemění. Měřicí okno to
neovlivní: jiný proces, nízká priorita, žádné sdílené soubory.

## Otázky na review

1. Jsou limity a izolace dostatečné pro 4GB produkci?
2. Je fáze `stop-tick` (forenzika, vypnutí, log zůstává) přijatelná jako samostatný krok?
3. `aggTrade` se podle review nepřidává. Případně až samostatně po změření provozu.
