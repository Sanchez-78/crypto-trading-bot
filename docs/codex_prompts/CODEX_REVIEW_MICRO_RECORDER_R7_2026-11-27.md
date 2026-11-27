# Review deploy skriptu sběrače rev. 7: datový adresář po DynamicUser (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-27_codex_review_micro_recorder_r7.md`.

Verdikt: **APPROVE_TO_DEPLOY / CHANGES_REQUIRED** pro postup v návrhu (sekce „Rev. 7“ na konci
`_workspace/2026-11-26_micro_recorder_design.md`).

**Co se stalo:** po tvém APPROVE_TO_DEPLOY R6 proběhl rollback rev. 5 (`ROLLBACK_OK`). Pak preflight rev. 6 selhal:
`target path /var/lib/cryptomaster-micro contains a symlink`. Ten odkaz (`-> private/cryptomaster-micro`)
vytvořil systemd při první instalaci kvůli `DynamicUser` + `StateDirectory`. Kontrola ho odmítá i ve skriptu
rev. 5, takže nejde ani návrat. **Sběrač stojí od 13:39 UTC 27. 11.** Data jsou zachovaná. Bota se to netýká
(PID 3840326 beze změny). Plán R6 i review to přehlédly.

| Soubor | SHA-256 |
|---|---|
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` (rev. 7) | `a00b12669a9cd3919fb5445c1ff83604d887600057c85f624d46f754eb33b3b6` |
| `_workspace/micro_recorder_release/rev5_fallback/deploy_micro_recorder.sh` (rev. 7 s pinem rev. 5) | `5832d085ba66f52789b9281ab79f73933a6eac34c7c0ef19a2c4223b2803b4f3` |
| `scripts/research/micro_recorder.py` = release kopie (beze změny od R6) | `b09b31b1bf6bc73904a0ec702049f477f07e39ffb1d65369b0d6bcce1847d466` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_deploy_micro_recorder_script.py` (+7 testů) | `0b70fced39b630b5ae3438b653d7ee9cca32c5b594d0e99c0a3d5fb7468e5d12` |
| `tests/test_micro_recorder.py` (beze změny) | `fff19b3fdbeefde39fde56c8ec16a44b4ea5c5240078dc7f15e32967ad6de5c6` |

**Ověř:**
1. **`data_dir_ok()`** přijme jen `DATA` bez symlinku, nebo přesně tvar systemd:
   - rodič bez symlinku;
   - `readlink DATA` = `private/<basename>`;
   - `private` je skutečný adresář, root, 0700;
   - cíl je skutečný adresář.
   Dá se tím podvrhnout cíl mimo `/var/lib/private`, nebo nějaký případ chybí? Je v pořádku, že v test režimu
   je očekávaný vlastník aktuální uid?
2. **`APP_DIR` a adresář unity** mají dál přísnou kontrolu bez symlinku. Do `DATA` deploy skript nezapisuje.
3. **Testy a mutace:**
   - Windows symlinky nedovolí, proto 7 testů běželo na serveru jako `nobody` v dočasném adresáři se stuby,
     adresář byl poté smazán. Výsledek 30 passed.
   - Mutace: 4 z 5 zabity. `private_may_be_link` je ekvivalentní (`stat` bez `-L` vrátí 777). Souhlasíš?
   - Je takové spuštění na produkčním serveru přijatelné, nebo ho příště dělat jinak?
4. **Postup:**
   - nahrát rev. 7 skript místo `e69e0464…`;
   - `preflight` → `install` → `verify` po 10 min (+ `connect public`/`market`, `liq_sampled` jen informace)
     → `verify` po 24 h.
   - Návrat přes záložní skript s pinem rev. 5: liší se jen řádkem `SCRIPT_SHA`, ověř diff.
5. Má se do postupu přidat ještě nějaká kontrola, aby se podobné přehlédnutí neopakovalo? Například spustit
   `preflight` nové verze před rollbackem staré s očekáváním jen chyb „already exists“.

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
a `protected_sha.py` před a po. Lokálně 33 passed, 8 skipped (symlinky), `PROTECTED_SAME`.
