# Audit výsledku nasazení sběrače rev. 6 přes deploy skript rev. 7

**Verdikt pro nasazení a desetiminutovou kontrolu k 27. 11. 2026 je `ACCEPT`.** Podklady dokládají spuštění schválené verze, obnovení zápisu knihy pro všech sedm symbolů a první uložené události `forceOrder`. Před kontrolou 28. 11. kolem 14:00 UTC není potřeba žádný zásah. Stav 24hodinové kontroly je `NOT_RUN`. [Provozní záznam](/C:/Projects/CryptoMaster_srv/docs/OPERATING_STATE.md:146)

### 1. Shoda se schváleným postupem R7

Lokálně jsem přepočítal celé SHA-256 sběrače (`b09b31b1…`), deploy skriptu (`a00b1266…`) a unity (`35b35cc0…`). Všechny tři odpovídají schváleným pinům. Provozní zápis uvádí kontrolu stejných artefaktů na serveru, spuštění v **13:51:53 UTC**, `PREFLIGHT_OK`, `CHECKS_OK mem=15896576`, `INSTALL_OK` a ve 14:03 UTC `VERIFY_OK` s návratovým kódem 0. To odpovídá pořadí schválenému v R7. [Schválené piny](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-27_codex_review_micro_recorder_r7.md:7) · [Postup R7](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-26_micro_recorder_design.md:317) · [Výsledek kontrol](/C:/Projects/CryptoMaster_srv/docs/codex_prompts/CODEX_REVIEW_MICRO_RECORDER_DEPLOY_RESULT_2026-11-27.md:13)

Pro sběrač s PID `2041483` jsou doloženy značky `start`, `connect public` a `connect market`. Značka `connect` vzniká už před pokusem o připojení. Příjem na obou větvích proto dokládají až uložená data: **4 611 řádků knihy** za 659 sekund, po 658–659 na symbol, a **6 řádků `liq_sampled`** (ETH 3, BTC 1, BNB 1, XRP 1). Zápis dále uvádí 0 restartů, paměťovou špičku 16,7 MB, CPU 5,5 s a stejný PID bota `3840326`. Pro přijetí této fáze žádný předepsaný důkaz nechybí. Serverové hodnoty přebírám z operátorského zápisu. Audit proběhl pouze čtením lokálních podkladů, bez SSH, testů a zápisu souborů. [Provozní výsledky](/C:/Projects/CryptoMaster_srv/docs/OPERATING_STATE.md:148) · [Význam značky `connect`](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/micro_recorder.py:265)

### 2. Mezera 781 sekund

**Výzkum má mezery odvozovat z `book.ts_s` pro každý symbol zvlášť.** Marker `start` určuje hranici běhů. Čas posledního platného snímku před odstávkou z něj určit nelze. U BTC jsou krajní pozorování **13:38:53 a 13:51:54 UTC**. Jejich odstup činí 781 sekund, takže uvnitř chybí **780 sekundových pozic**, od 13:38:54 do 13:51:53 včetně. Pro ostatní symboly je třeba určit vlastní krajní časy. [Záznam mezery BTC](/C:/Projects/CryptoMaster_srv/docs/OPERATING_STATE.md:155)

Z výpočtů vyřadit okna, která takovou mezeru překlenují. Značky `disconnect`/`connect` podle spojení, `disk_skip` a `dropped_rows` použít jako doplňující důkaz o výpadku či ztrátě dat. Pro `market` je podstatné rozlišit doloženou odstávku od období bez přijaté likvidace. Pravidelná kniha dokládá příjem na `public`, zatímco řídký `liq_sampled` má vlastní spojení a událostní rytmus. [Návrh evidence výpadků](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-26_micro_recorder_design.md:101) · [Rozdělení streamů](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-26_micro_recorder_design.md:233)

### 3. Velikost datového adresáře

**Opravu `du` spojit s příští potřebnou změnou skriptu.** Hodnota `0` patří samotnému symlinku. Operátor pro cílový adresář uvádí 35 MB. Při denní kontrole stačí přečíst velikost přímo přes `du -sh -- /var/lib/private/cryptomaster-micro` a volné místo na příslušném souborovém systému přes `df`. Chybný výpis velikosti neovlivňuje zápis ani diskovou pojistku sběrače. [Výpis ve `verify`](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/deploy_micro_recorder.sh:275) · [Kontrola volného místa při zápisu](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/micro_recorder.py:167)

### 4. Obsah kontroly po 24 hodinách

Spustit plánované `verify` a vyhodnotit přesné okno **od 27. 11. 13:51:53 do 28. 11. 13:51:53 UTC**, s koncem mimo interval. Okno zasahuje do dvou denních souborů a první z nich obsahuje také data rev. 5. Samotné `verify` čte pouze nejnovější soubor `book` a `gaps` a u každého ověří, že obsahuje alespoň jeden řádek. [Implementace `verify`](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/deploy_micro_recorder.sh:261)

| Oblast | Co zaznamenat |
|---|---|
| Kniha | Přečíst oba denní soubory. Pro každý symbol uvést první a poslední `ts_s`, počet unikátních sekund z 86 400 možných, duplicity a nejdelší mezeru. Ověřit návaznost přes půlnoc a čerstvost posledního zápisu s ohledem na 60s flush. |
| Likvidace a spojení | Uvést počty `liq_sampled` po hodinách a symbolech, první a poslední `event_ms` a porovnat je s hodinovými počty zpráv `market` a `public`. Nula za jednotlivou hodinu je u vzorkovaných likvidací možná. Delší ticho nebo zprávy `market` bez odpovídajících uložených dat vyžadují vysvětlení. Chybějící hodinový výpis vykázat jako chybějící důkaz. Sběrač používá `print` bez vynuceného vyprázdnění výstupu, takže zpráva v journalu může mít zpoždění. |
| Výpadky a zdraví služby | Za celé okno projít `start`, páry `disconnect`/`connect` podle spojení, `disk_skip`, `dropped_rows` a chyby v journalu. Uvést `NRestarts`, `MemoryCurrent`, `MemoryPeak`, události OOM a spotřebu CPU. PID a čas startu bota porovnat s výchozím stavem, přiložit výsledek kontroly HTTP 200 dashboardu. |
| Disk | Uvést skutečnou velikost dat, přírůstek za známý interval a zbývající volné místo. Výsledek porovnat s hranicí 5 GiB pro zápis a s retenčním limitem 4 GiB. |

Podkladem pro výklad jsou způsob počítání zpráv, interval zápisu a provozní limity připnuté verze. [Hodinová diagnostika](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/micro_recorder.py:293) · [Limity sběrače](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-26_micro_recorder_design.md:109)

### 5. Read-only preflight upgradu

**Připravit a zrevidovat jej před příštím upgradem, dokud dosavadní sběrač běží.** Má ověřit piny nové sady i očekávané instalované verze, skutečné cesty včetně `StateDirectory`, prostředí, dostupné zdroje a připnuté soubory pro návrat. Dnešní `preflight` při existující unitě skončí před kontrolou disku a paměti. Samotné očekávané `already exists` tedy nepotvrzuje připravenost k výměně. Teprve úspěšná kontrola nad běžící instalací má předcházet jejímu zastavení. [Pořadí kontrol v R7](/C:/Projects/CryptoMaster_srv/_workspace/micro_recorder_release/deploy_micro_recorder.sh:125) · [Doporučení schváleného review](/C:/Projects/CryptoMaster_srv/_workspace/2026-11-27_codex_review_micro_recorder_r7.md:25)