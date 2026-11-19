# Re-review: plánovač kolo 4 + hlídání v conftestu kolo 2 (Codex, 2026-11-19)

Jen audit a doporučení, žádná implementace. Report napiš česky do
`_workspace/2026-11-19_codex_rereview_planner_r4_conftest_guard_r2.md`.

## Kontext

Tvé review `_workspace/2026-11-19_codex_review_planner_r3_conftest_guard.md` vrátilo obě části
(A1: zkrácený close jako `closed`; B1: změna obsahu v `runtime/` se stejnou velikostí a mtime).
Oprava je v `_workspace/2026-11-18_claude_cache_isolation_repair.md`, oddíl „Kolo 5“. Opravený je
také počet mutací z kola 3 (13, ne 14).

Soubory (necommitnuto):
- `src/services/v5_legacy_bridge/outbox_reconcile.py` (`_OPEN_FIELDS`, `_CLOSE_FIELDS`, `_complete`)
- `tests/test_outbox_reconcile_plan.py`
- `tests/conftest.py` (`_protected_snapshot` hashuje obsah všech souborů v runtime adresářích)
- `tests/test_conftest_runtime_db_isolation.py`
- `_workspace/cache_isolation_repair_20261118/protected_sha.py` (nyní hashuje i obsah runtime adresářů)
- mutace (jen dočasná kopie): `_workspace/cache_isolation_repair_20261118/mutations.py`, `mutations_conftest.py`

## Co ověřit

A. Plánovač
1. Je reprodukce A1 opravená, včetně `symbol=" "`?
2. Odpovídají `_OPEN_FIELDS`/`_CLOSE_FIELDS` přesně `LegacyPaperOpenEvent.to_dict()` /
   `LegacyPaperCloseEvent.to_dict()` (`event_models.py`)? Chybí pole, nebo je některý validátor
   přísnější, než skutečný writer může vyprodukovat (např. `size`, `expected_move_bps`, `created_at`,
   `symbol` u reálných symbolů typu `1000PEPEUSDT`)? Zbytečný odklad je přijatelný, ale uveď ho.
3. Zůstane skutečný close po learning merge (`build_learning_update`, `build_close_metadata`)
   `closed`?

B. Conftest
4. Je B1 opravené (přepis stejné velikosti s obnoveným mtime, smazání existujícího souboru)? Jsou
   limity v komentáři pravdivé a úplné?
5. Pokrývají mutace (8 u conftestu, 17 u plánovače) tvé dřívější návrhy? Pokud mutační skripty
   nesmíš spustit, protože zapisují JSON výsledky do `_workspace/cache_isolation_repair_20261118/`,
   můžeš je spustit s výstupem přesměrovaným jinam, nebo jen přečíst `mutation_results.json` a
   `mutation_conftest_results.json`.

## Bezpečnost

- Hashe ulož a porovnej přes
  `python -B -I _workspace/cache_isolation_repair_20261118/protected_sha.py save|check <json mimo repo nebo ve vlastním _workspace adresáři>`,
  nikdy přes `rtk diff a b` (vrací 0 i při rozdílu). Výchozí stav je stav po změně 19. 11. 07:06.
  Jakýkoli další rozdíl je incident: zastav a nahlas.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py tests/test_conftest_runtime_db_isolation.py tests/test_outbox_terminal_backlog.py`
- Žádný server, deploy, Firebase, commit, obnova ani úprava chráněných souborů.
- Verdikt zvlášť pro A a B: APPROVE (jen kód, plánovač dál vypnutý) nebo CHANGES_REQUIRED s reprodukcí.
