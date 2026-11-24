# Re-review: R5 (`ALLOW_OPEN_POSITIONS`) a Stonkfly fáze A po S1 (Codex, 2026-11-24)

Jen audit. Report napiš česky do `_workspace/2026-11-24_codex_rereview_r5_and_stonkfly_a.md`.
Dva verdikty APPROVE / CHANGES_REQUIRED: **A** pro R5, **B** pro Stonkfly fázi A.

## A. R5 — tvůj re-review `_workspace/2026-11-24_codex_rereview_allow_open_positions_r4.md`

`deploy/research_eval/deploy_env_check.py`, commit (viz `git log`), invariant TP/SL podle typu pozice:
- `tp` musí být vždy na ziskové straně vstupu.
- **Dynamická pozice** používá stejný predikát jako `update_paper_positions()`
  (`paper_trade_executor.py:2938`): `explore_bucket == P0_8_PLUS_EVIDENCE_COLLECTION` a
  `strategy_id == trend_cost_aware`. Pro ni platí:
  - `sl` smí ležet kdekoli v mezích, tedy i za vstupem a za `tp`, pokud je uložený
    `dynamic_exit_initial_stop` a leží na ztrátové straně;
  - bez uloženého původního stopu musí `sl` sám ležet na ztrátové straně (netrailovaná pozice).
- **Ostatní pozice** mají dál přísné `tp > entry > sl` (BUY), resp. `tp < entry < sl` (SELL).
  `sl` jinak než přes dynamický exit nikdo nemění; jediný zápis je `:2825`.
- Původní stop na ziskové straně → `Refused`.

Testy:
- `test_trailed_stop_is_accepted_only_for_dynamic_exit_positions_with_a_recorded_initial_stop`
  (přijetí za vstupem i za `tp` pro BUY i SELL; odmítnutí bez původního stopu, pro nedynamickou
  pozici, pro jiný bucket a pro původní stop na ziskové straně);
- `test_stop_trailed_by_the_real_exit_engine_past_tp_is_accepted_and_reloads_and_settles`:
  - stop vytvoří skutečný `dynamic_trend_exit_v1.evaluate_exit` (tvůj scénář, nový stop 100,4 >
    `tp` 100,35);
  - validátor stav přijme;
  - skutečný `_load_paper_state()` ho v `tmp_path` obnoví beze změny `sl`/`tp`;
  - `_calculate_pnl` na trailed stopu je konečný a `PaperCloseJournal.prepare()` ho přijme.
  - **Mez:** samotné `close_paper_position()` jsem nevolal kvůli jeho runtime vedlejším účinkům
    (cache, learning hooky).
- Na HEAD selžou oba nové testy. Tvůj `_workspace/2026-11-24_r4_round2_repro.py` teď vypíše
  `after_accepted`.
- 162 passed (s `bash`), `PROTECTED_SAME`.
- Živý stav ve 07:40 UTC (1 pozice, SELL `trend_cost_aware`, netrailovaná): `ACCEPTED 1`. Ověřeno
  jen pro čtení, validátor přes stdin.

**Ověřit:**
- Je predikát dynamické pozice přesně ten, podle kterého executor trailuje?
- Je správně, že u nedynamických pozic zůstává přísný invariant?
- Je `dynamic_exit_initial_stop` vždy zapsán před prvním trailem (`:2755–2758`)?

## B. Stonkfly fáze A — tvoje review `_workspace/2026-11-24_codex_review_stonkfly_phase_a.md`

Lokální, **necommitnuté** změny:
- `scripts/research/stonkfly_input_sensitivity.py`:
  - docstring uvádí jen statickou ustálenou složku R1–R6 jako kandidátní vysvětlení, bez R8 a bez
    výstupu sítě;
  - mirror je popsaný jako duplicitní kontrola;
  - `load_receptors()` vrací `(uv, verified)` proti `artifacts.ARRAY_HASHES`; `main()` neověřená
    data odmítne (rc 2), pokud se nepoužije `--allow-unverified`, a výsledek pak nese
    `data_status: UNVERIFIED_DATA`.
- `tests/test_stonkfly_input_sensitivity.py`: kontrola pinu a odmítnutí, mirror = falling.
- Report `_workspace/2026-11-24_claude_stonkfly_learning_rework.md`:
  - závěr přepsaný na tvou podporovanou formulaci;
  - opravené tvrzení o `changed_edges` (plastic běží s `learning=True`, váhy může měnit vnitřní
    KC/DAN aktivita);
  - mezi NOT_VERIFIED doplněno R8 a výstup sítě.
- Opakovaný běh na serveru (jen čtení, stdin): `data_status: VERIFIED_PIN`, čísla shodná s prvním
  během. Výstup je v `_workspace/stonkfly_eval_20261123/input_sensitivity_20261124.json`.
- 103 passed, 1 skipped, `PROTECTED_SAME`. Balík `src/services/stonkfly/` beze změny.

**Ověřit:** Odpovídají teď formulace datům? Je fáze A (statická část) uzavřená s tím, že A2 (běh
modelu, R8) zůstává otevřené?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py tests/test_stonkfly_input_sensitivity.py tests/test_stonkfly_integration.py tests/test_paper_neural_context.py`
s kontrolou `protected_sha.py` před a po.
