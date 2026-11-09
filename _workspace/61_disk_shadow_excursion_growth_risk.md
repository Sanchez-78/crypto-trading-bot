# Riziko zaplnění disku — `shadow_excursion.sqlite` bez retence (2026-11-09)

Autorita aktuálního stavu: `docs/OPERATING_STATE.md`. Tento report je nález z
rutinního monitoringu (SSH read-only), ne zásah — žádný kód ani runtime data
nebyly měněny.

## Zjištění

- Disk `/` na serveru: 87 % v 08:36 UTC (viz `_workspace/60_audit_remediation.md`),
  88 % v 10:09 UTC (`32 809 940/4 582 376 KB used/avail`, SSH `df`). Zbývá ~4,37 GiB.
- `/opt/cryptomaster/local_learning_storage/` = 13 GiB. Z toho **11,1 GiB
  (přes 99 %) je jediný soubor `shadow_excursion.sqlite`** (`du`, `stat` 2026-11-09
  10:03–10:09 UTC, soubor aktivně rostl v době kontroly).
- Obsah (SQLite `COUNT(*)` na serveru):
  - `shadow_path_1s`: **69 120 411 řádků** (1s OHLC bucket na observaci/sekundu horizontu) — dominantní tabulka.
  - `shadow_excursion_observations`: 223 531 řádků.
  - `shadow_first_crossing`: 744 668, `shadow_strategy_predictions`: 15 496.
- Kód (`src/services/shadow_excursion_recorder.py:189-229,428-467`): schéma je
  pouze `CREATE TABLE IF NOT EXISTS` a `INSERT OR REPLACE`. **Nikde není mazání,
  TTL, rotace ani cap** — tabulka roste neomezeně, dokud běží
  `PAPER_DATA_COLLECTION_ONLY=true` (aktivní na serveru, M1.3b aggTrade hook
  v `market_stream.py:219-227`, signal hook v `paper_trade_executor.py:4751-4800`
  a `signal_generator.py:678-686`).
- **Hrubý odhad tempa růstu:** 87 %→88 % za ~93 min (08:36→10:09 UTC) ≈ 240–250
  MiB/h ≈ 5–6 GiB/den. Jde o jediný vzorek (1 percentuální bod), ne kalibrovaná
  míra — ale při zachování tempa by zbývajících 4,37 GiB vydrželo **řádově
  hodiny až ~2 dny**, tedy výrazně méně než 7 dní do uzavření C1 (~16. 11.).

## Co riziko NENÍ

- Zápisy do shadow recorderu jsou ve všech voláních obaleny `try/except`
  (`market_stream.py:219-227`, `signal_generator.py:680-686`,
  `paper_trade_executor.py:4785-4800`) — `OperationalError` (`SQLITE_FULL`) by
  se tiše spolkla. Zaplnění disku by **nemělo shodit živou PAPER obchodní
  cestu** touto konkrétní cestou.

## Co riziko JE

- Zaplnění disku je systémové: postihuje i `cache.sqlite` (12 MB,
  `local_persistent_cache.py`), `journalctl`, `cryptomaster-research-eval.timer`
  výstupy (`manifest.json`, `verdict.log`), případný budoucí deploy přes
  `deploy_bot_files.sh` (zálohy). Tiché umlčení shadow recorderu navíc ztrácí
  přesně ta data (DEV_FADE/Stonkfly excursion evidence pro budoucí E1–E4
  counterfactual), která je smysl PAPER_DATA_COLLECTION_ONLY sbírat — bez
  alertu (viz `OPERATING_STATE.md` bod 4: „Alert mimo sezení: neřešeno").
- `verdict.log`/`STATUS` toto nehlídá (hlídá jen úspěch/neúspěch evaluačního
  běhu, ne volné místo na disku).

## Co jsem NEudělal a proč

Nemazal, nezkracoval ani jinak neměnil `shadow_excursion.sqlite` ani jiná
runtime data. `AGENTS.md:63-70` je výslovně řadí mezi „runtime data — nikdy
neměnit" a `OPERATING_STATE.md:83` sám uvádí, že výklad tohoto zákazu vůči
Claude „čeká na potvrzení" — tedy destruktivní zásah do jediné kopie
sebraných dat bez explicitního souhlasu operátora je přesně ten případ, kdy
autonomie („dělej vše bez ptaní") nemá nahrazovat rozhodnutí operátora.
Žádná konfigurace sběru (limity, symboly, CONTROL podíl) nebyla měněna —
to je zmrazeno do konce C1.

## Navržené možnosti (čeká na operátora)

1. **Rozšířit disk** (Hetzner volume/upgrade) — nejrychlejší, nic nemaže, C1 i
   sběr běží dál beze změny. Vyžaduje operátora (mimo PAPER rozsah agenta).
2. **Retenční politika v `shadow_excursion_recorder.py`** (např. mazat/archivovat
   `shadow_path_1s` řádky starší než N dní, nebo ukládat jen ladder/first-crossing
   bez plného 1s path) — kódová změna na živém botu; i když nemění rozhodovací
   politiku ani C1 protokol, šla by přes `deploy_bot_files.sh` s review, jak
   vyžaduje `OPERATING_STATE.md`. Riziko: může zahodit data, která audit v5 §7/§8
   považoval za nutná pro E1–E4; návrh na posouzení, ne hotová věc.
3. **Přesunout `shadow_excursion.sqlite` na jiný/větší mount** bez změny obsahu —
   provozní zásah, ne datová ztráta; opět vyžaduje operátora (zásah do
   produkčního serveru nad rámec SSH read-only).
4. **Nic nedělat do dalšího monitoringu** — riziko: možný zápas s diskem dřív
   než C1 skončí; necháno na operátorovi, protože jde o posouzení priority
   (víc PAPER dat vs. riziko výpadku jiné služby), ne o technický fakt.

Žádná z těchto akcí nebyla provedena. Toto je jen nález a doporučení.

## Zdroje

SSH read-only (`root@78.47.2.198`, 2026-11-09 10:03–10:12 UTC): `df`, `du -sh`,
`stat`, `python3 sqlite3 COUNT(*)`. Kód: `src/services/shadow_excursion_recorder.py`,
`src/services/market_stream.py:178-227`, `src/services/paper_trade_executor.py:4748-4800`,
`src/services/signal_generator.py:678-686`.
