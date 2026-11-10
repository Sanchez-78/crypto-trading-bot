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

H7: jediná pooled L2 logistická regrese na výše uvedených 12 scores (včetně
BTC feature i pro BTC jako vstupu modelu). Inputs clip na ±10 a standardizace
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

## Výsledky

PENDING — zatím nebyl proveden žádný výpočet nad TRAIN, TEST ani HOLDOUT.
