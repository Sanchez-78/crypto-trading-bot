# Re-review: nasazovací krok outboxu, nález B4 (Codex, 2026-11-19, kolo 3)

Jen audit. Report napiš česky do `_workspace/2026-11-19_codex_rereview_outbox_deploy_b4.md`.

## Kontext

Re-review `_workspace/2026-11-19_codex_rereview_post_c1_deploy_and_bucket_cap.md` schválilo dashboard
(A) a kód stropu (C). Outbox (B) vrátilo kvůli nálezu B4: `deploy_bot_files.sh` před přepsáním
neověřoval, že živé soubory jsou stále schválený serverový preimage.

Oprava (`deploy/research_eval/deploy_bot_files.sh`, SHA-256 `aa73c519…26fd`, LF):
- nové povinné `EXPECTED_PREIMAGE_SHA256` (`path=sha …`);
- první kontrola `verify_pinned "$APP" "$FILES" "$EXPECTED_PREIMAGE_SHA256"` pod zámkem, hned po
  allowlistu a před stagingem a zálohou;
- druhá kontrola těsně před prvním zápisem (`install_staged`), tedy po validaci v sandboxu a po čekání
  na nulové pozice (až 30 min). Při neshodě `trap - ERR INT TERM`, log `REFUSED …` a `exit 2` **bez
  rollbacku**, protože ten by kopíroval zálohu přes novější živou změnu;
- `deploy_pinned.sh` beze změny (`74a1fec7…`, na serveru už nainstalovaný).

Testy:
- `tests/test_deploy_bot_files_allowlist.py::test_live_preimage_is_checked_before_backup_and_right_before_install`
  (statické pořadí);
- `tests/test_deploy_pinned.py::test_live_file_changed_after_preflight_is_never_overwritten` (skutečný
  bash: živý soubor se po první kontrole změní a druhá kontrola zastaví instalaci).

Runbook: `docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md`, oddíl B, včetně příkazu s preimage
hashi `a3d7d7a4…4413` a `b173ea7c…6e9e`.

## Co ověřit

1. Je B4 opravený? Neexistuje cesta, která zapíše do `$APP` nebo drop-inu před druhou kontrolou?
2. Je správné ukončit druhou kontrolu bez rollbacku? Co záloha a drop-in v tu chvíli? Před instalací
   se nic nezapisuje.
3. Zbývá okno mezi druhou kontrolou a `install_staged` (milisekundy). Je přijatelné, nebo navrhni
   jiné řešení bez nových závislostí.
4. Nerozbila změna jiné části skriptu (`set -u` s novou proměnnou, logování, `verify_pinned`
   s preimage seznamem)?

## Bezpečnost

- Žádné SSH, nasazení, Firebase ani commit.
- Testy jen:
  `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_pinned.py tests/test_deploy_env_check.py`
  (bashové testy potřebují `bash` v `PATH`, např. Git Bash `C:\Program Files\Git\usr\bin`).
- Pokud `tests/conftest.py` selže na `os.chdir()` do dočasného adresáře (sandbox), testy nespouštěj a
  uveď to. Nevytvářej dočasné adresáře v `_workspace/`.
- Hashe chráněných souborů před a po porovnej přes `_workspace/cache_isolation_repair_20261118/protected_sha.py`.
- Verdikt pro B: APPROVE (nasazovací krok outboxu) nebo CHANGES_REQUIRED s reprodukcí.
