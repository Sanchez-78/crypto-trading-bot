# Claude: oprava izolace testů po incidentu s lokální cache (2026-11-18)

Pracuj pouze v aktuálním pracovním stromu `C:\Projects\CryptoMaster_srv`. Strom je záměrně dirty; žádné existující soubory nevracej, nemaž ani necommituj. Příkazy spouštěj s prefixem `rtk` podle `C:\codex\RTK.md`. Nepřipojuj se k serveru, nenasazuj a nerestartuj služby. Nečti ani nepřepočítávej skutečný výsledek C1. Produkční PAPER/REAL nastavení a obchodní parametry neměň.

## Kontext a doložený stav

Nezávislé review `_workspace/2026-11-18_codex_review_post_c1_remediation.md` bylo přerušeno: po přímém spuštění sedmi cílených pytest souborů z kořene projektu se SHA-256 chráněného `local_learning_storage/cache.sqlite` změnil z `31767b56391e77b4143c1e1129b7fa2a4447f4c71f931469e512a4f01ed17646` na `0f2fbd24c8b4420b6b6f56fccb24b6d83eb9a6862ee2bca0fd42d12459cf0d7e`. Soubor má mtime 2026-11-18 07:54:58 UTC. Ostatních pět chráněných souborů se nezměnilo. Předchozí Claudeův izolovaný runner ponechal původní SHA beze změny. Přímý pytest dokončil 134 PASS, 9 SKIP; zelený výsledek neřeší porušení integrity.

Přímá importní hrana je doložena kódem: `tests/test_dashboard_contract_fixes.py:22` importuje `src.services.local_persistent_cache` během collection. `src/services/local_persistent_cache.py:33,43-46,189` používá relativní `LOCAL_DB_PATH` a při importu volá `_init_db()`, který otevírá SQLite pro zápis a provádí schema migrace. Fixture `cache_db` v testu přesměruje cestu až v řádcích 122–126, tedy pozdě. Proto je **import-time zápis do runtime DB při spuštění z rootu prokazatelně možný** a je nejpravděpodobnějším vysvětlením změny SHA. Přesnou změnu řádků nebo schématu a vyloučení souběžného procesu zatím prokázat nelze, protože nemáme kopii databáze z okamžiku před incidentem. Po incidentu `PRAGMA quick_check = ok`, `schema_version = 29`, `closed_trades = 473` a nejsou přítomny soubory `cache.sqlite-wal` ani `cache.sqlite-shm`. To dokazuje jen současnou čitelnost, ne nezměněnost dat.

## Úkol A — incident a bezpečná izolace

1. Zaznamenej aktuální SHA, velikost a čas chráněné DB. Prohlídku dělej jen přes SQLite URI `mode=ro` s `PRAGMA query_only=ON`; žádné `VACUUM`, checkpoint, migrace, obnova, reset nebo přepis. Pokud najdeš dřívější kopii **s ověřeným původním SHA**, porovnej schéma a agregované počty read-only. Pokud ne, přesný obsahový rozdíl označ `NOT_VERIFIED`; neodvozuj jej z `quick_check`.
2. Na syntetické databázi v izolovaném dočasném adresáři prokaž importní side effect a zjisti, zda samotný import s dnešním schématem mění hash. Před/po každém pokusu ověř SHA skutečného `local_learning_storage/cache.sqlite`; při další změně ihned zastav. Test ani reproduktor nesmějí otevřít skutečnou runtime DB pro zápis.
3. Oprav příčinu s minimálním diffem: načtení `local_persistent_cache` při pytest collection z rootu nesmí zapisovat do runtime cesty. Přesměrování až v běžné fixture nestačí. Zvaž import po nastavení izolovaného cwd nebo jiný mechanismus účinný **před collection**. Produkční inicializační chování modulu neměň, pokud to není nezbytné a samostatně zdůvodněné.
4. Přidej regresi, která na syntetických datech selže se starou podobou testu a projde s opravou. Ověř kombinované pořadí všech sedmi review souborů. Žádný red-test ani mutace nesmí během selhání sahat na skutečný `local_learning_storage/**`. Měř SHA všech šesti souborů uvedených v `AGENTS.md` před a po. Pro testy použij `rtk python -B -m pytest -q -p no:cacheprovider` a pouze cílené soubory uvedené v zadání review; pokud je bezpečná izolace stále nejistá, testy nespouštěj a vysvětli blocker.

## Úkol B — již nalezená chyba plánovače rekonciliace

V témže nezávislém review vznikl statický nález, který musí být opraven před jakýmkoli zapojením plánovače. `src/services/v5_legacy_bridge/outbox_reconcile.py:63-77` rozpoznává uzavřený cloud dokument jen podle `status == "closed"`. Skutečný `LegacyPaperCloseEvent.to_dict()` v `src/services/v5_legacy_bridge/event_models.py:73-94` zapisuje `event_type="paper_close"` a žádné `status`. Plánovač proto může navrhnout `WRITE_CLOSE` pro již uzavřený dokument. Pro neznámý nebo nevalidní existující dokument nesmí předpokládat bezpečný přepis.

Ověř kontrakt proti skutečnému writeru a oprav pouze čistý, stále vypnutý plánovač a jeho testy. Existující close musí vést na `SKIP_PRESENT`; nejasný cloud stav na `UNKNOWN`/odklad. Ověř chování open, close, learning i limitu zápisů. Neimplementuj executor, replay ani nové zápisy do Firebase; `ENABLED=False` musí zůstat. Tento úkol odděl v diffu a reportu od incidentu cache.

## Výstup a hranice

Napiš český report do `_workspace/2026-11-18_claude_cache_isolation_repair.md`: časová osa a síla důkazů, obsahový rozdíl DB jako VERIFIED/NOT_VERIFIED, přesný diff, testy a mutace, SHA před/po, neuzavřená rizika. Úpravy nech necommitnuté pro další nezávislé review Codexem. Původní review dashboardu a outbox visibility zůstává nedokončené; nevydávej jejich schválení ani nepovoluj nasazení na základě tohoto úkolu.
