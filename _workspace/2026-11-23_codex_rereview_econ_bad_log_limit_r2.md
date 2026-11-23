# Re-review omezení výpisů `REJECT_ECON_BAD_ENTRY`, kolo 3 — 2026-11-23

**Verdikt: APPROVE (kód).** Nález R2 je odstraněn změnou kontraktu: souhrn se nepotvrzuje, nýbrž další doručená řádka nese kumulativní počty všech uzavřených oken. Schválení se netýká nasazovacího kroku ani skutečné retence journalu.

## Ověřená oprava R2

`EconBadRejectLogLimiter.observe()` aktualizuje `_totals` a `seq` pod jedním zámkem ještě před sestavením řádky (`src/services/realtime_decision_engine.py:806–837`). `_econ_bad_should_emit_reject_detail()` se nesnaží potvrdit zápis (`:851–866`); selhání loggeru nemůže vymazat kumulativní počty. Aktuální okno a souhrn za uzavřená okna mají oddělené čítače. Kategorie v obou strukturách mají strop 16 pojmenovaných hodnot plus `other` (`:786–804`).

Upravil jsem svůj import-free AST reproduktor `_workspace/econ_bad_r1_independent_repro_20261123.py` pro nový kontrakt. Po ztrátě `seq=1` kvůli přímo vyhozené výjimce dorazil `seq=2` s `window_rejects=3 window_suppressed=2 total_rejects=6 total_suppressed=4`. Se skutečným `logging.Logger` a standardním `StreamHandler`, který chybu `write()` spolkne, dorazil `seq=2` s `window_rejects=1 window_suppressed=0 total_rejects=4 total_suppressed=2`. Oba scénáře včetně ztraceného prvního okna prošly. Reproduktor importuje ze zdroje jen limiter a jeho pomocné funkce, ne RDE ani Firebase.

Navíc jsem přes AST ověřil 8 souběžných vláken × 1 000 odmítnutí s rotací každých 50 pozorování. Vzniklo 159 unikátních `seq`, každá řádka měla přesně 50 odmítnutí a 49 potlačených detailů, kumulativní součty odpovídaly `50×seq` a `49×seq`; zbývajících 50 odmítnutí bylo v aktuálním okně. Pořadí *zápisu* řádek se při souběhu může lišit od pořadí `seq`, protože logování je mimo zámek; počty i čísla sekvence tím zůstávají správné. Analýza journalu proto musí řádky řadit podle `seq` v rámci PID.

Odmítací větev stále vrací `None` a helper zachovává near-miss, resolver/invariant, `track_blocked`, flush a emit při každém odmítnutí (`:869–897`, `:3974–3979`). Jen detailní trace a print jsou podmíněny příznakem, který je výchozím stavem vypnutý. Cílené testy ověřují i `[ECON_BAD_READY_BUT_REJECTED]` při potlačení detailu.

## Meze a neblokující dokumentační úprava

Kontrakt nemůže zachránit poslední ztracený souhrn před ukončením procesu ani poslední otevřené okno bez dalšího odmítnutí. `seq` se po restartu vrací na 1; rozlišení běhů vyžaduje PID z journalu. Tyto meze jsou v reportu autora uvedené; komentář u limiteru výslovně uvádí restart a podmínku další doručené řádky, ale poslední ztracený souhrn by mohl pojmenovat přímo.

V autorově reportu má oddíl „Kolo 3“ správný nový kontrakt, zatímco pozdější oddíl „Výsledek“ (`_workspace/2026-11-23_claude_econ_bad_journal_volume.md:80–88`) stále ukazuje starý formát bez `seq` a kumulativních polí. Před review nasazení doporučuji tento příklad opravit, aby provozní dokumentace nebyla rozporná. Nemění to verdikt ke kódu.

## Ověření

- Přesně povolený cílený běh: **30 passed, 1 deprecation warning**. Jiné testy jsem nespouštěl.
- Nezávislý AST reproduktor: přímo vyhazující logger **PASS**, selhávající produkční typ `StreamHandler` **PASS**, souběžná rotace 8 000 odmítnutí **PASS**.
- `_workspace/econ_bad_journal_20261123/mutation_results.json` hlásí 14/14 zachycených mutací včetně `seq`, kumulativních počtů, jejich stropu a odlišení okna od součtu. Výsledky jsem četl, mutační skript znovu nespouštěl.
- Před a po testech: `_workspace/cache_isolation_repair_20261118/protected_sha.py` hlásí **PROTECTED_SAME** pro šest chráněných souborů a obsah `runtime/` i `src/runtime/`.
- SHA-256 současného RDE souboru: `95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03`, shodný s reportovaným postimage. Shoda se serverovou verzí **NOT_VERIFIED**. Neprováděl jsem SSH, nasazení, Firebase zápis, restart ani commit.

Před nasazením je nutné samostatně ověřit artefakt proti živé serverové preimage, postup nasazení a plán měření journalu. Zelené testy nejsou důkaz prodloužení retence ani obchodního edge.
