# Codex: re-review č. 3 `deploy_bot_files.sh` po opravě N1 (2026-11-11)

**Role:** nezávislý reviewer (skript upravil Claude). Jen ověřuj a raď.
**Report:** `_workspace/80_codex_deploy_allowlist_rereview3.md` (česky), důkazy do
`_workspace/deploy_allowlist_rereview3_20261111/`.
**Zakázáno:** commit, push, SSH, deploy, restart, změna kódu nebo testů, čtení výsledků C1 po
cutoffu.

## Předmět

Commit `e39a1b7` (oprava nálezů P1–P3 z `_workspace/77_codex_deploy_allowlist_review.md`):
`deploy/research_eval/deploy_bot_files.sh`, nový `deploy/research_eval/deploy_env_check.py`,
testy `tests/test_deploy_env_check.py` a `tests/test_deploy_bot_files_allowlist.py`. Shrnutí a
serverový dry run: `_workspace/candle_fix_deploy_20261111/README.md`.

## Ověř

1. **P1:** model vrstev `Environment=` → `EnvironmentFile=` (přepisuje) → `.env` přes
   `load_dotenv(override=False)` (jen doplňuje). Na serveru má efektivní unit podle dry runu
   prázdné `EnvironmentFiles` a `.env` načítá `start.py`. Je model správný pro oba případy?
   Odmítnutí plánovaného klíče v `EnvironmentFile` i v `.env`, kontrola po restartu přes
   `/proc/<MainPID>/environ` s doplněním z `.env` pro invarianty.
2. **P2:** validátory a import všech nasazovaných modulů v `systemd-run -p ProtectSystem=strict
   -p ReadWritePaths=$STAGE_DIR`. Projde pokus o zápis jinam? Je chování `--pipe` se stdin
   heredocem spolehlivé a vrací se exit code? Na serveru dry run vyšel PASS (config ok) a
   negativní případ REFUSED.
3. **P3:** povinné `EXPECTED_SHA256` pro každý soubor, kontrola před zálohou a zásahem, a
   pravdivý komentář.
4. Rollback, zámek, pořadí drop-inu a další dosavadní záruky skriptu se nezhoršily. Nový
   `deploy_env_check.py` musí být na serveru vedle skriptu a skript bez něj skončí.
5. Konce řádků: pracovní kopie na Windows hlásí CRLF varování. Navrhni kontrolu LF před
   instalací skriptu na server.

Testy: `tests/test_deploy_env_check.py` a `tests/test_deploy_bot_files_allowlist.py` přímo
přes pytest (izolovaný runner nekopíruje `.py` z `deploy/`). SHA chráněných runtime souborů
před a po.

## Výstup

APPROVE / CHANGES_REQUIRED pro skript a READY / BLOCKED pro nasazení, nálezy s `soubor:řádek`
a syntetickou reprodukcí.

## Doplněno pro kolo 2 (oprava nálezů review 78)

Předmět navíc: poslední commit měnící `deploy/research_eval/deploy_bot_files.sh` (oprava R1 a R2 z
`_workspace/78_codex_deploy_allowlist_rereview.md`), nový `deploy/research_eval/deploy_pinned.sh` a
`tests/test_deploy_pinned.py`. Popis a serverový dry run: konec `_workspace/candle_fix_deploy_20261111/README.md`.
Ověř hlavně, že zdroj se čte jen jednou, že validované, instalované a nakonec zkontrolované bajty jsou tytéž
bajty připnuté k `EXPECTED_SHA256` a že sandbox stage nemůže změnit. Spusť navíc `tests/test_deploy_pinned.py`
(skutečný bash) a vlastní reprodukci závodu proti nové verzi.

## Doplněno pro kolo 3 (oprava N1 z review 79)

Předmět: poslední commit měnící `deploy/research_eval/deploy_bot_files.sh` a `deploy_pinned.sh` (funkce `build_tree`,
`PYTHONPYCACHEPREFIX`, kontroly identity zdroje v sandboxu) a nové testy v `tests/test_deploy_pinned.py`. Popis a
serverový dry run: konec `_workspace/candle_fix_deploy_20261111/README.md`. Ověř svou reprodukci
`repro_stale_pyc.py` proti nové verzi (timestamp i unchecked-hash) a zda zbývá jiná cesta, jak by import ve
stagingu vykonal jiný kód než připnuté bajty (např. modul načtený dřív z jiného místa v `sys.path`).
