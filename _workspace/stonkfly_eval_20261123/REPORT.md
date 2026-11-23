# Vyhodnocení Stonkfly (2026-11-23, jen čtení)

Skript `stonkfly_eval.py` jsem spustil na serveru přes stdin (`nice`/`ionice`). Databáze
`shadow_excursion.sqlite` a `cache.sqlite` byly otevřené `mode=ro` + `query_only`. Ven šly jen agregáty.

## Data

- Predikce frozen varianty `shadow_strategy_predictions`:
  - `stonkfly_frozen_v1`: 1. 10. – 13. 10.;
  - `stonkfly_frozen_paired_v1`: 13. 10. – 23. 11.
- Do vyhodnocení šly jen nezastaralé predikce s trajektorií `data_quality='ok'` a alespoň 500 s
  cenové cesty: **n = 9 659** za 45 dní.
- Trajektorie je surový pohyb ceny BTC od referenční ceny rozhodnutí (`OBSERVE`), horizont 600 s.
- Simulace odpovídá živé geometrii bota: BUY, TP 35 / SL 25 bps, timeout 600 s, náklad 9 bps round
  trip. Pokud se TP i SL protnou ve stejné sekundě, rozhoduje dřívější extrém.
- Interval spolehlivosti: bootstrap přes celé dny (pozorování se po 5 min a s horizontem 10 min
  překrývají, proto se nepočítají jako nezávislá).

## Výsledky

1. **Stonkfly nemá žádný směr.** Všech 20 038 uložených predikcí (obě varianty, včetně stale) je
   `BUY`, žádné `SELL` ani `HOLD`. Frozen má ve všech případech `KC_spikes = 0` a
   `changed_edges = 0`. Pozorování navíc běží v pevném rytmu (~5 min), takže Stonkfly nevybírá ani
   okamžik. Obchodovat jeho signál je totéž jako „kupuj BTC každých 5 minut“.
2. **Ekonomika „vždy BUY“:**

   | Kohorta | n | Hrubý pohyb 600 s | Čistě (TP/SL, náklad) | 95% CI (dny) | WR |
   |---|---:|---:|---:|---|---:|
   | frozen_v1 | 1 179 | +0,17 bps | −8,91 bps | [−10,04; −7,69] | 13,2 % |
   | frozen_paired_v1 | 8 480 | −0,52 bps | −9,39 bps | [−9,84; −9,01] | 20,1 % |
   | **vše** | **9 659** | **−0,43 bps** | **−9,33 bps** | **[−9,73; −8,95]** | **19,3 %** |

   Hrubý pohyb je prakticky nulový, takže výsledek je ztráta zhruba ve výši nákladu.
   Ziskovost je vyloučená s vysokou jistotou: horní mez CI je −8,95 bps.
3. **Neurální příznaky nenesou informaci o budoucím pohybu.**
   - Data jsem rozdělil chronologicky na dvě poloviny (TRAIN, TEST).
   - Spearman `difference_hz` vs. pohyb za 600 s: +0,002 (TRAIN) a −0,013 (TEST).
   - Spearman `gate_spikes` vs. pohyb za 600 s: −0,016 (TRAIN) a −0,010 (TEST).
   - 94 % pozorování spadá do jediného bucketu (`+d2g2`). Žádný bucket s n ≥ 30 neměl na TRAIN
     kladný čistý průměr, takže pro TEST nebylo co vybrat.
4. **Skutečné PAPER obchody s neurálním kontextem** (BTC, od 13. 10.):
   - s kontextem: n = 43, −6,76 bps, WR 20,9 %;
   - bez kontextu: n = 857, −7,42 bps, WR 33,6 %.
   - 43 obchodů nestačí k rozlišení. Žádné zlepšení vidět není a WR je nižší.

## Závěr

**NO EDGE.** Povolit Stonkfly otevírat obchody by znamenalo nakupovat BTC v pravidelném intervalu
za očekávaných ≈ −9,3 bps na obchod. Ani jeho neurální příznaky (kontextová cesta) neukazují
vztah k budoucímu pohybu.

**Doporučení:**
- oprávnění otevírat obchody neudělovat;
- zvážit vypnutí neurálního kontextu (`PAPER_STONKFLY_CONTEXT_ENABLED=false`), protože jen
  rozděluje BTC obchody do další kohorty bez přínosu;
- případně vypnout celý Stonkfly (`STONKFLY_ENABLED=false`) a ušetřit CPU (~6–8 s výpočtu každých
  5 min na 4GB serveru).

Data, checkpointy a evidence se při vypnutí nemažou. Obě vypnutí jsou změna konfigurace s restartem
služby a podle pravidel jdou přes review.

**Meze vyhodnocení:**
- jen frozen varianta (plastic dává stejné labely BUY);
- jen 600s horizont a živá geometrie TP/SL;
- jiné semantiky (např. jiný horizont) nebyly testovány. Při nulovém hrubém pohybu a konstantním
  labelu ale nemají z čeho edge vytvořit.
