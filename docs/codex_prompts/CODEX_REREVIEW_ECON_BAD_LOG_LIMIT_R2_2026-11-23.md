# Re-review: omezení výpisů `REJECT_ECON_BAD_ENTRY`, kolo 3 (nález R2) (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md`.
Verdikt APPROVE / CHANGES_REQUIRED (kód). Nasazovací krok tím schválený není.

## Kontext

Tvé re-review `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r1.md` (R2: `StreamHandler` spolkne
chybu zápisu a potvrzení smaže neodeslaný souhrn). Řešení je popsané v oddílu „Kolo 3“ reportu
`_workspace/2026-11-23_claude_econ_bad_journal_volume.md`. Kontrakt jsem změnil podle tvé druhé
možnosti: potvrzování je odstraněné. Každý souhrn nese `seq` a kumulativní součty od startu procesu.
Ztráta řádky se pozná podle mezery v `seq` a její počty jsou v součtech další řádky.

Soubory (necommitnuto): `src/services/realtime_decision_engine.py` (diff
`_workspace/econ_bad_journal_20261123/rde.diff`, postimage `95e499e7…2c03`),
`tests/test_econ_bad_reject_log_limit.py`, `_workspace/econ_bad_journal_20261123/mutations.py`
a `mutation_results.json`.

Poznámka: tvůj reproduktor `_workspace/econ_bad_r1_independent_repro_20261123.py` volá odstraněné
`pending_snapshot()`. Pro ověření ho uprav na `totals_snapshot()` nebo čti pole `seq` a `total_*` ze souhrnu.

## Co ověřit

1. Ztratí se se skutečným `StreamHandler` a chybujícím streamem nějaké počty? Je mezera v `seq`
   viditelná a obsahují součty další řádky ztracené okno?
2. Je paměť omezená (součty se stropem kategorií)? Jsou počty přesné při souběhu?
3. Je nový kontrakt a jeho mez (ztráta poslední řádky před koncem procesu, reset `seq` při restartu)
   jasně zdokumentovaný v kódu i reportu?
4. Zůstává beze změny vše, co jsi dřív ověřil? Rozhodnutí, `track_blocked`, near-miss, invariant,
   vypnutý příznak a pořadí ve větvi.

## Bezpečnost

- Žádné SSH, nasazení, Firebase ani commit.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_econ_bad_reject_log_limit.py "tests/test_v10_13u_patches.py::test_v10_13u19c_econ_bad_entry_return_trace_emits_on_weak_ev_reject" "tests/test_v10_13u_patches.py::test_v10_13u19c_ready_but_rejected_invariant_emits"`
- Hashe chráněných souborů před a po přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
