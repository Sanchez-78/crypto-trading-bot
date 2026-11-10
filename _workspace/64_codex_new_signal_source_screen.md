# Offline screen futures flow — předregistrace a výsledky

Zadání: `docs/codex_prompts/CODEX_NEW_SIGNAL_SOURCE_SCREEN_2026-11-09.md`.
Datum: 2026-11-09. Pouze offline; žádná změna bota, runtime dat, konfigurace nebo C1.

## Předregistrace — zapsána před prvním výpočtem TRAIN/TEST/HOLDOUT

Tato sekce se po pohledu na TEST nemění. Implementační chyby se případně
zdokumentují samostatně; nezakládají oprávnění ladit hypotézy na TEST.

- Universe: BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT.
- Data: veřejné Binance USD-M futures 1m klines, daily 5min metrics, monthly
  fundingRate; spot 1m klines pro nezávislou část objemové imbalance.
- Období od 2024-01 do posledního dostupného kompletního měsíce, nejvýše
  2026-10 podle data zadání. Chybějící soubory a mezery se explicitně reportují;
  nevyrábějí se syntetická tržní data ani forward-fill neznámých cen.
- TRAIN: [2024-01-01, 2025-07-01). TEST: [2025-07-02, 2026-04-01).
  HOLDOUT: [2026-04-02, konec dostupných dat). První den každého nového bloku
  je embargo; label ani otevřená simulace nesmí překročit konec bloku.
- Hodnota timestampovaná t je dostupná nejdříve t + interval: 1m OHLCV,
  5min metrics; u funding konzervativně až calc_time + funding_interval_hours.
  Funding není zpětně připsán na začátek svého období. Žádný timestamp z budoucna.
- Rozhodnutí na konci 1m baru, vstup na open **následující minuty po tomto
  rozhodnutí** (další 1m prodleva po dostupnosti). Např. bar 12:00 je známý
  ve 12:01, vstup ve 12:02. Hlavní cenový target je futures, nikoli spot.
- R15: signed return od tohoto open k close patnáctého drženého 1m baru.
  TPSL: TP 35 / SL 25 bps, timeout stejných 15 barů. TP i SL ve stejném baru
  znamenají SL; gap skrz SL se plní na horším open, TP maximálně na cíli.
  Ceny chybějící v kterékoli z 15 minut zneplatní celý vzorek.
- Report obou hrubých targetů a po fixním round-trip nákladu 9 a 18 bps.
  Jde o cost-wall screen, nikoli executable fills; skutečný spread, funding
  cashflow, order-book latency a market impact nejsou v těchto fixních scénářích.
- V každé hypotéze/configu nejvýše jeden signál na symbol za 15 minut,
  i pokud TPSL skončí dříve. Žádný souběh uvnitř symbolu.
- Z-skóre: striktně předchozích 7 dní, bez aktuálního bodu v odhadu průměru/SD.
  Vyžadován celý časový warmup a alespoň 80 % očekávaných pozorování u 1m/5m
  řad; u funding nejméně 8 událostí. Nulová SD nebo chybějící input = žádný signál.

### Pevná rodina a grid

U H1–H6 jsou prahy absolutního z-skóre {1, 1.5, 2} a obě orientace ±1.
Pravidlo vybírá jedinou konfiguraci společnou všem symbolům pouze na TRAIN
podle maxima min(průměr R15 net9, průměr TPSL net9); vyžaduje ≥200 TRAIN
signálů. Shoda se řeší lexikografickým ID, žádné dodatečné ladění po TEST.

| Hypotéza | Dva lookbacky | Předem určený score před volbou orientace |
|---|---|---|
| H1 OI × cena | 5, 60 min | sign(ΔOI) × sign(výnos ceny stejného horizontu) × abs(z(ΔOI/OI)); růst OI pokračování, pokles vyčerpání |
| H2 taker ratio | 5, 15 min | z časového průměru `sum_taker_long_short_vol_ratio` |
| H3 top vs retail | 5, 60 min | z časového průměru `sum_toptrader_long_short_ratio − count_long_short_ratio` |
| H4 taker imbalance | 5, 15 min | z součtu 1m imbalance; equal-weight průměr futures a spot `(2*takerBuy-volume)/volume` |
| H5 funding × pohyb | 5, 15 min | −z(funding) pouze pokud sign(funding) souhlasí se směrem pohybu ceny; opačná orientace testuje pokračování |
| H6 BTC vede alty | 1, 5 min | z BTC futures výnosu; obchodují se jen ostatní symboly |

H7: jediná pooled L2 logistická regrese na výše uvedených 12 scores; H6 vstupy
jsou u BTC pevně nula, protože BTC→alty se nevztahuje na BTC samotný. Inputs clip na ±10 a standardizace
jen z příslušného train foldu, bez imputace chybějících hodnot. Label je
kladný hrubý R15. Pro fit se berou jen úplné vzorky na pevném 15min rastru.
C ∈ {0.1, 1, 10} se vybírá podle průměrné log-loss v časové CV na TRAIN:
train 2024 H1 → validation 2024 H2; train do 2024-12 → validation 2025 Q1;
train do 2025-03 → validation 2025 Q2. Vždy 1 den embargo a purge labelů
na hranici. Následně se z OOF predikcí vybraného C zvolí jediný práh
max(p, 1−p) ∈ {0.55, 0.60, 0.65} stejným cost-wall skóre; finální model
se jednou fitne na celém TRAIN. Koeficienty se ukládají jako JSON, ne pickle.

Rozpočet: 6 × 2 lookbacky × 3 prahy × 2 orientace = **72** pravidel;
3 C kandidáti (3 časové foldy každý), potom 3 threshold kandidáti H7.
Celkem nejvýše **75 obchodních konfigurací a 3 regularizační kandidáti**;
počty skutečně vyhodnocených konfigurací, fitů a chybějících dat se reportují.

### Zmrazení, statistika a rozhodnutí

- TRAIN výběr, model a režimový threshold se zapíší před načtením TEST;
  TEST výsledky se zmrazí před načtením HOLDOUT. HOLDOUT se vyhodnotí jednou,
  i kdyby TEST byl negativní. Žádné zpětné přeučení po TEST.
- Regime: efficiency ratio za 60 min; threshold je pooled TRAIN medián,
  nad ním TREND, jinak CHOP. Tržní směr je znaménko známého BTC 24h výnosu.
- Denní block bootstrap společný přes symboly: 2 000 resamplů celých UTC dní,
  včetně dní bez signálu; percentile 95% CI; seed 20261109. Oba targety mají
  vlastní CI. Jednostranné p z centrovaného bootstrapu; pro hypotézu se bere
  horší p obou targetů a Holm přes všech 7 hypotéz samostatně v TEST/HOLDOUT.
- LEAD vyžaduje na TEST i HOLDOUT oba net9 průměry > +3 bps, obě dolní CI >0,
  Holm p≤0.05 a ≥200 signálů v TEST i (konzervativně) v HOLDOUT. Kladné oba
  targety v obou polovinách TEST a v obou režimech. Regime/long/short/UP/DOWN
  kontroly vyžadují ≥20 vzorků a kladné net9 obou targetů; kontrolují se v TEST
  i HOLDOUT. Pro oba targety největší symbolový podíl na součtu kladných
  symbolových net9 výsledků ≤50 %. Žádné dodatečné regime gating.
- Nesplnění = NO_EDGE; chybějící data nebo neověřený běh = NOT_VERIFIED,
  nikdy LEAD. LEAD není návrh nasazení, pouze podklad pro další předregistraci.


## Výsledky skutečného běhu

H1=NO_EDGE, H2=NO_EDGE, H3=NO_EDGE, H4=NO_EDGE, H5=NO_EDGE, H6=NO_EDGE, H7=NO_EDGE.

Předregistrace a testy vznikly 2026-11-09; úplný výpočet TRAIN → TEST → HOLDOUT proběhl 2026-11-10. Přesné začátky etap v UTC jsou v `screen/*.started.json`.

Byla použita skutečná veřejná historická data, nikoli syntetické tržní výsledky. Syntetické fixtures sloužily pouze jednotkovým testům. Nebyl znovu otevřen C1 ani změněn bot.

# Futures flow — offline cost-wall screen

Bez změn bota; fixní náklady jsou scénář, nikoli důkaz executable fills.

| Hypotéza | Blok | n | R15 gross / net9 / net18 bps | R15 CI95 net9 | TPSL gross / net9 / net18 bps | TPSL CI95 net9 | WR TPSL net9 | Max symbol share R15 / TPSL |
|---|---|---:|---|---|---|---|---:|---|
| H1 | TRAIN | 24140 | 1.0094 / -7.9906 / -16.9906 | [-9.0104, -6.9263] | 0.1138 / -8.8862 / -17.8862 | [-9.2439, -8.538] | 0.3870 | N/A / N/A |
| H1 | TEST | 12126 | 0.9128 / -8.0872 / -17.0872 | [-9.5062, -6.4893] | -0.1546 / -9.1546 / -18.1546 | [-9.6779, -8.6566] | 0.3783 | N/A / N/A |
| H1 | HOLDOUT | 9026 | 0.7431 / -8.2569 / -17.2569 | [-9.2397, -7.1477] | -0.0428 / -9.0428 / -18.0428 | [-9.4819, -8.5801] | 0.3552 | N/A / N/A |
| H2 | TRAIN | 60795 | 0.2765 / -8.7235 / -17.7235 | [-9.1031, -8.3503] | 0.1701 / -8.8299 / -17.8299 | [-9.0493, -8.6226] | 0.3402 | N/A / N/A |
| H2 | TEST | 28207 | 0.4093 / -8.5907 / -17.5907 | [-9.0519, -8.1283] | 0.3728 / -8.6272 / -17.6272 | [-8.9141, -8.3131] | 0.3335 | N/A / N/A |
| H2 | HOLDOUT | 19097 | 0.2715 / -8.7285 / -17.7285 | [-9.1983, -8.31] | 0.5147 / -8.4853 / -17.4853 | [-8.8408, -8.1575] | 0.2918 | N/A / N/A |
| H3 | TRAIN | 43096 | 0.7635 / -8.2365 / -17.2365 | [-8.7352, -7.7052] | 0.4362 / -8.5638 / -17.5638 | [-8.8211, -8.3045] | 0.3674 | N/A / N/A |
| H3 | TEST | 22423 | 0.2352 / -8.7648 / -17.7648 | [-9.395, -8.1045] | 0.1621 / -8.8379 / -17.8379 | [-9.2034, -8.4939] | 0.3496 | N/A / N/A |
| H3 | HOLDOUT | 16825 | 0.1538 / -8.8462 / -17.8462 | [-9.4681, -8.1994] | -0.0385 / -9.0385 / -18.0385 | [-9.4068, -8.671] | 0.3205 | N/A / N/A |
| H4 | TRAIN | 53145 | 0.3810 / -8.6190 / -17.6190 | [-8.997, -8.241] | 0.3117 / -8.6883 / -17.6883 | [-8.909, -8.4714] | 0.3446 | N/A / N/A |
| H4 | TEST | 24389 | 0.3818 / -8.6182 / -17.6182 | [-9.0477, -8.1582] | 0.2312 / -8.7688 / -17.7688 | [-9.0811, -8.4434] | 0.3295 | N/A / N/A |
| H4 | HOLDOUT | 17562 | 0.4062 / -8.5938 / -17.5938 | [-9.0758, -8.1238] | 0.4097 / -8.5903 / -17.5903 | [-8.9132, -8.2701] | 0.2926 | N/A / N/A |
| H5 | TRAIN | 76255 | 0.1108 / -8.8892 / -17.8892 | [-9.3177, -8.4596] | 0.0676 / -8.9324 / -17.9324 | [-9.1424, -8.7126] | 0.3599 | N/A / N/A |
| H5 | TEST | 41914 | 0.3996 / -8.6004 / -17.6004 | [-9.0578, -8.1235] | 0.0569 / -8.9431 / -17.9431 | [-9.2019, -8.6616] | 0.3419 | N/A / N/A |
| H5 | HOLDOUT | 37723 | -0.2319 / -9.2319 / -18.2319 | [-9.7332, -8.741] | 0.0509 / -8.9491 / -17.9491 | [-9.2429, -8.6452] | 0.3133 | N/A / N/A |
| H6 | TRAIN | 175290 | 0.6359 / -8.3641 / -17.3641 | [-8.8648, -7.8415] | 0.2635 / -8.7365 / -17.7365 | [-8.9596, -8.5168] | 0.3803 | N/A / N/A |
| H6 | TEST | 89256 | 0.0497 / -8.9503 / -17.9503 | [-9.7354, -8.2141] | 0.0376 / -8.9624 / -17.9624 | [-9.3158, -8.607] | 0.3732 | N/A / N/A |
| H6 | HOLDOUT | 66876 | 0.2876 / -8.7124 / -17.7124 | [-9.2814, -8.1709] | 0.5519 / -8.4481 / -17.4481 | [-8.8302, -8.0602] | 0.3574 | N/A / N/A |
| H7 | TRAIN | 27755 | -0.1621 / -9.1621 / -18.1621 | [-10.7492, -7.6839] | -0.1657 / -9.1657 / -18.1657 | [-9.6278, -8.7166] | 0.3828 | N/A / N/A |
| H7 | TEST | 18570 | -1.5403 / -10.5403 / -19.5403 | [-13.089, -8.3549] | -0.2346 / -9.2346 / -18.2346 | [-9.8156, -8.6257] | 0.3780 | N/A / N/A |
| H7 | HOLDOUT | 13310 | 0.8753 / -8.1247 / -17.1247 | [-9.2421, -7.0628] | 0.7455 / -8.2545 / -17.2545 | [-8.7946, -7.6559] | 0.3689 | N/A / N/A |

## Verdikty

- H1: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H2: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H3: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H4: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H5: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H6: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient
- H7: **NO_EDGE**; TEST:r15_net9_not_above_3; TEST:r15_ci_not_positive; TEST:r15_symbol_concentration; TEST:tpsl_net9_not_above_3; TEST:tpsl_ci_not_positive; TEST:tpsl_symbol_concentration; TEST:holm_not_significant; TEST:side_-1_not_positive_or_insufficient; TEST:side_1_not_positive_or_insufficient; TEST:market_UP_not_positive_or_insufficient; TEST:market_DOWN_not_positive_or_insufficient; TEST:regime_CHOP_not_positive_or_insufficient; TEST:regime_TREND_not_positive_or_insufficient; TEST:half_0_not_positive_or_insufficient; TEST:half_1_not_positive_or_insufficient; HOLDOUT:r15_net9_not_above_3; HOLDOUT:r15_ci_not_positive; HOLDOUT:r15_symbol_concentration; HOLDOUT:tpsl_net9_not_above_3; HOLDOUT:tpsl_ci_not_positive; HOLDOUT:tpsl_symbol_concentration; HOLDOUT:holm_not_significant; HOLDOUT:side_-1_not_positive_or_insufficient; HOLDOUT:side_1_not_positive_or_insufficient; HOLDOUT:market_UP_not_positive_or_insufficient; HOLDOUT:market_DOWN_not_positive_or_insufficient; HOLDOUT:regime_CHOP_not_positive_or_insufficient; HOLDOUT:regime_TREND_not_positive_or_insufficient

Konfigurace pravidel: 75; C kandidáti: 3; úspěšné CV fity: 9.

TRAIN H7 statistiky jsou OOF. Podrobné režimy, poloviny, směry, symboly, CV, datové pokrytí a Holm p jsou v report.json.

Data schema: https://github.com/binance/binance-public-data (spot od 2025 používá mikrosekundy).


## Datové pokrytí a reprodukce

Období archivů: 2024-01 až 2026-10; souborů 7959, nedostupných 0, ZIP data 0.856 GiB. Všechny použité ZIPy ověřeny proti SHA-256 CHECKSUM; při čtení znovu proti zmrazenému manifestu. Úplný seznam je `futures_flow_20261109/download/downloads.json`.

Žádný chybějící archiv.

Počty níže jsou jen uvnitř příslušného bloku, bez warmupu. Přesné chybějící časové intervaly jsou v `report.json` → blok → coverage → sources → missing_ranges (UTC epoch ms); nevzniká cena ani metrika interpolací přes mezeru.

| Blok | Symbol | Futures řádků / chybí | Spot řádků / chybí | Metrics řádků / chybí | Funding událostí |
|---|---|---:|---:|---:|---:|
| TRAIN | BTCUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | ETHUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | SOLUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | ADAUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | BNBUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | DOTUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TRAIN | XRPUSDT | 787680 / 0 | 787680 / 0 | 157409 / 127 | 1641 |
| TEST | BTCUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | ETHUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | SOLUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | ADAUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | BNBUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | DOTUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| TEST | XRPUSDT | 393120 / 0 | 393120 / 0 | 78621 / 3 | 819 |
| HOLDOUT | BTCUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | ETHUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | SOLUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | ADAUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | BNBUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | DOTUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |
| HOLDOUT | XRPUSDT | 305280 / 1440 | 306720 / 0 | 61344 / 0 | 639 |

Přesné mezery uvnitř dostupných archivů (konec intervalu je exkluzivní):

| Blok | Data | Od UTC | Do UTC | Chybí na symbol | Symboly |
|---|---|---|---|---:|---|
| TRAIN | metrics | 2024-02-16 13:35 | 2024-02-17 00:00 | 125 | BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT |
| TRAIN | metrics | 2024-10-28 16:25 | 2024-10-28 16:35 | 2 | BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT |
| TEST | metrics | 2025-08-29 06:20 | 2025-08-29 06:35 | 3 | BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT |
| HOLDOUT | futures | 2026-10-28 00:00 | 2026-10-29 00:00 | 1440 | BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT |

### Zmrazený výběr z TRAIN

| Hypotéza | Feature | Práh | Orientace |
|---|---|---:|---:|
| H1 | H1_60 | 2.0 | +1 |
| H2 | H2_15 | 1.5 | -1 |
| H3 | H3_60 | 2.0 | +1 |
| H4 | H4_15 | 2.0 | -1 |
| H5 | H5_15 | 1.0 | +1 |
| H6 | H6_5 | 1.0 | -1 |
| H7 | logistic | 0.55 | +1 |

Pooled TRAIN medián efficiency ratio: 0.10294118. H7: C=0.1, finální fit na 345443 vzorcích. Detaily CV a všechny TRAIN kandidáty obsahuje `screen/train.json`.

SHA-256 skriptu při výpočtu: `a393d07682630136efd5c29ed6cd6bafbd0cf9b595b32b5c5fff9b5eb1c1328f`. SHA-256 canonical manifestu dat: `08e8895aed77a47ebb36e85209cb8867dc7d658bdab25dccd202e7eef427e294`.

### Číselná interpretace HOLDOUT

Rozsah průměrů jednotlivých zmrazených hypotéz (nejde o výnos společného portfolia):

- R15 po 9 bps: -9.2319 až -8.1247 bps na obchod.
- R15 po 18 bps: -18.2319 až -17.1247 bps na obchod.
- TPSL po 9 bps: -9.0428 až -8.2545 bps na obchod.
- TPSL po 18 bps: -18.0428 až -17.2545 bps na obchod.
- TPSL WR po 9 bps: 29.18–36.89 %.

WR v hlavní tabulce je zlomek 0–1. N/A u podílu symbolu znamená, že žádný symbol nemá kladný součet net9; nepředstavuje splnění podmínky diverzifikace.


Příkazy:

```text
rtk python -X utf8 scripts/research/futures_flow_screen.py --download-only --cache data/research/binance_futures --out _workspace/futures_flow_20261109/download --end-month 2026-10
rtk python -X utf8 -B scripts/research/futures_flow_screen.py --offline --manifest _workspace/futures_flow_20261109/download/downloads.json --cache data/research/binance_futures --out _workspace/futures_flow_20261109/screen --end-month 2026-10
rtk python _workspace/code_audit_20260921_runner.py tests/test_futures_flow_screen.py -q --tb=short
rtk python -X utf8 _workspace/futures_flow_20261109/verify.py
```

Existující zmrazené stage soubory se načtou bez nového výpočtu. Změna kódu/dat/protokolu nebo přerušené první vyhodnocení vyvolá chybu; nemažte zámky pro získání druhého pohledu na HOLDOUT.

Implementace: `scripts/research/futures_flow_screen.py`; testy: `tests/test_futures_flow_screen.py`. Jen stdlib a již přítomné numpy/pandas/scikit-learn, bez nových závislostí. Běh ověřen na Pythonu 3.14, numpy 2.4.3, pandas 3.0.1, scikit-learn 1.8.0; syntaxe odpovídá Pythonu 3.12.

## Testy a kontrola rozsahu

Aritmetika výsledků, náklady, součty rozkladů a shoda zmrazených etap ověřeny bez dalšího čtení tržních dat a bez opakování HOLDOUT (`result_integrity.json`).

Finální izolovaná sada: 29 PASS, 0 FAIL, 0 ERROR. Spouštěn pouze požadovaný testovací soubor; žádná celá sada ani přístup k serveru.

| Mutace | Očekávaná selhání testů |
|---|---:|
| metrics_early | 1 |
| funding_early | 1 |
| tp_before_sl | 2 |
| overlapping | 1 |
| no_purge | 1 |
| early_holdout | 1 |
| z_includes_current | 1 |
| btc_self_lead | 1 |

Podrobné logy/XML a `mutations.json` jsou pod `futures_flow_20261109/`. Mutace běžely pouze v izolované kopii. Síť i vytvoření privátní mutační kopie vyžadovaly povolení mimo sandbox; nešlo o přístup k Hetzneru. Při implementaci zachycena a opravena duplicitní deklarace funkce (před výpočty) a reálné milisekundové offsety funding timestampů. Offset se zachovává, nezaokrouhluje dolů.

Před TRAIN výběrem a před TEST upřesněn H7: H6 hodnoty BTC jsou nula podle zadání 'jen alty'. Původní i upřesněná předregistrace a jejich hashe jsou zachovány v `preregistration_initial.md`, `preregistration.md`, `preregistration_clarification.json`. Žádná hypotéza, lookback, threshold ani kritérium nebyly změněny po pohledu na TEST.

Předchozích 516 hashovaných souborů beze změny, včetně všech šesti runtime souborů. HEAD před: `adcc41e2ec1a13c0ca19d6b52a6a1cd5a0e2e972`, po: `5cd463a744f931bfb851ad591cb702d58c026711`; větev `main`. V tomto úkolu jsem neprovedl commit/push/deploy/restart. Přidal jsem dva požadované kódové soubory, research cache a důkazní/reportové artefakty pod `_workspace`.

HEAD se mezi původním snapshotem 9. 11. a dokončením 10. 11. změnil mimo příkazy tohoto úkolu. Reflog ukazuje `d210d56` (9. 11. 13:49 +01:00, Claude Code plugins) a `5cd463a` (10. 11. 08:02 +01:00, Autonomy daily log). Tyto existující změny zůstaly zachovány; shoda obsahu 516 hashovaných souborů včetně runtime je ověřena nezávisle na HEAD.

| Chráněný soubor | SHA-256 před = po |
|---|---|
| `local_learning_storage/cache.sqlite` | `31767b56391e77b4143c1e1129b7fa2a4447f4c71f931469e512a4f01ed17646` |
| `data/paper_open_positions.json` | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| `server_local_backups/paper_adaptive_learning_state.json` | `9263583f87369276b82646e80d85e92433e6602858b0551204983d064a27c93c` |
| `server_local_backups/learning_state_phase1.json` | `fbf592e2fb30a6d0a1da4d2050c1136dc9718665653a28b498fa2163eaabf5e6` |
| `runtime/v5_quota_usage.sqlite` | `0a3bf519ac254cb670486ff3c9539ccf55385c9f1a17fe8b516f34cf79161b03` |
| `src/runtime/v5_quota_usage.sqlite` | `8b65fbaaccdc984882e1dacc112cbbd16c544fc3c36d58630684205e213f81e1` |

## NOT_VERIFIED a omezení

- Nejde o fills ani výsledek aktuálního bota: model neaplikuje jeho portfolio, admission, learning a risk gates. Fixních 9/18 bps neřeší skutečný spread, funding cashflow, market impact ani latenci. Žádný návrh nasazení.
- Režimy a UP/DOWN jsou předem zvolené trailing diagnostiky, nikoli důkaz market neutrality. Denní bootstrap a Holm omezují statistické omyly za svých předpokladů; nepokrývají všechny strukturální zlomy trhu.
- Dostupnost historické hodnoty na t+interval je konzervativní model timestampu; skutečná publikační latence Binance není v archivech ověřena. Funding je záměrně zpožděn o vlastní interval.
- Skutečné spuštění na Pythonu 3.12, nezávislé review a budoucí forward performance nejsou ověřeny. Ruff nebyl instalován. Výsledek NO_EDGE platí pro tuto předregistrovanou rodinu a cenový screen.

Schémata, přechod spot timestampů na mikrosekundy a CHECKSUM mechanismus: [Binance public data](https://github.com/binance/binance-public-data). Data: [Binance Data Collection](https://data.binance.vision/).
