# Codex audit: producer manifestu původu C1 (2026-11-10)

**Role:** nezávislý auditor. Codex jen ověřuje a radí; implementaci provedl Claude.
**Report:** `_workspace/70_codex_c1_provenance_producer_audit.md` (česky), důkazy do
`_workspace/c1_provenance_audit_20261110/`. Nic jiného neměň.
**Zakázáno:** commit, push, SSH, deploy, restart, reset, stash, clean; změna kódu, testů,
předregistrace, cutoffu nebo runtime dat. Skutečné post-cutoff outcomes C1 neotvírej.
Používej jen syntetická data.

## Proč a termín

`scripts/research/cost_and_learning_review.py` (reporty 67 a 69) přijme skutečný výsledek
C1 jen s manifestem `c1_provenance_v1`, zaznamenaným **při původním zmrazení**. Server ho
zatím nezapisuje. První možné zmrazení je při běhu 2026-11-16 17:47 UTC (7 dní od cutoffu
2026-11-09 07:31:56 UTC; vyhodnocení běží 05:47 a 17:47). Pokud do té doby producer
nebude nasazený, skutečný C1 zůstane v nástroji natrvalo NOT_VERIFIED. Nasazení proběhne
až po tomto auditu.

## Předmět auditu (poslední commit, který mění `scripts/research/learner_replay_report.py`; `git log -1 -- scripts/research/learner_replay_report.py`)

- `scripts/research/learner_replay_report.py`: `frozen_preregistered()` při prvním
  konečném verdiktu zapíše `prereg_provenance.json` (contract, hypothesis, scored_after_ms,
  run_id, evaluated_at_ms = stejný `now_ms`, jaký dostal evaluator, result_sha256 přesně
  zapsaných bytů, id_hash_convention), oba soubory jsou 0444. Vrací `(result, sha|None)`.
  `main()` přidává `--run-id` a do výstupní řádky `provenance_sha256=` jen v běhu, který
  zmrazil.
- `deploy/research_eval/run_eval.sh`: předává `--run-id "$run_id"`. Řádka REPLAY se
  připisuje do append-only `verdict.log`; ta je nezávislou referencí hashe manifestu.
- `tests/test_replay_blinding.py`: 4 nové testy a jedna doplněná kontrola.
- Důkazy: `_workspace/cost_review_r01_r03_fixes_20261110/provenance_mutations.py` a
  `provenance_mutation_results.json` (6/6 mutací zachyceno).

## Co ověřit

1. **Evaluator se nemění:** verdikt, hodnocená množina, čas a kritéria jsou stejné jako
   před změnou. Jediný rozdíl je zachycení `now_ms` do proměnné. Porovnej s rodičovským
   commitem a se serverovou verzí (SHA `7362a118…877f` = verze před změnou).
2. **Slepota:** producer nevypisuje ani neloguje outcome hodnoty, nic dalšího se před
   zmrazením nečte, PENDING ani INSUFFICIENT_DATA nic nezapíšou.
3. **Vazba:** `result_sha256` odpovídá přesně bytům `prereg_result.json`, `evaluated_at_ms`
   je čas vyhodnocení a ne čas pozdějšího reportu, cutoff se shoduje s předregistrací.
   Konvence ID se shoduje s `cost_and_learning_review.ID_HASH_CONVENTION`.
4. **Pořadí a pády:** manifest se zapisuje před výsledkem (výsledek je marker zmrazení).
   Posuď pád mezi zápisy, opakované běhy, souběh (zámek v `run_eval.sh`), práva 0444 a
   přepsání osiřelého manifestu při dalším běhu. Je hash v `verdict.log` jako reference
   dostatečně nezávislý? Navrhni lepší místo, pokud existuje bez nové služby.
5. **Kompatibilita:** stávající zmrazený výsledek (soubor bez manifestu) se dál vrací beze
   změny. `run_eval.sh` funguje i bez `prereg_after`. Nasazení nevyžaduje restart bota
   (jen kopie do `/opt/cryptomaster_research/code` a `run_eval.sh`).
6. **Testy:** jsou dostatečné? End-to-end test
   `test_produced_manifest_is_accepted_by_cost_review` (reálný cutoff, 2 000 replikací)
   trvá ~3 min. Je to přijatelné, nebo ho označit jako pomalý?
7. **Plán nasazení:** zkontroluj a doplň postup níže.

## Navržený postup nasazení (Claude, po auditu)

1. Záloha `/opt/cryptomaster_research/code/scripts/research/learner_replay_report.py` a
   `/opt/cryptomaster_research/run_eval.sh` (SHA před).
2. Ověřit, že `prereg_result.json` neexistuje a žádný běh neprobíhá (zámek `.run.lock`).
3. Kopie dvou souborů, ověření SHA po, `bash -n`, `python3 -m py_compile` do dočasného
   adresáře.
4. Neinvazivní ověření: `learner_replay_report.py --json <syntetický export> ...` do
   dočasného adresáře na serveru, ne nad skutečnou DB po cutoffu.
5. Další běh časovače ověřit podle `STATUS OK` a REPLAY řádky (PENDING, bez provenance).
6. Rollback: obnova obou souborů ze zálohy.

## Výstup

Verdikt APPROVE / CHANGES_REQUIRED, nálezy s prioritou, `soubor:řádek` a syntetickou
reprodukcí, příkazy a výsledky testů (jen `tests/test_replay_blinding.py`,
`tests/test_learner_replay.py`, `tests/test_cost_and_learning_review.py`) a SHA chráněných
runtime souborů před a po (`AGENTS.md`). Odděl ověřené od předpokládaného.
