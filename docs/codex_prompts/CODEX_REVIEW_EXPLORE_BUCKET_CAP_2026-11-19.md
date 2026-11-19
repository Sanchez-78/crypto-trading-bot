# Nezávislé review: konfigurovatelný strop otevřených pozic v průzkumném bucketu (2026-11-19)

Odpovídej česky. Úkol je **review**, ne implementace. Snaž se změnu zamítnout. Report zapiš do
`_workspace/2026-11-19_codex_review_explore_bucket_cap.md` s verdiktem `APPROVE` / `APPROVE_WITH_FIXES` /
`REJECT` a nálezy (soubor:řádek, scénář selhání, závažnost). Nic nenasazuj, necommituj, neměň runtime
data (`local_learning_storage/**`, `data/**`, `runtime/**`, evidence).

## Kontext (ověřeno agentem 2026-11-19 ze serveru, jen počty)

- Bot je PAPER only (`TRADING_MODE=paper_train`, REAL příznaky false). Cíl operátora: co nejvíc
  PAPER obchodů pro měření učení; virtuální ztráta nevadí. Autorita: `docs/OPERATING_STATE.md`.
- 2026-11-18 07:05 UTC nasazena oprava svíček (kohorta `candle-refresh`): `REJECT_STALE_MARKET_DATA`
  kleslo z ~45 % kandidátů P0.8+ na 0–4 %, přijatých kandidátů přibylo (12 h: 230–340 → 455–528),
  ale vstupů ne (~118 / 12 h). Nové vázající omezení v journalu:
  `[P0_8_PLUS_LIVE_OPEN] … status=blocked reason=max_open_per_bucket` a
  `[PAPER_ENTRY_BLOCKED] … reason=max_open_per_bucket bucket=P0_8_PLUS_EVIDENCE_COLLECTION open_bucket=2`.
- Příčina: `paper_trade_executor._check_exploration_exposure_caps()` má natvrdo `bucket_count >= 2`.
  Ostatní stropy na serveru nevážou (`PAPER_MAX_OPEN_POSITIONS=100`,
  `PAPER_TRAIN_MAX_OPEN_PER_BUCKET=40`, `PAPER_TRAIN_MAX_OPEN_PER_SYMBOL=20`); notional 7,5 USD/pozice.

## Změna (přesný diff `_workspace/bucket_cap_20261119/task.diff`)

1. `src/services/paper_trade_executor.py`: `exploration_bucket_cap(env)` čte
   `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET` (ASCII celé číslo 1–7); prázdné/neplatné → 2 (původní
   konstanta, bez výjimky ve vstupní cestě). Strop bucketu ji používá; `max_open_per_symbol = 1` a
   `max_open_per_symbol_bucket = 1` beze změny. Preimage na serveru `5b0b15cc…`, nové bajty `7079c2b5…`.
2. `deploy/research_eval/deploy_env_check.py`: `STRICT_INT_KEYS` — klíč, pokud je nastaven, musí být
   `[0-9]+` v [1, 7], jinak `Refused` (pre i post kontrola).
3. `deploy/research_eval/deploy_bot_files.sh`: allowlist + `paper_trade_executor.py` a klíč
   `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET`. **Pozor:** dosavadní politika (test
   `test_files_exclude_execution_cost_and_mode_modules`) zakazovala moduly exekutoru; nyní jediná
   výslovná výjimka `EXECUTOR_EXCEPTION`. Posuď, zda je přijatelná (pinning `EXPECTED_SHA256`, staged
   import, rollback), nebo zda je bezpečnější jiná cesta.
4. Testy: `tests/test_explore_bucket_cap.py`, upravený `tests/test_deploy_bot_files_allowlist.py`.
   Lokálně: 298 passed; 1 selhání `test_paper_mode.py::test_strict_take_disabled_for_training` je
   předchozí a závislé na lokálním `.env` (`PAPER_TRAIN_STRICT_TAKE_ENABLED=true`) — ověř.

## Plánované nasazení (jen po APPROVE)

`deploy_bot_files.sh` s `FILES="src/services/paper_trade_executor.py"`,
`VARS="PAPER_EXPLORE_MAX_OPEN_PER_BUCKET=7"`, drop-in `zzzzzzzzzzzzz-explore-bucket-cap.conf`,
pinned hash `7079c2b5…`; nejdřív nainstalovat reviewované verze `deploy_bot_files.sh` (`d5f94824…`)
a `deploy_env_check.py` (`57f0e887…`). Nová kohorta s markerem v `stage.log`; nesloučit s
`candle-refresh`.

## Zkontroluj zejména

- Zda soubor `paper_trade_executor.py` neobsahuje cestu k reálným objednávkám a zda je nahrazení
  celého souboru (lokální strom = server + jen tento diff) skutečně jen tento diff.
- Zda vyšší strop nerozbije jiné invarianty: race re-check (`_race_cap_check`, ~ř. 2351), idempotenci
  vstupů, duplicitní pozice (P1.1AV/AW), stale pozice, výpočty exitů, Firebase zápisy/kvóty při
  ~3× více souběžných pozicích, zátěž `update_paper_positions`.
- Zda `exploration_bucket_cap()` volané při každé kontrole nemá výkonový dopad (čte `os.environ`).
- Zda strop platí i pro jiné průzkumné buckety než P0.8+ a zda to vadí.
- Zda hodnota 7 dává smysl (7 symbolů, symbol cap 1) a co při rollbacku na 2 s 3–7 otevřenými pozicemi.
