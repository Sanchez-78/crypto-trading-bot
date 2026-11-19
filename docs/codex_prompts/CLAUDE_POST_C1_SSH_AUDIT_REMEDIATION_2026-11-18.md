# Zadání pro Claude — po-C1 provozní nálezy a bezpečná náprava

Jsi implementátor CryptoMasteru. Přečti nejprve `AGENTS.md`, `docs/OPERATING_STATE.md` a nezávislý čtecí audit `_workspace/2026-11-18_ssh_full_audit.md` včetně jeho čtyř JSON důkazů v `_workspace/c1_full_audit_20261118/`. Autorita je aktuální serverový stav, nikoli historické odstavce dokumentace. Pracuj na stávajícím root projektu a větvi, zachovej všechny cizí a necommitované změny. Komunikuj a reportuj česky.

Toto zadání výslovně dovoluje **pouze čtecí SSH ověření** na `root@78.47.2.198` pomocí již známého klíče. Nespouštěj přes SSH žádnou instalaci, deploy, restart, reset, migraci, mazání, replay outboxu ani úpravu práv. Na lokálních souborech smíš připravit malé opravy a testy. Před živou změnou projdi nezávislým review přesného diffu podle provozních pravidel; dokud není review hotové, vše nech v pracovním stromu. Necommituj ani nepushuj. Nepovoluj REAL trading. Nemaž C1 výsledek, provenienci, historické trades, Firebase ani learning state.

## Ověřený výchozí stav k 2026-11-18 07:33 UTC

- C1 je zmrazené s verdiktem `CONTRARIAN_NOT_SHOWN`, N=1000, lift −1,58 bps, 95% interval [−4,47; +1,31]. SHA manifestu `f7b2345e2065e276dbcb8177ecafdd9dbd5229d78d14a692e50d57ac2ae2538c`, SHA výsledku `0d97eb6e837042a786810b11cba9eee150a72d24e681be7064b5833d441f69a9`. C2 není předregistrovanými pravidly povolené. Nespouštěj znovu vyhodnocení holdoutu ani nepřepočítávej C1 z nových dat.
- Bot je PAPER (`TRADING_MODE=paper_train`; všechny relevantní REAL příznaky false), PID 886991 po restartu 07:03:59 UTC. Oprava svíček byla nasazena 07:05:14 UTC jako nová kohorta. Od restartu bylo v journalu do 07:27 UTC 0 stale rejections a 52 stáří dat 3,5–7,8 s. Dva první uzavřené obchody nové kohorty nic neříkají o P/L.
- `PAPER_LEARNING_CONTROL_FRACTION=1.0`: adaptivní veto je vypnuté, sběr a kontextové štítky běží. Stonkfly frozen/plastic jsou shadow-only, `readiness_eligible=0`; data a efekt učení hodnotit odděleně.
- Hlavní dashboard `/api/dashboard/metrics` vrací 200 a `degraded=false`; `/api/dashboard/readiness` vrací „No metrics available yet“. Jeho monitor opakovaně hlásí permission denied na `/opt/cryptomaster/.env`.
- V aktivní `src/runtime/v5_trade_outbox.sqlite` je 6191 historických událostí, všechny na `retry_count>=3`, 0 replayable. Běžný `pending_count()` je proto neukazuje. Aktuální quota stav je `normal`; nový outbox řádek od srpna nevznikl. Nevyvozuj automaticky aktuální cloud výpadek.
- Shadow DB má 11,39 GB, server má 15,26 GB volných. `daily-log-fix-prompt-bot.service` je failed, relevance neznámá.

## Úkol 1 — potvrdit scope a provozní invarianty

Přečti aktuální živou cestu `start.py → bot2/main.py`, hlavní signal router, paper executor, Stonkfly kontext, bridge a dashboard. Znovu přes SSH read-only ověř service PID, efektivní PAPER/REAL flags, C1 hashe, stage marker, URL stavy, aktuální disk a DB počty. U časových hranic SQLite použij sekundy pro `closed_trades.entry_ts`, milisekundy pro marker `cohort_start_ms=1794985514000`. Neodvozuj aktuální stav z lokálního git HEAD: produkce je nasazena souborově. Zaznamenej všechny skutečné změny od tohoto auditu.

## Úkol 2 — readiness dashboard bez přístupu k tajnému `.env`

Reprodukuj transitive import/chybovou cestu `src/services/readiness_monitor.py:get_current_metrics()` pod skutečným neprivilegovaným účtem dashboardu. Rozliš hlavní metrics API, které funguje, od chybného readiness endpointu. Oprav readiness tak, aby používal existující bezpečný read model nebo jasně vrátil PAPER-only stav bez importu paper executoru a bez přístupu k `.env`. Nedávej `.env` širší ACL, nekopíruj tajné proměnné do dashboardu a neotvírej cestu k REAL. Doplň cílený regression test, který pod nepřístupným `.env` ověří funkční metrics API i konzistentní readiness odpověď; ověř, že žádný import nemá side effect do runtime DB. Pokud je readiness pro REAL trading mrtvý koncept, zdokumentuj bezpečnou kompatibilní změnu API místo zavedení falešného `ready=true`.

## Úkol 3 — terminální Firebase outbox a jeho viditelnost

Nejprve pouze čtecí forenzní analýza: schéma a unikátní index `(event_type,idempotency_key)`, počty podle typu/stáří/error/retry, vazba na lokální autoritativní trade DB a případně již zapsané cloud dokumenty přes existující read path/kvótu. Nepředpokládej, že 6191 řádků znamená 6191 chybějících cloud dokumentů; zápis mohl uspět před timeoutem. Navrhni přesně idempotentní reconciliation včetně stavu UNKNOWN, deterministických ID a limitu write quota. **Žádný automatický reset `retry_count`, slepý replay ani DELETE.**

Lokálně oprav observability: odděleně vykazuj `replayable_pending`, `terminal_unsynced`, počty podle typu a nejstarší stáří; původní význam stávajícího `pending_count()` neměň bez ověření všech klientů. Nepublikuj ID ani payloady do vysokokardinalitních metrik, nezvyšuj Firebase write rate. Cílené testy musí prokázat, že terminální řádky jsou viditelné, že se z metrik nestávají nové writes a že duplicitní klíč napříč `paper_open`/`paper_close` není omylem vyhodnocen jako duplicitní trade. Pokud skutečný cloud reconciliation vyžaduje neznámé credentials nebo nebezpečnou operaci, dokonči lokální implementaci a zanech ji deaktivovanou s přesným blockerem.

## Úkol 4 — další měření kohorty a kapacity

Zaznamenej odděleně `closed_trades` před/po 07:05:14 UTC 18. 11. a stejnou definici výhry pro obě skupiny. Minimálně sleduj `REJECT_STALE_MARKET_DATA`, `data_age_ms`, počet fetchů na symbol/minutu, dokončené svíčky a ztracené kandidáty v novém funnelu. Nevyhlašuj účinek opravy ani ziskovost podle prvních dvou obchodů; vyšší throughput se nesmí vydávat za zlepšené učení. Změř růst `shadow_excursion.sqlite` a syslogu ze dvou či více časových bodů a odhadni bezpečnou rezervu disku; žádné mazání evidence bez retenčního protokolu a zálohy. Rozliš Stonkfly frozen/plastic, stale, quality a kontextové využití. Prověř `daily-log-fix-prompt-bot.service` pouze read-only a rozhodni, zda jde o relevantní alerting.

## Úkol 5 — validace a výstup

Před testy a po nich porovnej SHA-256 chráněných runtime souborů podle `AGENTS.md`. Použij jen cílené testy v `tmp_path`, syntax/lint podle dostupnosti. Pokud některý test runtime data změní, zastav a nahlas incident. Každou lokální změnu provázej malým diffem a ověř její dosažitelnost na živé cestě. Neprováděj optimalizaci Stonkfly threshold, TP/SL, P0, fee, risk, position sizing ani nové signály; C1 nic takového nepodporuje. V reportu uveď pro každý nález P0/P1/P2/P3, důkaz, změněný soubor, test, zbývající riziko a doporučené review/deploy pořadí. Připrav přesný rollback pro případnou pozdější dashboard nebo metrics změnu, ale nyní server neměň.

Výstup ulož do `_workspace/2026-11-18_claude_post_c1_remediation.md`; zdrojové a testovací úpravy nech lokálně k nezávislému review. Nepiš „P/L+“ ani „learning works“ bez nového předregistrovaného, chronologického a po nákladech pozitivního důkazu.
