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
