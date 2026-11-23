# Re-review omezení výpisů `REJECT_ECON_BAD_ENTRY`, kolo 2 — 2026-11-23

**Verdikt: CHANGES_REQUIRED (kód).** Oprava R1 funguje pro logger, který při chybě `warning()` vyhodí výjimku. S produkčním typem handleru však může souhrn stále zmizet. Nasazovací krok nebyl předmětem tohoto review.

## Blokující nález — standardní `StreamHandler` skryje selhání zápisu

`_econ_bad_should_emit_reject_detail()` potvrzuje souhrn, jakmile se `log.warning(summary)` vrátí bez výjimky (`src/services/realtime_decision_engine.py:868–875`). Produkční `bot2/main.py:1233–1238` používá `logging.basicConfig(stream=sys.stderr)`, tedy standardní `StreamHandler`. Jeho `emit()` zachytí chybu `stream.write()` a zavolá `handleError()`; do volajícího ji nepropaguje. `ack(token)` proto může smazat `_pending`, i když řádka souhrnu do journalu vůbec nedošla. Nastavení `logging.raiseExceptions=False` tuto situaci zcela umlčí.

**Nezávislá reprodukce:** `_workspace/econ_bad_r1_independent_repro_20261123.py` načítá přes AST pouze čtyři funkce/třídu limiteru z aktuálního zdroje, bez importu RDE nebo jeho vedlejších účinků. Tři odmítnutí `weak_ev` v prvním okně dávají `rejects=3 suppressed_details=2`. Při přechodu okna `StreamHandler` zapisuje do streamu, jehož `write()` vyhodí `OSError`, ale `log.warning()` se vrátí. `limiter.pending_snapshot()` je poté `None`. Po přepnutí handleru na funkční stream a dalším přechodu okna se zapíše jen `windows=1 rejects=1 suppressed_details=0`. Staré `3/2` se nezapíší nikdy. Reproduktor skončil `STREAM_HANDLER_R1_STILL_FAILS` a kód 0.

Autorský test `FlakyLog.warning()` (`tests/test_econ_bad_reject_log_limit.py:239–280`) vyhazuje výjimku přímo, takže tuto produkční cestu nepokrývá. Doplň test se skutečným `logging.Logger` a `StreamHandler` s chybujícím streamem, potom zajisti, aby potvrzení čekajícího souhrnu záviselo na prokazatelném přijetí výstupu. Návrh musí zachovat omezení počtu kategorií, neblokovat ostatní účinky odmítnutí a výchozí vypnutí příznaku. Pouhý návrat z `Logger.warning()` není potvrzení zápisu; ani `logging.raiseExceptions=True` by výjimku `StreamHandler` nepropagovalo. Pokud není spolehlivé potvrzení možné, kontrakt „souhrn se neztratí při selhání loggeru“ je třeba výslovně změnit a doložit, jak bude ztráta diagnostiky zjistitelná.

## Co oprava prokazatelně řeší

Původní reprodukce s loggerem, který chybu vyhazuje, nyní prošla: po jedné chybě zůstane `_pending` `{"windows": 1, "counts": {"weak_ev": (3, 2)}}`; následující úspěšná řádka nese `windows=2 rejects=6 suppressed_details=4`. `ack()` pod zámkem maže jen aktuální generaci. Při další rotaci se do `_pending` slučují počty a nejvýš 16 kategorií plus `other`; opakované chyby proto nevytvářejí seznam neomezeně mnoha oken. Úspěšně zapsaný starší souhrn se při souběhu s rotací oken může překrývat s novějším; u čistě diagnostického logu je tato zdokumentovaná mez přijatelná, ale souhrny pak nelze bez deduplikace prostě sčítat. Obdobná nejistota platí, pokud výstup proběhne a handler teprve poté vyhodí chybu.

Změněná část stále ponechává `return None` odmítací větve a pořadí near-miss, trace, `track_blocked`, print, flush a emit. Testy ověřují zachování těchto účinků i invariantu `[ECON_BAD_READY_BUT_REJECTED]` při potlačení detailu. Příznak `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED` je ve výchozím stavu vypnutý. Objem ani prodloužení retence produkčního journalu zůstává `NOT_VERIFIED`.

## Ověření a hranice

- Povolený cílený běh: `29 passed, 1 warning` (27 testů limiteru a dva existující regresní případy). První běh v sandboxu selhal při vytváření dočasného adresáře conftestu (`PermissionError`); opakování téhož příkazu mimo sandbox prošlo. Žádné jiné testy jsem nespouštěl.
- Nezávislý AST reproduktor: původní R1 s přímo vyhazujícím loggerem **PASS**, varianta se standardním `StreamHandler` **reprodukuje ztrátu**. Neimportoval RDE a nezapsal runtime DB.
- `_workspace/cache_isolation_repair_20261118/protected_sha.py`: před testy snapshot, po testech **PROTECTED_SAME** pro šest souborů a obsah `runtime/` i `src/runtime/`.
- `_workspace/econ_bad_journal_20261123/mutation_results.json` uvádí 14/14 zachycených mutací; mutační skript jsem znovu nespouštěl. Současné mutace neobsahují selhávající standardní `StreamHandler`.
- Aktuální SHA-256 `src/services/realtime_decision_engine.py`: `07e3b7bf209baa0fd738511283db869e13f0d5db2d3e510c692f020a340b2a5e`, odpovídá reportovanému postimage. Produkční shoda souboru je **NOT_VERIFIED**. Žádné SSH, nasazení, Firebase, restart ani commit.

Po opravě tohoto nálezu je potřeba další nezávislé review kódu. Schválení kódu samo neschválí nasazení.
