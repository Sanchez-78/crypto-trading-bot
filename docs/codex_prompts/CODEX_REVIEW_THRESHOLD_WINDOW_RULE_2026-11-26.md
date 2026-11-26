# Review rozhodovacího pravidla po měřicím okně (Codex, 2026-11-26)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_review_threshold_window_rule.md`.

Verdikt: **APPROVE_RULE / CHANGES_REQUIRED**.

Operátor chce, aby se po konci okna (2026-12-02 09:00 UTC) automaticky vyhodnotilo a provedlo zlepšení WR a
P/L. Předem jsem zapsal mechanické pravidlo, výsledky okna jsem nepočítal.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_threshold_window_decision_rule.md` | (viz commit) |
| `scripts/research/threshold_window_eval.py` | `571ef346ee5292e295bf6a44d01c4bd0759f2c2b9b0b20cc383024dbeee77852` |
| `tests/test_threshold_window_eval.py` (12 testů) | `caf4ed026afe454592dffebc62a71ed30c2bd96d7132d02aeb530308da20c8c1` |

**Ověř:**
1. **Shoda s předregistrací** okna v `docs/OPERATING_STATE.md`:
   - okno [T0, END) podle času vstupu;
   - řezy −25/−10/0;
   - minimum 1 000 obchodů;
   - metriky;
   - termín se neprodlužuje.
2. **Rozhodovací pravidlo.** Je přijatelné změnit PAPER práh `PAPER_PROBE_MIN_NET_BPS`, když vyřazené obchody
   jsou prokazatelně horší (párový bootstrap přes dny, dolní mez > 0, ≥ 100 vybraných)? Jde to proti tvému
   rozhodnutí B z 2026-11-24 (−25 neměnit kvůli objemu učení). Operátor teď upřednostňuje WR a P/L.
3. **Ekvivalence řezu a brány:** `predicted_net_edge_bps = ev_at_entry × 10⁴ = net_expected_edge_bps` u
   průzkumu (`p0_8_plus_live_pipeline.py:180`, `local_persistent_cache.py:328`). Brána je `>=`
   (`paper_source_learning.py:129`), rozsah [−100, 0].
4. **Statistika:** bootstrap přes UTC dny, párový rozdíl, štítky `LOSS_REDUCTION` /
   `POSITIVE_HYPOTHESIS`, fail-closed chování a `NOT_YET` před `END + 1800 s`.
5. **Postup nasazení** (jeden řádek drop-inu, záloha, restart, ověření, návrat) a **kritérium replikace**.
6. Smoke test proběhl jen na 7 dnech před T0. Je správně, že nejde o pohled do okna?

Při APPROVE_RULE provedu pravidlo po konci okna mechanicky a pošlu ti výsledek k auditu.

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_threshold_window_eval.py`
a `protected_sha.py` před a po.
