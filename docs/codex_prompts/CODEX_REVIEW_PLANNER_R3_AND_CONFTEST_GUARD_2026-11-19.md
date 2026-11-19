# Review: plánovač rekonciliace kolo 3 + hlídání chráněných souborů v conftestu (Codex, 2026-11-19)

Jen audit a doporučení, žádná implementace. Report napiš česky do
`_workspace/2026-11-19_codex_review_planner_r3_conftest_guard.md`.

## Kontext

- Tvé re-review `_workspace/2026-11-18_codex_rereview_outbox_reconcile.md` vrátilo plánovač
  (CHANGES_REQUIRED: neúplný `paper_open` bez `symbol`/`side`, neplatný close pro learning merge).
- Oprava a nový incident jsou v `_workspace/2026-11-18_claude_cache_isolation_repair.md`, oddíly
  „Kolo 3“ a „Kolo 4“.
- Incident 19. 11. 07:06:26 UTC: `server_local_backups/paper_adaptive_learning_state.json` a
  `learning_state_phase1.json` se změnily během pytestu souběžné autonomní session z kořene. Proto je
  detekce v `tests/conftest.py` rozšířená na všech šest chráněných souborů a na `runtime/` a
  `src/runtime/`.
- Zjištění k nástrojům: `rtk diff a b` (dva soubory) vrací 0 i při rozdílu. Hashe porovnávej
  v Pythonu, např. `python -B -I _workspace/cache_isolation_repair_20261118/protected_sha.py save|check <json>`.

Soubory (necommitnuto v pracovním stromu):
- `src/services/v5_legacy_bridge/outbox_reconcile.py`, `tests/test_outbox_reconcile_plan.py`
- `tests/conftest.py`, `tests/test_conftest_runtime_db_isolation.py`
- mutace: `_workspace/cache_isolation_repair_20261118/mutations.py` a `mutations_conftest.py`
  (pracují jen v dočasné kopii)

## Co ověřit

A. Plánovač
1. Jsou opravené reprodukce z re-review (chybějící `symbol`/`side` → dříve `open` + `WRITE_CLOSE`;
   neplatná `side`, cizí `event_type`, nulová exit cena → dříve `closed` + `MERGE_LEARNING`)?
2. Odpovídá `doc_state` přesně `event_models.py` (`LegacyPaperOpenEvent`/`LegacyPaperCloseEvent`)
   a merge payloadu `learning_bridge.build_learning_update()` (`learning_bridge.py:157-180`, včetně
   rozbalení `**metadata`)? Existuje platný reálný dokument, který skončí jako `unknown` (zbytečný
   odklad je přijatelný), nebo nevalidní, který skončí jako `open`/`closed` (nepřijatelné)?
3. Je blokátor aktivace (atomický zápis přes transakci nebo precondition) v docstringu popsaný
   dostatečně? `ENABLED=False`, bez I/O a bez executoru?

B. Conftest
4. Zachytí detekce změnu, vznik i zmizení u všech šesti souborů a v `runtime/` i `src/runtime/`?
   Nevznikají falešné poplachy (např. SQLite `-wal`/`-journal`, `__pycache__`, souběžné procesy)?
5. Nemění conftest chování testů ani produkčního kódu kromě zamýšlené prevence a detekce? Funguje
   s `pytest -p no:cacheprovider` a s `python -B`?
6. Jsou mutace dostatečné (jen `cache.sqlite`, bez skenu runtime, nenastavený `exitstatus`, vypnutá
   prevence)? Navrhni chybějící.

## Bezpečnost

- Před testy a po nich ulož a porovnej hashe přes `protected_sha.py` (ne `rtk diff a b`).
  Výchozí stav je stav **po** změně 19. 11. 07:06; jakýkoli další rozdíl = incident: zastav a nahlas.
- Testy jen tyto soubory:
  `python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py tests/test_conftest_runtime_db_isolation.py tests/test_outbox_terminal_backlog.py`
- Žádný server, deploy, Firebase, commit, obnova ani úprava chráněných souborů; zapisuj jen vlastní report.
- Verdikt zvlášť pro A a B: APPROVE (jen kód) nebo CHANGES_REQUIRED s reprodukcí.
