# Re-review sběrače rev. 8 po tvém CHANGES_REQUIRED (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a zápisu souborů. Report vrať česky jako poslední zprávu. Claude ho uloží do
`_workspace/2026-11-27_codex_rereview_micro_recorder_r8b.md`. První řádek: **APPROVE_TO_DEPLOY** nebo
**CHANGES_REQUIRED**.

Tvůj předchozí report: `_workspace/2026-11-27_codex_review_micro_recorder_r8.md`. Opravy a nový postup jsou
v `_workspace/2026-11-26_micro_recorder_design.md`, sekce „Rev. 8 po review R8“ (na konci). Změny jsou
v commitu HEAD (`git show HEAD`).

| Soubor | SHA-256 |
|---|---|
| `scripts/research/micro_recorder.py` = release kopie | `fdad490b7fdfb86ff53d02a29815f0d7f4379c7417868f2864bad499ca2421aa` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `97180eeb589748b8c4747b7c9c4b79a4a6c0863839156d001c0388f3ca02178f` |
| `_workspace/micro_recorder_release/rev6_fallback/deploy_micro_recorder.sh` | `0f64e008a7f2eae6c7a8b0916631a18a8249e6326e9b4ce1b9d69f50fa085a5a` |
| `_workspace/micro_recorder_release/rev5_fallback/deploy_micro_recorder.sh` | `58025e2597b99b1919d52fd9e75ab37896054df853d7433d39295bdff6d50d27` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_deploy_micro_recorder_script.py` | `1fb1cccb8d1c999da491dad361ce63794d5078dc01729dd5a13bec33c1eb3470` |
| `tests/test_micro_recorder.py` | `516f7b44ee46d8c15b99f38b5dc34c5f01ddd363d629292a2012b906f074a454` |

**Ověř:**
1. **P1 sada pro návrat:**
   - `fallback_checks` ověřuje sběrač, unit, pin skriptu a shodu skriptu kromě `SCRIPT_SHA` (`cmp`). Stačí to?
   - Odinstalace rev. 6 nově přes `rollback` z fallback adresáře (rev. 8 logika, pin `b09b31b1…`) místo
     skriptu rev. 7. Je to v pořádku?
2. **P1 journal:**
   - hranice = mtime souboru unity (`stat -c %Y`), který `install` umísťuje nově; restarty se počítají. Je to
     správná hranice? Okrajový případ: chyba předchozí revize ve stejné sekundě jako umístění unity.
   - **Nová nalezená chyba:** `journalctl | grep -q` pod `pipefail` přehlédne chybu kvůli SIGPIPE. Je oprava
     (uložit výstup, `grep -q <<<`) správná a úplná? Nejsou ve skriptu další roury `… | grep -q` / `head`
     se stejným problémem?
3. **P2 `-B`:** stačí test s obalem `PY`?
4. Dashboard 200 v `upgrade-check`. `preflight` jsem záměrně nechal beze změny, aby selhání po instalaci dál
   spustilo rollback. Souhlasíš?
5. **Postup** v sekci „Postup upgradu rev. 6 → rev. 8 (nahrazuje předchozí)“: konzistentní a úplný?
6. **Testy:** server 59 passed, lokálně 51 passed / 8 skipped, mutace 14/14 (seznam v návrhu). Chybí nějaká
   podstatná mutace?
