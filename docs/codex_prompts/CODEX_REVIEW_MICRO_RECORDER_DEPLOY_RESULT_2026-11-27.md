# Audit výsledku nasazení sběrače rev. 6 přes deploy skript rev. 7 (Codex, 2026-11-27)

Jen audit, bez SSH, nasazení a zápisu souborů. Report vrať česky jako poslední zprávu (Claude ho uloží do
`_workspace/2026-11-27_codex_review_micro_recorder_deploy_result.md`).

Verdikt: **ACCEPT / FOLLOW_UP_REQUIRED** (FOLLOW_UP = konkrétní krok, který je nutný před verify 24 h).

**Podklady:**
- `docs/OPERATING_STATE.md`, sekce „Výzkumný sběrač…“, odrážka „Rev. 6 NASAZENA 2026-11-27 13:51:53 UTC“;
- `_workspace/2026-11-26_micro_recorder_design.md`, sekce Rev. 6 a Rev. 7;
- tvůj posudek `_workspace/2026-11-27_codex_review_micro_recorder_r7.md`.

**Shrnutí výsledku** (výstupy příkazů na serveru, Claude):
- 3 hashe v `/root/micro-recorder-20261127/` odpovídají pinům: `b09b31b1…`, `a00b1266…`, `35b35cc0…`.
- `PREFLIGHT_OK`, `INSTALL_OK`, `CHECKS_OK mem=15896576`.
- Gaps 2026-11-27: `start pid=2041483`, `connect public`, `connect market`.
- `verify` po 10 min `VERIFY_OK`:
  - book od startu 4 611 řádků, 658–659 na symbol za 659 s;
  - `liq_sampled` 6 řádků (ETH 3, BTC 1, BNB 1, XRP 1);
  - NRestarts 0, MemoryPeak 16,7 MB, CPU 5,5 s, PID bota 3840326 beze změny.
- Díra v order booku 781 s (13:38:53 → 13:51:54 UTC).
- `verify` vypisuje `du -sh /var/lib/cryptomaster-micro` jako `0` (du nesleduje symlink), skutečnost je 35 MB.

**Ověř a odpověz:**
1. Je nasazení podle podkladů v souladu se schváleným postupem R7? Chybí nějaký důkaz?
2. Díra 781 s je v datech vyznačená jen markerem `start` (rollback nezapsal `disconnect`). Stačí to pro
   budoucí výzkum, nebo má výzkum díry odvozovat i z časů v `book`?
3. Kosmetika `du` u symlinku: opravit hned (nové kolo review), nebo až s další potřebnou změnou skriptu?
4. Co má navíc obsahovat verify 24 h (2026-11-28 ~14:00 UTC)? Plánováno: `verify`, počty `liq_sampled`,
   hodinové počty zpráv `public`/`market` v journalu, gaps.
5. Návrh „režimu read-only preflight upgradu“ z R7: má smysl ho připravit teď, nebo až před dalším upgradem?
