# Nový zdroj signálu: offline EVENT screen E1/E2 (předregistrace rev. 3, 2026-11-26)

Rev. 2 zapracovává review `_workspace/2026-11-26_codex_review_event_screen_protocol.md`:
- explicitní nulový bootstrap;
- kontrola úplnosti archivů s fail-closed zastavením;
- TRAIN jen jako výběrový a popisný.

## Proč

Aktuální signály mají hrubý pohyb ≈ 0 proti nákladům 9 bps (`_workspace/2026-11-24_wr_pl_decline_analysis.md`).
Operátor požaduje nový zdroj signálu, pokud je potřeba ke kladnému P/L.

Dřív vyloučené rodiny:
- mikrostruktura (cost wall);
- 10 cenových rodin (momentum a reverze na více horizontech, v roce 2024 šlo o betu, ne alfu);
- funding carry (NO-GO);
- futures flow H1–H7 na 15 min (`_workspace/64_codex_new_signal_source_screen.md`, vše NO_EDGE).

Charter (`RESEARCH_PIVOT_CHARTER.md`) uvádí jako dosud nevyzkoušenou třídu **událostní / režimové
obchodování** a delší držení s pohybem ≫ nákladu. Tento screen testuje dvě takové rodiny. Je to jen
offline cost-wall screen na veřejných datech. Bot, konfigurace ani běžící měřicí okno C1 se nemění.

- Skript: `scripts/research/event_shock_screen.py`.
- Testy: `tests/test_event_shock_screen.py` (11 testů).
- Načítání archivů je převzato ze `scripts/research/futures_flow_screen.py`: kontrola SHA-256,
  ZIP bez rozbalení.

## Data a bloky

- **Symboly:** BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, BNBUSDT, DOTUSDT, XRPUSDT.
- **Zdroje:** Binance USD-M futures 1m klines a fundingRate (data.binance.vision), od 2024-01 do
  posledního kompletního měsíce ≤ 2026-10. Chybějící archivy se vykážou, nic se nedoplňuje.
- **Bloky:**
  - TRAIN [2024-01-01, 2025-07-01);
  - TEST [2025-07-02, 2026-04-01);
  - HOLDOUT [2026-04-02, konec dat).
- **Embargo:** první den TEST a HOLDOUT. Okno držení nesmí přesáhnout konec bloku.
- **Zahřátí:** data se načítají 8 dní před blokem (7denní z-skóre, BTC 24h). Vzorky z tohoto období
  nevznikají.

## Časování (jako screen 64)

- 1m bar s razítkem t je znám v t+1m.
- Rozhodnutí na baru t, vstup na open baru t+2m.
- R_H = znaménko × ln(close H-tého drženého baru / open vstupu) v bps.
- Chybějící bar v držení vzorek zneplatní.
- Funding vypořádaný v `calc_time` se smí použít až od `calc_time + funding_interval_hours`.

## Rodiny a grid (20 konfigurací, pevně dané)

- **E1 šok** (12):
  - r5 = ln(close_t / close_{t−5}), v5 = objem barů t−4..t;
  - z-skóre ze striktně předchozích 7 dní (≥ 80 % pokrytí);
  - signál, když |z_r5| ≥ k a z_v5 ≥ 2;
  - k ∈ {3, 4, 5}, orientace fade (−sign r5) / follow (+sign r5), H ∈ {60, 240} min.
- **E2 funding** (8):
  - pro každé vypořádání T symbolu se vezme f = nejnovější dostupný funding k okamžiku rozhodnutí;
  - z(f) se počítá z 30 předchozích dostupných hodnot;
  - signál, když |z| ≥ k, k ∈ {1, 2}, orientace fade (−sign f) / follow (+sign f);
  - okno pre: rozhodovací bar T−62m, vstup T−60m, H 60;
  - okno post: rozhodovací bar T−1m, vstup T+1m, H 120.
- **Bez souběhu:** v jedné konfiguraci nejvýš jeden otevřený vzorek na symbol. Další signál až po
  výstupu.

## Výběr, zmrazení, statistika

- **Výběr** na TRAIN pro každou rodinu: konfigurace s max. průměrem net9 (= R_H − 9 bps) mezi
  těmi, které mají ≥ 200 vzorků TRAIN. Při shodě rozhoduje id. Bez kandidáta vychází
  `NOT_EVALUABLE`.
- **Zmrazení:** `sealed_stage` ze screenu 64.
  - `train.json` se zapíše dřív, než se spočítá TEST, a `test.json` dřív než HOLDOUT.
  - Každý blok se vyhodnotí jednou.
  - Podpis zahrnuje hash skriptu a manifest dat, takže změna skriptu po TRAIN běh zastaví.
- **Úplnost dat (rev. 2):** před jakoukoli etapou musí být všech 7 × 2 × počet měsíců očekávaných
  archivů (futures a funding) se stavem OK a ověřeným SHA-256. Pro konec 2026-10 je to 476 archivů.
  Jinak běh skončí `NOT_EVALUABLE` a nezapíše nic, ani `manifest.json` ani soubory etap (`check_complete` běží před prvním zápisem; rev. 3).
- **Role TRAIN (rev. 2):** CI a p v `train.json` jsou jen výběrové a popisné (in-sample). Potvrzující
  jsou pouze TEST a HOLDOUT.
- **Statistika:**
  - bootstrap celých kalendářních dnů bloku (včetně dnů bez signálu), 2000×, seed 20261126;
  - 95% percentilové CI průměru net9;
  - jednostranné p pro H1 (průměr net9 > 0) z **explicitního nulového bootstrapu** (rev. 2).
    Každý vzorek net9 se vycentruje odečtením pozorovaného průměru a dny se losují stejně.
    p = (1 + #{nulový průměr ≥ pozorovaný průměr}) / (B + 1);
  - Holm přes 2 rodiny v každém bloku;
  - vykazuje se i net18 (konzervativní náklad).

## LEAD (musí platit v TEST i HOLDOUT)

- průměr net9 > +3 bps;
- dolní mez CI > 0;
- Holm p ≤ 0,05;
- n ≥ 200 (TEST), resp. n ≥ 100 (HOLDOUT);
- net9 > 0 zvlášť při rostoucím i klesajícím BTC za 24 h (každý směr n ≥ 20) a v TEST i v obou
  polovinách;
- žádný symbol nemá víc než 50 % kladného net9 součtu.

Jinak `NO_EDGE`. Chybějící výběr nebo data vedou na `NOT_EVALUABLE`.

**LEAD není nasazení.** Následoval by důkaz se spustitelnými fills podle charteru (bid/ask, latence,
realistické náklady, purged walk-forward) a samostatný shadow protokol. TP/SL ani náklady živého bota
se tímto screenem nemění.

## Meze

- Fixní náklady 9/18 bps jsou scénář, ne skutečné fills.
- BTC 24h je hrubý ukazatel režimu.
- Blok TEST použil už screen 64 pro jiné hypotézy. Tyto hypotézy jsou nové a předem zapsané.
