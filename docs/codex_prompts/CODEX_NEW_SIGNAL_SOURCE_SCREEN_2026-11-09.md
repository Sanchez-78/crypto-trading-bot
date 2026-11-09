# Codex zadání: offline screen nového zdroje signálu, data z Binance futures (2026-11-09)

**Pro:** Codex (offline výzkum). **Review:** Claude / operátor.
**Režim:** pouze offline výpočty nad veřejnými historickými daty. Bot, server, runtime data
a konfigurace se nemění (`AGENTS.md`). Žádný commit/push/SSH/deploy.
**Report:** `_workspace/64_codex_new_signal_source_screen.md` (česky).

## 1. Proč

- Bot (PAPER, 7 USDT párů: BTC, ETH, SOL, ADA, BNB, DOT, XRP) nemá prokázaný edge. Za 915
  obchodů je hrubý pohyb po vstupu +0,02 ± 1,34 bps a čistý výsledek ≈ −náklad 9 bps
  (`_workspace/58_why_bot_does_not_improve.md`, včetně errat).
- Dosavadní výzkum testoval jen **cenové** signály (breakout, momentum, mean reversion,
  cross-sectional, residual reversal, long-horizon) a funding carry. Všechno selhalo
  (`RESEARCH_COSTWALL_FINDINGS.md`, `RESEARCH_LONGHORIZON_FINDINGS.md`,
  `RESEARCH_FUNDING_CARRY_FINDINGS.md`, `CryptoMaster_EXTERNAL_AUDIT_REPORT_v9.md`).
- **Netestováno:** informace z trhu derivátů a toku objednávek na krátkém horizontu, kde bot
  obchoduje: open interest, poměry long/short, poměr taker buy/sell objemu, funding, imbalance
  z 1m klines (taker buy volume) a vedení BTC vůči altcoinům.
- Cíl operátora: P/L+ a WR > 50 %. Tento screen má levně rozhodnout, zda tato informační sada
  vůbec může překonat náklady, **dřív** než se cokoli staví (charta `RESEARCH_PIVOT_CHARTER.md`:
  „cost wall first, never build first“).

## 2. Geometrie obchodu bota (cílová proměnná musí odpovídat)

Data z epochy do cutoffu C1 (1 083 obchodů): medián držení 495 s, p10 142 s, p90 900 s
(timeout 900 s). TP 35 / SL 25 bps; výstupy TIMEOUT 45 %, strukturální/volatilní hard stop
29 %, SL 13 %, TP 6 %. Náklad paper modelu 9 bps na obchod (round trip). Realistický spot taker
je 15–20 bps.

Cílové proměnné (obě reportovat):
- **R15:** výnos mid/close z 1m klines od otevření další minuty po signálu do +15 min, ve
  směru signálu, v bps.
- **TPSL:** simulace TP 35 / SL 25 / timeout 15 min na 1m high/low od open další minuty.
  Když je TP i SL ve stejné svíčce, počítej SL (konzervativně).

## 3. Data (veřejná, `https://data.binance.vision`)

Cache do `data/research/binance_futures/` (je v `.gitignore`). Nic necommituj.
- USDⓈ-M futures `daily/metrics/<SYM>/` (5min: `sum_open_interest`, `sum_open_interest_value`,
  `count_toptrader_long_short_ratio`, `sum_toptrader_long_short_ratio`,
  `count_long_short_ratio`, `sum_taker_long_short_vol_ratio`).
- USDⓈ-M futures `monthly/fundingRate/<SYM>/`.
- USDⓈ-M futures a spot `monthly/klines/<SYM>/1m/` (sloupec taker buy base volume).
- Období: 2024-01 až poslední dostupný kompletní měsíc. Pokud metrics pro nějaký symbol nebo
  období chybí, uveď přesně co a pokračuj s tím, co je.
- **Když síť není dostupná:** nic nesimuluj ani nevymýšlej. Napiš skript, ověř ho na malém
  syntetickém fixture v `tmp_path`, do reportu dej `NOT_RUN: network` a přesný příkaz ke
  spuštění. Claude data stáhne a skript spustí.

## 4. Předregistrace (zapiš do reportu PŘED prvním výpočtem na testovacích datech)

Rozdělení podle času, bez míchání:
- **TRAIN:** 2024-01 až 2025-06 (výběr pravidel a parametrů).
- **TEST:** 2025-07 až 2026-03 (jediné ověření vybraných pravidel).
- **HOLDOUT:** 2026-04 až konec dat. Nedotýkat se, dokud nejsou pravidla na TEST zmrazená.
  Pak právě jednou, s výsledkem v reportu, ať dopadne jakkoli.
- Embargo 1 den mezi bloky.

Pevná rodina hypotéz. Nic nepřidávej po pohledu na TEST. Každá dvousměrně, z-skóre
z trailing 7 dní, rozhodnutí na uzavřené 5min/1m hodnotě (žádný look-ahead: hodnota s časovým
razítkem t je použitelná až od t + délka intervalu):
1. ΔOI (5–60 min) × směr ceny: rostoucí OI + růst = pokračování, klesající OI + pohyb = vyčerpání.
2. Extrém `sum_taker_long_short_vol_ratio` (5min): pokračování nebo reverze.
3. Extrém top-trader vs. retail long/short (rozdíl `sum_toptrader…` − `count_long_short…`).
4. Imbalance taker buy z 1m klines: (2·takerBuy − vol)/vol, součet 5–15 min.
5. Funding extrém × krátkodobý pohyb (crowded side).
6. BTC vede alty: 1–5min výnos BTC → následný výnos altu (jen alty).
7. Kombinace: jedna regularizovaná logistická regrese (L2, pevné C vybrané na TRAIN časovou
   CV) nad features 1–6, jeden model pro všechny symboly.

Pro každou hypotézu nejvýš 3 prahy a 2 lookbacky, vybrané jen na TRAIN. Reportuj celkový
počet testovaných konfigurací a použij Holmovu korekci nebo samotný HOLDOUT jako jediný
rozhodující test.

Nepřekrývání: v jednom symbolu nanejvýš jeden otevřený signál (další až po 15 min), aby
vzorky odpovídaly obchodům.

## 5. Kritéria (z charty, pevná)

Pravidlo je **LEAD** jen když na TEST i HOLDOUT současně platí:
- průměr R15 i TPSL po nákladu **9 bps > +3 bps** a zvlášť se reportuje výsledek při 18 bps;
- dolní mez 95% block bootstrap CI (bloky po 1 dni) > 0;
- ≥ 200 nepřekrývajících se signálů v TEST;
- kladné v obou polovinách TEST a v ≥ 2 režimech (trend/chop podle efficiency ratio z TRAIN);
- žádný symbol > 50 % zisku;
- není to beta: kontrola výsledku zvlášť pro long a short a v rostoucím a klesajícím trhu.

Jinak **NO_EDGE** pro danou hypotézu. Nadhodnocený výsledek je horší než negativní: když
si nejsi jistý, verdikt je NO_EDGE / `NOT_VERIFIED`.

## 6. Výstup

- Skript `scripts/research/futures_flow_screen.py` (Python 3.12 kompatibilní, jen stdlib +
  knihovny, které už repo používá; žádné nové závislosti). Deterministický (seed), parametry
  na CLI, výstup JSON + markdown do zadaného adresáře.
- Testy `tests/test_futures_flow_screen.py`: look-ahead (feature v čase t nesmí použít data
  po t), TPSL simulace (TP a SL ve stejné svíčce = SL), nepřekrývání, embargo. Spouštěj jen
  tento soubor.
- Report `_workspace/64_codex_new_signal_source_screen.md`:
  předregistrace (zkopírovaná před výpočtem TEST), pokrytí dat, tabulka hypotéz
  (TRAIN/TEST/HOLDOUT, n, průměr hrubý/9/18 bps, CI, WR TPSL, podíl symbolu),
  počet konfigurací, verdikt pro každou hypotézu, co je `NOT_VERIFIED`.
- Jasně odděl ověřené od předpokládaného. Žádná tvrzení o ziskovosti mimo čísla z HOLDOUT.

## 7. Nikdy

Neměň kód bota, konfiguraci, runtime data ani C1 (`docs/OPERATING_STATE.md`). Nenavrhuj
nasazení. Případný LEAD je jen podklad pro operátora a novou předregistraci po skončení C1.
