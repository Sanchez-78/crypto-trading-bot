# Nezávislé review po-C1 nápravy — dokončeno po opravě izolace testů

**Konečný verdikt 2026-11-18:** dashboard readiness **APPROVE (kód)**, viditelnost outboxu **APPROVE (kód)**, vypnutý plánovač rekonciliace **CHANGES_REQUIRED**. Izolace testů je pro cílenou review sadu **APPROVE**. To není souhlas s nasazením: dashboard potřebuje vlastní review nasazovacího postupu a outbox rozšíření allowlistu. Plánovač nesmí být zapojen ani použit pro replay.

Původní review bylo přerušeno po změně hash chráněné lokální `cache.sqlite`. Následující odstavce zachovávají původní incidentní záznam; nová ověření a konečné verdikty jsou v oddílu „Dokončené review“. Server nebyl kontaktován ani změněn. Databázi jsem nevracel ani neupravoval.

## Integrita chráněných souborů

- Před testy: `cache.sqlite` SHA-256 `31767b56391e77b4143c1e1129b7fa2a4447f4c71f931469e512a4f01ed17646`.
- Po testech: `cache.sqlite` SHA-256 `0f2fbd24c8b4420b6b6f56fccb24b6d83eb9a6862ee2bca0fd42d12459cf0d7e`.
- Ostatních pět chráněných souborů ze seznamu `AGENTS.md` zůstalo beze změny. Přesné hashe jsou v `post_c1_remediation_review_20261118/protected_before.json` a `protected_after.json`.
- Spuštěno pouze sedm souborů povolených zadáním: `test_readiness_paper_only.py`, `test_outbox_terminal_backlog.py`, `test_outbox_reconcile_plan.py`, `test_dashboard_contract_fixes.py`, `test_sec_01_dashboard_boundary.py`, `test_v5_legacy_bridge_outbox.py`, `test_phase4d_outbox_flush_worker.py`. Výsledek **134 passed, 9 skipped**. Zelené testy neodstraňují incident integrity. Další testy ani mutace nebyly spuštěny.

## Předběžné nálezy z již přečteného diffu

1. **Plánovač rekonciliace: CHANGES_REQUIRED (statický důkaz, dosud bez dynamické reprodukce).** `src/services/v5_legacy_bridge/outbox_reconcile.py:63–77` pozná již uzavřený cloud dokument jen podle `status == "closed"`. Skutečný `LegacyPaperCloseEvent.to_dict()` v `src/services/v5_legacy_bridge/event_models.py:73–94` žádné `status` nevytváří; používá `event_type: "paper_close"`. `firebase_writer.py:321–324` tento payload zapisuje do `v5_trades/{trade_id}` bez merge. Plánovač proto pro existující dokument uzavřeného obchodu může navrhnout `WRITE_CLOSE` místo `SKIP_PRESENT`. Navíc pro neznámý či nevalidní existující dokument nabízí přepis close místo fail-closed UNKNOWN. Modul je nyní `ENABLED=False` a není zapojený, takže nejde o doložený živý zápis. Před jakýmkoli použitím opravit klasifikaci cloud dokumentu podle skutečného kontraktu a ověřit čerstvost stavu při zápisu.
2. **Dashboard readiness: NOT_COMPLETED.** Diff odstraňuje import executoru a vrací PAPER-only odpověď. Kontrola všech klientů, zbylých importních side effectů a deploymentu nebyla dokončena kvůli incidentu.
3. **Viditelnost outboxu: NOT_COMPLETED.** Diff přidává souhrnný log a `backlog_stats()`, zachovává `pending_count()`. Nebyla dokončena analýza chybových stavů a všech klientů. Při chybě DB vrací `backlog_stats()` nulové počty s `error`, zatímco `get_status()` `error` nepředává; to může v status odpovědi skrýt neznámý backlog. Vyžaduje další ověření.

## Původní další bezpečný krok (následně splněn)

Nejdřív read-only zjistit, co změnilo lokální `cache.sqlite` během testu, a zda zůstala konzistentní. Neprovádět reset, obnovu ani další testy bez vyjasnění incidentu. Potom obnovit nezávislé review v čistě izolovaném testovacím prostředí s novou kontrolou hashů před a po. Do té doby **nenasazovat žádnou ze tří částí**.

## Dodatek 2026-11-18 — read-only šetření po přerušení

`tests/test_dashboard_contract_fixes.py:22` importuje `local_persistent_cache` už při pytest collection. Modul má relativní `LOCAL_DB_PATH` (`src/services/local_persistent_cache.py:33`) a import spouští `_init_db()` (`:189`), který otevírá SQLite pro zápis (`:46`). Testová fixture přesměruje cestu až později (`tests/test_dashboard_contract_fixes.py:122-126`). Přímé spuštění pytestu z kořene tedy může změnit chráněnou runtime DB; Claudeův dřívější běh používal izolovaný runner. To je silné vysvětlení časově související změny SHA, nikoli důkaz konkrétní obsahové změny ani vyloučení souběžného procesu.

DB měla při tomto šetření 172032 bajtů, mtime 2026-11-18 07:54:58 UTC a read-only `PRAGMA quick_check = ok`, `schema_version = 29`, `closed_trades = 473`. Kopie souboru před incidentem není doložena; integrita jednotlivých řádků vůči stavu před testem je `NOT_VERIFIED`. V této fázi neproběhl další pytest ani zápis do DB. Pro Claude bylo připraveno zadání `docs/codex_prompts/CLAUDE_REPAIR_POST_C1_TEST_ISOLATION_2026-11-18.md`.

## Dokončené review po Claudeově opravě

### Izolace a integrita testů — APPROVE pro cílenou sadu

Claude prokázal importní mechanismus na syntetické starší DB a opravil `tests/conftest.py:35-51`: před collection importuje cache modul v dočasném cwd a nastaví absolutní dočasné cesty. `pytest_sessionfinish` na řádcích 54–60 hlásí změnu skutečné cache DB. Regrese `tests/test_conftest_runtime_db_isolation.py` používá oddělenou kopii kódu a syntetickou DB; s předchozí podobou conftestu změnu SHA zachytí. Tvrzení o přesném obsahu lokální DB před incidentem zůstává `NOT_VERIFIED`, protože původní binární kopie není k dispozici.

Nezávisle jsem přímo z kořene spustil přesně sedm souborů z review zadání a novou regresi: **140 PASS, 9 SKIP**. SHA všech šesti chráněných souborů před a po souhlasí; `cache.sqlite` zůstává na novém hashi `0f2fbd24c8b4420b6b6f56fccb24b6d83eb9a6862ee2bca0fd42d12459cf0d7e`. Claudeových 6/6 zachycených mutací jsem ověřil čtením výsledků v `_workspace/cache_isolation_repair_20261118/mutation_results.json`, nikoli novým spuštěním. Globální conftest zasahuje i testy mimo tuto cílenou sadu; ty podle `AGENTS.md` nebyly spuštěny.

Přesné hashe, příkaz, počty a výstupy čistých reproduktorů jsou v `_workspace/post_c1_remediation_review_20261118/independent_final.json`.

Zbylá mez: `tests/conftest.py:36-37` při již importovaném `local_persistent_cache` tiše vrací bez přesměrování. Kdyby jej načetl pytest plugin před conftestem, mohl by zápis předcházet i výchozímu SHA na řádku 32; tuto situaci současná detekce nerozpozná. Pro zde povolenou sadu jsem takový pre-import nepozoroval. Před použitím ochrany jako obecné garance pro libovolný pytest běh doporučuji tento stav explicitně odmítnout.

### Dashboard readiness — APPROVE (kód)

`src/services/readiness_monitor.py:19-30` už neimportuje `paper_trade_executor` ani nečte `.env`; při importu se nespouští monitorovací vlákno. Tím odpadá doložená hrana, kterou dashboard unit s `InaccessiblePaths=/opt/cryptomaster/.env` odmítal. Dashboard je samostatný proces, takže starý výpočet nad in-memory pozicemi bota neměl platná data. `src/services/dashboard_web.py:1372-1401` vrací na `/api/dashboard/readiness` HTTP 200 s `is_ready_for_trading=false` i při chybě. Cílený test simuluje nepřístupnou `.env` a zakazuje import executoru, DB i start vlákna při importu.

Klient `C:\Projects\CryptoMaster_app\src\services\dashboardApi.js:87-95` objektovou odpověď tohoto endpointu převádí na prázdné pole; stejným způsobem zacházel i se starým objektovým kontraktem, proto jde o zachování dosavadního chování aplikace, nikoli o zobrazení nové readiness. Endpoint `/api/dashboard/readiness/status` dál používá obecnou cache `trading_readiness_checker`; v aktuální dashboard cestě neexistuje volání `check_readiness` s metrikami, takže výchozí stav zůstává false. Pro budoucí úplnou PAPER-only semantiku by bylo vhodné sjednotit i tento pomocný endpoint, ale v tomto diffu nevznikl doložený falešný `ready=true`.

### Viditelnost outboxu — APPROVE (kód)

`DurableOutbox.backlog_stats()` (`src/services/v5_legacy_bridge/outbox.py:261-310`) agreguje podle event type a hranice retry. Nemění `pending_count()` ani payloady, nevydává ID a nevolá Firebase. `OutboxFlushWorker` loguje terminální součet při startu a při změně počtu; `get_status()` nyní předává `backlog_error`, takže selhání čtení DB nelze zaměnit s ověřenou nulou. Přímý test potvrzuje 3 terminální + 1 replayable řádek, oddělení stejného trade ID napříč event types, absenci cloud volání a chybový status. Stav 6 191 historických terminálních řádků pochází z Claudeova read-only auditu serveru; já jsem ho znovu přes SSH neověřoval.

Nejde o schválení replaye. `firebase_writer.py:317-324` zapisuje `paper_open` i `paper_close` na stejnou cestu bez merge; přehrání starého open může zvrátit uzavřený dokument. Nová metrika znamená „lokálně nepotvrzené“, nikoli prokazatelně chybějící dokumenty v cloudu.

### Plánovač rekonciliace — CHANGES_REQUIRED (stále vypnutý)

1. **P2, chybně uzavřený nevalidní dokument.** `src/services/v5_legacy_bridge/outbox_reconcile.py:64-72` klasifikuje jako `closed` jakýkoli mapping s `event_type="paper_close"` *nebo* pouhou přítomností klíčů `exit_ts` a `exit_price`. Čistý reproduktor ukázal pro `{"event_type":"paper_close"}`, pro `{"exit_ts":null,"exit_price":null}` i pro dokument s cizím `trade_id` akci `MERGE_LEARNING`. Tyto podoby neodpovídají úplnému `LegacyPaperCloseEvent.to_dict()` (`event_models.py:73-94`). Neznámý/nevalidní existující dokument má být `UNKNOWN`, bez zápisu. Při klasifikaci ověř i soulad `trade_id` s klíčem, pokud je přítomen; u chybějící identity zvol konzervativní pravidlo a test.
2. **P2, opomenutý learning při uzavření dosud neexistujícího dokumentu.** Pro `Row("paper_close","t")` a `Row("learning_update","t")` s `cloud={"t": None}`, `max_writes=2` vrací `WRITE_CLOSE`, potom `DEFERRED_NO_TRADE_DOC` (`outbox_reconcile.py:105-111`). To odporuje deklaraci, že learning lze přidat, když se close zapisuje ve stejném plánu. Budoucí executor by také musel rozlišit pozorovaný stav před plánem od stavu po předchozí akci; samotné `expect="absent"` na následujícím merge není dostačující compare-before-write kontrakt. Doplň test absent→close→learning s rozpočtem i bez něj a explicitní závislost/expected-state po close, nebo dokumentuj konzervativní odklad a oprav tvrzení v reportu. Žádný replay ani executor nyní nezapojovat.

Původní nález `status == "closed"` je odstraněn a testy podle skutečného event kontraktu procházejí. `ENABLED=False`, modul nemá I/O ani živou cestu; uvedené nálezy tedy **neznamenají probíhající cloud přepis**.

### Pořadí nasazení a otevřené limity

Kód dashboardu lze řešit odděleně od bota: záloha dvou souborů, ověřené hashe, restart pouze dashboard služby a kontrola readiness/metrics i absence `[METRICS_COLLECTION_ERROR]`. To je návrh postupu, ne provedené nasazení; podle místních pravidel vyžaduje samostatné review konkrétního dashboard deploy kroku. Outbox visibility patří do jiné kohorty bota. Aktuální allowlist `deploy/research_eval/deploy_bot_files.sh:42` tyto dva moduly neobsahuje; bez reviewovaného rozšíření skriptu a rollbacku nenasazovat. Plánovač ponechat vypnutý až do opravy nálezů a případného rozhodnutí, zda cloud historii vůbec rekoncilovat.

Server, Firebase a skutečné C1 výsledky jsem v tomto pokračování neotevíral. Zelené testy ani tato oprava neprokazují kladné P/L nebo obchodní edge.
