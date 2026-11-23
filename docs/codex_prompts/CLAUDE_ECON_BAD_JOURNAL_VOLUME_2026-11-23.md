# Claude: omezit záplavu `REJECT_ECON_BAD_ENTRY` bez změny rozhodování

## Kontext a cíl

Bot je PAPER only. Po nasazení kohorty `explore-bucket-cap` dne 2026-11-23 07:45:02 UTC funguje bucketový strop: v 08:16 byly v P0.8+ současně tři pozice. V asi 16 minutách dostupného journalu bylo kolem 48 tisíc řádků obsahujících `REJECT_ECON_BAD_ENTRY`. Journal uchovává jen přibližně 15 minut. Cíl této úlohy je **prodloužit dostupnou historii provozních chyb omezením redundantních řádků**, aniž se změní jediný obchodní verdikt nebo ztratí souhrnná evidence odmítnutí.

Jde o lokální implementaci k nezávislému review. Bez SSH, nasazení, restartu, změny serverových dat, Firebase a obchodních parametrů. Necommitovat ani nepushovat podle `AGENTS.md`. Před testy a po nich ověř hashe chráněných runtime souborů postupem z `AGENTS.md`.

## Ověřená cesta a místa

- `start.py → bot2/main.py → src/services/signal_generator.py:1164 → src/services/realtime_decision_engine.py:evaluate_signal()` je v lokálním kódu dosažitelná cesta. `trade_executor.on_price()` je přihlášen k `price_tick`; četnost konkrétního call site ani identita živých serverových bajtů není v tomto zadání ověřena.
- Při skutečném ECON BAD odmítnutí v `realtime_decision_engine.py:3820–3841` proběhnou `_update_econ_bad_near_miss()`, `_trace_econ_bad_entry_return(..., final_decision="REJECT_ECON_BAD_ENTRY")`, `track_blocked(reason="ECON_BAD_ENTRY")`, `print("decision=REJECT_ECON_BAD_ENTRY…")`, `_maybe_flush_econ_bad_diagnostics()` a `_maybe_emit_econ_bad_diag_from_reject()`, pak `return None`.
- `_trace_econ_bad_entry_return()` vypisuje `[ECON_BAD_ENTRY_RETURN_TRACE]` jako `log.warning` (`:604–745`), ale obsahuje i invariant `[ECON_BAD_READY_BUT_REJECTED]` na jiné větvi. Existující diagnostika drží `total_econ_bad_blocks` a důvody (`:142–271`) a `learning_event.track_blocked()` počítá každý reject (`learning_event.py:730–733`).
- Zjištěných ~48 tisíc řádků je **operátorem hlášený počet v journalu**, nikoli potvrzený počet jednotlivých rozhodnutí. Pokud je dostupná lokální kopie tohoto okna, rozděl počet podle přesných markerů/šablon: trace, `print`, další `on_price` řádky; jinak rozpad označ `NOT_VERIFIED` a připrav přesný postup pro pozdější read-only měření. Nepředpokládej, že jedna řádka = jedno odmítnutí.

## Implementace

1. Nejprve hledej dostupný připnutý serverový preimage mezi již uloženými lokálními artefakty a manifesty. Produkce běží ze souborových manifestů, ne z git commitu. Pokud přesná serverová verze není lokálně doložena, označ její shodu s pracovním stromem `NOT_VERIFIED`; nepředstírej, že lokální diff je produkční diff. Pro budoucí nasazení bude potřeba operátorem dodaná kopie živých bajtů, z níž se připraví samostatný artefakt jako serverové bajty + minimální diff. Nezahrnuj další dirty změny.
2. Omez pouze redundantní **výpis** `REJECT_ECON_BAD_ENTRY` v uvedené větvi a per-reject warning `[ECON_BAD_ENTRY_RETURN_TRACE]`. Zachovej volání diagnostiky, aktualizaci near-miss, `track_blocked`, volání recovery resolveru, `return None`, event publikaci a všechny bezpečnostní/invariantní logy včetně `[ECON_BAD_READY_BUT_REJECTED]`. `TAKE`/recovery-probe trace a jiné důvody odmítnutí zůstanou beze změny.
3. Nové chování dej za explicitní env příznak s výchozí hodnotou **vypnuto**. Při zapnutí udržuj přesný počet potlačených řádků v omezeném, thread-safe stavu a nejvýš jednou za rozumné časové okno zapiš souhrn s počtem odmítnutí, počtem potlačených detailů a omezenou kategorií důvodu. První výskyt nebo změnu kategorie můžeš zalogovat ihned, aby se neztratila diagnostika. Žádné `decision_id` jako label, žádné per-tick Firebase zápisy. Nedopusť neomezený růst mapy podle volného textu důvodu.
4. Nenahrazuj to globálním filtrem journalu nebo zvýšením `RateLimit`; ten by mohl zahodit traceback či ALERT. Neměň `REJECT_ECON_BAD_ENTRY` výsledek, ekonomické prahy, P0, risk, sizing, TP/SL, executor, Stonkfly ani učicí politiku. Neodstraň existující periodické ECON BAD souhrny.
5. Pro nasazení později připrav **oddělený** návrh: přesný hash artefaktu, preimage, změnu allowlistu pro `realtime_decision_engine.py` a nový env klíč, zálohu, rollback, kontrolu PAPER/REAL a důkaz účinného příznaku. Nyní allowlist ani server neměň. Účinek na kohortu obchodů zaznamenej jako změnu observability, nikoli jako novou strategii nebo důkaz edge.

## Testy a ověření

- Přidej cílený test, který bez opravy selže: více shodných ECON BAD odmítnutí ve zvoleném okně vytvoří omezený počet detailních řádků a přesný souhrnný počet. Projdi hranici okna, změnu kategorie, vysokou kardinalitu důvodu, souběžná volání, chybnou/nezadanou konfiguraci a případnou chybu loggeru.
- Ověř, že výchozí vypnutý příznak zachovává dosavadní výstup. Při zapnutém příznaku porovnej stejnou sekvenci syntetických signálů před/po: identická rozhodnutí, počty `track_blocked`, near-miss a diagnostika; `[ECON_BAD_READY_BUT_REJECTED]` a povolený recovery-probe výstup zůstanou viditelné. Žádný test nesmí importem či během změnit runtime DB.
- Proveď mutaci vrácením per-reject výpisu a mutaci přeskočení `track_blocked`; testy musí obě chyby zachytit. Spusť jen nové cílené testy a relevantní případ z `tests/test_v10_13u_patches.py`, ne celou historickou sadu. Syntaxe musí být kompatibilní s Pythonem 3.12.
- Předběžný objem opři o dodaný údaj ~48 tisíc řádků / 16 minut; přesný rozpad markerů a následné měření po nasazení jsou bez serverového čtení `NOT_VERIFIED`. V reportu připrav reprodukovatelný read-only postup pro srovnatelné časové intervaly a skutečné časové pokrytí journalu. Pokud pozdější měření neukáže delší historii, identifikovat další dominantní marker; nepřidávat další potlačení bez samostatného důkazu.

## Výstup

Napiš česky lokální report do `_workspace/2026-11-23_claude_econ_bad_journal_volume.md`: preimage/postimage hashe, přesný diff, měření markerů, testy/mutace, ochrana runtime dat, co se v rozhodování nezměnilo, návrh nasazení a rollbacku. Výslovně uveď `NOT_VERIFIED`, kde chybí serverové měření. Počkej na nezávislé review kódu i nasazovacího kroku před změnou služby.
