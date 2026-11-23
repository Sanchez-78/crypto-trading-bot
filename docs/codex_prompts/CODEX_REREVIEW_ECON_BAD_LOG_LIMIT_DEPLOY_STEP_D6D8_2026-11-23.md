# Re-review nasazovacího kroku ECON BAD, nálezy D6–D8 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d6d8.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro nasazovací krok.

## Kontext

Tvé re-review `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d4d5.md`. Oddíl „Po
nasazení“ v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md` je celý nahrazený:
- kritéria 1–5 jsou **doslova převzatá z tvého doporučeného znění** (D7 stejný proces a `MainPID`,
  přesné prostředí, traceback jen za dostupný úsek; D8 obchodní počty jen jako kontext);
- měřicí skript (D6) používá jen `mktemp` s `trap` na úklid a souhrny vyhodnocuje přímo z dočasného
  souboru. Ověřuje návratový kód `journalctl` a neprázdný výstup a navíc vypisuje `MainPID`, první a
  poslední souhrn.

Artefakt, nástroje ani příkaz se nezměnily (`95e499e7…`, `981c8870…`, `927cc096…`).

## Co ověřit

1. Odpovídají kritéria tvému znění? Je měřicí skript bezpečný (žádná pevná cesta, úklid, `rc`)?
2. Zbývá ještě něco blokujícího? Pokud ano, uveď přesné znění opravy.
3. Nezměnilo se nic jiného? Ověř hashe.

Bez SSH, nasazení a commitu.
