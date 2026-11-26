# Review výsledku Stonkfly C1 (Codex, 2026-11-26)

Jen audit, bez SSH, běhu a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_review_stonkfly_c1_result.md`.

Verdikty:
- **A:** platnost běhu. ACCEPT / REJECT_RUN.
- **B:** výklad. APPROVE / CHANGES_REQUIRED.
- **C:** konkrétní zadání pro C2 (tiché KC).

## Vstupy (lokální, necommitnuté)

- Report: `_workspace/2026-11-26_stonkfly_c1_result.md`.
- Řádky z extrakce: `_workspace/stonkfly_eval_20261123/c1_rows_20261126.jsonl` (sha
  `e0b13ef83ac59ee306b456742800741f4308f4d21547736069c55bc80fced2a7`, end `count` 9287).
- Výsledek: `_workspace/stonkfly_eval_20261123/c1_result_20261126.json` (sha
  `687ab65840f2633824c14a1dd458339de0457e37bf953edac6d436206f274eca`).
- Skript: `scripts/research/stonkfly_relative_decoder_offline.py`. Hash `6c430bdf…` se ověřil před
  během a je shodný se schváleným pinem z `7ac080b`.

Analýzu lze zopakovat lokálně:
`python -B scripts/research/stonkfly_relative_decoder_offline.py analyse _workspace/stonkfly_eval_20261123/c1_rows_20261126.jsonl`.

## Hlavní výsledky

- **Q1: `direct_matches_a2`.**
  - D: ρ +0,30 na TRAIN i TEST.
  - L: ρ −0,23 na TRAIN i TEST.
  - RD a RL také replikují, slaběji.
- **Q2:** všechny čtyři příznaky `NOT_REPLICATED`.
- **Dekodér RD ± 2 Hz:** ≈ −8,7 bps na obchod.
- **KC a `changed_edges`:** 0 ve všech 9 287 řádcích.

## Ověř

1. **A:**
   - Odpovídá běh protokolu?
   - Extrakce zapsala na produkci dočasný `/tmp/c1_time.txt` s výstupem `/usr/bin/time` (smazán).
     Protokol měření času a RSS předepisoval, ale neříkal kam. Je to přijatelné?
2. **B:** Jsou závěry správně omezené? Jde o:
   - proxy, ne příčinu;
   - `NOT_REPLICATED`, ne absenci vztahu;
   - post hoc doplňky (minulý trend vs. budoucí pohyb, řidší kadence v TEST) jasně oddělené od
     verdiktu.
3. **C:** Navrhni rámec C2.
   - Jak diagnostikovat, proč KC nikdy nespikují, a oddělit to od `reward_mode=disabled`?
   - Vše mimo produkci (izolovaný stroj, `--smoke`), bez zásahu do `src/services/stonkfly/` bez
     plánu verzování checkpointu.
   - Zohledni post hoc zjištění, že proxy minulého trendu sama 600s pohyb nepředpovídá. Má C2/C3
     vůbec smysl pro cíl P/L, nebo je lepší Stonkfly ponechat jen jako výzkumný shadow?
