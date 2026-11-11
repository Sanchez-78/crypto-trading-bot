# Codex: nezávislé re-review opravy B1–B3 produceru původu C1 (2026-11-11)

**Role:** nezávislý reviewer (implementace: Claude). Codex jen ověřuje a radí.
**Report:** `_workspace/73_codex_c1_provenance_fix2_review.md` (česky), důkazy do
`_workspace/c1_provenance_fix2_review_20261111/`. Nic jiného neměň.
**Zakázáno:** commit, push, SSH, deploy, restart, reset, stash, clean; změna kódu, testů,
předregistrace, cutoffu nebo runtime dat. Skutečné post-cutoff outcomes C1 neotvírej. Jen
syntetická data.
**Termín:** výsledek před 2026-11-16 17:00 UTC (první možné zmrazení C1 je 17:47 UTC).

## Předmět

Poslední commit měnící `scripts/research/learner_replay_report.py`
(`git log -1 -- scripts/research/learner_replay_report.py`), oprava nálezů B1–B3 z
`_workspace/71_codex_c1_provenance_fix_review.md`. Popis opravy:
`_workspace/72_c1_provenance_fix2_20261111.md`. Předchozí stav: commity `c1fe52c`,
`efc3447`.

## Ověř

1. **B1:** `validate_freeze_inputs` odmítne log, který po `resolve()` (relativní cesty,
   symlinky) odpovídá výsledku, manifestu nebo jejich `.tmp`, a to v knihovně i CLI před
   jakýmkoli zápisem a před evaluací. Zůstává jiný alias, například hardlink, jiný mount
   nebo stejný soubor jinou cestou? Posuď, zda je potřeba `os.path.samefile` pro
   existující soubory.
2. **B2:** run ID odpovídá `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`. Ověř, že nejde vložit další
   řádku ani zfalšovat pole a že vyhovuje ID ze serveru (`%Y%m%dT%H%M%SZ`).
3. **B3:** `fsync` obsahu před `replace`, `fsync` adresáře po něm (POSIX) a `fsync` adresáře
   při vytvoření logu. Jaká je nyní přesná záruka při výpadku hosta a co zůstává
   NOT_VERIFIED?
4. Evaluator, kritéria, slepota a dosavadní vlastnosti A1/A2 jsou zachované.
5. Symlink test se na Windows přeskočí, protože chybí oprávnění. Navrhni jeho ověření na
   serveru v rámci syntetického preflightu.

Testy jen `tests/test_replay_blinding.py`, `tests/test_learner_replay.py`,
`tests/test_cost_and_learning_review.py`. Mutace jen v izolované kopii. SHA chráněných
runtime souborů před a po.

## Výstup

APPROVE / CHANGES_REQUIRED, nálezy s prioritou a `soubor:řádek`, syntetické reprodukce,
příkazy a výsledky testů, odlišení ověřeného od předpokládaného.
