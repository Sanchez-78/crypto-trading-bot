# Codex: nezávislé re-review hardlinkové opravy produceru původu C1 (2026-11-11)

**Role:** nezávislý reviewer (implementace: Claude). Jen ověřuj a raď.
**Report:** `_workspace/75_codex_c1_provenance_fix3_review.md` (česky), důkazy do
`_workspace/c1_provenance_fix3_review_20261111/`. Nic jiného neměň.
**Zakázáno:** commit, push, SSH, deploy, restart, reset, stash, clean; změna kódu, testů,
předregistrace, cutoffu nebo runtime dat. Skutečné post-cutoff outcomes C1 neotvírej. Jen
syntetická data. **Termín:** před 2026-11-16 17:00 UTC.

## Předmět

Poslední commit měnící `scripts/research/learner_replay_report.py`, oprava P1 z
`_workspace/73_codex_c1_provenance_fix2_review.md` (hardlink logu na `.tmp` výsledku).
Popis: dodatek na začátku `_workspace/72_c1_provenance_fix2_20261111.md`.

## Ověř

1. Tvůj `hardlink_probe.py` nad opraveným kódem (spusť ho v kopii, aby se nepřepsaly
   tvoje důkazy).
2. `os.path.samefile` pro existující soubory z chráněné množiny a fail-closed při chybě
   identity. Zbývá alias, který kontrola nepozná?
3. `_write_frozen`: `unlink` + exkluzivní vytvoření (`xb`). Zachovává to atomické
   zveřejnění a pořadí `fsync`? Existuje souběh, kdy by zápis prošel přes cizí inode?
4. Zachování B2, B3, A1/A2, evaluatoru a slepoty.
5. Preflight na serveru z tvého reportu 73 (symlink a hardlink v dočasném adresáři, běžné
   zmrazení): doplň, co chybí.

Testy jen `tests/test_replay_blinding.py`, `tests/test_learner_replay.py`,
`tests/test_cost_and_learning_review.py`; mutace jen v izolované kopii; SHA chráněných
runtime souborů před a po.

## Výstup

APPROVE / CHANGES_REQUIRED, nálezy s prioritou a `soubor:řádek`, reprodukce, výsledky testů,
odlišení ověřeného od předpokládaného.
