# Re-review: plánovač R4 a ochrana testů R2 — 2026-11-19

**A — plánovač: APPROVE (pouze kód).** Zkrácený close, prázdný symbol a další reprodukce z minulého review nyní dávají `UNKNOWN`; plánovač je nadále vypnutý a nemá executor. Toto není schválení aktivace rekonciliace.

**B — `tests/conftest.py`: APPROVE.** Obsahové hashe nyní zachytí změnu souboru v `runtime/` či `src/runtime/` i při stejné velikosti a obnoveném `mtime_ns`; odstranění souboru se také zachytí. Ochrana stále jen detekuje koncový stav běhu.

## A — porovnání se skutečným writerem

`_OPEN_FIELDS` a `_CLOSE_FIELDS` v `src/services/v5_legacy_bridge/outbox_reconcile.py:101-128` jsem nezávisle porovnal s klíči skutečných `LegacyPaperOpenEvent.to_dict()` a `LegacyPaperCloseEvent.to_dict()` v `event_models.py:31-94` pomocí AST. Po odečtení samostatně kontrolovaných `trade_id` a `event_type` nemá žádná sada chybějící ani nadbytečný klíč. Povinné open hodnoty (`size`, entry čas/cena, nákladové bps, boolean `cost_edge_ok`) a close výsledky (PnL, fees, spread, exit reason, délka držení, eligibility flagy) jsou typově kontrolované. `real_orders_allowed` musí být přesně `False`. `_symbol("1000PEPEUSDT")` vrací `True`; mezera a neplatné znaky jsou odmítnuté.

Původní A1 dokument `{trade_id, symbol, side, event_type, exit_ts, exit_price}` bez výsledku obchodu nyní dostane `doc_state(...) == "unknown"` a dvojice close/learning má akce `UNKNOWN, UNKNOWN` (`tests/test_outbox_reconcile_plan.py::test_truncated_close_from_review_is_unknown_not_merged`). Totéž platí pro `symbol=" "`. Testy vynechávají jednotlivě každé povinné pole u open i close a kontrolují neplatné hodnoty. Platné dokumenty vytvořené event modelem procházejí. Přísnější validace může odložit historický nebo chybný tvar; to je zde požadované fail-closed chování.

U learning merge jsem staticky ověřil `build_close_metadata()` a `build_learning_update()` (`learning_bridge.py:24-40,72-114,155-180`). Metadata whitelist neobsahuje `event_type`; výsledný update proto nechává `paper_close` beze změny. Přepisovaná povinná pole jako `symbol`, `side`, `exit_price`, PnL a eligibility berou hodnoty z původního close eventu nebo bool výpočtu, takže typový kontrakt zůstává splněný. Test obsahuje close s reprezentativním learning merge a vyhodnotí jej jako `closed`. Přímé porovnání se skutečným cloudovým dokumentem nebylo provedeno: **NOT_VERIFIED**.

`ENABLED=False` (`outbox_reconcile.py:44`); modul importuje jen standardní knihovnu, nemá I/O ani executor a `rg` nenašel jeho použití v `src/`, `bot2/` či `start.py`. Docstring nyní výslovně uvádí nutnost atomické transakce/precondition a porovnání lokálního payloadu s cloudovým dokumentem před budoucím zápisem. Tyto dvě věci jsou **blokátory aktivace**, které toto review neschvaluje.

**Neblokující odolnost (P3):** `_number()` volá `math.isfinite()` nad libovolným Python `int` (`outbox_reconcile.py:79-80`). Pro `10**1000` vyvolá `OverflowError`, takže čistá funkce nevrátí `unknown`. Reprodukce proběhla přes `runpy` bez I/O. Tento vstup neodpovídá běžnému zdroji plánovače: [Firestore podporuje podepsaná 64bitová celá čísla](https://firebase.google.com/docs/firestore/manage-data/data-types), která tento problém nemají. Pokud se v budoucnu bude plánovač používat i s libovolnými lokálními mapami/JSON, doporučuji zachytit `OverflowError` v `_number()` a testovat návrat `UNKNOWN`. Nedělám z tohoto out-of-contract vstupu podmínku schválení současného vypnutého kódu.

## B — hashování runtime dat

`tests/conftest.py:30-60,82-91` počítá SHA-256 pro šest souborů z `AGENTS.md` a pro všechny další soubory nalezené v `runtime/` a `src/runtime/`. Rozdíl hodnot i množiny cest nastaví neúspěšný exit status. Původní izolace importu `local_persistent_cache` v `conftest.py:63-79` zůstala. Pomocný `_workspace/cache_isolation_repair_20261118/protected_sha.py` nyní rovněž hashuje obsah všech těchto souborů, nikoli jen jejich seznam.

Nezávisle jsem spustil skutečnou `_protected_snapshot()` extrahovanou z AST nad izolovaným modelem souboru: změna obsahu `AAAA` → `BBBB` při stejné cestě/velikosti/mtime změnila snapshot; odebrání souboru jej také změnilo. Regresní testy navíc používají vnořený pytest v `tmp_path` a ověřují přepis se zachovaným mtime, smazání, vznik a kontrolu všech šesti cest (`tests/test_conftest_runtime_db_isolation.py`).

Limity jsou v komentáři přesné: soubor, který vznikne i zmizí mezi oběma snímky, zůstane nepozorovaný; souběžný proces či zanechaný SQLite `-wal`/`-shm`/`-journal` může shodit test, aniž změnu způsobil test sám. Hláška uvádí jen „during tests“. Žádný souběh ani transientní SQLite soubor jsem nesimuloval: **NOT_VERIFIED dynamicky**. To není chyba obsahového srovnání koncového stavu.

## Testy, mutace a integrita

- Povolený běh z kořene: `rtk python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py tests/test_conftest_runtime_db_isolation.py tests/test_outbox_terminal_backlog.py` → **116 PASS** (96 + 14 + 6). AST parse pěti dotčených Python souborů → **PASS**.
- Výsledky mutací jsem pouze četl, skripty jsem nespouštěl, protože zapisují vlastní JSON: `mutation_results.json` má 17/17 mutací se selháním cílených testů, baseline/restored PASS a bez import/syntax errors; `mutation_conftest_results.json` má 8/8 mutací s neúspěšným během a baseline/restored PASS. Mutace pokrývají minulé A1/B1, vynechání chráněných cest, smazání, vypnutý exit status i prevenci. Nezávislé opakování mutačních běhů: **NOT_RUN**.
- Před testy uložený `_workspace/2026-11-19_codex_rereview_planner_r4_protected_before.json` a následné `protected_sha.py check` → **PROTECTED_SAME** pro šest chráněných souborů i obsah všech dalších souborů v obou runtime adresářích. Výchozí stav je již stav po změně 19. 11. 07:06; nic jsem neobnovoval.
- Server, Firebase a produkční data: **NOT_RUN**. Bez commitů, nasazení a změn runtime souborů.
