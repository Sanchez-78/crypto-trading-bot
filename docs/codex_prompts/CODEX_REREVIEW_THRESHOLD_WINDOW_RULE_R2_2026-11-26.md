# Re-review rozhodovacího pravidla po měřicím okně, rev. 2 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_threshold_window_rule_r2.md`.

Verdikt: **APPROVE_RULE / CHANGES_REQUIRED**. Schválení se týká pravidla a jeho vyhodnocení. Případnou změnu
drop-inu po výsledku posoudíš samostatně.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_threshold_window_decision_rule.md` (rev. 2) | (viz commit) |
| `scripts/research/threshold_window_eval.py` (rev. 2) | `80c742dec44e22c425181dd5dcd63dd9b3501b0235f4dabce70834de6eeb5bd5` |
| `tests/test_threshold_window_eval.py` (21 testů) | `88904a7f1cd077a722b77a9f71a62675d9b7d32a80309697ef19c4b8764ff65b` |

## Opravy podle `_workspace/2026-11-26_codex_review_threshold_window_rule.md`

1. **Baseline −25.**
   - Populace brány G = platná predikce ≥ −25.
   - Ponechané K_c = predikce ≥ c, nově vyřazené D_c = −25 ≤ predikce < c. Obchody pod −25 ani bez
     predikce se do D_c nedostanou.
   - Test `test_trades_below_current_cut_never_make_a_cut_eligible`: v G není rozdíl a přidáno 700 obchodů
     s predikcí −40 a −80 bps, výsledek `KEEP_CURRENT`.
2. **Minimum 1 000 jen z G.**
   - Všechny obchody, chybějící predikce a obchody pod −25 se vykazují jen popisně.
   - Test `test_minimum_counts_only_the_gate_population`: 900 v G + 400 mimo → `INSUFFICIENT_DATA`.
3. **Holm.**
   - Jednostranné bootstrap p = (počet rozdílů ≤ 0 + 1) / (platné + 1), převrácení CI.
   - Holm přes {−10, 0} na rodinné hladině 0,025, jednostranně.
   - Chybějící p se nezamítá a proceduru zastaví.
   - 5 parametrizovaných testů `holm`.
4. **Bez `--now`.**
   - CLI má jen `--db`; čas je `time.time()`.
   - Testy čas nahrazují monkeypatchem. Test, že `--now` CLI odmítne, a test běhu po `END + 1800 s`.
5. **Interpretace.**
   - WR není v pravidle a vyšší WR je hypotéza.
   - Výsledek je prediktivní třídění.
   - Žádná automatická změna konfigurace: při `TIGHTEN` připravím postimage a pošlu ho k samostatnému
     review.

**Mutace (ve scratch kopii)** zachytí testy:

| Mutace | Selhané testy |
|---|---:|
| D_c ze všech řádků | 2 |
| minimum ze všech řádků | 1 |
| bez Holma | 1 |

**Smoke test rev. 2 jen na 7 dnech před T0:** `KEEP_CURRENT`. Řez 0 p = 0,0147 > 0,0125, řez −10
p = 0,038. Čísla jsou v pravidle.

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_threshold_window_eval.py`
a `protected_sha.py` před a po.
