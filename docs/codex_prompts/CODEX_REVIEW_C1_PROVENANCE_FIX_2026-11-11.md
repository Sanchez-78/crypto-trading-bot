# Codex: nezávislé re-review produceru původu C1 po opravě A1/A2 (2026-11-11)

**Role:** nezávislý reviewer. Implementaci i předchozí audit 70 provedl Claude (autor), proto
je potřeba nezávislý pohled. Codex jen ověřuje a radí.
**Report:** `_workspace/71_codex_c1_provenance_fix_review.md` (česky), důkazy do
`_workspace/c1_provenance_fix_review_20261111/`. Nic jiného neměň.
**Zakázáno:** commit, push, SSH, deploy, restart, reset, stash, clean; změna kódu, testů,
předregistrace, cutoffu nebo runtime dat. Skutečné post-cutoff outcomes C1 neotvírej. Jen
syntetická data.
**Termín:** výsledek před 2026-11-16 17:00 UTC (první možné zmrazení C1 je 17:47 UTC).

## Předmět

Commity `c1fe52c` (producer manifestu) a `efc3447` (oprava A1/A2) ve
`scripts/research/learner_replay_report.py`, `deploy/research_eval/run_eval.sh` a
`tests/test_replay_blinding.py`. Kontext: původní zadání
`CODEX_AUDIT_C1_PROVENANCE_PRODUCER_2026-11-10.md`, report 70 s dodatkem a konzument
`scripts/research/cost_and_learning_review.py` (reporty 67 a 69).

## Ověř

1. Evaluator, kritéria, hodnocená množina a slepota se nemění (porovnej se serverovou verzí
   SHA `7362a118…877f`, tj. rodič `c1fe52c`).
2. Uzavření A1: existuje-li zmrazený výsledek, je jeho řádka `PROVENANCE` v logu s `fsync`
   vždy předem, a to i když selže pozdější krok `run_eval.sh` nebo zápis `replay.*`.
   Posuď osiřelé řádky a manifesty po pádu před markerem a jejich jednoznačnost pro
   operátora (run ID), opakované běhy a zámek.
3. Uzavření A2: zmrazení bez `--run-id`/`--provenance-log` není možné v CLI ani v knihovně.
   Rozbije povinnost argumentů běžný běh bez `--prereg-result` nebo PENDING běh?
4. Konzument přijme manifest skutečného evaluatoru
   (`test_produced_manifest_is_accepted_by_cost_review`) a odmítne nesoulad.
5. Plán nasazení v reportu 70 (doplněný), včetně ověření na serveru jen synteticky a
   rollbacku. Chybí něco?

Testy jen `tests/test_replay_blinding.py`, `tests/test_learner_replay.py`,
`tests/test_cost_and_learning_review.py`. Mutace jen v izolované kopii.
Kontroluj SHA chráněných runtime souborů před a po.

## Výstup

APPROVE / CHANGES_REQUIRED, nálezy s prioritou a `soubor:řádek`, syntetické reprodukce,
příkazy, výsledky testů a odlišení ověřeného od předpokládaného.
