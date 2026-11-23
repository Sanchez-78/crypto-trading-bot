# Review: omezení detailních výpisů `REJECT_ECON_BAD_ENTRY` (Codex, 2026-11-23)

Jen audit, žádná implementace. Report napiš česky do
`_workspace/2026-11-23_codex_review_econ_bad_log_limit.md`. Verdikt APPROVE / CHANGES_REQUIRED (kód).
Nasazovací krok tím schválený není.

## Kontext

Zadání: `docs/codex_prompts/CLAUDE_ECON_BAD_JOURNAL_VOLUME_2026-11-23.md`. Report implementace:
`_workspace/2026-11-23_claude_econ_bad_journal_volume.md`. Necommitnuto v pracovním stromu:
- `src/services/realtime_decision_engine.py` (diff `_workspace/econ_bad_journal_20261123/rde.diff`,
  preimage `realtime_decision_engine.before.py`);
- `tests/test_econ_bad_reject_log_limit.py`;
- mutace `_workspace/econ_bad_journal_20261123/mutations.py` + `mutation_results.json`.

## Co ověřit

1. Je přesun side effectů do `_econ_bad_reject_outputs()` věrný? Stejné pořadí a argumenty,
   `return None` ve větvi, `score=_score_adj`, `coherence=_coh`, `ctx=_probe_ctx`.
2. Mění se při **vypnutém** příznaku cokoli na výstupu nebo v chování? Nesmí.
3. Při zapnutém příznaku: jsou omezené jen `[ECON_BAD_ENTRY_RETURN_TRACE]` a `print`?
   - Běží resolver uvnitř trace funkce dál?
   - Zůstává `[ECON_BAD_READY_BUT_REJECTED]`?
   - Jsou správné počty v souhrnu, hranice okna a omezená kardinalita?
   - Je vše thread-safe a bez výjimek?
4. Jsou testy dostatečné? Zachytí mutace obě povinné chyby (vrácený výpis, vynechaný `track_blocked`)?
   Navrhni chybějící.
5. Je správné vložit omezovač přímo do RDE, aby se nasazoval jeden soubor? Nové soubory nasazovací
   nástroj neumí.
6. Je návrh nasazení v reportu úplný? Serverová preimage je NOT_VERIFIED.

## Bezpečnost

- Žádné SSH, nasazení, Firebase ani commit.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_econ_bad_reject_log_limit.py "tests/test_v10_13u_patches.py::test_v10_13u19c_econ_bad_entry_return_trace_emits_on_weak_ev_reject" "tests/test_v10_13u_patches.py::test_v10_13u19c_ready_but_rejected_invariant_emits"`
- Hashe chráněných souborů před a po přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
  Pozor: v čisté kopii stromu import RDE vytvoří `runtime/firebase_cache.sqlite` (starší vedlejší efekt,
  guard v conftestu ho hlásí). V hlavním stromu soubor existuje.
