# Denní přehled učení (režim MAX_DATA od 2026-11-09)

| Datum (UTC) | Obchody/24 h | LEARN kódy | estimate_rho | ctx_p | persist_rho | Křivka ADAPTIVE−CONTROL (bps) | Rozdíl, 95% CI |
|---|---:|---|---:|---:|---:|---|---|
| 2026-11-09 07:15 (výchozí, před zvýšením objemu) | ~47 | SIGNAL_NO_GROSS_EDGE, CONTEXTS_NOISE_ONLY, CONTEXTS_DO_NOT_PERSIST, ESTIMATE_UNINFORMATIVE, CURVE_FLAT_OR_WORSE | −0,11 | 0,752 | −0,19 | +2,87 / +2,56 / +1,02 / −1,25 | +1,39 [−1,42; +4,20] |

07:17 UTC nasazeno zvýšení objemu (480/den, 30/h, cooldown 300 s, min. net −25 bps, bez blacklistu).
První 3 minuty: 3 vstupy (ETH, BTC, SOL).

07:31 UTC sběrný režim `PAPER_LEARNING_CONTROL_FRACTION=1.0` (všichni kandidáti vstupují, odhad učení se jen loguje);
předregistrace C1_contrarian, `prereg_after=1794209516`. Replay na 915 starších obchodech: všech 10 variant
záporný holdout lift (V0 −3,50 [−7,52; +0,51]). Tempo po zvýšení limitů ~18 obchodů/h.

Od 08:55 UTC slepá fáze C1 — z čerstvých obchodů jen počty.

| Čas (UTC) | Poslední běh / STATUS | Obchody/24 h | Čerstvé (COHORT_BLIND) | C1 | Funnel |
|---|---|---:|---|---|---|
| 2026-11-09 09:59 | 20261109T085520Z OK | 66 (6 symbolů, DOT 0) | 18 / 6 symbolů (~7,3/h → 1 000 za ~5,7 dne) | PENDING | vázající je počet kandidátů (`no_candidate_pattern`), ne limity; tap nasazen 09:57 |
| 2026-11-10 07:01 | 20261110T054710Z OK, ALERT prázdný, disk 58 % | 218 (všech 7, i DOT) | 204 / 7 symbolů (~220/den → 1 000 za ~4,5 dne; pevný konec až po 7 dnech, ~16. 11. 13:31 UTC) | PENDING (`fresh_n=204/1000`, `days=0.93/7`) | 12 h: 993 kandidátů P0.8+ → 259 přijato, 415 `REJECT_STALE_MARKET_DATA` (42 %), 173 learning/cooldown, 87 záporný net, 59 risk; 103 vstupů |
| 2026-11-11 07:00 | 20261111T054700Z OK, ALERT prázdný, disk 59 % | 216 (6 symbolů, DOT 0) | 418 / 7 symbolů (~214/den) | PENDING (`fresh_n=418/1000`, `days=1.93/7`) | 12 h: 1 064 kandidátů → 306 přijato, 448 `REJECT_STALE_MARKET_DATA` (42 %), 133 learning, 106 záporný net, 71 risk; 104 vstupů. Server `run_eval.sh` ≠ repo záměrně (`c1fe52c` čeká na audit Codexu) |
| 2026-11-12 06:54 | 20261112T054720Z OK, ALERT prázdný, disk 59 % | 208 (6 symbolů, DOT 0) | 632 / 7 symbolů (~214/den) | PENDING (`fresh_n=632/1000`, `days=2.93/7`) | 12 h: 1 091 kandidátů → 317 přijato, 473 `REJECT_STALE_MARKET_DATA` (43 %), 146 learning, 109 záporný net, 46 risk; 101 vstupů. Server `run_eval.sh` = repo HEAD (SHA `515090bd…`) |
