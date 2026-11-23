# Review nasazovacího kroku: omezení výpisů `REJECT_ECON_BAD_ENTRY` (Codex, 2026-11-23)

Jen audit a doporučení; snaž se krok zamítnout. Report napiš česky do
`_workspace/2026-11-23_codex_review_econ_bad_log_limit_deploy_step.md`. Verdikt APPROVE /
CHANGES_REQUIRED / REJECT. Bez SSH, nasazení a commitu.

## Kontext

Kód má APPROVE (`_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md`). Nasazovací postup
popisuje `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`.

## K review

1. Artefakt `_workspace/econ_bad_deploy_20261123/artifact/realtime_decision_engine.py`
   (`95e499e7…2c03`), serverová kopie `server_copy/realtime_decision_engine.server.py`
   (`4a46037b…`, read-only scp), `SERVER_STATE.txt`, `build_artifact.py`, `MANIFEST.json`. Ověř, že
   artefakt = server + jen schválený diff a že v gitu zůstává byte-exaktní (`-text`).
2. `deploy/research_eval/deploy_bot_files.sh` (`981c8870…7d29`): RDE v `ALLOWED_FILES`, klíč
   v `ALLOWED_KEYS`, opravený komentář v hlavičce. Nic jiného se změnit nesmí.
3. `deploy/research_eval/deploy_env_check.py` (`927cc096…51c5`): klíč ve `STRICT_BOOL_KEYS`, tedy
   pre i post kontrola jen `true`/`false`.
4. Testy `tests/test_deploy_bot_files_allowlist.py`, `tests/test_deploy_env_check.py` (nové případy
   pro klíč).
5. Příkaz, drop-in (řazení za `zzzzzzzzzzzzz-explore-bucket-cap.conf`), post-check a rollback v runbooku.
6. Staged import RDE v sandboxu je při nasazení nový (dříve se RDE neimportoval). Zkouška na serveru
   v `/tmp` ukázala 0 síťových volání, jedno daemon vlákno a jediný soubor
   `runtime/firebase_cache.sqlite` v pracovním adresáři. Je to v sandboxu (`ProtectSystem=strict`,
   `ReadWritePaths=SCRATCH`, `WorkingDirectory=SCRATCH`) bezpečné? Sandbox nemá síťovou izolaci (P2).
7. Je očekávaný účinek popsaný poctivě (~−1/3 řádků, ne „historie hodin“)?

## Bezpečnost

- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py tests/test_econ_bad_reject_log_limit.py`
- Hashe chráněných souborů před a po přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
- Verdikt výslovně jen pro tento nasazovací krok.
