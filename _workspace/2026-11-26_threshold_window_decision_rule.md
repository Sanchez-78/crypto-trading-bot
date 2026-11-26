# Rozhodovací pravidlo po měřicím okně — rev. 3 (předem zapsáno 2026-11-26, před koncem okna)

Rev. 3 opravuje re-review R2 (`_workspace/2026-11-26_codex_rereview_threshold_window_rule_r2.md`):
- oba kandidáti jsou vždy v Holmově rodině (netestovatelný s p = `None`, nezamítnutelný);
- chybějící nebo neplatné `pnl_usd` označí USD metriky jako `NOT_EVALUABLE_MISSING_PNL_USD` (počet `missing_pnl_usd`), nikdy jako nulu.

Operátor 2026-11-26: „pokračuj s měřením a automaticky po skončení vyhodnoť a se zlepšením WR a PL“.

Rev. 2 opravuje review Codexu (`_workspace/2026-11-26_codex_review_threshold_window_rule.md`, CHANGES_REQUIRED):
- srovnává se jen s nově vyřazenými obchody;
- populace je vymezená bránou;
- Holmova korekce pro dva prahy;
- bez časového override v CLI;
- WR jen jako hypotéza;
- žádná automatická změna konfigurace.

Okno (`docs/OPERATING_STATE.md`, zapsáno 2026-11-25 před T0) běží beze změny do
**2026-12-02 09:00 UTC**. Výsledky okna jsem nepočítal. Skript běžel jen jako smoke test na 7 dnech
**před** T0.

## Vyhodnocení (jednou)

- **Skript:** `scripts/research/threshold_window_eval.py` (rev. 3, SHA-256 `1f999cc1…d4d0`).
  - Testy: `tests/test_threshold_window_eval.py` (24 testů, `0533d5ae…0755`).
  - Jen stdlib. DB otevírá s `mode=ro` + `PRAGMA query_only=ON`, zapisuje jen na stdout.
- **Kdy:** 2. 12. ≥ 09:30 UTC.
  - Před `END + 1800 s` skript odmítne běžet (`NOT_YET`, rc 2). CLI nemá žádný časový override; testy
    nahrazují `time.time`.
  - Příkaz: `ssh … 'python3 -I - --db /opt/cryptomaster/local_learning_storage/cache.sqlite' < scripts/research/threshold_window_eval.py`
- **Výstup:** `_workspace/threshold_window_20261202/result.json` + SHA-256.

## Populace

- **Populace brány G:** obchody okna (vstup v [T0, END)) s platnou `predicted_net_edge_bps` ≥ −25.
  - Predikce se ukládá jen pro `explore_bucket == P0_8_PLUS_EVIDENCE_COLLECTION`
    (`local_persistent_cache.py:328`).
  - Je to stejná veličina, kterou kontroluje brána `PAPER_PROBE_MIN_NET_BPS`:
    `p0_8_plus_live_pipeline.py:180`, brána `>=` v `paper_source_learning.py:129`.
- **Minimum 1 000 obchodů se počítá jen z G**, jinak `INSUFFICIENT_DATA`.
- **Jen popisně:**
  - všechny obchody okna;
  - počet bez predikce;
  - počet pod −25. Ty v okně nemají být, protože je brána nepustila.
- **Metriky pro G a každý řez:**
  - n;
  - kanonický WR (výhry / n, hranice ±0,05 % podle `trade_metrics_contract`);
  - průměrný a kumulativní net bps; USD a PF jen popisně (při chybějícím `pnl_usd` nevyhodnotitelné);
  - 95% CI průměru (bootstrap přes UTC dny, 4 000 replikací);
  - kalibrace na G.

## Pravidlo

1. **G < 1 000 → `INSUFFICIENT_DATA`.**
2. **Pro c ∈ {−10, 0}:**
   - ponechané K_c = predikce ≥ c;
   - nově vyřazené D_c = −25 ≤ predikce < c;
   - H_c: průměr(K_c) − průměr(D_c) ≤ 0;
   - jednostranné p z párového bootstrapu přes UTC dny: (počet rozdílů ≤ 0 + 1) / (platné + 1).
3. **Holmova korekce** přes obě hypotézy na rodinné hladině 0,025 (jednostranně):
   - menší p ≤ 0,0125, druhé p ≤ 0,025;
   - hypotéza je testovatelná jen při |K_c| ≥ 100 a |D_c| ≥ 1. Netestovatelný kandidát zůstává v rodině
     (p = `None`, nezamítá se), takže druhý musí projít prvním krokem 0,0125.
4. **Způsobilý řez** = H_c zamítnutá.
   - Žádný způsobilý řez → `KEEP_CURRENT`.
   - Jinak `TIGHTEN` s řezem s nejvyšším průměrem net bps; při shodě volnější řez.
   - Štítek `POSITIVE_HYPOTHESIS`, když dolní mez CI průměru K_c > 0, jinak `LOSS_REDUCTION`.
5. **WR v pravidle není.** Vyšší WR po zpřísnění je hypotéza, ne předpověď.
6. **Výsledek je prediktivní třídění, ne kauzální účinek prahu.** I `TIGHTEN` jen opravňuje navrhnout změnu.

## Co následuje po výsledku (žádná automatická změna konfigurace)

- **`INSUFFICIENT_DATA` / `KEEP_CURRENT`:** nic se nemění. Report + Codex audit výsledku.
- **`TIGHTEN`:** připravím konkrétní postimage drop-inu
  `/etc/systemd/system/cryptomaster.service.d/zzzzzzzzzz-probe-volume.conf`.
  - Mění se jen řádek `Environment="PAPER_PROBE_MIN_NET_BPS=-25"` → doporučený řez.
  - Postup nasazení:
    1. záloha do `/opt/cryptomaster_deploy_backups/probe-min-net-<UTC>/`;
    2. kontrola přesného předobrazu, jinak STOP;
    3. `daemon-reload` + restart;
    4. ověření: `active`, nová hodnota v `/proc/<PID>/environ`, `PAPER_ENTRY` nebo odmítnutí prahem do
       30 min, bez tracebacku z `validate_config`;
    5. při selhání obnova zálohy.
  - **Návrh i výsledek jdou Codexu k samostatnému review.** Nasazuje se až po jeho schválení.
- **Nikdy se nemění:** TP/SL, náklady, limity 480/30/300 s, symboly, CONTROL podíl, model, REAL,
  Stonkfly ani sběrač.
- **Cena zpřísnění:** o 60–85 % méně PAPER vzorků pro učení. Dřívější rozhodnutí Codexu B
  (2026-11-24) stálo na cíli „max vzorků“; operátor teď upřednostňuje WR a P/L.
- **Replikace po případném nasazení:**
  - 7denní okno od restartu;
  - `REPLICATED`, když dolní mez 95% CI (dny) průměru net bps okna 2 > průměr G okna 1;
  - jinak návrat na −25;
  - skript replikace bude mít vlastní review.

## Fail-closed

Při chybě skriptu (neplatný řádek, duplicitní `trade_id`, DB) nebo nejednoznačném výsledku se nic nemění
a výsledek jde Codexu.

## Známé předem (ne test)

Smoke test rev. 2 na 7 dnech (rev. 3 mění jen netestovatelné řezy a USD, oba řezy zde testovatelné) před T0 (už analyzovaná data):

| | Počet |
|---|---:|
| G | 1 907 |
| bez predikce | 4 |
| pod −25 | 0 |

| Řez | K: n, bps | D: n, bps | p | Holm |
|---|---|---|---:|---|
| −10 | 744, −6,77 | 1 163, −9,33 | 0,038 | ne |
| 0 | 231, −4,02 | 1 676, −8,93 | 0,0147 | ne (> 0,0125) |

Výsledek smoke testu: `KEEP_CURRENT`. Pravidlo je tedy konzervativní: 7 dní vzorku dalo těsně pod hranicí.
