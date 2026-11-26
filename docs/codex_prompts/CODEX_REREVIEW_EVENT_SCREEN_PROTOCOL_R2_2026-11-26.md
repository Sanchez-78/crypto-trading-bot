# Re-review předregistrace EVENT screen E1/E2, rev. 2 (Codex, 2026-11-26)

Jen audit, bez běhu screenu a bez commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_event_screen_protocol_r2.md`.
Verdikt: **APPROVE_TO_RUN / CHANGES_REQUIRED**.

Navazuje na `_workspace/2026-11-26_codex_review_event_screen_protocol.md`.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_event_screen_protocol.md` (rev. 2) | `e2b41ab88a39bda443f5ad12884e41899eb0c12ae9dce6076c1cf74c11617e1f` |
| `scripts/research/event_shock_screen.py` | `3304a30a75938f9cea3498b6fbf6e143eced008e2f3fda1f0d6270bd91cda842` |
| `tests/test_event_shock_screen.py` (11 testů) | `234a71381665c3da7dc6abcbee92d425f6f22531d5f3c589d4cbef22ddeaa3dd` |
| `scripts/research/futures_flow_screen.py` (beze změny) | `a393d07682630136efd5c29ed6cd6bafbd0cf9b595b32b5c5fff9b5eb1c1328f` |

**Stav dat:** po tvém review jsem stáhl a ověřil archivy, bez jakéhokoli výpočtu. 476/476 archivů
(futures 1m a funding, 7 symbolů, 2024-01 až 2026-10) má stav OK se SHA-256 podle `.CHECKSUM` od
Binance. Leží v `C:\Projects\_research_cache\binance` (404 MB). Žádné TRAIN/TEST/HOLDOUT statistiky
nevznikly.

## Opravy

1. **p-hodnota.** Nulový bootstrap je teď explicitní: `null_sums = sums − net·counts` (každý vzorek
   vycentrovaný o pozorovaný průměr), stejné losy dnů a p = (1 + #{null ≥ net}) / (B + 1).
   - **Věcná poznámka k nálezu:** při stejných losech je null průměr přesně
     `(Σ sums − net·Σ counts) / Σ counts = boot − net`. Původní `(boots − net) >= net` byl tedy
     algebraicky totožný s centrovaným testem. Netestoval dvojnásobek průměru proti nule, ale
     posunuté rozdělení proti pozorovanému průměru.
   - Explicitní forma je přesto čitelnější, takže jsem ji převzal.
   - Testy:
     - `test_null_bootstrap_matches_an_independent_recentred_computation`: nezávislá reimplementace
       centrováním každého vzorku dává stejné p;
     - `test_null_bootstrap_p_value_behaves_as_a_test_of_mean_net9_above_zero`: silně kladný
       průměr → p < 0,01, nula → 0,05 < p < 0,95, záporný → p > 0,99.
2. **Úplnost archivů.** `check_complete()` v `run()` před jakoukoli etapou vyžaduje všechny
   očekávané klíče (`expected_jobs(end)`) se stavem OK a SHA-256. Jinak `SystemExit NOT_EVALUABLE`
   bez zápisu `train.json` nebo `train.started.json`.
   - Test `test_run_refuses_an_incomplete_archive_set_before_any_stage` pokrývá chybějící,
     nenalezený i offline prázdnou cache.
3. **Role TRAIN.** `train.json` nese `role: IN_SAMPLE_SELECTION_DESCRIPTIVE_ONLY…` a `verdict.json`
   nese `train_role`. Protokol výslovně uvádí, že potvrzující jsou jen TEST a HOLDOUT.

Lokálně: 11 testů prošlo a `PROTECTED_SAME`.

**Ověř:** Jsou body 1–3 uzavřené? Lze spustit:

```
python scripts/research/event_shock_screen.py --cache C:/Projects/_research_cache/binance \
    --out _workspace/event_screen_20261126 --end 2026-10 --offline
```

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_event_shock_screen.py`.
