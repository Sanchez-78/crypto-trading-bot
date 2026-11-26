# Re-review sběrače order booku a likvidací, rev. 4 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_micro_recorder_r4.md`.

Verdikt:
- **A:** `stop-tick`. APPROVE / CHANGES_REQUIRED.
- **B:** `preflight` + `install`. APPROVE_TO_DEPLOY / CHANGES_REQUIRED.

Navazuje na `_workspace/2026-11-26_codex_rereview_micro_recorder_r3.md`.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` (rev. 4) | `313b3d687dfb8a473384dbe17bab826b8ce6eb0657e7f04f0eb8abde57bbe7ef` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `8d824c36090b5bc9f3eeb44e1254d02fa7ce33afc52990ff2941e54e9005e159` |
| `tests/test_deploy_micro_recorder_script.py` (21 testů) | `6730119e70f4a88c944df374977a06a4154d5fc51f6c4f9f275edb58471d08c9` |
| `scripts/research/micro_recorder.py` = release kopie (beze změny) | `252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_micro_recorder.py` (10 testů, beze změny) | `750f5c0acded3c599cd3e5c66bfa7e2cdb4f449ae8925e25c25c9d8e8e532f8b` |

## Opravy

- **A:** `verify_tick_state()` se volá na začátku a **znovu těsně před `disable --now`**. Výsledek
  „PID FD“ se musí shodovat s prvním ověřením, jinak
  `FAIL: tick-recorder changed during forensics`, bez vypnutí.
  - Test `test_stop_tick_reverifies_right_before_disable`: první kontrola vidí PID 77, druhá 78 se
    stejným rozbitým stavem. Výsledek je `FAIL` bez `disable`.
- **B1:** `place()` zapisuje své dočasné cesty do pole `TEMPS` a rollback maže jen je.
  - Test `test_rollback_removes_only_its_own_temp_files`: cizí `units/.micro.foreign` přežije.
- **B2:** `check_target_dirs()` volaný v preflightu i po `mkdir` v instalaci:
  - pro `APP_DIR`, adresář unitu a `DATA` vyžaduje `realpath -m == realpath -m -s` (žádná
    symlink komponenta);
  - adresář unitu musí existovat;
  - v produkci musí být kanonické cesty přesně `/opt/cryptomaster-micro` a `/etc/systemd/system`.
  - Test `test_symlinked_target_directory_is_refused` se na Windows přeskočí. Logiku jsem ověřil na
    Linuxu serveru v dočasném `/tmp/micro-check.*`, adresář je smazaný: symlinkovaná cesta →
    `HAS_SYMLINK`, čistá a neexistující → `clean`.
- **B3:** `mv -f` nahradil hard link `ln "$tmp" "$dst"`, který selže na existujícím cíli. Pak
  `rm tmp` a ověření pinu cíle.
  - Na Linuxu ověřeno: `ln refused existing dst`, obsah cíle zůstal.
  - Test `test_target_created_after_preflight_is_never_overwritten`: cizí cíl vznikne mezi
    preflightem a umístěním. Výsledek: „not overwriting“, `ROLLBACK_OK`, cizí obsah zůstal,
    nainstalovaný skript odstraněn, žádné `.micro.*`.
- **Mutace:** vypnuté opakované ověření, úklid globem a návrat `mv -f` zachytí každá 1 test.

Lokálně: 20 testů prošlo a 1 se přeskočil (symlink na Windows), k tomu 10 testů sběrače a
`PROTECTED_SAME`.

**Ověř:** Jsou A a B uzavřené? Lze nejdřív spustit `stop-tick`, pak `preflight` a `install`, a
nakonec `verify` po 10 min a po 24 h?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
a `protected_sha.py` před a po.
