# Review návrhu sběrače order booku a likvidací (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_review_micro_recorder_design.md`.
Verdikt: **APPROVE_TO_DEPLOY / CHANGES_REQUIRED**.

Navazuje na tvé doporučení C, krok 2: nejdřív návrh, limity paměti a zápisu, potom review a
nasazení až po schválení. Měřicí okno (krok 1) běží do 2026-12-02 beze změny.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_micro_recorder_design.md` | `a546619813d24ba08ce13b2028f82307cd862fdebdaabcd8c02a828934a58259` |
| `scripts/research/micro_recorder.py` | `868e488a7fb73fff0029574fc26dfe0ebf272f8032aea856e0e4bb9800302150` |
| `tests/test_micro_recorder.py` (9 testů) | `409c002fc752ecc43eb868c8e134ad82af891dd672265ae8acc254e17b25ef4b` |
| `_workspace/micro_recorder_release/cryptomaster-micro-recorder.service` | `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8` |

## Shrnutí

- **Sběr:** samostatný proces, systémový `/usr/bin/python3 -I` se stdlib a `websocket-client`.
  Streamy jsou `depth20@500ms` a `forceOrder` pro 7 symbolů. Ukládá 1 řádek odvozených znaků order
  booku na symbol a sekundu, likvidace jako události a mezery jako značky. Vše do denních `csv.gz`
  ve `StateDirectory`.
- **Limity:** `MemoryMax` 128M, `CPUQuota` 20 %, buffer 50 000 řádků, flush 60 s s `fsync`,
  disková pojistka 5 GiB, retence 120 dní a 4 GiB, logy jen do journald s rate-limitem.
  Izolace přes `DynamicUser` a `ProtectSystem=strict`.
- **Lokální měření** (185 s proti živému streamu, jen PC): ≈ 26 MB za den, heap 1,2 MB.
- **Nález na produkci** (jen čtení): `tick-recorder.service` je od 2026-07-10 nefunkční.
  - Jeho DB je smazaná, ale otevřená a drží 1,27 GB disku.
  - Za tu dobu zapsal 6 milionů chyb do `/tmp/tick_recorder.log` (282 MB).
  - RSS 115 MB, rostoucí počet FD.
  - Návrh: v rámci nasazení ho vypnout (`disable --now`) a smazat log.

## Ověř

1. **Bezpečnost pro 4GB produkci:** limity, izolace, chování při chybě zápisu (exit 3 →
   restart s `StartLimit`), při plném disku a při výpadku websocketu (backoff 1–60 s, značky
   `gaps`).
2. **Správnost dat:**
   - poslední snímek sekundy a uzavření sekundy jen po jejím konci;
   - jedna hlavička přes víc gzip členů;
   - pole pásem a pokrytí (`*_range_bps`);
   - likvidace;
   - čitelnost pro pozdější předregistrovaný screening.
3. **Tick-recorder:** smí se v tomto nasazení vypnout a jeho log smazat? Rollback ho neobnovuje,
   protože byl nefunkční.
4. **Rozsah:** stačí `depth20` a `forceOrder`, nebo přidat `aggTrade` (podepsaný objem)?
5. **Postup nasazení a kontroly po 10 min / 24 h.** Je potřeba přísnější skript s piny jako
   u release exit-taxonomy?

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_micro_recorder.py` a
`protected_sha.py` před a po.
