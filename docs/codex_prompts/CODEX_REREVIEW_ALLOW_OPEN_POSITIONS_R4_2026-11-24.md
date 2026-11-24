# Re-review: `ALLOW_OPEN_POSITIONS=1`, R4 (kolo 2) (Codex, 2026-11-24)

Jen audit. Report napiš česky do `_workspace/2026-11-24_codex_rereview_allow_open_positions_r4.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro další použití povolení. Stonkfly se tohoto review netýká.

## Kontext

Tvoje review `_workspace/2026-11-23_codex_review_r4_and_stonkfly_off.md`:
- A: extrémní poměr cen, budoucí `entry_ts`, `_dyn_exit_trend_features`;
- B: vypnutí Stonkfly je SUPERSEDED.

## Změny

1. **B vráceno:** `deploy_bot_files.sh` je zpět na verzi z R3 (bez nasazení jen konfigurace a bez
   klíčů Stonkfly). Jediná změna oproti R3 je opravený komentář u `ALLOW_OPEN_POSITIONS`
   (`8ab8505b…3b`). `STRICT_BOOL_KEYS` a testy nástroje jsou také zpět na verzi z R3.
2. **`deploy_env_check.py` (`1de83667…0034`), `open_positions_count(text, now=None)`:**
   - Cenová pole `tp`, `sl`, `max_seen`, `min_seen`, `last_price`, `dynamic_exit_initial_stop` musí
     ležet v rozmezí ×2 od `entry_price` (`_PRICE_RATIO_MAX`).
   - `entry_price ≥ 1e-6` (`_PRICE_MIN`). Výstup se vypořádá skutečnou tržní cenou, ne uloženým
     polem, takže sám poměr nestačí: `(exit − entry) / entry · 100 · size` musí zůstat konečný i pro
     extrémní tržní cenu.
   - Časová pole `entry_ts`, `created_at`, `max_seen_ts`, `min_seen_ts`, `last_price_ts` nesmí ležet
     dál než 60 s do budoucnosti od `now`, výchozí je `time.time()` (`_CLOCK_SKEW_S`). Validátor i
     bot běží na stejném hostiteli.
   - Klíče runtime cache `_dyn_exit_trend_features`, `_dyn_exit_features_ts`, `_dyn_exit_atr_bps` se
     odmítají už samotnou přítomností, protože `_save_paper_state()` je vždy odstraní
     (`paper_trade_executor.py:795`). Z numerické tabulky jsou pryč.
3. **Nový nález z živých dat, oprava false refusal existujícího od R1:**
   - Validátor dnes v 07:19 UTC odmítl skutečnou živou pozici SELL XRPUSDT (entry 0,947,
     tp 0,94369, `sl` 0,94649 < entry).
   - Dynamický výstup posouvá `sl` jako trailing stop (`paper_trade_executor.py:2821–2825`,
     `_POSITIONS[...]["sl"] = decision.new_stop_price`) a u ziskové pozice ho dostane za vstup.
   - Nový invariant: `tp` na ziskové straně vstupu, `sl` za `tp` (BUY `sl < tp`, SELL `sl > tp`).
     Pouze netrailovaný `dynamic_exit_initial_stop`, pokud je uložený, musí ležet na ztrátové
     straně vstupu.
   - Po opravě živý stav s 3 pozicemi (BNB SELL, BTC BUY, XRP SELL trailed) → `ACCEPTED 3`. Ověřeno
     jen pro čtení, validátor přes stdin.

## Testy

`tests/test_deploy_env_check.py`:
- 16 nových případů v `test_open_positions_count_refuses_unsafe_tick_or_settlement_field`:
  - tvůj `entry=1e-300`, `tp=1e9`, `sl=5e-301`;
  - `entry` pod 1e-6;
  - ceny mimo ×2;
  - budoucí časy včetně `time.time() + 3600`;
  - přítomnost tří klíčů runtime cache.
- `test_future_timestamp_tolerance_is_bounded`: přesná hranice 60 s přes `now`.
- `test_trailed_stop_past_entry_is_accepted_but_initial_stop_must_be_on_the_loss_side`.
- `test_accepted_extremes_keep_settlement_finite`: přidaný nejlevnější přijatelný vstup (1e-6) a
  vypořádání při tržních cenách 1e9 a 1e-9 pro všechny záznamy, skutečný `_calculate_pnl` a
  `PaperCloseJournal.prepare()` v `tmp_path`.

Mutace na HEAD `803bb88`: selže všech 17 nových odmítacích případů a test trailed stopu (na HEAD je
trailed SELL odmítnut). Celkem 161 passed (s `bash`), `PROTECTED_SAME`.

## Co ověřit

1. Jsou meze (×2, 1e-6, 60 s) v souladu se vstupními invarianty executoru a nepovedou ke zbytečnému
   odmítání živého stavu?
2. Je invariant pro trailed `sl` správný vůči `dynamic_trend_exit_v1` (může trailing stop přejít `tp`)?
   Platí i pro ostatní exit profily?
3. Zbývá jiná třída stavů, které projdou, ale zablokují tick nebo close?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
s kontrolou `protected_sha.py` před a po.
