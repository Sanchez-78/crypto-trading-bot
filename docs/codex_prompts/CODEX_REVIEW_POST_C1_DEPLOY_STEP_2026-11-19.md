# Review nasazovacího kroku: readiness (dashboard) + viditelnost outboxu (bot) (Codex, 2026-11-19)

Jen audit a doporučení, žádná implementace a žádné nasazení. Report napiš česky do
`_workspace/2026-11-19_codex_review_post_c1_deploy_step.md`.

## Kontext

Kód obou oprav má APPROVE (`_workspace/2026-11-18_codex_review_post_c1_remediation.md`, commit
`4581329`). Tvé review tehdy výslovně požadovalo samostatné review nasazovacího kroku dashboardu a
rozšíření allowlistu pro outbox. Návrh je v `docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md`.

Přezkoumej:
1. `_workspace/deploy_post_c1_20261119/deploy_dashboard_readiness.sh` (nový jednorázový skript,
   SHA-256 `a64e3679…2628`).
2. `deploy/research_eval/deploy_bot_files.sh`: rozšíření allowlistu o `v5_legacy_bridge/outbox.py` a
   `outbox_flush_worker.py`, zálohu podle `dirname` každého souboru a odmítnutí duplicitních jmen
   souborů. Stejný soubor upravila i změna stropu bucketu (commit `f61fca4`, vlastní review
   `CODEX_REVIEW_EXPLORE_BUCKET_CAP_2026-11-19.md`). Posuzuj jen části týkající se outboxu a cest.
3. `tests/test_deploy_bot_files_allowlist.py` (nový test pro vnořené cesty a duplicitní jména).
4. Artefakty `_workspace/deploy_post_c1_20261119/{dashboard,bot}/` a `MANIFEST.json` z
   `build_artifacts.py`: LF, serverová kopie z 18. 11. odpovídá zaznamenanému SHA a artefakt se liší
   přesně o schválený diff.

## Otázky

A. Skript pro dashboard
- Ověřuje preimage před jakoukoli změnou? Čte zdroj jen jednou? Instaluje jen pinované bajty?
- Je rollback úplný: obnovení vlastníka a módu, kontrola hashů, restart a `ALERT` při selhání?
  Jsou správně nastavené `trap` a `set -e` (např. `restart_and_wait || rollback`, `api` uvnitř
  `$(...)`, `pipefail` u `printf | curl`)?
- Nemůže token uniknout do `ps`, logu, journalu nebo `stage.log`? Je hledání credentialu
  (`/etc/credstore`, `/run/credstore`) pro `LoadCredential=dashboard_api_token` bez cesty správné?
  Co když je credential šifrovaný (`/etc/credstore.encrypted`)? Skript pak rollbackne. Je to
  přijatelné?
- Odpovídá kontrola kontraktu `paper_only` kódu v `dashboard_web.py` (artefakt)?
- Opravdu bot tyto moduly neimportuje? Ověř přes `start.py` → `bot2/main.py`.

B. Nástroj pro bota
- Je rozšíření allowlistu bezpečné? Ověř, že import obou modulů v read-only sandboxu nic nezapisuje
  (`deploy_post_c1_20261119/../post_c1_remediation_20261118/deploy_prep_check.json`: žádný vytvořený
  soubor), že `verify_staged_import` funguje i pro vnořený balíček a že journal grep a post-check
  dávají smysl.
- Je doporučené `VARS=""` + `DROPIN_NAME` korektní (žádný drop-in, rollback `rm -f` neexistujícího)?

## Bezpečnost

- Žádné SSH, nasazení, Firebase, commit ani úprava chráněných souborů.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
- Hashe chráněných souborů před a po porovnej přes
  `python -B -I _workspace/cache_isolation_repair_20261118/protected_sha.py save|check <json>`
  (ne přes `rtk diff a b`). Výchozí stav je stav po změně 19. 11. 07:06.
- Verdikt zvlášť pro A a B: APPROVE (nasazovací krok) nebo CHANGES_REQUIRED s reprodukcí.
