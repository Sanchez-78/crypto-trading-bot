# Rozhodovací pravidlo po měřicím okně (předem zapsáno 2026-11-26 ~13:40 UTC, před koncem okna)

Operátor 2026-11-26: „pokračuj s měřením a automaticky po skončení vyhodnoť a se zlepšením WR a PL“.

Okno (`docs/OPERATING_STATE.md`, zapsáno 2026-11-25 před T0) běží beze změny do
**2026-12-02 09:00 UTC**. Tento dokument doplňuje, **co se po vyhodnocení mechanicky stane**. Výsledky
okna jsem nepočítal. Jediný běh skriptu na datech byl smoke test na 7 dnech **před** T0.

## Vyhodnocení (jednou)

- Skript `scripts/research/threshold_window_eval.py` (SHA-256 `571ef346…77852`), testy
  `tests/test_threshold_window_eval.py` (12 testů, `caf4ed02…8c1`). Jen stdlib, DB `mode=ro` +
  `PRAGMA query_only=ON`, zápis jen na stdout.
- Spuštění: **2. 12. ≥ 09:30 UTC**. Skript před `END + 1800 s` odmítne běžet (`NOT_YET`, rc 2).
  Nejdelší držení obchodu za 30 dní před T0 bylo 901 s.
  - Příkaz: `ssh … 'python3 -I - --db /opt/cryptomaster/local_learning_storage/cache.sqlite' < scripts/research/threshold_window_eval.py`
- Výstup: `_workspace/threshold_window_20261202/result.json` + SHA-256. Skript se po běhu nemění.
- Metriky podle předregistrace pro všechny obchody i pro každý řez (≥ −25 / ≥ −10 / ≥ 0):
  - n;
  - kanonický WR, tj. výhry / n. Hranice ±0,05 % je stejná jako v `trade_metrics_contract`;
  - průměrný a kumulativní net bps, kumulativní USD;
  - PF;
  - 95% CI průměru (bootstrap přes UTC dny, 4 000 replikací);
  - kalibrace `predicted_net_edge_bps` (Spearman, Pearson, kvintily).
- Řez filtruje stejnou veličinu jako serverový práh:
  - `predicted_net_edge_bps = ev_at_entry × 10⁴`;
  - u průzkumu je to `net_expected_edge_bps` (`p0_8_plus_live_pipeline.py:180`);
  - brána je `net_expected_edge_bps >= PAPER_PROBE_MIN_NET_BPS` (`paper_source_learning.py:129`).

## Pravidlo (mechanické)

1. **n < 1 000 → `INSUFFICIENT_DATA`.** Nic se nemění, okno se neprodlužuje.
2. **Způsobilý řez** c ∈ {−10, 0} musí splnit obojí:
   - vybere ≥ 100 obchodů;
   - obchody, které by vyřadil, jsou na obchod horší. Párový bootstrap přes UTC dny: dolní mez 95% CI
     rozdílu (vybrané − vyřazené) musí být > 0.
3. **Žádný způsobilý řez → `KEEP_CURRENT`.** Práh zůstává −25.
4. **Jinak `TIGHTEN`:** vyhrává způsobilý řez s nejvyšším průměrem net bps; při shodě volnější řez.
   - Štítek `POSITIVE_HYPOTHESIS`, když dolní mez CI průměru zvoleného řezu > 0. Jinak `LOSS_REDUCTION`.
   - `POSITIVE_HYPOTHESIS` je jen hypotéza k replikaci, ne důkaz zisku.

## Akce při `TIGHTEN` (jen PAPER)

- **Mění se jen jeden řádek:** `PAPER_PROBE_MIN_NET_BPS=-25` → doporučený řez v
  `/etc/systemd/system/cryptomaster.service.d/zzzzzzzzzz-probe-volume.conf`.
- **Postup:**
  1. Záloha drop-inu do `/opt/cryptomaster_deploy_backups/probe-min-net-<UTC>/`.
  2. Kontrola, že drop-in obsahuje přesně řádek `Environment="PAPER_PROBE_MIN_NET_BPS=-25"`, jinak STOP.
  3. Náhrada řádku, `systemctl daemon-reload`, `systemctl restart cryptomaster.service`.
  4. **Ověření:**
     - služba `active`;
     - `/proc/<nový PID>/environ` obsahuje novou hodnotu;
     - do 30 min `PAPER_ENTRY`, nebo v logu odmítnutí kvůli prahu;
     - žádný traceback ve `validate_config`.
     Selhání → obnova zálohy a restart.
- **Nemění se:** TP/SL, náklady, limity 480/30/300 s, symboly, CONTROL podíl, model, REAL, Stonkfly ani
  sběrač.
- **Proč to zlepší WR a P/L:** podle dat z okna je ztráta na vybraných obchodech nižší a WR vyšší.
  Méně obchodů navíc znamená pomalejší kumulativní ztrátu. **Kladné P/L to neslibuje.**
- **Cena:** o 60–85 % méně PAPER vzorků pro učení. Dřívější rozhodnutí Codexu B (2026-11-24, −25 neměnit)
  stálo na cíli „max vzorků“. Operátor teď výslovně upřednostňuje zlepšení WR a P/L.

## Replikace po `TIGHTEN`

- Nové 7denní okno začne T1 = čas restartu.
- **Kritérium `REPLICATED`:** dolní mez 95% CI (bootstrap přes dny) průměru net bps v okně 2 je vyšší
  než průměr všech obchodů okna 1 (bodový odhad, práh −25).
- Jinak `NOT_REPLICATED`, tedy návrat na −25 stejným postupem.
- Skript replikace připravím před koncem okna 2 s vlastním Codex review.

## Fail-closed

Když skript selže (neplatný řádek, duplicitní `trade_id`, chyba DB) nebo výstup nejde jednoznačně namapovat
na pravidlo, nic se nemění a jde to Codexu.

## Známé předem (ne test)

Smoke test na 7 dnech před T0 (n 1 911; tato data už byla analyzována) by dal `TIGHTEN 0 /
LOSS_REDUCTION`:

| Řez | n | net bps |
|---|---:|---:|
| ≥ −25 | 1 907 | −8,33 |
| ≥ −10 | 744 | −6,77 |
| ≥ 0 | 231 | −4,02 |

Okno je nezávislá kontrola tohoto vzoru.
