# Dodatečné review: `ALLOW_OPEN_POSITIONS=1` v `deploy_bot_files.sh` (Codex, 2026-11-23)

Jen audit. Report napiš česky do `_workspace/2026-11-23_codex_review_allow_open_positions.md`.
Verdikt APPROVE / CHANGES_REQUIRED.

## Kontext

Operátor nařídil nasadit omezení výpisů ECON BAD i s otevřenými pozicemi („proveď vše i tak“). Při
stropu průzkumného bucketu 7 se PAPER pozice otevírají nepřetržitě a čekání na nulu skončilo dvakrát
`SKIPPED`. Změnu nástroje jsem proto udělal a nasadil **před** review; toto review je dodatečné.

- Commit `ff10f96`, `deploy/research_eval/deploy_bot_files.sh` (SHA-256 `3bb51c5e…9be9`), test
  `test_open_positions_opt_in_is_explicit_logged_and_default_waits`.
- Chování:
  - jen přesně `ALLOW_OPEN_POSITIONS=1` přeskočí čekání a zaloguje `OPEN_POSITIONS_ALLOWED open=N`;
  - nečitelný soubor pozic vede dál na `SKIPPED`;
  - výchozí chování je beze změny;
  - povolení se vyhodnotí před nastavením rollback trapu.
- Ověřený výsledek nasazení (`docs/OPERATING_STATE.md`, kohorta „econ-bad-log-limit“): restart se 2
  otevřenými pozicemi, po startu `[PAPER_STATE_LOAD] open_positions=2` a
  `[PAPER_STATE_RECONCILE_SUMMARY] loaded=2 … alive=2`.

## Co ověřit

1. Je povolení správně ohraničené (jen `=1`, logované, nečitelný stav odmítnut, výchozí beze změny)?
   Neovlivňuje kontrolu preimage, validaci, rollback ani kontrolu prostředí?
2. Je restart s otevřenými pozicemi bezpečný podle kódu executoru: `_load_paper_state`, atomický zápis
   `os.replace`, žurnál uzavření `_paper_close_journal().closed_ids`, rekonciliace? Co se stane
   s pozicí, která se uzavírá přesně v okamžiku restartu?
3. Rollback po neúspěšném nasazení také restartuje s otevřenými pozicemi. Je to přijatelné?
4. Mělo by povolení vyžadovat ještě něco dalšího (např. výpis ID otevřených pozic do `stage.log`)?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_pinned.py`
s kontrolou `protected_sha.py` před a po.
