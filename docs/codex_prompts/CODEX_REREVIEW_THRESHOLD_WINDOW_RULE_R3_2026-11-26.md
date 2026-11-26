# Re-review rozhodovacího pravidla po měřicím okně, rev. 3 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_threshold_window_rule_r3.md`.

Verdikt: **APPROVE_RULE / CHANGES_REQUIRED**. Schválení se týká pravidla a jeho vyhodnocení. Případnou změnu
drop-inu po výsledku posoudíš samostatně.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_threshold_window_decision_rule.md` (rev. 3) | (viz commit) |
| `scripts/research/threshold_window_eval.py` (rev. 3) | `1f999cc1c0a5e8d9eaefbaa2cbcdc5dbe623ac1efcc4e4c78816a5a36f26d4d0` |
| `tests/test_threshold_window_eval.py` (24 testů) | `0533d5aebe30f1ff7c508597e732577657660bf88d0a24715f891f6c343b0755` |

## Opravy podle `_workspace/2026-11-26_codex_rereview_threshold_window_rule_r2.md`

1. **Holm má vždy oba kandidáty.**
   - `pvalues` dostane −10 i 0 vždy. Netestovatelný řez (|K| < 100 nebo prázdné D) dostane `None` a příznak
     `testable=False`.
   - `holm()` řadí `None` na konec, nikdy ho nezamítne a počítá ho v rodině. Druhý řez tak musí projít
     prvním krokem 0,025 / 2.
   - Integrační testy: D_−10 je prázdné, D_0 neprázdné.
     - `test_untestable_cut_stays_in_holm_family`: p(0) = 0,02 → `KEEP_CURRENT`.
     - `test_testable_cut_passes_first_holm_step`: p(0) = 0,01 → `TIGHTEN 0`.
     - p se nastavuje monkeypatchem `day_difference`, populace i ramena jsou skutečná.
2. **`pnl_usd`.**
   - `prepare()` už nedosazuje 0, chybějící nebo neplatná hodnota zůstane `None`.
   - `summary()` vykáže `missing_pnl_usd`. Při > 0 je `usd_status = NOT_EVALUABLE_MISSING_PNL_USD` a
     `cum_pnl_usd = pf = None`.
   - Rozhodnutí stojí jen na `pnl_pct`, který je fail-closed.
   - Test `test_missing_pnl_usd_marks_usd_metrics_not_evaluable`.

**Mutace (scratch kopie):**

| Mutace | Výsledek |
|---|---|
| netestovatelný řez vynechán z rodiny | zachytí 1 test |
| `pnl_usd or 0.0` | zachytí 1 test |
| `None` → `1.0` | přežije; je významově shodná (p = 1 se nezamítne a zůstává v rodině) |

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_threshold_window_eval.py`
a `protected_sha.py` před a po. Lokálně 24 testů prošlo a `PROTECTED_SAME`.
