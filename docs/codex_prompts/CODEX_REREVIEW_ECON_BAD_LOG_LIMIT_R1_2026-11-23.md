# Re-review: omezení výpisů `REJECT_ECON_BAD_ENTRY`, kolo 2 (nález R1) (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r1.md`.
Verdikt APPROVE / CHANGES_REQUIRED (kód). Nasazovací krok tím schválený není.

## Kontext

Tvé review `_workspace/2026-11-23_codex_review_econ_bad_log_limit.md` (R1: chyba zápisu souhrnu ztratí
počty). Oprava je popsaná v oddílu „Kolo 2“ reportu `_workspace/2026-11-23_claude_econ_bad_journal_volume.md`:
- čekající agregát `_pending`;
- `observe()` vrací `(emit, summary, token)`;
- `ack(token)` jen po úspěšném zápisu;
- slučování oken s omezenou kardinalitou;
- `windows=N` v souhrnu.

Soubory (necommitnuto): `src/services/realtime_decision_engine.py` (diff
`_workspace/econ_bad_journal_20261123/rde.diff`, postimage `07e3b7bf…2a5e`),
`tests/test_econ_bad_reject_log_limit.py`, `_workspace/econ_bad_journal_20261123/mutations.py`
a `mutation_results.json`.

## Co ověřit

1. Zopakuj svou reprodukci R1. Zůstanou počty `rejects=3 suppressed_details=2` po jednorázové chybě
   zachované a zapíše je další úspěšný souhrn?
2. Opakované chyby: je paměť omezená a souhrn po obnovení přesný?
3. Logika tokenu a zámku: nemůže se agregát smazat bez úspěšného zápisu? Je přijatelná uvedená mez
   (možné zdvojení v logu, když zápis trvá déle než okno)?
4. Zůstává beze změny vše, co jsi dřív ověřil? Rozhodnutí, `track_blocked`, near-miss, invariant,
   vypnutý příznak.

## Bezpečnost

- Žádné SSH, nasazení, Firebase ani commit.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_econ_bad_reject_log_limit.py "tests/test_v10_13u_patches.py::test_v10_13u19c_econ_bad_entry_return_trace_emits_on_weak_ev_reject" "tests/test_v10_13u_patches.py::test_v10_13u19c_ready_but_rejected_invariant_emits"`
- Hashe chráněných souborů před a po přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
