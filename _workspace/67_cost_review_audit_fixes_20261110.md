# Opravy auditu cost/learning review (F01–F04), 2026-11-10

> **Dodatek (2026-11-10):** nezávislé ověření `_workspace/68_codex_cost_review_verification_20261110.md`
> potvrdilo F01 a F04. U F02 a F03 našlo zbývající mezery (R01 vnitřní konzistence C1,
> R02 skutečné řádky a rozsahy pokrytí) a ztrátu identity vstupu mu (R03). Tvrzení níže, že
> jsou vstupní vady uzavřené, bylo předčasné. Pozitivní fixture C1 (upper 520 z 1 000,
> 28 bloků za 5 dní) nebyla dosažitelná evaluatorem. Opravy jsou v
> `_workspace/69_cost_review_r01_r03_fixes_20261110.md`.

Zadání: `docs/codex_prompts/CLAUDE_COST_REVIEW_AUDIT_FIXES_2026-11-10.md`. Audit:
`_workspace/66_codex_cost_review_audit_20261110.md` (nezměněn). Implementoval Claude.
Výchozí stav: HEAD `1758da85a29107d34eaf0f39539391aba5e4025d`, větev `main`; HEAD
na konci stejný. Auditovaný skript měl SHA `dc404106…e0e1` (shoda ověřena na začátku,
kopie v `cost_review_fixes_20261110/original/`). Žádný commit, push, SSH, deploy ani restart.

## F01–F04

| Nález | Příčina | Místo | Oprava | Test | Stav |
|---|---|---|---|---|---|
| F01 | `build()` načetl mu před kontrolou finálního C1 | `build`, nově `c1_review` | Pořadí: futures souhrn → manifest původu → výsledek C1 → kontroly → teprve pak mu. Bez C1, při PENDING/INSUFFICIENT_DATA, chybějící referenci, nesouladu nebo neplatném final se mu odmítne před otevřením (`BlindingRefusal`, exit 3). Pole `exposure` rozlišuje raw post-cutoff obchody (vždy ne), zmrazený výsledek C1 a mu podle skutečného čtení. JSON i Markdown uvádějí totéž a chyby nevypisují hodnoty. | `test_f01_*` (8 testů, spy loader se sentinelem, API i CLI) | PASS |
| F02 | Stačil řetězec CONFIRMED + neprázdný seznam ID | `verify_provenance`, `verify_result`, `verify_mu` | Kontrakt `c1_provenance_v1` (níže), konstanty protokolu z předregistrace, kontrola ID, součtů, CI, bloků, času a souladu verdiktu s intervaly. Mu je vázané na hash výsledku, hash ID množiny, cutoff, jednotku a nákladovou bázi. Statistiky se nepřepočítávají. | `test_f02_*` (3 verdikty, n = 1 137 s nestejnými skupinami, 19 nekonzistentních výsledků, 6 špatných manifestů, nesoulad hashe, starý artefakt bez původu, 7 špatných mu) | PASS |
| F03 | `statistics: {}` a chybějící coverage → OK | `futures_cost_table`, nově `coverage_review` | Povinné fáze, H1–H7 i oba targety; neznámé hypotézy a konflikt `n` se odmítnou. OK jen při doložených 7 symbolech a zdrojích futures/spot/metrics (`expected_rows` > 0, `missing_rows` a `missing_ranges` v souladu) a neprázdném fundingu. Zdokumentované mezery dávají PARTIAL, chybějící doklad NOT_VERIFIED. Počet rozsahů a chybějících řádků se uvádí zvlášť. U fundingu se mezery neodvozují. | `test_f03_*` (12 testů) | PASS |
| F04 | Obrácený interval a n = 0 dávaly rozpočty | `sensitivity`, `_interval`, `_count` | `lower > upper` → chyba; n = 0 → `{"status": "NO_DATA", "n": 0}` bez odhadů; bool, NaN, Infinity a necelé n se odmítnou. Interval, který neobsahuje průměr, je dál přípustný. | `test_f04_*` (14 případů) | PASS |

## Kontrakt původu C1 a hranice důvěry

```text
--c1-provenance-sha256  důvěryhodná reference: hash manifestu zaznamenaný nezávisle při
                        zmrazení C1 (např. zapsaný do docs/OPERATING_STATE.md), nikdy
                        odvozený z ověřovaných souborů
--c1-provenance         manifest c1_provenance_v1, čtený jednou; hash i parsování ze stejných bajtů:
  {"contract": "c1_provenance_v1", "hypothesis": "C1_contrarian",
   "scored_after_ms": 1794209516000, "run_id": "<UTC run ID>",
   "evaluated_at_ms": <čas vyhodnocení>, "result_sha256": "<sha prereg_result.json>",
   "id_hash_convention": "sha256(utf8(json.dumps(ids, separators=(',', ':'))))"}
--c1-result             prereg_result.json, čtený jednou; hash musí být result_sha256
--c1-mu                 {"contract": "c1_mu_v1", "result_sha256", "scored_set_sha256",
                         "scored_after_ms", "unit": "bps", "cost_basis": "paper_net_9bps", "mu_bps"}
```

- Hash prokazuje shodu s referencí, ne pravdivost obsahu. Bez reference je stav
  NOT_VERIFIED a výsledek se vůbec neotevře.
- Konstanty protokolu jsou v nástroji pevné podle předregistrace (dodatky 1–1c) a
  `src/services/learner_replay.py:56-78`: cutoff `1794209516000`, `final_n` 1 000,
  `min_days` 7, nejméně 16 bloků po 6 h, 7 × 24 h od cutoffu a 6 h od posledního
  hodnoceného vstupu. Sada může mít víc než 1 000 obchodů (dodatek 1c), podmínka
  `n == 1000` se nezavádí. Zaokrouhlené `days_elapsed` se nepoužívá; čas vyhodnocení
  dokládá `evaluated_at_ms` z manifestu.
- **Starší artefakty:** dnešní `deploy/research_eval/run_eval.sh` ani
  `learner_replay_report.py` manifest nezapisují. `prereg_result.json` neobsahuje čas
  vyhodnocení ani run ID. Skutečný výsledek C1 proto zůstane NOT_VERIFIED, dokud se při
  zmrazení nezaznamená manifest a jeho hash. Doplnění do serverového běhu je samostatná
  změna mimo tento úkol (po review). Metadata se nedoplňují odhadem a zmrazený evaluator
  se neměnil.
- Hash seznamu ID má verzovanou konvenci (viz výše). Shoda ID sama nenahrazuje vazbu na běh.

## Testy a mutace

- `rtk python _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short`
  → **85 PASS**, 0 FAIL. Původně 16 testů; žádný test nebyl odstraněn kvůli zelenému
  výsledku. Fixtures jsou upravené na skutečné schéma (n na úrovni hypotézy, 7 symbolů,
  zdroje coverage). Neplatnou pozitivní fixture (3 ID proti 520 + 480) nahradila
  konzistentní syntetická `_c1()` s 1 000 ID a provenancí.
- Mutace (`cost_review_fixes_20261110/mutations.py`, jen v dočasné kopii, výsledky
  `mutation_results.json`): baseline 85 PASS. **Všech 13 mutací zachyceno** (F01: 2,
  F02: 6, F03: 3, F04: 2). Po obnovení opět 85 PASS. Dvě původně navržené mutace F03 byly
  ekvivalentní: chybějící coverage zachytí i kontrola universe symbolů a pořadí sloučení
  `n` je nepodstatné, protože konflikt se odmítne dřív. Nahradil jsem je mutacemi, které
  vracejí skutečnou původní vadu (obě kontroly coverage současně, resp. odstranění kontroly
  konfliktu). Auditní reprodukce jsem neupravoval.
- Syntaxe pro Python 3.12 (AST `feature_version=(3,12)`): PASS. Ruff NOT_RUN.

## Smoke test nad zmrazeným souhrnem

`rtk python -B scripts/research/cost_and_learning_review.py --futures-report _workspace/futures_flow_20261109/screen/report.json --out _workspace/cost_review_fixes_20261110/frozen_smoke`
→ exit 0, `c1=PENDING`, `coverage=PARTIAL`.

- **42 buněk (7 × 3 × 2): všechny aritmeticky shodné** s původním
  `_workspace/cost_and_learning_review_20261110/review.json` (n, gross, CI, net pro
  0/9/15/18/20, budgety). Doklad je `smoke_compare.json`. Nové je jen pole `status: OK`.
- Očekávané změny: schéma 1 → 2, `exposure` místo `post_cutoff_outcomes_opened`,
  coverage OK → PARTIAL (28 rozsahů; 10 990 chybějících řádků v intervalu zdroje: metrics
  TRAIN 889, TEST 21, futures HOLDOUT 10 080 minut).

## Integrita (SHA před = po)

`sha_before.txt` / `sha_after.txt`: shodné pro šest chráněných runtime souborů
(`cache.sqlite` `31767b56…`, `paper_open_positions.json` `44136fa3…` atd.), zmrazený
`report.json`, report 66 a auditní důkazy `cost_review_audit_20261110/*`. Změnily se jen
dva povolené soubory: skript `e8e88256…` a testy `53b813dc…`
(`sha_changed_files_after.txt`).

## CLI

- Bez C1: `python -B scripts/research/cost_and_learning_review.py --futures-report <report.json> --out <nový adresář>`.
- Ověřený syntetický final je v testech (`_final_set`):
  `--c1-result <syntetický prereg_result.json> --c1-provenance <manifest> --c1-provenance-sha256 <hash manifestu>`
  a případně `--c1-mu <mu.json>`. Příkaz nad skutečným C1 neuvádím: C1 je PENDING a
  manifest neexistuje.
- Návratové kódy: 0 = report zapsán (včetně PENDING/NOT_VERIFIED), 2 = poškozený nebo
  nekonzistentní vstup, 3 = odmítnuto pravidly slepoty (mu bez ověřeného finálního C1).
  Při 2 a 3 se nic nezapisuje.

## Změněné soubory

- `scripts/research/cost_and_learning_review.py`, `tests/test_cost_and_learning_review.py`
- erratum v `_workspace/65_codex_cost_and_learning_review.md`
- tento report a `_workspace/cost_review_fixes_20261110/` (original/, mutations.py,
  mutation_results.json, frozen_smoke/, smoke_compare.json, sha_*.txt, baseline_*.txt)

## Výslovně

Žádné skutečné C1 outcomes ani mu nebyly otevřeny, futures HOLDOUT nebyl znovu
vyhodnocen, bot, server, runtime data ani AGENTS.md se nezměnily, žádný
deploy/restart/commit/push. Opravy nejsou důkazem edge, ziskovosti ani potvrzením C1.

## Zbývající omezení

- Serverový běh nezapisuje manifest původu, takže skutečný C1 zatím nejde ověřit
  (navazující změna po review).
- Mu je vázané na hash výsledku, ale jeho vlastní původ (kdo spočítal agregát) není
  součástí kontraktu v1.
- Konzistenci verdiktu s intervaly nástroj kontroluje, správnost samotných intervalů ne
  (nepřepočítává se).
