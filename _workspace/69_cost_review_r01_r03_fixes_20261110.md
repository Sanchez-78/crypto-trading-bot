# Opravy R01–R03 (audit 68), 2026-11-10

Zadání: `docs/codex_prompts/CLAUDE_COST_REVIEW_R01_R03_FIXES_2026-11-10.md`. Audit:
`_workspace/68_codex_cost_review_verification_20261110.md` (nezměněn). Implementoval Claude.

Výchozí stav (`cost_review_r01_r03_fixes_20261110/baseline_*.txt`): HEAD
`43137334a3566c3a659f1dd6dad6ac5b11ee7fd0`, větev `main`. Skript a testy bez lokálního diffu,
SHA skriptu `e8e88256…0bd6e` = auditovaná verze. Kopie výchozích souborů je v `original/`.
HEAD na konci je stejný. Žádný commit, push, SSH, deploy, restart ani reset.

## R01–R03

| Nález | Příčina | Změna | Test | Stav |
|---|---|---|---|---|
| R01 | `verify_result` nekontroloval počet platných replikací, horní mez bloků, velikost mediánových skupin ani prázdná ID; pozitivní fixture byla nedosažitelná | `valid` je int bez bool a 1 800 ≤ valid ≤ 2 000 (`learner_replay.py:214-234`). Bloky: 16 ≤ blocks ≤ min(n, `last//6h − (cutoff+1)//6h + 1`). `upper_n ≤ n // 2` a obě skupiny ≥ 5 (`score()`, `learner_replay.py:160-175`), součet zachován. ID jsou neprázdné `str` (`learner_replay_report.py:44-47`). Konstanty jsou v kódu s odkazy, ne ze vstupu. | `test_r01_impossible_final_rejected_and_mu_unopened` (11 případů, mu sentinel na cestě `build()`), `test_r01_boundary_values_accepted` (valid 1 800/2 000, 21 bloků, upper 500 a 5), `test_r01_split_means_stays_generic` | PASS |
| R02 | `coverage_review` nečetl `rows` ani obsah rozsahů | Pro futures/spot (1 min) a metrics (5 min) podle `futures_flow_screen.source_coverage:448-461`: nezáporné int bez bool, `rows + missing = expected`, `missing ≤ expected`, každý rozsah má start/end/count > 0, `end − start = count × krok`, rozsahy jsou seřazené, bez překryvu i dotyku (producer je ukládá jako maximální běhy) a jejich součet = missing. Kde blok ukládá `start_ms`/`end_ms`: expected = ⌈span/krok⌉ a rozsahy leží v bloku na mřížce. Chybějící `rows` nebo expected = 0 → NOT_VERIFIED. Rozporné nebo poškozené údaje → chyba (exit 2). Zdroj bez řádků a konzistentně celý chybějící → NO_DATA. Funding se kontroluje jen na přítomnost. | `test_r02_inconsistent_coverage_rejected_on_cli` (12 případů, exit 2), `test_r02_missing_rows_field_is_not_verified`, `test_r02_documented_gap_1m_and_5m_is_partial`, `test_r02_entirely_missing_source_is_no_data_not_ok`, `test_r02_funding_irregular_and_missing_bounds_tolerated` | PASS |
| R03 | `mu, _ = loader(...)` zahodil hash; `inputs` neuváděl manifest ani referenci | `inputs` (schéma 3): `c1_provenance_sha256_expected` (reference od operátora), `c1_provenance_sha256_observed` (hash přečtených bytů), `c1_provenance_verified`, `c1_result_sha256_expected`/`_observed`/`_verified`, `c1_mu_sha256_observed`, `c1_run_id` a dál `futures_report_sha256`. Co se nečetlo, má null. Reference se nikdy nevydává za pozorovaný hash. Hash pochází ze stejných bytů, které parser čte; mu se hashuje až po ověřeném finálním C1. Markdown uvádí totéž. | `test_r03_mu_hash_tracks_the_bytes_used`, `test_r03_identical_bytes_identical_report`, `test_r03_mismatch_keeps_observed_apart_from_expected`, `test_r03_reference_without_reading_is_not_reported_as_observed`, `test_r03_no_mu_hash_without_permission` | PASS |

Hranice důvěry beze změny: hash prokazuje shodu s referencí, ne vnitřní bezrozpornost. Tu
kontroluje R01. Hash mu identifikuje použitý soubor, ale neprokazuje správnost výpočtu ani
autorství. Horní mez bloků je nutná podmínka; časy jednotlivých vstupů artefakt nenese a
nebyly ověřeny.

**Rozhodnutí u R02:** zmrazený souhrn ukládá `start_ms`/`end_ms` jen pro TEST a HOLDOUT, ne
pro TRAIN. Hranice TRAIN nástroj nedopočítává z protokolu. U TRAIN se ověří vnitřní
konzistence počtů a rozsahů a výstup uvádí `grid_bounds_checked: false`.

**Opravené fixtures:** `_c1()` má n = 1 000, upper 480 / lower 520, 16 bloků, valid 2 000 a
poslední vstup cutoff + 5 dní. Delší prefix je n = 1 137 s upper 551 / lower 586. Pokrytí je
v kompletním formátu produceru na syntetické mřížce s neplatným zarovnáním na minutu; TEST
a HOLDOUT mají hranice, TRAIN ne (jako reálný souhrn).

## Testy a mutace (ověřeno v tomto úkolu)

- `rtk proxy python -B _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short`
  → **124 PASS**, 0 FAIL. Výchozích 85 testů zůstalo, upraveny byly jen fixtures a dvě
  očekávané hodnoty q (520 → 480, 601/1 137 → 551/1 137).
- `cost_review_r01_r03_fixes_20261110/mutations.py` (izolovaná kopie, výsledky
  `mutation_results.json`): baseline 124 PASS. **Všech 21 mutací zachyceno** (R01: 7,
  R02: 10, R03: 4), žádná chyba importu ani kolekce. Po obnovení 124 PASS.
- AST Python 3.12 (skript, testy, mutační skript): PASS. Ruff NOT_RUN.
- Reproduktor auditu 68 jsem spustil jen v kopii (ve scratchpadu), protože přepisuje svůj
  `reproductions.json`. Na prvním vadném vstupu (`valid=0`) teď skončí chybou
  `ReviewError: bootstrap valid replicates outside the protocol range`. To je očekávané
  odmítnutí; reproduktor výjimky nezachytává. Auditní důkazy se nezměnily.

## Smoke test nad zmrazeným souhrnem

`python -B scripts/research/cost_and_learning_review.py --futures-report _workspace/futures_flow_20261109/screen/report.json --out _workspace/cost_review_r01_r03_fixes_20261110/frozen_smoke`
→ exit 0, C1 PENDING, coverage **PARTIAL, 28 rozsahů, 10 990 řádků v intervalu zdroje**,
`grid_bounds_checked` TEST/HOLDOUT ano, TRAIN ne. **42/42 buněk shodných** s původním
`_workspace/cost_and_learning_review_20261110/review.json` (n, gross, CI, net 0/9/15/18/20,
rozpočty; `smoke_compare.json`). Všech 63 zdrojových záznamů skutečného souhrnu splnilo nový
kontrakt (kontrola před implementací). Všechna C1 pole v `inputs` jsou null; hash futures
souhrnu je `30163589…e77a`.

## Integrita

`sha_before.txt` = `sha_after.txt` pro šest chráněných runtime souborů, zmrazený
`report.json`, audit 68 a `cost_review_verification_20261110/*`. Změnily se jen povolené
soubory: skript `53933ebe…` a testy `adbe3973…` (`sha_changed_files_after.txt`).

## Diff vůči výchozímu stavu

- `scripts/research/cost_and_learning_review.py` (+152/−40 vůči HEAD = výchozí stav): konstanty protokolu, R01 v `verify_result`, `_check_gap_source` a `NO_DATA` v
  `coverage_review`, `empty_identity` a identita v `c1_review`/`build`/`render`, schéma 3.
- `tests/test_cost_and_learning_review.py`: fixtures a 39 nových testovacích případů (124 − 85).
- Dodatek v reportu 67, tento report a `_workspace/cost_review_r01_r03_fixes_20261110/`.

## Výslovně

Skutečné C1 outcomes ani mu nebyly otevřeny. Futures HOLDOUT nebyl znovu vyhodnocen, pouze
přečten zmrazený souhrn. Bot, server, evaluator C1, předregistrace ani runtime data se
nezměnily. Nic z toho není důkaz edge ani ziskovosti.

## Zbývající omezení

- Serverový producer manifestu `c1_provenance_v1` neexistuje. Skutečný C1 zůstane
  NOT_VERIFIED, dokud se při původním zmrazení nezaznamená manifest s časem a identitou běhu
  (samostatná změna po review). Pozdější čas reportu nesmí nahradit čas zmrazení.
- Hranice TRAIN chybí ve zmrazeném souhrnu, takže mřížka TRAIN není ověřena vůči bloku.
- Autorství a správnost výpočtu mu kontrakt v1 neověřuje.
