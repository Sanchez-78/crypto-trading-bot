# Sběrač order booku a likvidací pro výzkum: návrh a limity (Claude, 2026-11-26, rev. 5)

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

Rev. 5 zapracovává `_workspace/2026-11-26_codex_rereview_micro_recorder_r4.md`:
- Codex schválil A (`stop-tick`). **Fáze A proběhla 2026-11-26 10:47:09 UTC**, rc 0, `TICK_STOPPED`:
  - služba je `inactive` a `disabled`;
  - uvolněno 1,24 GB disku (`free_kb` 14 940 156 → 16 181 436) a ~50 MB RAM;
  - PID bota 3840326 se nezměnil;
  - forenzní záznam je v `/root/tick-recorder-forensics-20261126T104709Z/` (gzip archiv 826 937 B, `gzip -t` OK);
  - log zůstal v `/tmp/tick_recorder.log`. Mezi hashem a zastavením proces zapsal ještě 1 řádek (gzip ohlásil `file size changed`). Konečná velikost 282 469 161 B a SHA-256 `f920ad60…` jsou doplněné jako dodatek do `state.txt`; archiv obsahuje už konečnou verzi.
- B: automatický rollback (po neúspěšné instalaci) maže a vypíná **jen cíle, které tento běh sám vytvořil**:
  - `CREATED` se plní po úspěšném `ln`;
  - `APP_DIR` se maže, jen když ho běh vytvořil;
  - unit se vypíná a kontroluje, jen když ho běh vytvořil.
- Ruční `rollback` (samostatné spuštění po úspěšné instalaci) dál maže podle pinu.
- Nové testy:
  - cizí cíl se **stejnými připnutými bajty** vzniklý po preflightu automatický rollback nechá a nevypne ho;
  - ruční rollback po úspěšné instalaci odstraní připnuté soubory.
- Mutace „automatický rollback jako ruční“ zachytí 1 test.
- Celkem 23 testů skriptu (22 prošlo, 1 přeskočen na Windows) a 10 testů sběrače.

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

Testy skriptu: `tests/test_deploy_micro_recorder_script.py` (23 testů, bash s nahrazenými
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

---

## Rev. 6 (2026-11-27): likvidace se nesbíraly, oprava adres streamů

**Nález při verify 24 h** (2026-11-27 11:13 UTC, `docs/OPERATING_STATE.md`): `VERIFY_OK`, order book 1 řádek
za sekundu na symbol, ale za 24 h **0 souborů `liq_sampled`**.

**Příčina** (sonda ze serveru, 2026-11-27 ~11:15 UTC, jen čtení veřejných streamů):

| Adresa | `forceOrder` | `depth20@500ms` |
|---|---|---|
| `wss://fstream.binance.com/stream` (dosavadní) | **0 zpráv / 120 s** (`!forceOrder@arr` i BTC/ETH) | 40 / 20 s |
| `wss://fstream.binance.com/public/stream` | – | 40 / 20 s, stejný formát `{"stream","data"}` |
| `wss://fstream.binance.com/market/stream` | 20 / 120 s napříč trhem | 0 |

Binance rozdělil USD-M WebSocket adresy. Na staré adrese už `forceOrder` nechodí.

**Oprava** (`scripts/research/micro_recorder.py`, SHA-256 `b09b31b1…d466`, release kopie identická):
- **Dvě spojení:**
  - `public` = `/public/stream` s `<sym>@depth20@500ms`;
  - `market` = `/market/stream` s `<sym>@forceOrder`.
- **Dispatch, výpočty, limity, výstupy a unit beze změny.**
- **`connection_loop()`** (testovatelná, s injektovaným `run_once`, hodinami a `sleep`):
  - `connect` / `disconnect` mají v `detail` jméno spojení;
  - backoff 1–60 s pro každé spojení zvlášť.
- **Spadlé vlákno spojení** (neočekávaná výjimka) ukončí proces (`os._exit(4)`), takže restartuje systemd.
  Nikdy nezůstane tiše jen polovina sběrače.
- **Každou hodinu** jeden řádek logu s počtem zpráv na spojení (diagnostika ticha). Dosud se o tichém
  streamu nedalo zjistit nic.
- **Deploy skript:** změněný jen pin `SCRIPT_SHA` (`e69e0464…e4a4`). Unit `35b35cc0…` beze změny.
- **Testy:**
  - `tests/test_micro_recorder.py`: 11 testů, nové jsou URL obou spojení a `connection_loop` (značky podle
    spojení, počty, backoff 2/4/8);
  - `tests/test_deploy_micro_recorder_script.py`: 23 testů beze změny, 1 přeskočen na Windows.
  - Lokálně 33 testů prošlo, 1 přeskočen, `PROTECTED_SAME`.
- **Živý smoke test na serveru** (2026-11-27, ~130 s, výstup do `mktemp -d /tmp/micro-smoke-*`, poté smazán;
  produkční služba nedotčena, PID bota 3840326):
  - book 833 řádků (119 na symbol);
  - **`liq_sampled` 4** (BTC/ETH);
  - gaps `start`, `connect public`, `connect market`.

**Postup upgradu** (žádná nová logika v deploy skriptu, jen dvě už schválené fáze):
1. Nový adresář `/root/micro-recorder-20261127/` s rev. 6: `micro_recorder.py`, unit a deploy skript s novým
   pinem. Ověřit 3 hashe a spustit `preflight`.
   - Očekávané selhání: unit a aplikace ještě existují (`already exists`). Preflight se proto spustí až po
     kroku 2.
2. Starý adresář `/root/micro-recorder-20261126/`: `bash deploy_micro_recorder.sh rollback` (ruční; pin
   `252dd1f7…` odpovídá nainstalovanému souboru) → `ROLLBACK_OK`. Data v `/var/lib/cryptomaster-micro`
   zůstávají.
3. Nový adresář: `preflight` → `install`.
   - 120 s kontroly, automatický rollback jen vlastních souborů při selhání.
   - Nový `start` marker uzavře díru po kroku 2, která trvá jednotky sekund.
4. **`verify`** po 10 min, navíc `liq_sampled` existuje a v gaps je `connect public` a `connect market`.
   Po 24 h znovu.
5. **Návrat při problému:**
   - nový adresář `rollback`;
   - starý adresář `install`, který obnoví rev. 5 (soubory tam zůstaly, pin sedí).

**Riziko:** Binance může později přesunout i `depth20` ze staré adresy. Proto rev. 6 už používá `/public`.

## Rev. 7 (2026-11-27): upgrade zastaven v preflightu, oprava kontroly datového adresáře

**Průběh upgradu** (po Codex APPROVE_TO_DEPLOY R6, `_workspace/2026-11-27_codex_review_micro_recorder_r6.md`):
1. Nový adresář `/root/micro-recorder-20261127/` nahrán, 3 hashe sedí (`b09b31b1…`, `e69e0464…`, `35b35cc0…`).
2. 13:39:08 UTC, starý adresář `rollback` → `ROLLBACK_OK`, data zůstala.
3. Nový adresář `preflight` → **FAIL: `target path /var/lib/cryptomaster-micro contains a symlink`**.
   `install` se nespustil. Sběrač od té doby stojí. Bot má PID 3840326 beze změny.

**Příčina:** `DynamicUser=yes` + `StateDirectory=cryptomaster-micro`. Systemd při prvním startu uložil data do
`/var/lib/private/cryptomaster-micro` (root:root 0700 pro `private`) a vytvořil odkaz
`/var/lib/cryptomaster-micro -> private/cryptomaster-micro`. `check_target_dirs()` vyžaduje u `DATA` cestu bez
symlinku. To platí jen před první instalací. Skript rev. 5 má stejnou kontrolu, proto nefunguje ani návrat
na rev. 5. Návrh upgradu i review R6 to přehlédly.

**Oprava** (jen `deploy_micro_recorder.sh`, sha `a00b12669a9cd3919fb5445c1ff83604d887600057c85f624d46f754eb33b3b6`):
- nová funkce `data_dir_ok()`. `DATA` je buď bez symlinku (jako dosud), nebo **přesně** odkaz systemd:
  - rodič `DATA` je bez symlinku;
  - `DATA` je symlink a `readlink` = `private/<basename>`;
  - `<rodič>/private` je skutečný adresář (ne symlink), vlastník root (v test režimu aktuální uid), režim 700;
  - `<rodič>/private/<basename>` je skutečný adresář.
- `APP_DIR` a adresář unity mají dál přísnou kontrolu bez symlinku. Ostatní logika beze změny.
- `install` do existujícího datového adresáře nic nezapisuje: data vlastní služba, deploy skript `DATA` jen
  kontroluje.

**Testy** (`tests/test_deploy_micro_recorder_script.py`, sha `0b70fced…5d12`, +7 testů):
- přijetí přesného odkazu;
- odmítnutí: jiný cíl odkazu, `private` 0755, `private` jako symlink, vnitřní adresář jako symlink, rodič
  jako symlink;
- upgrade `install` nad zachovanými daty (data nedotčena, odkaz zůstal).
- Windows symlinky nedovolí (7 testů se lokálně přeskočí). Proto běžely na serveru: dočasný adresář
  `/tmp/micro-r7-test-*`, uživatel `nobody`, venv s pytest, systémové příkazy stubované, adresář poté smazán.
  Výsledek: **30 passed**. Lokálně 33 passed, 8 skipped, `PROTECTED_SAME`.
- **Mutace** `data_dir_ok()` na serveru: zabité jsou bez kontroly `readlink`, bez kontroly vlastníka a režimu,
  vnitřní adresář jako symlink a rodič jako symlink. **Přežila** `private` jako symlink. Je ekvivalentní:
  `stat -c '%u %a'` bez `-L` čte samotný odkaz (777), takže symlinkovaný `private` odmítne už kontrola
  režimu. Explicitní `! -L` zůstává kvůli čitelnosti.

**Záložní varianta pro návrat na rev. 5:** `_workspace/micro_recorder_release/rev5_fallback/deploy_micro_recorder.sh`
(sha `5832d085…b4f3`). Je to rev. 7 skript, který se liší jen pinem `SCRIPT_SHA=252dd1f7…`, tedy sběrač rev. 5,
jehož soubor je na serveru v `/root/micro-recorder-20261126/`.

**Postup po schválení:**
1. Do `/root/micro-recorder-20261127/` nahrát rev. 7 `deploy_micro_recorder.sh` místo `e69e0464…` a ověřit 3
   hashe (`b09b31b1…`, `a00b1266…`, `35b35cc0…`).
2. `preflight` → `install` (120 s kontroly, při selhání automatický rollback vlastních souborů).
3. `verify` po 10 min. Navíc ručně `connect public` / `connect market` v gaps. `liq_sampled` je podle R6
   jen informace, ne podmínka.
4. Po 24 h znovu `verify`, `liq_sampled` a hodinové počty zpráv.
5. Návrat: `rollback` v novém adresáři. Pak záložní skript rev. 5: nahrát ho do `/root/micro-recorder-20261126/`
   místo `8f471aca…` → `preflight` → `install`.

## Rev. 8 (2026-11-27): log se vyprazdňuje, read-only `upgrade-check`, `du` přes symlink

**Nasazení rev. 6** (13:51:53 UTC, deploy skript rev. 7): `INSTALL_OK`, verify po 10 min `VERIFY_OK`, 6 likvidací.
Audit výsledku Codexem: **ACCEPT** (`_workspace/2026-11-27_codex_review_micro_recorder_deploy_result.md`).

**Nález z auditu (bod 4):** sběrač loguje přes `print` bez vyprázdnění. Pod systemd je stdout blokově bufferovaný
(8 KiB). Hodinový řádek počtů (~100 B) by se tak v journalu objevil až po ~80 h. Horší je, že `os._exit(3/4)`
buffer nevyprázdní, takže **poslední hláška před ukončením („write failed“, „connection … crashed“) se
ztratí**. Na `journalctl | grep 'write failed'` v `checks()` se proto nedá spolehnout. `PYTHONUNBUFFERED`
v unitě nepomůže, protože `-I` proměnné `PYTHON*` ignoruje.

**Změny:**
- `scripts/research/micro_recorder.py` (sha `fdad490b…21aa`, release kopie identická): nová funkce
  `log_line()` = `print(message, flush=True)`, výchozí `log` třídy `Recorder`. Jinak beze změny.
- `deploy_micro_recorder.sh` (sha `8d403e96…e895`):
  - nový pin `SCRIPT_SHA` a nový `PREV_SCRIPT_SHA=b09b31b1…` (rev. 6, právě nainstalovaná);
  - `preflight` rozdělen na `release_checks` (piny, websocket, kompilace, ExecStart/StateDirectory, cesty
    vč. `data_dir_ok`) a `resource_checks` (disk, paměť, PID bota). Chování `preflight` je stejné;
  - **nová fáze `upgrade-check`** (doporučení R7 a auditu výsledku), jen pro čtení, spouští se, dokud běží
    předchozí revize. Ověří:
    - `release_checks`;
    - nainstalovaná unit je skutečný soubor s pinem `UNIT_SHA`, takže ji rollback předchozího release
      odstraní;
    - nainstalovaný sběrač je skutečný soubor s pinem `PREV_SCRIPT_SHA`;
    - služba je `active`;
    - `resource_checks`, které `preflight` při existující unitě nikdy nedošel ověřit.
  - `verify`: `du -sh "$DATA/"`, tedy přes symlink. Dřív vypisoval `0`.
  - Unit beze změny (`35b35cc0…`).
- Testy:
  - `tests/test_micro_recorder.py` (sha `516f7b44…454`, +1: výchozí log volá `flush`);
  - `tests/test_deploy_micro_recorder_script.py` (sha `831a17fd…1701`, +5: `upgrade-check` projde nad
    předchozí revizí bez jakéhokoli zápisu a volání `enable`/`disable`/`daemon-reload`; odmítne jiný
    nainstalovaný sběrač, jinou unit, neaktivní službu a změněný nový release).
  - Lokálně 39 passed, 8 skipped (symlinky), `PROTECTED_SAME`. Server (dočasný adresář, `nobody`, smazán):
    **47 passed**.
  - Mutace: zabito 5/5 (bez kontroly PREV pinu, bez kontroly pinu unity, bez kontroly `active`, bez
    `release_checks` v `upgrade-check`, log bez `flush`).

**Postup upgradu rev. 6 → rev. 8** (poprvé s `upgrade-check` před odinstalací):
1. Nahrát do `/root/micro-recorder-20261127-r8/` sběrač `fdad490b…`, deploy skript `8d403e96…`, unit
   `35b35cc0…` a ověřit 3 hashe.
2. Nový adresář `upgrade-check` → `UPGRADE_CHECK_OK`. Rev. 6 stále běží. Při selhání konec, nic se neodinstaluje.
3. Starý adresář `/root/micro-recorder-20261127/` (skript rev. 7, pin `b09b31b1…`): `rollback` → `ROLLBACK_OK`.
4. Nový adresář `preflight` → `install`.
5. `verify` po 10 min (gaps `start`/`connect public`/`connect market`, `liq_sampled` jen informace). Po ~65 min
   v journalu řádek `[MICRO] messages in the last hour` s počty `public` i `market`. Verify 24 h podle tabulky
   z auditu výsledku.
6. Návrat: `rollback` v novém adresáři → `install` ve starém (rev. 7 skript s rev. 6 sběračem projde přes
   symlink StateDirectory).

### Rev. 8 po review R8 (Codex CHANGES_REQUIRED, `_workspace/2026-11-27_codex_review_micro_recorder_r8.md`)

**Opravy:**
1. **P1, sada pro návrat se neověřovala.** Nový adresář `FALLBACK` (výchozí `/root/micro-recorder-rev6-fallback`,
   přepsatelný jen v test režimu). Obsahuje sběrač rev. 6, unit a deploy skript rev. 8, který se liší jen
   `SCRIPT_SHA=b09b31b1…` (`rev6_fallback/deploy_micro_recorder.sh`). `upgrade-check` volá `fallback_checks`:
   - sběrač v `FALLBACK` = `PREV_SCRIPT_SHA`;
   - unit = `UNIT_SHA`;
   - deploy skript má právě jeden řádek `SCRIPT_SHA`, a to `PREV_SCRIPT_SHA`;
   - bez řádků `SCRIPT_SHA` je bajtově shodný s tímto skriptem (`cmp`), takže pin se nedá zacyklit.
   - Rev. 6 se pak odinstaluje `rollback` z `FALLBACK` (pin `b09b31b1…`), ne skriptem rev. 7.
2. **P1, journal z dřívějších instalací.** `checks()` čte journal jen od mtime souboru unity
   (`stat -c %Y`), který `install` pokaždé umísťuje nově. Restarty po instalaci se počítají, chyby dřívější
   revize ne. Platí i pro návrat, protože ten jde přes rev. 8 skript s pinem rev. 6.
   - **Mutační test navíc odhalil skutečnou dřívější chybu:** `journalctl | grep -q` pod `set -o pipefail`.
     `grep -q` skončí při první shodě, `journalctl` dostane SIGPIPE a roura vrátí 141. `if` je pak nepravdivé
     a **chyba v journalu se přehlédne**, kdykoli za ní následuje další výstup. To platilo ve všech
     dosavadních revizích. Oprava: výstup se nejdřív uloží (`journal="$(…)"`, při selhání `die`) a teprve pak
     se v něm hledá přes `grep -q <<<`.
   - Regresní test: chyba + 3000 dalších řádků. Se starou formou selže, s novou projde.
3. **P2, `.pyc`.** `import websocket` se spouští s `-I -B`. Test obalí `PY` a ověří, že všechna volání
   Pythonu začínají `-I -B`.
4. **Dashboard už předem:** `upgrade-check` vyžaduje HTTP 200, dokud rev. 6 běží. `preflight` beze změny, aby
   selhání po instalaci dál vedlo k rollbacku.
5. Test „bez zápisu“ porovnává jména i SHA-256 obsahu.

**Soubory:**

| Soubor | SHA-256 |
|---|---|
| `scripts/research/micro_recorder.py` = release kopie (beze změny) | `fdad490b…21aa` |
| `deploy_micro_recorder.sh` | `97180eeb589748b8c4747b7c9c4b79a4a6c0863839156d001c0388f3ca02178f` |
| `rev6_fallback/deploy_micro_recorder.sh` | `0f64e008a7f2eae6c7a8b0916631a18a8249e6326e9b4ce1b9d69f50fa085a5a` |
| `rev5_fallback/deploy_micro_recorder.sh` (přegenerován z rev. 8) | `58025e2597b99b1919d52fd9e75ab37896054df853d7433d39295bdff6d50d27` |
| `tests/test_deploy_micro_recorder_script.py` | `1fb1cccb8d1c999da491dad361ce63794d5078dc01729dd5a13bec33c1eb3470` |
| `tests/test_micro_recorder.py` | `516f7b44…454` |

**Testy:**
- server (dočasný adresář, `nobody`, smazán): **59 passed**;
- lokálně 51 passed / 8 skipped (symlinky), `PROTECTED_SAME`;
- **mutace 14/14 zabity**: PREV pin, pin unity, `active`, celé `fallback_checks`, pin sběrače, unity a
  skriptu ve fallbacku, `cmp`, dashboard předem, journal bez `--since`, roura `grep -q`, import bez `-B`, bez
  `release_checks`, log bez `flush`.

**Postup upgradu rev. 6 → rev. 8 (nahrazuje předchozí):**
1. Nahrát a ověřit hashe:
   - `/root/micro-recorder-20261127-r8/`: `fdad490b…`, `97180eeb…`, `35b35cc0…`;
   - `/root/micro-recorder-rev6-fallback/`: sběrač `b09b31b1…` (kopie z `/root/micro-recorder-20261127/`),
     unit `35b35cc0…`, skript `0f64e008…`.
2. `/root/micro-recorder-20261127-r8`: `upgrade-check` → `UPGRADE_CHECK_OK`. Rev. 6 běží. Při selhání konec.
3. `/root/micro-recorder-rev6-fallback`: `rollback` → `ROLLBACK_OK`.
4. `/root/micro-recorder-20261127-r8`: `preflight` → `install`.
5. `verify` po 10 min. `start` a `connect public`/`connect market` musí být z nového běhu (nový pid) a přírůstek
   knihy po startu. Po ~65 min v journalu `[MICRO] messages in the last hour` (klíč `market` může při nule
   chybět).
6. Návrat: r8 `rollback` → fallback `preflight` + `install`.
