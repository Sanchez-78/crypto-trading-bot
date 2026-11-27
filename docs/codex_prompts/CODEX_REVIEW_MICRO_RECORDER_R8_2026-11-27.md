# Review sběrače rev. 8: vyprazdňování logu a read-only upgrade-check (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a zápisu souborů. Report vrať česky jako poslední zprávu (Claude ho uloží do
`_workspace/2026-11-27_codex_review_micro_recorder_r8.md`).

Verdikt: **APPROVE_TO_DEPLOY / CHANGES_REQUIRED** pro upgrade popsaný v návrhu (sekce „Rev. 8“ na konci
`_workspace/2026-11-26_micro_recorder_design.md`).

**Kontext:** rev. 6 běží od 13:51:53 UTC. Tvůj audit výsledku je `ACCEPT`
(`_workspace/2026-11-27_codex_review_micro_recorder_deploy_result.md`). Upozornil jsi, že log se nevyprazdňuje.
To má i horší důsledek: `os._exit()` ztratí poslední hlášku. Rev. 8 to opravuje a přidává `upgrade-check`,
který jsi doporučil v R7 i v auditu výsledku.

| Soubor | SHA-256 |
|---|---|
| `scripts/research/micro_recorder.py` = release kopie | `fdad490b7fdfb86ff53d02a29815f0d7f4379c7417868f2864bad499ca2421aa` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `8d403e96197cceac06b96b3cd8a207853f074e0d2223ad0501af57155a5ee895` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_micro_recorder.py` (+1) | `516f7b44ee46d8c15b99f38b5dc34c5f01ddd363d629292a2012b906f074a454` |
| `tests/test_deploy_micro_recorder_script.py` (+5) | `831a17fd1c00841a60492b1fc25280a8af8c2f8d10b12919386353ece33f1701` |

Diff proti HEAD: `git diff HEAD -- scripts/research/micro_recorder.py _workspace/micro_recorder_release/ tests/`
(pokud už je commitnuto, pak `git show HEAD`).

**Ověř:**
1. **`log_line()` s `flush=True`:** řeší ztrátu hlášky před `os._exit()` a zpoždění hodinového řádku? Chybí
   ještě nějaká cesta, kde se loguje jinak?
2. **`upgrade-check`:**
   - je opravdu jen pro čtení?
   - Ověřuje to, co je potřeba, než se zastaví běžící revize? Tedy: nový release, nainstalované soubory podle
     pinů, které rollback předchozího release umí odstranit, `active` a zdroje.
   - Chybí něco, co by po rollbacku mohlo zastavit `preflight` nebo `install`?
3. **Refaktor `preflight`** na `release_checks` + `resource_checks`: je chování `preflight` beze změny?
4. **`du -sh "$DATA/"`:** správně?
5. **Postup:** `upgrade-check` → starý `rollback` → nový `preflight` + `install` → `verify`; návrat opačně přes
   rev. 7 skript. Je konzistentní?
6. **Testy a mutace:** server 47 passed (jako `nobody`, dočasný adresář), lokálně 39 passed / 8 skipped,
   mutace 5/5 zabity. Testy `upgrade-check` v kopii skriptu přepíšou `PREV_SCRIPT_SHA` na hash falešného
   souboru. Je to přijatelné?

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
(v read-only sandboxu nemusí jít spustit, pak stačí statická kontrola).
