# Re-review: plánovač rekonciliace outboxu, kolo 2 (Codex, 2026-11-18)

Jen audit a doporučení, žádná implementace. Report napiš do
`_workspace/2026-11-18_codex_rereview_outbox_reconcile.md` (česky).

## Kontext

Tvé review `_workspace/2026-11-18_codex_review_post_c1_remediation.md` vrátilo plánovač se dvěma
nálezy P2: neúplný, rozporný nebo cizí dokument jako `closed`, a odložený learning po plánovaném
uzavření dokumentu `absent`. Oprava je popsaná v oddílu „Kolo 2“ reportu
`_workspace/2026-11-18_claude_cache_isolation_repair.md`.

Soubory (necommitnuto v pracovním stromu):
- `src/services/v5_legacy_bridge/outbox_reconcile.py`
- `tests/test_outbox_reconcile_plan.py`
- mutace: `_workspace/cache_isolation_repair_20261118/mutations.py` (pracuje jen v dočasné kopii)

## Co ověřit

1. Jsou obě tvé reprodukce (`independent_final.json`) opravené? Spusť je znovu proti nové signatuře
   `doc_state(doc, key)` a `plan(...)`.
2. Je `doc_state` fail-closed vůči skutečnému kontraktu `event_models.py` a merge payloadu
   `learning_bridge.apply_learning_from_close`? Najdi případný reálný dokument, který by byl `unknown`
   (zbytečný odklad je přijatelný), nebo nevalidní dokument, který by byl `closed`/`open` (není přijatelné).
3. Je kontrakt `expect` + `depends_on` dostatečný pro budoucí compare-before-write executor, včetně
   stropu (`max_writes` 0, 1 i 2)?
4. Zůstává `ENABLED=False`, bez I/O a bez executoru?

## Bezpečnost

- Testy jen: `python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py`
  (případně i `tests/test_outbox_terminal_backlog.py`). `tests/conftest.py` už chrání runtime DB a při
  změně jejího SHA běh shodí; i tak porovnej SHA šesti chráněných souborů z `AGENTS.md` před a po.
- Žádný server, deploy, Firebase, commit ani zápis mimo vlastní report.
- Verdikt: APPROVE (jen kód, plánovač dál nezapojený) nebo CHANGES_REQUIRED s reprodukcí.
