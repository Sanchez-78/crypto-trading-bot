# Re-review: `ALLOW_OPEN_POSITIONS=1`, nález R2 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_allow_open_positions_r2.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro další použití povolení.

## Kontext

Tvůj re-review `_workspace/2026-11-23_codex_rereview_allow_open_positions_r1.md`:
- R2: prázdné `trade_id` projde validátorem, ale žurnál uzavření ho odmítne;
- nepřesné vysvětlení `max_hold_s: null`;
- testová mezera: tréninkový `timeout_s` se v testu reálně nezkracoval.

Oprava:
- `deploy/research_eval/deploy_env_check.py`, `open_positions_count()`: klíč (= `trade_id`) musí být
  neprázdný a bez okrajových bílých znaků, jinak `Refused`. Docstring u `max_hold_s: null` teď uvádí,
  že executor při exitu čte `null` jako `PAPER_MAX_POSITION_AGE_S` a že cesta P0.8+ ukládá stejnou
  hodnotu i do `timeout_s`.
- `tests/test_deploy_env_check.py`:
  - `test_open_positions_count_refuses_empty_or_padded_trade_id` (`""`, `" "`, `" t"`, `"t "`, `"\t"`
    s jinak úplným záznamem). Na verzi z HEAD selže všech 5;
  - křížový test proti loaderu:
    - přidán tréninkový záznam `d` s `timeout_s=1200 > max_hold_s=300`; test ověří, že loader
      timeout skutečně zkrátí na 300 a `_effective_paper_hold_s()` je před i po stejné;
    - každý přijatý a načtený záznam se zapíše přes `PaperCloseJournal.prepare()` do žurnálu
      v `tmp_path`, aby šlo prokázat, že se dá uzavřít.
- `deploy_bot_files.sh` beze změny (`b955625f…b9da`).
- Ověřeno: 108 passed (s `bash`), `PROTECTED_SAME`.

## Co ověřit

1. Uzavírá oprava R2 všechny případy, kdy záznam projde, načte se, ale nedá se uzavřít do žurnálu?
   Jsou ještě jiné podmínky v `prepare()`/`_commit_paper_close_result()`, které validátor nepokrývá
   (např. hodnoty, které `json.dumps(allow_nan=False)` odmítne v ostatních polích záznamu)?
2. Je nové vysvětlení `max_hold_s: null` přesné?
3. Je křížový test izolovaný (žurnál a stav jen v `tmp_path`)?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
s kontrolou `protected_sha.py` před a po.
