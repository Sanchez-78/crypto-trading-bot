# Review: R4 (`ALLOW_OPEN_POSITIONS`) a vypnutí Stonkfly (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_review_r4_and_stonkfly_off.md`.
Dva samostatné verdikty APPROVE / CHANGES_REQUIRED: **A** pro R4, **B** pro vypnutí Stonkfly
(změna nástroje a nasazovací krok).

## A. R4 — tvůj re-review `_workspace/2026-11-23_codex_rereview_allow_open_positions_r3.md`

Místo přidávání polí po jednom je teď v `deploy/research_eval/deploy_env_check.py` tabulka
`_POSITION_NUMERIC_FIELDS`. Obsahuje všechna pole, se kterými tick a uzavření v
`paper_trade_executor.py` přímo počítají (prošel jsem všechny přístupy `pos[...]`/`pos.get(...)`):

- **Povinná pole:**
  - `entry_price`, `tp`, `sl`: (0, 1e9];
  - `size_usd`: (0, 1e6];
  - `entry_ts`: (0, 1e11];
  - `timeout_s`: (0, 1e7];
  - `max_hold_s`: klíč povinný, `null` povolen, jinak (0, 1e7];
  - poplatek a skluz: [0; 0,1].
- **Nepovinná pole bez ochrany v ticku, `null` zakázán:**
  - `max_seen`, `min_seen` (`:2918–2923`);
  - `_dyn_exit_features_ts` (`ts - cached_ts`, `:2780`);
  - `created_at`.
- **Nepovinná pole za guardem nebo `_safe_float`, `null` povolen, ale hodnota musí být rozumná:**
  `last_price`, `last_price_ts`, `max_seen_ts`, `min_seen_ts`, `dynamic_exit_initial_stop`,
  `_dyn_exit_atr_bps`.
- **Textová pole** `regime`, `explore_bucket`, `training_bucket`, `bucket`, `paper_source`,
  `strategy_id`, `mode`, `source` musí být řetězec nebo `null`.

Horní meze leží daleko nad živými hodnotami a drží konečné i odvozené hodnoty při vypořádání
(`fee * 100`, pohyb ceny, P/L v USD).

Testy v `tests/test_deploy_env_check.py`:
- `test_open_positions_count_refuses_unsafe_tick_or_settlement_field`: 23 případů včetně tvých
  `fee=1e308` a `max_seen="broken"`. Na HEAD `18cf49c` selže všech 23.
- `test_accepted_extremes_keep_settlement_finite`: záznamy přesně na mezích validátoru (BUY i SELL)
  počítá skutečný `_calculate_pnl` při výstupu na TP, SL, `max_seen` i `min_seen`. Výsledek je
  konečný, serializovatelný s `allow_nan=False` a `PaperCloseJournal.prepare()` (v `tmp_path`) ho
  přijme.
- `test_open_positions_count_accepts_nullable_guarded_fields`.

Živý stav (jen čtení, validátor přes stdin) ve 14:15 UTC: `ACCEPTED 1`. Ze sledovaných polí pozice
obsahovala `created_at`, `entry_price`, `entry_ts`, `max_hold_s`, `max_seen`, `min_seen`, obě nákladové
frakce, `size_usd`, `sl`, `timeout_s` a `tp`. Fixture `_pos()` má teď `max_seen`/`min_seen`/`regime`
jako zapisující kód.

**Ověřit:** Je tabulka polí úplná vůči tickové a close cestě (včetně `_check_dynamic_trend_exit`,
`compute_excursion`, learning hooků po close)? Jsou meze rozumné? Je ještě jiná třída stavů, které
projdou, ale zablokují tick nebo close?

## B. Vypnutí Stonkfly

Důvod: `_workspace/stonkfly_eval_20261123/REPORT.md` (NO EDGE; všech 20 038 predikcí je BUY,
příznaky bez informace o budoucím pohybu) a tvé doporučení vypnout kontext i výpočet a zachovat
checkpointy i evidence.

Změna nástroje `deploy/research_eval/deploy_bot_files.sh` (`9b7892bc…76d6`):
- **Nasazení jen konfigurace:** `FILES=""` je povolené jen s neprázdným `VARS` a prázdnými
  `EXPECTED_SHA256` i `EXPECTED_PREIMAGE_SHA256`. S `FILES` jsou oba piny povinné jako dřív.
- `mkdir -p "$BACKUP"` před zálohou drop-inu.
- `POSTIMAGE.sha256` bez souborů je prázdný soubor (`sha256sum` bez argumentů by četl stdin).
- **`ALLOWED_KEYS`** rozšířeno o `STONKFLY_ENABLED`, `STONKFLY_PAIRED_ENABLED`,
  `PAPER_STONKFLY_CONTEXT_ENABLED`. V `deploy_env_check.py` (`b70554b2…711d`) jsou v
  `STRICT_BOOL_KEYS`.
- **Sandbox** navíc volá `StonkflyConfig.from_env(env)`; `paper_neural_context.validate_config(env)`
  už volal.
- Komentář u `ALLOW_OPEN_POSITIONS` je aktualizovaný (odkaz na validátor a meze).

Testy:
- statické: `test_stonkfly_switches_are_allowlisted_strict_and_validated`, `test_env_only_deploy_guards`;
- bashové: `test_env_only_deploy_header_guard` (7 kombinací) a
  `test_pinned_helpers_are_noops_for_an_env_only_deploy`.
- Celkem 251 passed (deploy, neural context a stonkfly integrace), `PROTECTED_SAME`.

Ověřeno na serveru (jen čtení, žádný zápis): skutečné prostředí `MainPID` doplněné o klíče `PAPER_*`
z `.env` projde `paper_source_learning.validate_config`, `paper_neural_context.validate_config` i
`StonkflyConfig.from_env` jak v současném stavu, tak s vypnutými přepínači. Výsledek:
`stonkfly enabled=False paired=False context=False learning=True`.

**Plánovaný nasazovací krok (po APPROVE A i B):**
1. Zálohovat a nainstalovat nové `deploy_bot_files.sh` a `deploy_env_check.py` do
   `/opt/cryptomaster_research` (záloha současných `3bb51c5e…` a `927cc096…` do `stage_backups/`).
2. Spustit nasazení:
   ```
   LABEL=stonkfly-off FILES="" EXPECTED_SHA256="" EXPECTED_PREIMAGE_SHA256="" \
   VARS="STONKFLY_ENABLED=false STONKFLY_PAIRED_ENABLED=false PAPER_STONKFLY_CONTEXT_ENABLED=false" \
   DROPIN_NAME=zzzzzzzzzzzzzzz-stonkfly-off.conf bash deploy_bot_files.sh
   ```
   Výchozí čekání na 0 otevřených pozic, bez `ALLOW_OPEN_POSITIONS`. Drop-in s 15 `z` se řadí za
   všechny současné (poslední je `zzzzzzzzzzzzzz-econ-bad-log-limit.conf`).
3. Post-check:
   - `APPLIED OK`;
   - v `MainPID` environ tři hodnoty `false`;
   - žádný podřízený proces `stonkfly-inference` (teď ~695 MB RSS);
   - od restartu žádné `[STONKFLY_SIGNAL]` ani `[STONKFLY_CONTEXT]`;
   - `decision_status.neural_context.enabled=false`;
   - `[PAPER_ENTRY]` pokračují;
   - 0 tracebacků.
4. Checkpointy `/var/lib/cryptomaster/stonkfly`, `shadow_excursion.sqlite` a staré drop-iny zůstanou
   beze změny.
5. Návrat: odstranit nový drop-in a restartovat.

**Ověřit:**
- Je nasazení jen konfigurace bezpečné (rollback, záloha, postcheck, preimage bez souborů)?
- Nemá vypnutí kontextu nežádoucí účinek na učení BTC (návrat na `paper_source_learning_v1`,
  oddělené kohorty)?
- Je správné vypnout i `STONKFLY_PAIRED_ENABLED`?

Další kroky Stonkfly z tvého plánu (offline kontrolní vstupy, diagnostika `KC_spikes=0`, plasticita
s přiřazenou odměnou, out-of-sample hodnocení) začnou až po vypnutí, kdy se uvolní paměť. Na 4GB
serveru se druhá instance modelu vedle živé nevejde bezpečně.

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py tests/test_paper_neural_context.py`
s kontrolou `protected_sha.py` před a po.
