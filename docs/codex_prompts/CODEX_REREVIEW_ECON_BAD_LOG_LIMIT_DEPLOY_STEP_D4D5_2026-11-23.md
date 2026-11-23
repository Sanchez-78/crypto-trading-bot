# Re-review nasazovacího kroku ECON BAD, nálezy D4/D5 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d4d5.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro nasazovací krok.

## Kontext

Tvé re-review `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d2d3.md`. Změněny jsou
jen body 2 a 3 kritérií po nasazení v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`:
- **D4:** četnost odmítnutí jako sazba
  `(B.total_rejects − A.total_rejects) / ((B.since_s − A.since_s) / 60)` mezi prvním a posledním
  doručeným souhrnem. Srovnává se s výchozí sazbou 1 744,4 za minutu. Funguje i při mezeře v `seq`.
  Součet `window_rejects` jen při souvislém `seq`; při méně než dvou souhrnech `NOT_VERIFIED`.
- **D5:** tvrdá mez detailů je jen 17 × počet zasažených 60s oken, včetně okrajových a posledního
  otevřeného (≤ 187 za 10 min). Kategorie z doručených souhrnů se jako tvrdé kritérium nepoužívají.

Artefakt, nástroje ani příkaz se nezměnily (`95e499e7…`, `981c8870…`, `927cc096…`).

## Co ověřit

1. Jsou body 2 a 3 v souladu s kontraktem omezovače, včetně `since_s`, hranic oken a mezer v `seq`?
2. Zbývá v kritériích po nasazení ještě něco, co by mohlo falešně selhat nebo falešně projít?
   Pokud ano, navrhni přesné znění.
3. Nezměnilo se nic jiného? Ověř hashe.

Bez SSH, nasazení a commitu.
