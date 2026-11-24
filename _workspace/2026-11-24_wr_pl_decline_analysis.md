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
