# Re-review nasazovacího kroku ECON BAD, nález D1 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d1.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro nasazovací krok.

## Kontext

Tvé review `_workspace/2026-11-23_codex_review_econ_bad_log_limit_deploy_step.md` (D1: chybné očekávání
„−1/3 řádků, 22 min“). Artefakt, nástroje ani příkaz se **nezměnily** (`95e499e7…`, `981c8870…`,
`927cc096…`). Opravený je jen runbook `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`:
- nové výchozí měření s bajty (`_workspace/econ_bad_deploy_20261123/baseline_journal_20261123.txt`):
  22,7 % řádků, 40,2 % bajtů textu, journald limity `RuntimeMaxUse=100M`;
- oddělené úspory pro řádky odmítnutí, řádky journalu a bajty textu;
- retence `NOT_VERIFIED` (horní meze 19,4–25 min);
- kritéria úspěchu nezávislá na velikosti úspory;
- post-check se stejným příkazem, řádky a bajty.

Navíc je uložený surový záznam zkoušky importu na serveru
(`_workspace/econ_bad_deploy_20261123/server_import_probe_20261123.txt`, AUTHOR_REPORTED).

## Co ověřit

1. Odpovídají nová čísla surovému měření a jsou správně spočítaná?
2. Je očekávání poctivé (horní meze, režie metadat, retence NOT_VERIFIED)? Nejsou kritéria úspěchu
   vázaná na nepodložené číslo?
3. Je post-check srovnatelný s výchozím měřením (stejné okno a formát)?
4. Nezměnilo se nic jiného (artefakt, nástroje, příkaz)? Ověř hashe.

## Bezpečnost

Bez SSH, nasazení a commitu. Testy nejsou potřeba (změnil se jen dokument); pokud je spustíš, jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_econ_bad_reject_log_limit.py`
s kontrolou `protected_sha.py` před a po.
