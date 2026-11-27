# Review sběrače rev. 6: likvidace přes nové adresy Binance (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-27_codex_review_micro_recorder_r6.md`.

Verdikt: **APPROVE_TO_DEPLOY / CHANGES_REQUIRED** pro upgrade popsaný v návrhu (sekce „Rev. 6“).

**Nález:** verify 24 h prošlo, ale za 24 h přišlo 0 likvidací. Sonda ze serveru ukázala:
- stará adresa `fstream.binance.com/stream` už `forceOrder` neposílá;
- `/market/stream` likvidace posílá;
- `depth20` posílá stará adresa i `/public/stream`.
Podrobnosti jsou v `docs/OPERATING_STATE.md` (verify 24 h) a v návrhu.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` (rev. 6 na konci) | (viz commit) |
| `scripts/research/micro_recorder.py` = release kopie | `b09b31b1bf6bc73904a0ec702049f477f07e39ffb1d65369b0d6bcce1847d466` |
| `_workspace/micro_recorder_release/deploy_micro_recorder.sh` (jen nový pin) | `e69e04643fc17e35b1d90b229ad20d5a6266b01e030a8b1beec5d073aaa3e4a4` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` (beze změny) | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |
| `tests/test_micro_recorder.py` (11 testů) | `fff19b3fdbeefde39fde56c8ec16a44b4ea5c5240078dc7f15e32967ad6de5c6` |
| `tests/test_deploy_micro_recorder_script.py` (beze změny) | `291bfb73e2d2feb6b37b7cd35fd29cdf44105fc4f9cb0b4189b9887a970d1c5d` |

**Ověř:**
1. **Dvě spojení:** order book přes `/public` a likvidace přes `/market`. Je správné
   - zpracovávat zprávy jedním dispatchem;
   - mít značky `connect`/`disconnect` podle jména spojení;
   - backoff zvlášť pro každé spojení;
   - při pádu vlákna `os._exit(4)`;
   - hodinový log počtů?
2. **Upgrade** pouze kombinací schválených fází: starý `rollback` (pin rev. 5), pak nový `preflight` +
   `install` + `verify`; návrat opačně. Díra je jednotky sekund a uzavře ji `start` marker.
3. **Deploy skript:** změna pouze pinu, `git diff` je 1 řádek.
4. **Smoke test** rev. 6 běžel naživo do dočasného adresáře ~130 s:
   - 4 likvidace, 833 řádků order booku;
   - produkční služba ani bot nebyly dotčeny.
   Je to přijatelné?
5. **Rozšíření verify:** chybí kontrola, že soubory `liq_sampled` vznikají. Po upgradu ji udělám ručně. Má být
   součástí `verify`, a pokud ano, jako varování, nebo jako selhání? Ticho může být legitimní.

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py tests/test_deploy_micro_recorder_script.py`
a `protected_sha.py` před a po. Lokálně 33 testů prošlo, 1 přeskočen, `PROTECTED_SAME`.
