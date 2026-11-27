# Re-review sběrače rev. 8, kolo C (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a zápisu souborů. Report vrať česky jako poslední zprávu. Claude ho uloží do
`_workspace/2026-11-27_codex_rereview_micro_recorder_r8c.md`. První řádek: **APPROVE_TO_DEPLOY** nebo
**CHANGES_REQUIRED**.

Tvůj předchozí report je `_workspace/2026-11-27_codex_rereview_micro_recorder_r8b.md`. Opravy, nový nález
o journalu a platný postup najdeš v `_workspace/2026-11-26_micro_recorder_design.md`, sekce „Rev. 8 po re-review
R8b“ (na konci). Změny jsou v commitu HEAD (`git show HEAD`).

| Soubor | SHA-256 |
|---|---|
| `scripts/research/micro_recorder.py` = release kopie | `ff52cab59451153bc1f6c5fadb517c5ca7ae4196deac7dce07c291e25b8a499a` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` | `2ed95ece25fd29c4a19c0ff7cb3e9b47f54db432fd4b7c3925a7aa902e4b370c` |
| `_workspace/micro_recorder_release/rev6_fallback/deploy_micro_recorder.sh` | `5d7d44afe1a67bf0cb13fb4d9d0377fe2ad9b6b92b76516053e1e076e471b263` |
| `_workspace/micro_recorder_release/rev5_fallback/deploy_micro_recorder.sh` | `884c383e7248b50c4066054c2f8c8e0328f5f68930b7abd6d49a67635857d9a7` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_deploy_micro_recorder_script.py` | `d1616f9cf38a1332267ce0d723a0697b3aac34d98fb11f7e50fb540ec96f19f0` |
| `tests/test_micro_recorder.py` | `fb995ae5ae91f70a43cd9e83fc9cd95672f90c1ab8a028ea68b05af9aa78fb82` |

**Ověř:**
1. **Fallback sada:** běžné soubory na cestě bez symlinků. Je to úplné, nebo zbývá cesta, jak fallback přijde
   o soubor při rollbacku? Například hardlink na instalovaný soubor: `place()` instaluje přes `ln` z dočasné
   kopie, takže instalovaný soubor má 1 link. Má `fallback_checks` kontrolovat i počet hardlinků?
2. **`cmp` přes `sed`:** fallback s vráceným pinem musí být bajtově shodný s tímto skriptem. Je to správně?
3. **Journal:**
   - hranice `date -r +%s.%N` a `--since @s.ns` (systemd 255 zlomky přijímá, ověřeno);
   - `grep` fail-closed: větev rc ≥ 2 netestovaná;
   - nález, že journal drží jen ~4 min: jsou kontroly v `install`/`verify` za těchto podmínek přiměřené?
4. **`msgs_hour` v gaps:** je to vhodné místo pro hodinové počty? `gaps` se zapisuje i při nedostatku místa.
   Výzkum musí řádky `kind=msgs_hour` při výpočtu mezer ignorovat.
5. **Postup s větvemi** (sekce „Postup upgradu rev. 6 → rev. 8 (platný…)“): úplný?
6. **Testy:** server 66 passed, lokálně 57 passed / 9 skipped, mutace 18/18. Chybí podstatná regrese?
