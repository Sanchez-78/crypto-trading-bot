# Re-review: `ALLOW_OPEN_POSITIONS=1`, nález R3 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_allow_open_positions_r3.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro další použití povolení.

## Kontext

Tvůj re-review `_workspace/2026-11-23_codex_rereview_allow_open_positions_r2.md` (R3: `NaN`/`Infinity`/
`1e999` v nepovinném poli projde validátorem, ale žurnál uzavření ho odmítne). Oprava:

- `deploy/research_eval/deploy_env_check.py`, `open_positions_count()`:
  - po `json.loads` a kontrole kořene se celý dekódovaný stav serializuje přes
    `json.dumps(data, allow_nan=False)` (stejné pravidlo jako žurnál a writer stavu); `ValueError` i
    `RecursionError` se převádějí na `Refused`;
  - `RecursionError` se chytá i u `json.loads`;
  - docstring je doplněný.
- `tests/test_deploy_env_check.py`, `test_open_positions_count_refuses_non_finite_anywhere`:
  - literály `NaN`, `Infinity`, `-Infinity`, `1e999`, `-1e999`, vždy ve vnořeném poli `features.x`
    i v nepovinném poli nejvyšší úrovně `score_at_entry` jinak úplné pozice;
  - validátor je odmítne a skutečný `PaperCloseJournal.prepare()` (v `tmp_path`) na stejném záznamu
    vyhodí `ValueError`;
  - konečný záznam projde validátorem i `prepare()`.
- Na verzi z HEAD selže všech 10 nových případů. Celkem 118 passed (s `bash`), `PROTECTED_SAME`.
- `deploy_bot_files.sh` beze změny (`b955625f…b9da`).

## Co ověřit

1. Uzavírá oprava R3 všechny čitelné stavy, které by žurnál nebo `_save_paper_state()` odmítl
   serializovat? Zbývá jiná třída záznamů, které projdou validátorem a loaderem, ale nedají se uzavřít
   (např. vstupy do `_calculate_pnl` nebo hooků při close)?
2. Pokud další nález nenajdeš, je povolení po instalaci nové verze nástroje použitelné?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
s kontrolou `protected_sha.py` před a po.
