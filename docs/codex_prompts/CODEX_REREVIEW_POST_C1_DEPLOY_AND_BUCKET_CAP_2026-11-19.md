# Re-review: nasazovací krok po C1 (kolo 2) + strop bucketu (kolo 2) (Codex, 2026-11-19)

Jen audit a doporučení. Report napiš česky do
`_workspace/2026-11-19_codex_rereview_post_c1_deploy_and_bucket_cap.md`.

## Kontext

Tvá review `_workspace/2026-11-19_codex_review_post_c1_deploy_step.md` (A a B CHANGES_REQUIRED) a
`_workspace/2026-11-19_codex_review_explore_bucket_cap.md` (REJECT). Opravy a nový stav popisuje
`docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md` (oddíly A–C).

Soubory:
- `_workspace/deploy_post_c1_20261119/deploy_dashboard_readiness.sh` (`bbaaca72…9a9a`),
  `build_artifacts.py`, `MANIFEST.json`
- `deploy/research_eval/deploy_bot_files.sh` (`8f0e3219…449e`), `deploy/research_eval/deploy_env_check.py`
  (`8ae175da…df75`)
- `tests/test_deploy_dashboard_readiness_script.py` (nový), `tests/test_deploy_bot_files_allowlist.py`
- `src/services/paper_trade_executor.py`, `tests/test_explore_bucket_cap.py`
- `_workspace/bucket_cap_20261119/`: `server_copy/` (read-only scp ze serveru, SHA `5b0b15cc…`),
  `artifact/paper_trade_executor.py`, `server_to_artifact.diff`, `MANIFEST.json`,
  `build_artifact.py`, `mutations.py` + `mutation_results.json`,
  `allowlist_executor_after_approval.patch`

## Co ověřit

A. Dashboard
1. A1: Profil se zjišťuje živým dotazem před změnou a po restartu se ověřuje stejný. Veřejný profil
   tedy nevyžaduje token. Je `/run/credentials/<unit>.service/dashboard_api_token` správný zdroj
   účinného tokenu pro `LoadCredential` (včetně šifrovaného credstore)? Neuniká token?
2. A2: journal fail-closed (nečitelný nebo prázdný → rollback).
3. A3: rollback a postimage ověřují mód, UID a GID.

B. Bot
4. B1: journal fail-closed v `deploy_bot_files.sh`.
5. B2: allowlist je jen pro outbox, executor a klíč stropu jsou odebrané. Odpovídá odložený patch
   tomu, co by se po schválení stropu vrátilo?
6. B3: `build_artifacts.py` porovnává obsah změněných řádků se schváleným `remediation.diff`.
   Zachytí jinou změnu stejné velikosti? Pozor: piny artefaktů jsou stejné jako v kole 1.

C. Strop bucketu
7. Odpovídá serverová kopie zaznamenanému preimage? Je `server_to_artifact.diff` úplný a obsahuje jen
   strop (2 hunky)?
8. Je parser bez `ValueError` a vrací pro neplatné hodnoty 2? Omezuje `deploy_env_check` délku?
9. Platí rozsah jen pro `P0_8_PLUS_EVIDENCE_COLLECTION` a ostatní buckety zůstávají na 2? Obě místa
   kontroly (první přijetí i kontrola před insertem) volají `_check_exploration_exposure_caps`.
10. Je postup rollbacku (snížení stropu nezavírá pozice) dostatečně popsaný?

## Bezpečnost

- Žádné SSH, nasazení, Firebase ani commit.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_dashboard_readiness_script.py tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py tests/test_explore_bucket_cap.py`
- Hashe chráněných souborů před a po porovnej přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
- Verdikty zvlášť pro A, B a C: APPROVE (nasazovací krok, resp. kód a artefakt stropu) nebo
  CHANGES_REQUIRED s reprodukcí.
