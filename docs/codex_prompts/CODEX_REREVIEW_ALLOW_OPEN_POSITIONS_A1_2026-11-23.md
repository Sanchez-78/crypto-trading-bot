# Re-review: `ALLOW_OPEN_POSITIONS=1`, nález A1 (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_rereview_allow_open_positions_a1.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro další použití povolení.

## Kontext

Tvé review `_workspace/2026-11-23_codex_review_allow_open_positions.md` (A1: čitelný, ale neobnovitelný
stav projde). Oprava:
- `deploy/research_eval/deploy_env_check.py` (`44dcdeb5…7b84`): nová `open_positions_count(text)` a
  podpříkaz `positions --file`. Přijme jen kanonickou mapu `trade_id → slovník`, ve které má každý záznam
  stejné `trade_id` jako klíč, neprázdný `symbol` a kladné konečné `entry_price` a `entry_ts`.
  Odmítne neplatný JSON, skalár, seznam (legacy), obal `{"positions": …}`, klíč `metadata`, záznam,
  který není slovník, a vadná pole.
- `deploy/research_eval/deploy_bot_files.sh` (`b955625f…b9da`): větev povolení volá
  `python3 -I -B "$CHECK" positions --file "$POSITIONS"`; při odmítnutí `SKIPPED … not restorable`.
  Opravená hlavička (ř. 14–15).
- Testy: `tests/test_deploy_env_check.py` (kanonický stav, prázdný stav, 15 odmítnutých tvarů, CLI)
  a `tests/test_deploy_bot_files_allowlist.py` (statická kontrola větve).
- Ověřeno: lokálně proběhl dry-run bloku čekání se skutečným validátorem: platný stav projde, `{"trade-1": 42}`
  i obal vedou na `SKIPPED` a bez povolení skript čeká. Na serveru živý stav (3 pozice) projde
  (validátor spuštěný jen pro čtení z `/tmp`).

## Co ověřit

1. Odpovídá validátor tomu, co `paper_trade_executor._load_paper_state()` načte 1:1? Je správné
   odmítnout legacy seznam a obal, které loader sice umí, ale přetváří?
2. Jsou povinná pole (`trade_id`, `symbol`, `entry_price`, `entry_ts`) přiměřená? Nemůže validátor
   odmítnout platný živý stav (zbytečný `SKIPPED` je přijatelný, ale uveď ho)?
3. Zbývající meze z tvého review (uzavření v okamžiku restartu, rollback, kompatibilita stavu při
   budoucí změně executoru): jsou zapsané v `docs/OPERATING_STATE.md` a runbooku dostatečně?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`
(bashové testy potřebují `bash` v `PATH`) s kontrolou `protected_sha.py` před a po.
