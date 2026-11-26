# Proč „stále padá WR a P/L“ — analýza (Claude, 2026-11-24 ~13:20 UTC)

Jen čtení: `cache.sqlite` přes `mode=ro` + `PRAGMA query_only=ON`. Nic se neměnilo.

## Fakta

- **Nová epocha** (`17b9bb8a…`, od 2026-11-23 13:38 UTC):
  - n = 334, WR 33,2 %, P/L −1,93 USD, průměr −7,74 bps, PF 0,56.
  - Předchozí epocha (n = 4 367): WR 25,7 %, −8,84 bps, PF 0,43. WR tedy neklesá, je vyšší.
- **Šestihodinová okna:**

  | Okno | WR |
  |---|---:|
  | 1 | 41,6 % |
  | 2 | 25,9 % |
  | 3 | 37,8 % |
  | 4 | 26,9 % |

  Při n ≈ 80 je směrodatná chyba WR ~5 p. b. Jde o šum, ne o trend.
- **P/L klesá z principu.** Každý obchod má v průměru zápornou hodnotu (~−8 bps), takže kumulativní
  P/L klesá skoro monotónně. Nejde o nový pokles výkonu.
- **333 z 334 obchodů** jsou průzkum `P0_8_PLUS_EVIDENCE_COLLECTION`. Pouští kandidáty až do
  modelovaného net −25 bps; to je záměr operátora, maximum obchodů pro učení (`docs/OPERATING_STATE.md`).
- **Výplata je skoro symetrická:**
  - výhry `DYNAMIC_TARGET_EXIT` +37,7 bps a `TP` +41,6 bps;
  - ztráty `HARD_STOP_VOLATILITY` −44,4 bps (85 obchodů, −2,83 USD) a `SL` −37,4 bps.

  Bod zvratu je proto ~50–55 % WR, skutečnost je 33 %.
- **Ztrátové obchody jdou proti hned od vstupu:** u `HARD_STOP_VOLATILITY` je medián MFE ~5 bps.
  Jde o chybějící edge vstupu (stejně jako `_workspace/43_…`), ne o vadu výstupu.

## Pomohl by přísnější výběr? (predikovaný net edge, pravidlo zvolené na staré epoše, kontrola na nové)

| Práh `predicted_net_edge_bps` | Stará: n | WR | bps | Nová: n | WR | bps |
|---|---:|---:|---:|---:|---:|---:|
| ≥ −25 (dnes) | 4 220 | 25,5 % | −8,85 | 333 | 33,0 % | −7,79 |
| ≥ −10 | 1 529 | 29,8 % | −8,35 | 139 | 36,7 % | −5,68 |
| ≥ 0 | 356 | 39,3 % | −5,92 | 58 | 39,7 % | −4,75 |
| ≥ 5 | 192 | 44,3 % | −4,40 | 44 | 45,5 % | −3,89 |

- **Prediktor třídí WR monotónně**, na obou epochách.
- **Průměr na obchod se ale zlepší jen asi o polovinu a zůstane záporný.** Žádný práh ani podskupina
  s rozumným n nedává kladný průměr.
  - `dynamic_breakout_exit_v1`: na nové epoše +4,2 bps (n = 27), na staré −5,03 (n = 232). Není
    to robustní.
- **Zpřísnění** (např. práh ≥ 0) by:
  - zvedlo WR na ~40 %;
  - snížilo ztrátu na obchod ~o 40 %;
  - snížilo počet obchodů o ~80–85 %, takže kumulativní ztráta by klesala ~10× pomaleji;
  - nepřineslo kladné P/L;
  - šlo proti cíli „co nejvíc obchodů pro učení“.

## Závěr

Měřený WR neklesá. P/L klesá, protože signály nemají edge nad náklady 9 bps a průzkum záměrně
pouští záporně modelované kandidáty. Rychlá oprava, která by z toho udělala zisk, v datech není.
Jediná podložená páka je práh průzkumu: méně ztráty a vyšší WR za cenu objemu učení. Změna se
nasazuje jen po rozhodnutí operátora a review Codexu.

## Aktualizace 2026-11-26 ~08:45 UTC (jen čtení)

- **Epocha `17b9bb8a…`:** n = 913, WR 29,7 % (271 výher, 511 ztrát, 131 nul), PF 0,50, průměr ≈ −8,3 bps
  na obchod. Posledních 100 obchodů: WR 20 %, PF 0,31.
- **12h okna** (n ≈ 160): WR 33,9 / 31,0 / 25,6 / 23,1 / 39,5 / 20,6 %, průměr vždy −3 až −12 bps.
  - Kolísá to kolem ~30 %. Při n ≈ 160 je směrodatná chyba ~3,6 p. b.
  - Na trvalý pád to nevypadá, ale poslední okno je dole.
- **Hrubý pohyb ≈ 0:** průměr net −8,3 bps + náklad 9 bps ≈ +0,7 bps hrubě.
  - Při TP 35 / SL 25 a nákladu 9 bps je potřeba WR ~57 %.
  - Ani obrácení směru by nepomohlo: hrubě −0,7, net −9,7.
- **Segmenty před T0** (30 dní, n = 4 699, profil × režim × strana, n ≥ 60):
  - **žádný segment nemá kladný průměr**;
  - nejlepší je `dynamic_breakout_exit_v1` / SIDEWAYS / BUY: −2,70 bps (n 128, WR 41 %);
  - nejhorší jsou `dynamic_trend_exit_v1` / BULL / BUY −10,5 bps (n 1 432) a
    `mean_reversion_exit_v1` / SIDEWAYS / BUY −11,5 bps;
  - po symbolech −7,8 až −11,5 bps.
- **Hodnocené okno:** během předem zapsaného okna (do 2026-12-02 09:00 UTC) se úrovně prahů
  průzkumu na datech okna záměrně nepočítaly.

**Závěr beze změny:** žádný filtr současných signálů nevede ke kladnému P/L. Výběr může snížit
ztrátu na obchod, ne ji otočit. Ke kladnému P/L je potřeba nový zdroj signálu s hrubým pohybem
> 9 bps, nikoli ladění prahů.

## Pomohlo by, kdyby Stonkfly ovlivňoval obchody? (2026-11-26, offline, post hoc)

Operátor povolil, aby Stonkfly ovlivňoval obchody, pokud to pomůže. Test offline:
- **Data:** BTC obchody 13. 10. – 25. 11. 00:00 UTC (před oknem). Ke každému obchodu poslední
  pozorování Stonkfly do 6 min před vstupem (`c1_rows_20261126.jsonl`). Spárováno 668 z 983 obchodů.
- **Měřítko:** průměr net bps, 95% CI bootstrapem přes dny.

| výběr | n | bps [CI] | WR |
|---|---:|---|---:|
| všechny spárované | 668 | −7,01 [−8,69; −5,38] | 33,2 % |
| strana souhlasí s RD | 139 | −5,82 [−8,82; −2,66] | 27,3 % |
| strana proti RD | 100 | −8,25 [−12,09; −4,33] | 36,0 % |
| strana souhlasí s D − 15 Hz | 430 | −6,30 [−8,11; −4,29] | 34,2 % |
| strana proti D − 15 Hz | 238 | −8,29 [−10,68; −6,12] | 31,5 % |
| jen BUY (= label Stonkfly) | 274 | −8,72 [−10,91; −6,24] | 29,9 % |
| jen SELL | 394 | −5,82 [−8,77; −3,05] | 35,5 % |

- Rozdíly jsou 1–2 bps a intervaly se překrývají. Výběr je post hoc z více variant.
- Řídit se labelem Stonkfly (BUY) je horší než opak.
- Žádná varianta není kladná.

**Rozhodnutí:** vliv Stonkfly na obchody se nezapíná. Nepomohl by a zkreslil by měřicí okno.
