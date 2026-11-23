# Re-review nasazovacího kroku ECON BAD, nálezy D2/D3 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d2d3.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro nasazovací krok.

## Kontext

Tvé re-review `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d1.md`. Změněna je
jen část „Po nasazení“ v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`:
- **D2:** četnost odmítnutí se počítá z rozdílu kumulativních `total_rejects` (nebo součtu
  `window_rejects`) za tatáž okna a teprve pak srovnává s 17 444.
- **D3:** mez detailů vychází z kontraktu, tedy ≤ 17 × počet oken (~187 na marker za 10 min), ne
  „desítky“. Mezera v `seq` je ztráta observability, ne chyba omezovače, a má samostatný reakční
  limit (> 10 % chybějících `seq` → prověřit journald).
- Doplněný přesný měřicí příkaz, kterým vzniklo výchozí měření.

Artefakt, nástroje ani příkaz se nezměnily (`95e499e7…`, `981c8870…`, `927cc096…`).

## Co ověřit

1. Jsou kritéria 2–4 v souladu s kontraktem omezovače (`src/services/realtime_decision_engine.py`,
   sekce 2026-11-23)?
2. Je výpočet četnosti z kumulativních součtů správný, včetně hranic oken?
3. Je měřicí příkaz shodný s tím, z něhož vzniklo `baseline_journal_20261123.txt`?
4. Nezměnilo se nic jiného? Ověř hashe.

Bez SSH, nasazení a commitu.
