# Re-review instalace sběrače, rev. 5 (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_micro_recorder_r5.md`.

Verdikt pro **B** (`preflight` + `install`): **APPROVE_TO_DEPLOY / CHANGES_REQUIRED**.

Krok A jsi schválil (`_workspace/2026-11-26_codex_rereview_micro_recorder_r4.md`) a **proběhl
2026-11-26 10:47:09 UTC**:
- skript `8d824c36…` ověřený na serveru, rc 0, `TICK_STOPPED`;
- tick-recorder je `inactive` a `disabled`;
- uvolněno 1,24 GB disku a ~50 MB RAM;
- PID bota 3840326 beze změny;
- forenzní záznam v `/root/tick-recorder-forensics-20261126T104709Z/`;
- log ponechán.

Mezi hashem a zastavením proces zapsal ještě 1 řádek. Konečná velikost a SHA-256 logu jsou proto
doplněné jako dodatek do `state.txt`, archiv obsahuje konečnou verzi. Podrobnosti jsou v návrhu,
rev. 5.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` (rev. 5) | `05f7e7268e17d350b7a82b5f99f37a20dc71e65b3b653ca66c16bb1d5f747c30` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `8f471aca44ab06702c03714375e314e531144b55c727848f19102c8eef8c60f2` |
| `tests/test_deploy_micro_recorder_script.py` (23 testů) | `291bfb73e2d2feb6b37b7cd35fd29cdf44105fc4f9cb0b4189b9887a970d1c5d` |
| `scripts/research/micro_recorder.py` = release kopie (beze změny) | `252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_micro_recorder.py` (10 testů, beze změny) | `750f5c0acded3c599cd3e5c66bfa7e2cdb4f449ae8925e25c25c9d8e8e532f8b` |

## Oprava nálezu z rev. 4

- **`place()` zapisuje vytvořené cíle.** Po úspěšném `ln` zapíše cíl do `CREATED`.
  `APP_DIR_CREATED=1` se nastaví, jen když `APP_DIR` předtím neexistoval.
- **`rollback auto` (z trapu EXIT)** pracuje jen s tím, co vytvořil tento běh:
  - unit vypíná (`disable --now`) a kontroluje `is-active` jen tehdy, když ho tento běh vytvořil;
  - maže jen cíle v `CREATED` (a jen s pinem), cizí soubory nechá s hláškou „not created by this
    run“;
  - `rmdir APP_DIR` provede jen při `APP_DIR_CREATED=1`;
  - uklidí jen vlastní `TEMPS`.
- **`rollback manual`** (samostatné spuštění, např. po úspěšné instalaci) maže podle pinu jako
  dřív.
- **Testy:**
  - `test_auto_rollback_keeps_a_concurrent_target_even_with_the_exact_pinned_bytes`: cizí unit
    s přesně připnutými bajty vznikne po preflightu. `ln` ho nepřepíše, automatický rollback ho
    nechá a nevypne. Náš skript se odstraní.
  - `test_manual_rollback_after_a_successful_install_removes_the_pinned_files`.
- **Mutace:** „automatický rollback jako ruční“ zachytí 1 test.

Lokálně: 22 testů prošlo a 1 se přeskočil (symlink na Windows, logiku jsem ověřil na Linuxu
v rev. 4), k tomu 10 testů sběrače a `PROTECTED_SAME`.

**Ověř:** Je B uzavřené? Lze spustit `preflight`, pak `install` a `verify` po 10 min a po 24 h?

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
a `protected_sha.py` před a po.
