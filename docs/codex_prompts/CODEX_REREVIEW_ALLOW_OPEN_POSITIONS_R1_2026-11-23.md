# Re-review: `ALLOW_OPEN_POSITIONS=1`, nález R1 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_allow_open_positions_r1.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro další použití povolení.

## Kontext

Tvůj re-review `_workspace/2026-11-23_codex_rereview_allow_open_positions_a1.md` (R1: validátor přijal
pozici bez `side`/`size_usd`/TP/SL, kterou loader doplní, chybějící směr na `BUY`; nedostatečně
popsané provozní meze). Oprava:

- `deploy/research_eval/deploy_env_check.py` (`47223e0d…1545`), `open_positions_count()`. Pro každý
  záznam navíc vyžaduje:
  - `side` ∈ {`BUY`, `SELL`};
  - kladné konečné `size_usd`, `tp`, `sl`, `timeout_s`;
  - `tp`/`sl` na správné straně vstupu podle směru;
  - klíč `max_hold_s` přítomný, hodnota `null` nebo kladná konečná. Cesta P0.8+ ukládá `null`
    (`p0_8_plus_live_pipeline.py` `extra` bez `max_hold_s` → `paper_trade_executor.py:2308`) a držení
    se pak bere z `timeout_s`. Povinné kladné `max_hold_s` by odmítlo každý živý stav;
  - připnutý nákladový snapshot (`paper_cost_contract_version == 1`, obě frakce konečné ≥ 0);
  - u tréninkových pozic `training_bucket` a `created_at`.

  Doslovné „1:1“ z docstringu je pryč. Loader u tréninkových pozic může snížit `timeout_s` na
  `min(max_hold_s, timeout_s, _MAX_AGE_S)`, a to je přesně efektivní držení, které
  `_effective_hold` (`:1238–1245`) pro trénink stejně použije. Exit se tím nemění; docstring to uvádí.
  Executor se v preflightu neimportuje.
- `deploy_bot_files.sh` beze změny (`b955625f…b9da`).
- Testy `tests/test_deploy_env_check.py`:
  - plný kanonický záznam (BUY, SELL, strict take, trénink) projde;
  - chybějící `side`, `size_usd`, `tp`, `sl`, `max_hold_s`, `timeout_s` a nákladová pole u BUY i SELL
    → `Refused`;
  - vadné hodnoty, SHORT s LONG geometrií a neúplný trénink → `Refused`;
  - křížová kontrola se skutečným `_load_paper_state()` (stuby: soubor v `tmp_path`, prázdný žurnál,
    `_save_paper_state`, `_reconcile_stale_paper_positions`): přijaté záznamy se načtou bez změny
    ekonomických polí a `_paper_cost_fractions` vrátí uložené frakce.
- Mutace: na verzi z HEAD (`3e8efb0`) selže všech 34 nových odmítacích testů; křížová kontrola
  projde (testuje přijetí).
- Ověřeno: 103 passed (s `bash`), `PROTECTED_SAME`. Na serveru (jen čtení, validátor přes stdin,
  žádný zápis) živý stav s 1 otevřenou pozicí v 13:28 UTC → `ACCEPTED 1`.
- Dokumentace:
  - `docs/OPERATING_STATE.md`, kohorta „econ-bad-log-limit“, část „Meze povolení“: close přerušený
    před potvrzením žurnálu, neidempotentní hooky, rollback, kompatibilita nového i vraceného kódu,
    ověření po restartu;
  - runbook `ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md` (Rollback): odstraněno nepřesné tvrzení
    „exit lifecycle běží dál“.

## Co ověřit

1. Pokrývá validátor všechna pole, která loader nebo close doplní či změní ekonomicky? Je přijetí
   `max_hold_s: null` správné?
2. Je zdůvodnění u tréninkového `timeout_s` správné (beze změny efektivního držení)?
3. Je křížový test proti loaderu dost silný a izolovaný (žádný zápis mimo `tmp_path`)?
4. Stačí meze v dokumentaci?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
s kontrolou `protected_sha.py` před a po.
