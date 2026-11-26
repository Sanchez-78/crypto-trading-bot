# Sběrač order booku a likvidací pro výzkum: návrh a limity (Claude, 2026-11-26)

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
| `<sym>@forceOrder` | `liq/YYYY-MM-DD.csv.gz` | 1 na likvidaci |
| — | `gaps/YYYY-MM-DD.csv.gz` | connect, disconnect, `dropped_rows` (výzkum vyloučí sekundy v mezerách) |

**Pole order booku:**
- `ts_s`, `event_ms`, `updates` (počet snímků v sekundě);
- `bid1`, `ask1`, `spread_bps`, `bid1_qty`, `ask1_qty`;
- notional na každé straně do 5/10/25 bps od mid, notional celých 20 úrovní;
- `bid_range_bps` a `ask_range_bps` (kam 20 úrovní sahá, tedy pokrytí pásem);
- `imbalance_10bps`.

Prázdná nebo překřížená kniha se nezapíše. Neplatná čísla se zahodí.

**Pole likvidací:** čas, symbol, strana, typ, stav, cena, průměrná cena, množství, plněno,
notional.

## Limity (fail-closed)

| limit | hodnota | kde |
|---|---|---|
| paměť | `MemoryHigh=96M`, `MemoryMax=128M`, `MemorySwapMax=0` | systemd unit |
| CPU | `CPUQuota=20%`, `Nice=10`, `IOSchedulingClass=idle`, `TasksMax=16` | unit |
| buffer | max 50 000 řádků na druh mezi flushi. Nadbytek se zahodí a zapíše jako `dropped_rows`. | `MAX_BUFFER` |
| zápis | flush 1× za 60 s (jeden gzip člen + `fsync`). Chyba zápisu → exit 3 → systemd restart (max 10 za 10 min). | `FLUSH_SECONDS`, `run()` |
| disk | při volném místě < 5 GiB se nezapisuje (počítá se `skipped_disk`, log max 1× za 5 min) | `MIN_FREE_BYTES` |
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
- Testy: `tests/test_micro_recorder.py` (9 testů), bez sítě:
  - výpočet pásem, nerovnováhy a pokrytí;
  - parsování likvidací;
  - 1 řádek za sekundu s posledním snímkem a počtem aktualizací;
  - neuzavření běžící sekundy;
  - jedna hlavička přes víc gzip členů;
  - strop bufferu a záznam do `gaps`;
  - disková pojistka a rate-limit logu;
  - retence podle stáří a velikosti, nikdy dnešní soubor;
  - směrování streamů.
- Unit: `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service`.

## Postup nasazení (až po APPROVE)

1. Ověřit hashe skriptu a unitu na serveru. `python3 -I -c "import websocket"`.
2. Nainstalovat `/opt/cryptomaster-micro/micro_recorder.py` (root:root 0644) a unit do
   `/etc/systemd/system/`, pak `daemon-reload`.
3. `systemctl disable --now tick-recorder.service` a `rm /tmp/tick_recorder.log`.
   Ověřit uvolnění 1,27 GB (`df`).
4. `systemctl enable --now cryptomaster-micro-recorder.service`.
5. **Kontrola po 10 min:**
   - `is-active`;
   - RSS < 128 MB (`systemctl show -p MemoryCurrent`);
   - soubory v `/var/lib/cryptomaster-micro/{book,gaps}`;
   - čitelné řádky;
   - žádné chyby v journalu;
   - PID `cryptomaster.service` beze změny;
   - dashboard 200.
6. **Kontrola po 24 h:** velikost za den, počet `dropped_rows` a mezer.
7. **Rollback:** `systemctl disable --now cryptomaster-micro-recorder` a smazat unit a
   `/opt/cryptomaster-micro`. Data ve `/var/lib/cryptomaster-micro` lze smazat. Tick-recorder se
   **neobnovuje**, protože byl nefunkční.

Bot (`cryptomaster.service`) se nerestartuje a jeho nastavení se nemění. Měřicí okno to
neovlivní: jiný proces, nízká priorita, žádné sdílené soubory.

## Otázky na review

1. Jsou limity a izolace dostatečné pro 4GB produkci?
2. Smí se v rámci tohoto nasazení vypnout nefunkční `tick-recorder` a smazat jeho log?
3. Stačí sběr 1× za sekundu z `depth20@500ms`, nebo přidat i `aggTrade` (podepsaný objem po
   sekundách) jako další informační třídu? Ta by přidala objem dat.
