# External Audit — Kolo 9 (funding-carry) — Kompletní podklady

**Sestaveno:** 2026-09-01, na žádost uživatele ("dej mi vsechny podklady pro externi audit/verdikt").

**Stav:** Kolo 9 už MÁ hotový, doručený verdikt — **NO-GO**, datováno 24. 8. 2026
(`CryptoMaster_EXTERNAL_AUDIT_REPORT_v9.md`, commit `cef00a0`). Tento dokument slučuje
VŠECHNY podklady, které k tomuto kolu patří (prompt, verdikt, evidenční charta, findings
z obou výzkumných větví, a plný zdrojový kód všech tří skriptů), do jednoho souboru pro
snadné předání/referenci. Nic zde není nové — je to jen konsolidace existujících,
commitnutých souborů v repozitáři.

**Pokud chceš připravit NAVAZUJÍCÍ kolo 10** (verdikt sám navrhuje jediný krok, který by ho
mohl změnit: extended 2021/22 historie — viz Sekce 2, "Jeden výsledek..."), řekni to a
připravím samostatný prompt pro kolo 10 stavějící na tomhle základu.

---

## Obsah
0. [Rychlý souhrn verdiktu](#0-rychlý-souhrn-verdiktu)
1. [EXTERNAL_AUDIT_PROMPT_v9.md — otázky položené auditorovi](#1-external_audit_prompt_v9md)
2. [CryptoMaster_EXTERNAL_AUDIT_REPORT_v9.md — doručený verdikt](#2-cryptomaster_external_audit_report_v9md)
3. [RESEARCH_PIVOT_CHARTER.md — evidenční práh (GO podmínky)](#3-research_pivot_chartermd)
4. [RESEARCH_LONGHORIZON_FINDINGS.md — kontext: co bylo zamítnuto před pivotem](#4-research_longhorizon_findingsmd)
5. [RESEARCH_FUNDING_CARRY_FINDINGS.md — v2 headline výsledky](#5-research_funding_carry_findingsmd)
6. [Zdrojový kód: funding_carry_v2.py](#6-zdrojový-kód-funding_carry_v2py)
7. [Zdrojový kód: funding_carry_v3.py](#7-zdrojový-kód-funding_carry_v3py)
8. [Zdrojový kód: funding_carry_robustness.py](#8-zdrojový-kód-funding_carry_robustnesspy)

---

## 0. Rychlý souhrn verdiktu

```
Delta-neutral perp-carry paper simulátor (nová infrastruktura): NO-GO, nestavět teď
Perp-leg scope jako princip (paper-only, budoucí lead): NEODMÍTNUTO, otevřeno
Funding-carry jako hypotéza: NENÍ prohlášena za definitivně mrtvou
Aktuální doporučení: NEPOKRAČOVAT v budování infra na základě tohoto leadu; pokud tým chce
  ho oživit, musí nejdřív doplnit extended 2021/22 historii A ukázat, že market-neutralita
  přežívá v3-grade fills (ne jen v2 abstraktní náklady) — obojí, ne jedno z toho
Observation-only sběr dat: může pokračovat (zdarma, žádné pozice)
REAL trading: ABSOLUTNÍ NO-GO
```

**Proč NO-GO, v kostce (4 důvody, plný detail v Sekci 2):**
1. Tvrdý FAIL na vlastním pre-committed prahu (≥200 OOS fills) — efektivní N ≈ 7,8.
2. Definiční vlastnost leadu ("market-neutral, vydělává v UP i DOWN trhu") se pod
   poctivější v3 exekucí zhroutí — down-market coin-měsíce čistě −30bp (base) / −102bp
   (conservative).
3. I v nejpříznivějším čtení je magnitude ~0,7–1,3 %/rok — poblíž nebo pod risk-free
   sazbou (T-bills ~4–5 %/rok) = opportunity-cost wash.
4. Edge dekaduje k prázdnému košíku přesně k datu verdiktu (34,9bp → 18,5bp → prázdný
   košík k 2026-Q2) — pravděpodobně není co sklízet ani při okamžité stavbě infra.

Auditor explicitně zdůraznil: toto **není hodnocení kvality výzkumu** — v3/robustness práce
označil za nejrigoróznější v celém výzkumném oblouku a šablonu pro budoucí leady.

---

## 1. EXTERNAL_AUDIT_PROMPT_v9.md

*(otázky, které jsme položili auditorovi — plné znění, anglicky, jak bylo odesláno)*

# External Audit Prompt v9 — Funding-Carry: Scope & Goal-Interpretation Sign-Off

You are the independent external auditor of the CryptoMaster HF-Quant paper-trading project. Your v8
verdict confirmed retiring DEV_FADE on the M5 cost arithmetic (~15 bp attainable spot round-trip vs
sub-2 bp affordable) and, in Q3, asked us to rank credible remaining paths — explicitly naming
"longer-horizon strategies where 15 bp matters less (hours+ holds, fundamentally different data
needs)" and "migrating to a venue/pair set with structurally lower costs." We pursued exactly that
and are back with the **first lead in the entire arc that survives your skeptic battery.** We now ask
you to rule on scope and goal-interpretation before any infrastructure is built.

### What changed since v8 (verifiable in the repo)
- `RESEARCH_LONGHORIZON_FINDINGS.md` — we first tested price-only long-horizon (tsmom, MA filter,
  donchian, xsec momentum) on 1h spot klines, 2023–2026, with adaptive monthly walk-forward. Two
  survivors (donchian, xsec) **were refuted by the same battery you taught us**: bootstrap CI spanned
  zero, all profit in 2024, wins only in up-markets → 2024 bull BETA, not alpha. Ten price-only
  families now fail rigorous OOS + cost. **Price-only momentum/reversion/breakout on 7 majors is
  beta + noise after costs.** We did not manufacture an edge; the learner correctly refused to.
- Pivot to a DIFFERENT information set: perpetual **funding**. `RESEARCH_FUNDING_CARRY_FINDINGS.md`
  + `scripts/research/funding_carry_v2.py`.

### The lead — delta-neutral funding carry (long spot / short perp, equal notional)
Monthly-rebalanced; a coin enters the equal-weight basket iff trailing-3-month funding
> 0.20 bp/8h (causal filter); a rolled position pays no re-entry cost; per coin-month P&L =
Σ funding (short receives) + basis (spot_ret − perp_ret) − transition cost. **TEST OOS
2025-01 .. 2026-06:**

| check | base 30 bp | stress 40 bp | passes your battery? |
|---|---|---|---|
| mean net / month | +18.5 bp | +16.3 bp | — |
| win_rate (months positive) — the goal metric | **0.733** | 0.733 | ✅ (> 0.50) |
| bootstrap CI[5,95] of monthly mean | **[+5.9, +31.0] bp** | [+3.5, +28.9] | ✅ lower > 0 |
| up-market vs down-market net | +1378 / **+187** | +1323 / +182 | ✅ positive in BOTH |
| max single-symbol profit share | 0.26 | 0.26 | ✅ |
| net by year | 2025 +1500, 2026 +63 | — | ✅ not one-year-only |
| approx annual yield | ~2.0 % | ~1.7 % | (modest) |

Unlike the refuted momentum leads, this is a funding YIELD, not a directional bet — which is
structurally why it wins in down-markets too (market-neutral) and does not collapse to 2024 beta.

**⚠ Reality check (do NOT read the table above at face value):** the v2 figures are single-leg
notional with an abstract 30/40 bp cost. The executable model (check 1 below) shows the honest
picture is **materially weaker — ~0.7–1.0%/yr on true deployed capital, and the down-market cushion
does not survive realistic per-leg fills.** We present v2's headline for continuity but the audit
questions below are framed on the executable numbers, not the headline.

### Deepening now in flight (three independent checks; numbers appended on completion)
We are NOT repeating the maker over-claim. Before asking you to bless scope, three checks are
running against your evidence bar (`RESEARCH_PIVOT_CHARTER.md`):
1. **Executable execution model (`funding_carry_v3.py`, COMPLETE):** short-leg funding accrued
   per-8h on the drifting perp notional, intra-month two-leg MtM at 8h (basis drift confirmed tiny,
   ~0.06 bp/coin-mo — delta-neutral really does cancel direction), realistic per-leg fills
   (optimistic/base/conservative), transition cost both legs, yield on TRUE deployed capital
   (1.48× notional = spot 1.0 + perp margin ~0.33 + 0.15 buffer). **This MATERIALLY DOWNGRADES the
   v2 headline on two fronts:** (i) v2's "~2%/yr" was single-leg; on true deployed capital it is
   **1.30%/yr BASE, 1.03% CONSERVATIVE, ~1.09% even OPTIMISTIC — roughly HALVED**; (ii) under
   realistic per-leg fills the **market-neutral-in-BOTH-directions property FAILS**: down-market
   coin-months net **−30 bp (base) / −102 bp (conservative)**, positive only in the optimistic
   scenario (+54). Net bp/mo: 13.5 opt / 10.8 base / 8.5 conservative; WR 0.667; PF 7.2/4.0/2.8;
   bootstrap CI conservative **[+0.5, +16.7] bp — barely > 0** (one or two bad months flips it).
   P&L decomp (base, 15 mo): funding +1039, basis +45, transition −276. by-year: 2025 +812,
   2026 −9 (≈ flat) → regime-dependent on 2025's rich positive funding. Fee/spread are calibrated
   assumptions, not a booked tier; margin/liquidation path modeled as a static buffer, not stressed.
2. **Robustness (`funding_carry_robustness.py`, COMPLETE except extended-history):** scored against
   your GO thresholds — **6/7 PASS, 1 hard FAIL.** PASS: OOS PF 4.25; expectancy +18.5 bp;
   **block-bootstrap CI lower STAYS POSITIVE** ([+3.48, +35.24] base; [+0.35, +33.59] stress —
   fragile but does NOT span zero, categorically unlike donchian/xsec [−26,+196]); no symbol > 50%
   (BTC 26%); positive in 2 years. **FAIL: the ≥200-fill bar — only 67 coin-months, and with lag-1
   autocorr 0.317 the EFFECTIVE N ≈ 7.8 monthly units** (the 7 coins in a month share that month's
   shock → not independent). Purged/embargoed walk-forward: filter is causal (verified no
   look-ahead); positive at all 6 tested split dates, BUT **monotonic decay** — mean 34.9 bp starting
   2024-06 → 18.5 at 2025-01 → basket EMPTY by 2026-Q2, i.e. the edge is front-loaded in the rich
   2025 funding regime and decays to flat. Negative-funding stress: 83% rich occupancy; the filter
   correctly empties the basket (no forced bad carry, fail-safe) but the strategy simply STOPS
   earning when funding dries up. **Extended pre-2023 history (2020–2022) — the single most decisive
   remaining test — is still downloading; appended as a follow-up.** If 2021/22 carry is also
   CI-positive the thin-sample concern eases materially; if not, this is 2025-regime comfort.
3. **Concrete venue cost (COMPLETE):** Binance VIP0+BNB tier, verified fees — spot 7.5 bp/side,
   USDⓈ-M perp 1.8 maker / 4.5 taker; funding confirmed (short RECEIVES when rate > 0, 8h cadence,
   ±0.3%/8h cap on majors). **True delta-neutral round-trip = ~26–29 bp (avg ≈ 27 bp)**, range 25.5
   (BTC) → 33 (DOT/ADA). **v2's 30/40 bp is realistic-to-mildly-conservative — NOT optimistic**, so
   this lead does not die on a hidden fee wall the way DEV_FADE and the six price-only classes did.
   TWO load-bearing caveats: (i) carry clears the wall **only under v2's roll/amortization** —
   a 1-month in/out FAILS (+18.5 gross − 27 RT ≈ −9 bp; breakeven hold ≈ 1.4–1.6 mo), so the
   no-churn roll discipline is essential; (ii) the ~2 %/yr gross carry is **near the risk-free
   opportunity cost of the fully-funded spot leg** (T-bills ~4–5 %/yr) — on an opportunity-cost
   basis the carry is roughly a wash, which is the real magnitude question below, not a cost wall.

### Executable bottom line — all three checks converge
Presenting honestly, not for continuity: the three independent deepenings agree.
- **Not a cost-wall death (a first in this arc).** Concrete venue cost ~27 bp RT ≤ v2's assumed
  30/40 bp; the fee arithmetic is clean and even favorable. Funding-carry does NOT die the way
  DEV_FADE and the six price-only classes did.
- **But it dies on MAGNITUDE, not cost.** On true deployed capital (1.48×) the yield is
  **~0.7–1.3%/yr**, and the venue check puts that **near/below the risk-free rate** (T-bills
  ~4–5%/yr) — an opportunity-cost wash.
- **Its single best property does not survive execution.** v2's market-neutral "wins in down-markets
  too" (the thing that made it alpha not beta) FLIPS negative in down-months under realistic per-leg
  fills (v3: −30/−102 bp base/conservative).
- **Real but thin and regime-contingent.** Block-bootstrap CI stays positive (categorically unlike
  the refuted momentum leads) — but effective N ≈ 8 months (hard fail on the ≥200-fill bar), the
  edge is front-loaded in 2025's rich funding and decays to an empty basket by 2026-Q2.

So this is a genuine, honestly-measured, market-neutral **cash-enhancement lead of ~sub-1%/yr real**
— not a compelling deployable edge. That framing, not the v2 headline, is what the questions ask you
to rule on.

### Q1 (decisive): is a delta-neutral perp-carry PAPER track within scope?
Your standing constraints (v6–v8) were "Binance **spot** data via WebSocket; single retail-tier
account; REAL = NO-GO." Carry **requires a perpetual short leg** — a USDⓈ-M instrument, not spot.
That is an instrument-scope expansion, in paper simulation only (no real money, no leverage risk
realized). **Do you authorize adding a delta-neutral perp-carry paper track** — a perp-leg paper
simulator + a carry admission/sizing loop — as the project's research direction? If you refuse,
state whether it is the perp-leg scope itself you reject, or the evidence you find insufficient.

### Q2 (goal interpretation): is ~2 %/yr market-neutral yield an acceptable reading of the goal?
The goal is "WR > 50% AND positive paper P&L, honestly." Funding-carry delivers 73% positive months
and CI-positive net — but at a **modest ~2%/yr gross**, and the concrete venue-cost check (3) shows
this is **near the risk-free opportunity cost** of the fully-funded spot leg (T-bills ~4–5%/yr), i.e.
on an opportunity-cost basis the strategy is roughly a wash vs doing nothing — before the still-
unmodeled intra-month basis/roll frictions (check 1) erode it further. Two sub-questions: (a) does a
market-neutral cash-enhancement yield satisfy the goal at all, or does "positive paper P&L" implicitly
require beating the risk-free alternative? (b) if a higher bar is required, name it (expectancy/
Sharpe/excess-over-cash) so the research has a concrete target rather than "positive but trivial."

### Q3: does the lead actually clear the evidence bar, or is it thin-sample comfort?
With only **15 monthly observations**, boundary-only basis, and a funding regime (2025) that was
richly positive, is the CI-positive result durable or is it the same thin/time-concentrated tell in
a market-neutral disguise? Once checks 1–3 are appended, rule: **GO to build the perp-carry paper
simulator, or NO-GO (declare the goal not attainable under current constraints).** Name the single
result that would most change your verdict.

### Ground rules (unchanged)
Be adversarial; refute us where the evidence allows. Cite our artifacts by name. Do not soften the
verdict for continuity's sake: if the honest answer is "stop, the goal is not attainable under these
constraints", say it. REAL trading stays an absolute NO-GO regardless of your answer.

---

## 2. CryptoMaster_EXTERNAL_AUDIT_REPORT_v9.md

*(doručený verdikt — plné znění, česky, jak přišlo)*

# CryptoMaster HF-Quant 5.0 — Externí audit, kolo 9

**Předmět:** rozsah + interpretace cíle pro delta-neutral funding-carry (perp short leg)
**Auditovaný stav:** `EXTERNAL_AUDIT_PROMPT_v9.md`, `RESEARCH_FUNDING_CARRY_FINDINGS.md`,
`scripts/research/funding_carry_v3.py`, `scripts/research/funding_carry_robustness.py`
(commit `cef00a0`)
**Datum:** 24. 8. 2026
**Režim:** PAPER only
**REAL trading:** **ABSOLUTNÍ NO-GO** (nezávisle na výsledku tohoto verdiktu)

### 0. Konečný verdikt

# **NO-GO — nestavět perp-carry paper simulátor na základě tohoto leadu**

Ne proto, že by tým lhal nebo přikrášloval — přesný opak: v3 model a robustness battery
jsou metodicky nejpoctivější a nejpřísnější práce v celém tomto výzkumném oblouku a tým
sám aktivně hledal důvody, proč vlastní headline číslo NEVĚŘIT, a našel je. Verdikt NO-GO
plyne přímo z **jejich vlastních**, sebou vygenerovaných čísel poměřených proti **jejich
vlastnímu**, už dříve schválenému evidenčnímu prahu (`RESEARCH_PIVOT_CHARTER.md`):

1. **Tvrdý FAIL na vlastním pre-committed prahu** (≥200 OOS fills) — efektivní N ≈ 7,8
   měsíčních jednotek po korekci na autokorelaci sdíleného měsíčního funding-režimu. Charta
   nestanovila tento práh jako doporučení, ale jako GO podmínku vedle ostatních pěti — a
   žádná z ostatních pěti pozitivních kontrol tento jeden tvrdý FAIL nekompenzuje.
2. **Definiční vlastnost leadu se pod poctivější exekucí zhroutí.** Celý důvod, proč se
   funding-carry vůbec zkoumal (na rozdíl od deseti zamítnutých price-only rodin), byl
   "market-neutral — vydělává v UP i DOWN trhu". v3's per-leg fill model (ne v2's abstraktní
   30/40bp) ukazuje přesný opak: down-market coin-měsíce čistě **−30bp (base) / −102bp
   (conservative)**. Lead se pod vlastním, přísnějším testem stal tím, co refutovalo
   donchian/xsec — směrovou sázkou, ne neutrálním výnosem.
3. **I v nejpříznivějším čtení je magnitude wash, ne edge.** ~0,7–1,3 %/rok na skutečně
   nasazeném kapitálu je poblíž nebo pod risk-free sazbou (T-bills ~4–5 %/rok) — méně, než
   kolik by operátor vydělal bez jakéhokoli obchodování.
4. **Edge dekaduje k prázdnému košíku přesně k aktuálnímu datu.** Monotónní pokles 34,9bp
   (2024-06) → 18,5bp (2025-01) → prázdný košík (2026-Q2) znamená, že k dnešnímu dni
   (24. 8. 2026) podle vlastních dat týmu pravděpodobně **není co sklízet** ani kdyby byla
   infrastruktura postavena okamžitě.

### 1. Co jsem ověřoval nezávisle (ne jen převzal ze shrnutí)

- Přečetl jsem `funding_carry_v3.py` (406 řádků) a `funding_carry_robustness.py` (398
  řádků) celé, ne jen výstupní JSON, který v promptu chybí (skripty vyžadují stažení dat
  z `data.binance.vision`, které jsem v tomto běhu nespouštěl — viz Sekce 4, Omezení).
- **Sign-check funding konvence (v3, `sign_check()`):** metoda je správná — short receives
  funding when funding>0 na Binance USDⓈ-M je standardní konvence a kód ji explicitně
  ověřuje na konkrétním měsíci (BTCUSDT, 2025-03) místo aby ji jen tvrdil.
- **Two-leg MtM (v3, `coinmonth_pnl()`):** spot leg `+Q_spot*(S_t-S_entry)`, perp leg
  `-Q_perp*(P_t-P_entry)` — správný delta-neutral setup, žádná záměna znaménka. Funding se
  akumuluje na *aktuální* (driftující) perp notional, ne na fixní vstupní hodnotu — to je
  přesně ten rozdíl oproti v2, který tým sám identifikoval jako chybějící a opravil.
- **GO scorecard (robustness, `go_scorecard()`):** mapuje přesně na šest prahů z
  `RESEARCH_PIVOT_CHARTER.md` bod za bodem (PF≥1.20, expectancy≥2bp, CI lower>0, ≥200
  fills, ≥2 pozitivní roky, žádný symbol >50 %) — žádný z prahů nebyl při implementaci
  tiše oslaben nebo přeformulován ve prospěch výsledku.
- **Block bootstrap + efektivní N (`effective_n()`):** `Neff = N*(1-ρ)/(1+ρ)` z lag-1
  autokorelace je standardní (Politis-Romano rodina) vzorec, ne vynález na míru; kód ho
  aplikuje symetricky (a hůř by dopadl u vyšší autokorelace) — nejde o cherry-picking
  metody, která právě prochází.
- **Charta samotná** (`RESEARCH_PIVOT_CHARTER.md`) — verifikoval jsem, že šest prahů
  citovaných v promptu odpovídá doslova tomu, co charta z 19.7. skutečně stanovila jako
  standing requirement, ne parafrázi vytvořenou pro toto kolo.

**Závěr ověření:** metodika je poctivá. Nenašel jsem místo, kde by v3/robustness tichým
předpokladem vylepšovaly vlastní číslo. Pokud něco, tým aktivně hledal a ukázal důvody proti
vlastnímu headline (viz "Executable bottom line" v promptu — to není obvyklé chování týmu,
který chce infrastrukturu prosadit).

### 2. Q1 — Je delta-neutral perp-carry PAPER track v rozsahu?

**Odpověď: rozsah perp-leg (paper-only) sám o sobě NEODMÍTÁM. Odmítám na základě
nedostatečné evidence PRO TENTO KONKRÉTNÍ LEAD.**

Instrument-scope expanze na perpetual futures v PAPER simulaci, bez reálného kapitálu a bez
reálného likvidačního rizika, není principiálně mimo mandát — cíl "WR>50 % a pozitivní paper
P&L" neomezuje informační sadu na spot. Kdyby budoucí lead skutečně splnil všech šest prahů
charty (včetně ≥200 nezávislých fillů a market-neutrality PŘEŽÍVAJÍCÍ realistický v3-grade
fill model), scope by nebyl blokující faktor.

Ale stavba perp-leg simulátoru + carry admission/sizing loop je netriviální nová
infrastruktura (margin, likvidační buffer i jako simulace, funding-rate data pipeline,
delta-neutral rebalancing logika) navrch na systém, který již nese značný technický dluh a
tuto sezónu opakovaně bojoval se stabilitou admission logiky (duplicate trades, admission
deadlock, dead-code v idle-tracking). Stavět další vrstvu složitosti na evidenci, která sama
tvrdě selhává na vlastním pre-committed prahu, je přesně ten vzorec, který `RESEARCH_
PIVOT_CHARTER.md` výslovně zakazuje: *"Lead with the cost-wall check; never build first and
measure later."* Zde je analogie: never build infra on a hard-failed evidence bar.

### 3. Q2 — Je ~2 %/rok (headline) / ~0,7–1,3 %/rok (v3, skutečný kapitál) přijatelné čtení cíle?

**Odpověď: NE jako primární základ pro tvrzení "cíl splněn". ANO jako legitimní, ale
nedostatečný dílčí signál.**

(a) Trh-neutrální cash-enhancement výnos sám o sobě cíl nesplňuje, pokud je pod nebo kolem
risk-free sazby — "pozitivní paper P&L" čtené doslovně by prošlo i výnosem 0,01 %/rok, ale to
by bylo gaming litery cíle proti jeho duchu (demonstrovat, že bot generuje edge, ne že
paper-portfolio technicky nekleslo pod nulu). Sám tým to correctly pojmenoval jako
"opportunity-cost wash" — souhlasím s jejich vlastním hodnocením, ne jen s jejich číslem.

(b) Konkrétní práh, který navrhuji (odpověď na jejich vlastní podotázku (b)): **expectancy
musí po realistických nákladech (v3-grade, ne v2 abstraktní) přesáhnout risk-free sazbu o
smysluplnou marži** (např. ≥ risk-free + 2–3 % ročně čistého, symetricky k tomu, jak charta
již vyžaduje ≥2–3bp rezervu nad transakčními náklady) **A** zároveň musí obstát ve všech
šesti bodech charty **A** market-neutralita musí přežít v3-grade per-leg fill model, ne jen
v2's abstraktní 30/40bp. Tento konkrétní lead selhává na všech třech současně.

### 4. Q3 — Čistí evidence bar, nebo je to thin-sample comfort v market-neutral přestrojení?

**Odpověď: thin-sample comfort, s poctivým sebeodhalením — přesně to, co battery měl odhalit.**

Rozdíl oproti donchian/xsec (RESEARCH_LONGHORIZON_FINDINGS.md) je reálný a stojí za
zaznamenání: bootstrap CI **nepřekračuje nulu** ani v konzervativním scénáři (`[+0,5;
+16,7]bp`), zatímco donchian/xsec měly CI `[−26,+196]` / `[−37,+196]` — kategoricky odlišný
výsledek. Toto NENÍ stejné selhání jako u price-only rodin a nemělo by se tak zjednodušeně
prezentovat.

Ale "CI nepřesahuje nulu" a "clears the evidence bar" nejsou totéž, když **efektivní N je
≈7,8**. — s tak malým N je i CI-positive výsledek přesně ten typ artefaktu, který charta bod 4
(purged nested walk-forward, block bootstrap, report effective sample size) měl chytit, a
chytil ho: split-sweep ukazuje **monotónní decay** (34,9bp → 18,5bp → prázdný košík), což je
přesně signatura "edge byl bohatý v jednom konkrétním režimu (2025 pozitivní funding), ne
strukturální" — analogické tomu, jak donchian/xsec byly "2024 bull beta", jen v jiné ose
(funding-regime místo price-regime).

**Jeden výsledek, který by nejvíc změnil verdikt** (odpověď na jejich explicitní žádost): tým
sám správně identifikoval extended pre-2023 historii (2021 bull, 2022 bear/LUNA/FTX) jako
nejrozhodnější zbývající test — souhlasím. Kdyby 2021/22 carry byl také CI-positive, tenčí
vzorek by přestal být hlavní obavou. **Ale i pozitivní 2021/22 výsledek by NEOPRAVIL** bod 2
z Sekce 0 (market-neutralita selhává pod v3 realistickými fills) ani bod 3 (magnitude je
kolem risk-free) — rehabilitoval by jen tenkost vzorku, ne magnitude ani neutralitu. Proto i
při pozitivním rozšířeném testu bych verdikt NO-GO na stavbu infrastruktury zatím neměnil bez
dalšího kola, které cíleně řeší body 2 a 3.

### 5. Provozní rozhodnutí

```text
Delta-neutral perp-carry paper simulátor (nová infrastruktura): NO-GO, nestavět teď
Perp-leg scope jako princip (paper-only, budoucí lead): NEODMÍTNUTO, otevřeno
Funding-carry jako hypotéza: NENÍ prohlášena za definitivně mrtvou (CI-positive je reálný,
  ojedinělý výsledek v celém oblouku) — ale nezasluhuje si další vázaný výzkumný rozpočet
  BEZ nového, rozhodujícího vstupu (extended history NEBO jiná informační sada)
Aktuální doporučení: NEPOKRAČOVAT v budování infra na základě tohoto leadu; pokud tým chce
  ho oživit, musí nejdřív doplnit extended 2021/22 historii A ukázat, že market-neutralita
  přežívá v3-grade fills (ne jen v2 abstraktní náklady) — obojí, ne jedno z toho
Observation-only sběr dat: může pokračovat (zdarma, žádné pozice) — analogicky k DEV_FADE
  precedentu, shromážděná data se neztrácí, pokud se tým později rozhodne dotest dokončit
REAL trading: ABSOLUTNÍ NO-GO
```

Toto NENÍ hodnocení kvality výzkumu — v3/robustness práce je nejrigoróznější v celém
oblouku a měla by být šablonou pro jakýkoli budoucí lead. Je to hodnocení, že **i poctivě
změřený, skutečně CI-positive signál** může být příliš tenký a příliš blízko risk-free na to,
aby ospravedlnil novou instrument-třídu infrastruktury na systému, který má jinde
nedořešený technický dluh.

### 6. Omezení tohoto auditu

- Neprovedl jsem live spuštění `funding_carry_v3.py` / `funding_carry_robustness.py` (vyžaduje
  stažení ~19 měsíců 8h/denních dat z `data.binance.vision` pro 7 symbolů × 3 instrumenty) —
  ověřil jsem kód (logiku, znaménka, prahy), ne přepočítal čísla nezávisle z raw dat. Čísla v
  `EXTERNAL_AUDIT_PROMPT_v9.md` beru jako self-reported, ale plausibilní vzhledem k ověřené
  logice skriptů, která je vygenerovala.
- Neřeším zde technickou proveditelnost budoucí perp-leg implementace (margin engine, funding
  scheduler) — pouze zda evidence odůvodňuje ji vůbec začít stavět.
- Q2's "risk-free srovnávací rámec" je má vlastní interpretační volba, ne odvozená z projektové
  dokumentace — operátor může tento rámec odmítnout a číst cíl doslovněji; pokud ano, žádám o
  explicitní potvrzení, protože to mění závěr Sekce 3.

**REAL trading = absolutní NO-GO nezávisle na jakémkoli výsledku tohoto verdiktu.**

---

## 3. RESEARCH_PIVOT_CHARTER.md

*(evidenční práh / GO podmínky, na které se auditor v Sekci 2 odkazuje — plné znění)*

# Research Pivot Charter (2026-07-19)

**Decision (autonomous, after external audit kolo 6 verdict C):**
- **DEV_FADE current implementation → RETIRED.** Taker at ~18 bp is unviable; the current
  (midpoint-touch) maker model gives no deployable basis. Kept OFF (bot stays in
  `PAPER_DATA_COLLECTION_ONLY=1`, 0 positions).
- **DEV_FADE hypothesis → NOT declared dead** (audit says evidence is insufficient), but we are
  **not** spending the bounded M1–M5 research budget on it now — the corrected experiment would
  most likely just re-confirm NO-GO (real executable fills are worse than midpoint touches, not
  better). **Research pivots to a different signal class.**
- **Observation-only collection stays ON** (free, no positions) — if anyone later wants the
  corrected DEV_FADE experiment the raw paths keep accruing.
- **REAL trading = absolute NO-GO** (unchanged).

### The one hard lesson: the cost wall
Every failure so far traces to one thing: **execution cost (~18 bp taker round-trip) dwarfs the
signal's gross edge (~2 bp).** So the pivot is governed by a single filter applied *before* any
engineering:

> **A candidate signal is only worth building for if it plausibly clears the cost wall — i.e.
> either (a) gross edge comfortably > ~18 bp per trade, OR (b) a *validated executable* ≤ ~3 bp
> round-trip path.** If neither, do not build infra for it.

DEV_FADE failed (a) (2 bp << 18 bp) and could not prove (b) with the data we had.

### The evidence bar (do NOT repeat the kolo-6 mistakes)
Any future signal's edge claim must be established with the auditor's corrected methodology —
these are now standing requirements, not optional:

1. **Executable fills, not midpoint.** Use bid/ask + aggTrade (aggressor side) + a queue/partial
   proxy. `(bid+ask)/2` touch is NOT a fill. Report optimistic / base / conservative fill
   scenarios; the verdict must hold in base *and* conservative.
2. **Admissible-trade dataset.** Evaluate on trades that would actually pass every entry gate
   (EV, segment, time, exposure, per-symbol/max-open caps) — not raw pre-gate signal candidates.
3. **Fill-time & TIF.** Model when the fill happens and a post-only→cancel(→conditional taker)
   policy; P&L must be measured from the fill, with at least {exit at signal expiry, fixed hold
   from fill}.
4. **Purged nested walk-forward.** Purge/embargo ≥ one max horizon around the split; block/cluster
   bootstrap by time/regime episode; report *effective* sample size (overlapping paths ≠
   independent trials).
5. **Realistic, venue-specific costs.** maker fee/rebate + taker exit + spread + slippage +
   partial-fill/cancel + latency — from a concrete tier, not abstract 0/3/18.
6. **GO thresholds:** OOS PF ≥ 1.20, expectancy > 0 with ≥ +2–3 bp reserve after realistic
   costs, cluster-bootstrap 95% CI lower > 0, ≥ 200 OOS fills for the chosen policy, stable in
   ≥ 2 regimes (or explicitly regime-gated), no symbol > 50% of profit.

### Candidate directions (to be filtered by the cost wall — none chosen yet)
Kept as options for the operator; each must pass a **cheap offline feasibility check against the
cost wall before any code**:
- **Larger-move / lower-frequency capture** — a horizon/signal where the target move is 50–100+ bp
  so ~18 bp is a small fraction (directly attacks the cost wall via (a)). DEV_FADE's own shadow
  data shows moves are tiny, so this needs a *different* predictive signal, not this one.
- **Funding / basis / carry** — perp-spot or cross-exchange structural signals with holding
  periods long enough that per-trade cost is amortized.
- **Event / regime-conditioned** — trade only in states where edge is large enough to clear cost
  (e.g. a fader restricted to validated RANGING regimes — but that still needs the executable
  proof above, and multi-regime data we don't yet have).

### Next concrete step (cheap, before any infra)
For whichever direction is chosen: run an **offline feasibility check first** — does the raw gross
edge plausibly clear ~18 bp (or is there a real ≤3 bp execution path)? Only then build the
executable-fill dataset + model to the evidence bar above. **Lead with the cost-wall check; never
build first and measure later** — that is the mistake this whole arc corrected.

*Governs research direction after DEV_FADE retirement. Pairs with `CryptoMaster_EXTERNAL_AUDIT_REPORT_v6.md` and `AUDIT_CHANGES_LOG.md` (2026-07-19).*

---

## 4. RESEARCH_LONGHORIZON_FINDINGS.md

*(kontext: co bylo testováno a zamítnuto PŘED pivotem na funding-carry — plné znění)*

# Long-Horizon Pivot — Findings (2026-07-21)

**Question:** second-scale strategies die on the ~15 bp attainable cost wall
(`RESEARCH_M5_COST_ARITHMETIC.md`). At multi-hour holds, moves are 100-500 bp, so cost is
friction not a wall. Do LONG-HORIZON, LONG-ONLY (spot) strategies clear realistic costs OOS?
Tested on 1h Binance spot klines for the 7 traded USDT pairs, 2023-01 .. 2026-06 (30,647 bars each,
data.binance.vision). Scripts: `scripts/research/longhorizon_{screen,walkforward,robustness}.py`.

### Step 1 — fixed configs (train 2023-24 select, test 2025-26 OOS): ALL FAIL
Every family: strong positive TRAIN, strong negative TEST — textbook overfitting.

| family | TRAIN exp | TEST exp @15bp |
|---|---|---|
| tsmom | +54 bp | **−53 bp** |
| MA filter | +73 bp | **−37 bp** |
| donchian | +338 bp | **−121 bp** |
| xsec momentum | +273 bp | **−86 bp** |

### Step 2 — walk-forward adaptive (re-select monthly on trailing 12mo): 2 survive... apparently
This is the honest "self-learning" test: each month picks the best config on prior data, trades the
next month (true OOS). tsmom/MA stay dead (~−1.5 bp). donchian +72 bp and xsec +75 bp looked ALIVE
(survive 20 bp stress). **Treated as a LEAD, not an edge** — the maker story also looked positive
and drew auditor verdict C.

### Step 3 — skeptic battery on the two survivors: LEAD REFUTED
| check | donchian | xsec | pass? |
|---|---|---|---|
| bootstrap CI[5,95] of mean net | **[−26, +196] bp** | **[−37, +196] bp** | ❌ lower < 0 |
| net by year | 2024 **+68186**, 2025 −10189, 2026 −15380 | 2024 **+30390**, 2025 −586, 2026 −11525 | ❌ all profit in 2024 |
| up-market vs down-market net | +57703 vs **−15085** | +51061 vs **−32782** | ❌ wins only when market up |
| max single-symbol profit share | 0.27 (XRP) | 0.22 (XRP) | ✅ (only passing check) |

**Verdict:** the apparent walk-forward edge is **2024 bull-market BETA, not alpha.** The adaptive
learner rode a rising market; when 2025-26 turned choppy/down it lost. Statistically insignificant
(CI spans zero), time-concentrated (one year), and directional (long-only beta). No durable,
market-neutral, cost-surviving edge.

### Cumulative honest scoreboard
Ten strategy families now fail rigorous OOS + realistic cost testing:
6 second-scale (`RESEARCH_COSTWALL_FINDINGS.md`) + 4 long-horizon (fixed AND adaptive, here).
The self-learning mechanism itself works (it adapts, selects, gates honestly) — but it can only
harvest what is in the strategy space, and price-only momentum/reversion/breakout on 7 majors
contains only beta + noise after costs.

### What this does and does not imply
- **Does NOT imply** the learning infrastructure is broken. It correctly refuses to manufacture edge.
- **Does imply** that net-of-cost profit needs one of:
  1. a richer information set where alpha may actually live — funding rates / basis, order-book
     microstructure, on-chain flows, cross-asset/macro, sentiment — a real research project, not tuning;
  2. short capability to harvest down-markets (futures) — but that adds leverage/liquidation risk and
     is outside the spot-only, REAL=NO-GO constraint, and momentum-short decay is its own problem;
  3. an explicit beta-timing mandate (be long only in detected bull regimes) — honest, but it is
     "own the market when it rises", not a market-neutral strategy, and it loses in bear markets.
- Open for the external auditor (v8 Q3): rank these, or declare the goal not attainable under the
  current constraints (spot-only, price-only, single retail account, realistic costs).

**REAL trading = absolute NO-GO throughout. No metric-gaming: every number here is out-of-sample.**

---

## 5. RESEARCH_FUNDING_CARRY_FINDINGS.md

*(v2 headline výsledky — plné znění)*

# Funding-Carry — Findings (2026-07-21) — FIRST robustness-surviving lead

**Context:** ten price-only strategy families failed rigorous OOS + cost testing; the apparent
long-horizon edge was 2024 beta (`RESEARCH_LONGHORIZON_FINDINGS.md`). Pivot to a DIFFERENT
information set: perpetual **funding**. Delta-neutral carry (long spot / short perp, equal notional)
harvests funding while cancelling price direction — structurally near-market-neutral, so it should
make money in up AND down markets if real. Scripts: `scripts/research/funding_carry_screen.py`
(v1, funding-term only) and `funding_carry_v2.py` (monthly rebalance + basis + robustness).
Data: Binance funding history + spot/perp daily klines (data.binance.vision), 7 USDT majors.

### Result — v2 passes the skeptic battery that refuted every prior lead
Monthly-rebalanced delta-neutral carry, coins included iff trailing-3mo funding > 0.20 bp/8h,
transition-cost only (no churn), WITH basis (spot_ret − perp_ret). TEST OOS 2025-01..2026-06:

| check | base 30bp | stress 40bp | pass? |
|---|---|---|---|
| mean net / month | +18.5 bp | +16.3 bp | — |
| win_rate (months positive) | **0.733** | 0.733 | ✅ (goal WR>50%) |
| bootstrap CI[5,95] of monthly mean | **[+5.9, +31.0]** | [+3.5, +28.9] | ✅ lower > 0 |
| up-market vs down-market net | +1378 / **+187** | +1323 / **+182** | ✅ positive in BOTH (market-neutral, not beta) |
| max single-symbol profit share | 0.26 | 0.26 | ✅ |
| net by year | 2025 +1500, 2026 +63 | — | ✅ not one-year-only |
| approx annual yield | ~2.0% | ~1.7% | (modest) |

This is the FIRST signal in the whole arc that is positive after realistic costs, has a CI lower
bound above zero, is market-neutral (wins in down-markets too), and is symbol/time diversified.
It structurally differs from the refuted momentum leads: carry is a funding yield, not a directional
bet, which is exactly why it survives the up/down-market split.

### Honest caveats — this is a LEAD, not a validated edge (do not repeat the maker over-claim)
1. **Modest magnitude:** ~2%/yr net. Cash-enhancement / market-neutral yield, not a large return.
2. **Basis is boundary-only:** measured at monthly spot/perp daily closes; intra-month delta-neutral
   tracking error, spot-perp slippage, and roll mechanics are not yet modeled. These can erode carry.
3. **Thin sample:** 15 monthly points; the bootstrap CI, while positive, is over few observations.
4. **Regime dependence:** 2025 funding was richly positive; in a prolonged negative-funding regime
   the breakeven filter empties the basket → flat (no loss, but no yield). 2026 already thinner (+63).
5. **Instrument scope:** carry REQUIRES a perpetual short leg (futures), not spot-only. In PAPER
   simulation that is fine (no real money), but the live bot today runs a single-leg spot fader —
   pursuing carry needs a delta-neutral perp-leg paper simulator (a real architecture step), and the
   auditor/operator should bless expanding the instrument set. REAL = absolute NO-GO regardless.

### Why this matters for the goal
It is the first strategy that could plausibly satisfy WR>50% + positive paper P&L *honestly*: 73%
of months positive, market-neutral, cost-surviving. The "self-learning" target is well-defined —
select durable-positive-funding coins and size the neutral carry — and it learns something REAL
(a structural funding yield) rather than overfitting price noise.

### Recommended next steps (in order)
1. **Deeper execution model:** intra-month basis tracking, realistic spot+perp fills, funding on
   both legs, roll costs, capital/margin efficiency. Confirm ~2%/yr survives.
2. **Longer history / more regimes:** extend before 2023 where data allows; stress a
   negative-funding regime explicitly.
3. **Auditor sign-off** (feed into v8): is a delta-neutral perp-carry paper track within scope, and
   is a ~2%/yr market-neutral yield an acceptable interpretation of the goal, or too modest?
4. **Only then**, if blessed: design the perp-leg paper simulator + a carry admission/sizing loop.

**REAL trading = absolute NO-GO. Every number here is out-of-sample. No metric-gaming.**

---

## 6. Zdrojový kód: funding_carry_v2.py

```python
#!/usr/bin/env python3
"""Funding-carry v2 — monthly-rebalanced delta-neutral carry WITH basis, honest OOS.

v1 finding: funding on majors is mostly positive; a static delta-neutral carry (long spot /
short perp) earned +200..+540 bp over ~18 months on BTC/ETH/ADA/XRP, near-market-neutral. But
v1's per-8h "timed" version churned (683 episodes × 30 bp) and died on cost — a bad execution of
a real signal, not a dead signal.

v2 fixes execution and adds the basis term:
  * MONTHLY rebalance. At each month start, include a coin in the equal-weight carry basket iff
    its trailing-3-month average funding > BREAKEVEN_BPS_PER_8H (must out-earn amortized cost).
    A coin held in consecutive months pays NO re-entry cost (position rolls); cost (30/40 bp) is
    charged only on ENTER and EXIT transitions. This kills the churn.
  * Per held coin-month P&L = Σ funding that month (short receives) + basis (spot_ret − perp_ret,
    the real delta-neutral price P&L) − transition cost. Basis from spot vs perp daily closes.
  * TEST OOS 2025-01..2026-06. Reports monthly net series, WR (fraction of positive months — the
    project's goal metric), annualized yield, up/down-market neutrality, per-coin/-year, bootstrap CI.

A positive, market-neutral, CI>0 result that survives basis + cost is the first legitimate learning
target: the "learning" is selecting durable-positive-funding coins and sizing the neutral carry.
REAL = NO-GO; this is paper research on public data.

Usage: python3 funding_carry_v2.py [cache_dir]
"""
from __future__ import annotations
import csv
import datetime as _dt
import io
import json
import os
import random
import sys
import urllib.request
import zipfile

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 7)]
TEST_START = (2025, 1)
END = (2026, 6)
COST_RT_BPS = {"base": 30.0, "stress": 40.0}
BREAKEVEN_BPS_PER_8H = 0.20     # trailing funding must beat this to bother (amortized cost/risk)
FUND_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
SPOT_URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip"
PERP_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1d/{s}-1d-{m}.zip"


def _dl(url, fp):
    if not os.path.exists(fp):
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return False
    return os.path.exists(fp)


def load_funding(cache):
    out = {}
    for s in SYMBOLS:
        rows = []
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-fund-{m}.zip")
            if not _dl(FUND_URL.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():
                            rows.append((int(row[0]), float(row[2])))
            except Exception:
                pass
        rows.sort()
        out[s] = rows
    return out


def load_daily(cache, url_tmpl, tag):
    out = {}
    for s in SYMBOLS:
        rows = {}
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-{tag}-{m}.zip")
            if not _dl(url_tmpl.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():
                            ts = int(row[0])
                            if ts > 10**14:
                                ts //= 1000
                            rows[ts] = float(row[4])
            except Exception:
                pass
        out[s] = rows
    return out


def ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def nextm(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def prevm(y, m, k):
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


def month_ret(daily_sym, lo, hi):
    ks = sorted(t for t in daily_sym if lo <= t < hi)
    if len(ks) < 2:
        return None
    return daily_sym[ks[-1]] / daily_sym[ks[0]] - 1


def month_funding(fund_sym, lo, hi):
    return sum(r for t, r in fund_sym if lo <= t < hi)


def trailing_avg_funding(fund_sym, lo3, lo):
    xs = [r for t, r in fund_sym if lo3 <= t < lo]
    return (sum(xs) / len(xs)) if xs else None


def run(funding, spot, perp, cost):
    """Monthly-rebalanced neutral carry. Returns (monthly_net[list], coinmonth_tagged[list])."""
    monthly, cm = [], []
    held_prev = set()
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        lo3 = ms(*prevm(y, m, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > BREAKEVEN_BPS_PER_8H:
                basket.append(s)
        held = set(basket)
        month_pnls = []
        for s in basket:
            f_bps = month_funding(funding[s], lo, hi) * 1e4
            sr, pr = month_ret(spot[s], lo, hi), month_ret(perp[s], lo, hi)
            basis_bps = ((sr - pr) * 1e4) if (sr is not None and pr is not None) else 0.0
            trans = 0.0
            if s not in held_prev:
                trans += cost / 2.0                      # enter (half round trip)
            net = f_bps + basis_bps - trans
            month_pnls.append(net)
            cm.append((s, lo, net))
        for s in held_prev - held:                       # pay exit for coins leaving basket
            if cm:
                pass
        exit_cost = len(held_prev - held) * (cost / 2.0)
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls) - exit_cost / max(1, len(month_pnls)))
        held_prev = held
        y, m = nextm(y, m)
    return monthly, cm


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "mean_bps": round(sum(vals) / n, 1), "total_bps": round(sum(vals), 0),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


def boot_ci(vals, B=4000, seed=7):
    n = len(vals)
    if n < 8:
        return None
    rng = random.Random(seed)
    m_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(m_[int(0.05 * B)], 1), round(m_[int(0.95 * B)], 1)


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    funding = load_funding(cache)
    spot = load_daily(cache, SPOT_URL, "spotd")
    perp = load_daily(cache, PERP_URL, "perpd")
    # market proxy: equal-weight perp monthly return
    mkt = {}
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = [month_ret(perp[s], lo, hi) for s in SYMBOLS]
        rs = [r for r in rs if r is not None]
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)

    out = {"note": ("Funding-carry v2: monthly-rebalanced delta-neutral (long spot/short perp) "
                    "carry WITH basis, transition-cost only (no churn). Goal metric = win_rate "
                    "over months. Positive + market-neutral (up~down) + CI>0 surviving basis+cost "
                    "= first legitimate learning target. Costs 30/40 bp per transition.")}
    for scen, cost in COST_RT_BPS.items():
        monthly, cm = run(funding, spot, perp, cost)
        # up/down neutrality on coin-months
        def mkey(t):
            d = _dt.datetime.utcfromtimestamp(t / 1000)
            return (d.year, d.month)
        up = sum(v for _, t, v in cm if mkt.get(mkey(t), 0) >= 0)
        dn = sum(v for _, t, v in cm if mkt.get(mkey(t), 0) < 0)
        prof, by_year = {}, {}
        for s, t, v in cm:
            if v > 0:
                prof[s] = prof.get(s, 0) + v
            yy = _dt.datetime.utcfromtimestamp(t / 1000).year
            by_year[yy] = round(by_year.get(yy, 0) + v, 0)
        tot = sum(prof.values())
        yrs = (END[0] - TEST_START[0]) + (END[1] - TEST_START[1]) / 12.0
        ann = round(sum(monthly) / yrs / 100.0, 2) if monthly else None   # % per year (bps→%)
        out[f"scenario_{scen}"] = {
            "monthly_basket": stats(monthly),
            "monthly_boot_ci_5_95_bps": boot_ci(monthly),
            "approx_annual_yield_pct": ann,
            "coinmonth_net_up_market_bps": round(up, 0),
            "coinmonth_net_down_market_bps": round(dn, 0),
            "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
            "net_bps_by_year": by_year,
        }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
```

---

## 7. Zdrojový kód: funding_carry_v3.py

```python
#!/usr/bin/env python3
"""Funding-carry v3 — honest EXECUTION model for delta-neutral carry (long spot / short perp).

v2 answered "does carry survive basis + transition cost?" at monthly resolution:
  OOS 2025-01..2026-06, 73% months positive, boot CI[+5.9,+31.0]bp, market-neutral, ~2%/yr net.
But v2 measured funding as a monthly SUM and basis from month-boundary daily closes ONLY. That
hides three things the operator asked us to model honestly before believing ~2%/yr:

v3 deepens execution WITHOUT changing v2's correct no-churn design (transition cost at enter/exit
only; a coin held in consecutive months rolls and pays nothing mid-position):

  1. SHORT-PERP FUNDING, intra-month path (8h cadence). Binance USDⓈ-M convention: funding>0 ->
     longs pay shorts. Our carry is SHORT perp, so short RECEIVES funding when funding>0. We accrue
     each 8h event on the *current* perp-leg notional (which drifts as the perp price moves), not a
     flat monthly sum. Verified sign below (SIGN_CHECK).
  2. INTRA-MONTH BASIS / delta-neutral drift, at 8h klines. Delta-neutral is set 1:1 in notional at
     entry; as spot and perp diverge intra-month the legs are no longer equal, so the position is
     only *approximately* neutral. We compute the true two-leg mark-to-market path:
        spot leg (long):  +Q_spot * (S_t - S_entry)
        perp leg (short): -Q_perp * (P_t - P_entry)
     with Q_spot*S_entry = Q_perp*P_entry = 1 unit notional at entry. We report BOTH:
        - NO intra-month rebalance (drift left to run, realistic for a low-churn book)
        - DAILY re-hedge to neutral (resize perp each day; costs perp fills — models churn tradeoff)
  3. REALISTIC PER-LEG FILLS. Spot fill and perp fill are separate instruments with separate
     half-spread + fee. Three scenarios OPTIMISTIC / BASE / CONSERVATIVE (bar requires BASE and
     CONSERVATIVE to hold). Transition costs BOTH legs on enter and on exit.
  4. CAPITAL / MARGIN EFFICIENCY. Delta-neutral ties up capital on BOTH legs: spot fully funded
     (1.0 notional) + perp initial margin (1/leverage) + a margin buffer to avoid liquidation on
     the short as price rises. Yield is expressed on TRUE deployed capital, not single-leg notional.
        deployed = spot_notional(1.0) + perp_margin(1/L) + buffer   [per 1.0 unit of carry notional]
     A "~2%/yr on single-leg" becomes materially smaller on true deployed capital.

Everything is OOS 2025-01..2026-06, public data (data.binance.vision), PAPER research only.
REAL trading = absolute NO-GO.

Usage: python3 funding_carry_v3.py [cache_dir]   (default /tmp/fund_cache)
"""
from __future__ import annotations
import csv
import datetime as _dt
import io
import json
import os
import random
import sys
import urllib.request
import zipfile

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]
# fetch a trailing warmup window before TEST_START so the 3-month funding filter is populated
MONTHS = [f"2024-{m:02d}" for m in range(9, 13)] + \
         [f"2025-{m:02d}" for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 7)]
TEST_START = (2025, 1)
END = (2026, 6)

# --- capital / margin model (per 1.0 unit of carry notional) ---
PERP_LEVERAGE = 3.0          # conservative isolated-margin leverage on the short perp leg
MARGIN_BUFFER = 0.15         # extra collateral held idle to survive adverse perp moves (fraction of notional)

# --- per-leg execution scenarios: (spot_half_spread_bp, spot_fee_bp, perp_half_spread_bp, perp_fee_bp)
#     fee = per-side taker/maker fee applied per leg per side; half_spread paid per leg per side.
#     Round-trip transition cost per leg = 2 * (half_spread + fee)  (enter + exit).
FILL_SCENARIOS = {
    # optimistic: patient maker on both legs, tight majors spread, maker fee ~1bp
    "optimistic": dict(spot_hs=0.5, spot_fee=1.0, perp_hs=0.5, perp_fee=1.8),
    # base: cross the half-spread once, blended maker/taker, realistic majors
    "base":       dict(spot_hs=1.0, spot_fee=5.0, perp_hs=1.5, perp_fee=4.0),
    # conservative: taker both legs, wider effective spread, retail-tier fees
    "conservative": dict(spot_hs=2.5, spot_fee=7.5, perp_hs=3.0, perp_fee=5.0),
}
BREAKEVEN_BPS_PER_8H = 0.20     # trailing funding must beat this to include a coin

FUND_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
SPOT_URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/8h/{s}-8h-{m}.zip"
PERP_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/8h/{s}-8h-{m}.zip"


def _dl(url, fp):
    if not os.path.exists(fp):
        try:
            with urllib.request.urlopen(url, timeout=45) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return False
    return os.path.exists(fp)


def load_funding(cache):
    """symbol -> sorted list of (calc_time_ms, funding_rate). Header row skipped."""
    out = {}
    for s in SYMBOLS:
        rows = []
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-fund-{m}.zip")
            if not _dl(FUND_URL.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():   # skips 'calc_time' header
                            rows.append((int(row[0]), float(row[2])))
            except Exception:
                pass
        rows.sort()
        out[s] = rows
    return out


def load_klines(cache, url_tmpl, tag):
    """symbol -> sorted list of (open_time_ms, close_price). 8h bars. Handles us/ms + header."""
    out = {}
    for s in SYMBOLS:
        rows = {}
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-{tag}-{m}.zip")
            if not _dl(url_tmpl.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():   # skips 'open_time' header
                            ts = int(row[0])
                            if ts > 10**14:      # spot 8h ts are in microseconds
                                ts //= 1000
                            rows[ts] = float(row[4])                 # close
            except Exception:
                pass
        out[s] = sorted(rows.items())
    return out


def ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def nextm(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def prevm(y, m, k):
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


def trailing_avg_funding(fund_sym, lo3, lo):
    xs = [r for t, r in fund_sym if lo3 <= t < lo]
    return (sum(xs) / len(xs)) if xs else None


def _slice(series, lo, hi):
    """list of (ts, val) with lo<=ts<hi, ts ascending."""
    return [(t, v) for t, v in series if lo <= t < hi]


def sign_check(funding, perp):
    """Verify short-perp receives funding when funding>0. Report a concrete month."""
    s = "BTCUSDT"
    lo, hi = ms(2025, 3), ms(2025, 4)
    ev = _slice(funding[s], lo, hi)
    pos = sum(r for _, r in ev if r > 0)
    neg = sum(r for _, r in ev if r < 0)
    net = sum(r for _, r in ev)
    return {
        "symbol": s, "month": "2025-03",
        "n_funding_events": len(ev),
        "sum_positive_rate": round(pos, 6), "sum_negative_rate": round(neg, 6),
        "net_rate": round(net, 6),
        "short_perp_pnl_bps_if_flat_notional": round(net * 1e4, 2),
        "convention": ("Binance USD-M: funding>0 => longs pay shorts. Carry is SHORT perp => "
                       "RECEIVES funding when funding>0. short-leg funding P&L = +rate*perp_notional "
                       "per 8h event."),
    }


def coinmonth_pnl(funding_sym, spot_sym, perp_sym, lo, hi, entry_this_month, exit_this_month,
                  fills, rehedge_daily):
    """
    True two-leg mark-to-market for one coin held over [lo,hi), per 1.0 unit carry notional.
    Returns dict with funding_bps, basis_bps (drift MtM), trans_bps, net_bps, and rehedge_cost_bps.

    Legs at entry (1.0 notional each): Q_spot = 1/S_entry (long), Q_perp = 1/P_entry (short).
      spot MtM  = +Q_spot*(S_t - S_entry)          (long profits when spot rises)
      perp MtM  = -Q_perp*(P_t - P_entry)          (short profits when perp falls)
    Funding accrues each 8h event on current perp notional Q_perp*P_t: +rate*Q_perp*P_t.
    If rehedge_daily: at each 08:00-boundary day start, resize Q_perp back to current-neutral
      (Q_perp = current_spot_leg_notional / P_t), paying a perp round-trip half-spread+fee on the
      resized delta.
    """
    perp_bars = _slice(perp_sym, lo, hi)
    spot_bars = _slice(spot_sym, lo, hi)
    fund_ev = _slice(funding_sym, lo, hi)
    if len(perp_bars) < 2 or len(spot_bars) < 2:
        return None

    # align on common timestamps (8h spot/perp share the same 00/08/16 boundaries)
    spot_map = dict(spot_bars)
    perp_map = dict(perp_bars)
    common = sorted(set(spot_map) & set(perp_map))
    if len(common) < 2:
        return None

    S0, P0 = spot_map[common[0]], perp_map[common[0]]
    Q_spot = 1.0 / S0          # long spot units, 1.0 notional
    Q_perp = 1.0 / P0          # short perp units, 1.0 notional

    funding_pnl = 0.0
    rehedge_cost = 0.0
    perp_hs, perp_fee = fills["perp_hs"], fills["perp_fee"]

    # index funding events by timestamp -> rate
    fund_at = {}
    for t, r in fund_ev:
        fund_at[t] = r

    last_day = None
    for t in common:
        S_t, P_t = spot_map[t], perp_map[t]
        # funding: any funding event at (or effectively at) this 8h boundary accrues on current perp notional
        if t in fund_at:
            funding_pnl += fund_at[t] * (Q_perp * P_t)     # short receives when rate>0

        if rehedge_daily:
            day = _dt.datetime.utcfromtimestamp(t / 1000).date()
            if last_day is not None and day != last_day:
                # target neutral: match current spot-leg notional
                spot_notional_now = Q_spot * S_t
                Q_perp_target = spot_notional_now / P_t
                delta_notional = abs(Q_perp_target - Q_perp) * P_t
                rehedge_cost += delta_notional * ((perp_hs + perp_fee) / 1e4)
                Q_perp = Q_perp_target
            last_day = day

    S_end, P_end = spot_map[common[-1]], perp_map[common[-1]]
    spot_mtm = Q_spot * (S_end - S0)
    perp_mtm = -Q_perp * (P_end - P0)
    basis_mtm = spot_mtm + perp_mtm        # the true delta-neutral price P&L (drift)

    # transition cost: cost BOTH legs, only on enter and/or exit this month
    trans = 0.0
    per_leg_rt = lambda hs, fee: (hs + fee) / 1e4   # one side (enter OR exit) per leg, in fraction
    if entry_this_month:
        trans += per_leg_rt(fills["spot_hs"], fills["spot_fee"])   # spot enter
        trans += per_leg_rt(perp_hs, perp_fee)                     # perp enter
    if exit_this_month:
        trans += per_leg_rt(fills["spot_hs"], fills["spot_fee"])   # spot exit
        trans += per_leg_rt(perp_hs, perp_fee)                     # perp exit

    net = funding_pnl + basis_mtm - trans - rehedge_cost
    return {
        "funding_bps": funding_pnl * 1e4,
        "basis_bps": basis_mtm * 1e4,
        "trans_bps": trans * 1e4,
        "rehedge_bps": rehedge_cost * 1e4,
        "net_bps": net * 1e4,
    }


def run(funding, spot, perp, fills, rehedge_daily):
    """Monthly-rebalanced neutral carry with intra-month path. Returns (monthly_net, coinmonth_tagged)."""
    monthly, cm = [], []
    held_prev = set()
    y, m = TEST_START
    # first, discover the full held-schedule so we know exit months
    schedule = []
    yy, mm = TEST_START
    while (yy, mm) <= END:
        lo, hi = ms(yy, mm), ms(*nextm(yy, mm))
        lo3 = ms(*prevm(yy, mm, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > BREAKEVEN_BPS_PER_8H:
                basket.append(s)
        schedule.append(((yy, mm), set(basket)))
        yy, mm = nextm(yy, mm)

    for i, ((yy, mm), held) in enumerate(schedule):
        lo, hi = ms(yy, mm), ms(*nextm(yy, mm))
        next_held = schedule[i + 1][1] if i + 1 < len(schedule) else set()
        month_pnls = []
        for s in held:
            entry = s not in held_prev
            exit_ = s not in next_held           # leaving after this month (or end of test)
            r = coinmonth_pnl(funding[s], spot[s], perp[s], lo, hi, entry, exit_, fills, rehedge_daily)
            if r is None:
                continue
            month_pnls.append(r["net_bps"])
            cm.append((s, lo, r))
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls))
        held_prev = held
    return monthly, cm


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "mean_bps": round(sum(vals) / n, 1), "total_bps": round(sum(vals), 0),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


def boot_ci(vals, B=4000, seed=7):
    n = len(vals)
    if n < 8:
        return None
    rng = random.Random(seed)
    m_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(m_[int(0.05 * B)], 1), round(m_[int(0.95 * B)], 1)


def market_proxy(perp):
    """equal-weight perp monthly return per (y,m), for up/down neutrality split."""
    mkt = {}
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = []
        for s in SYMBOLS:
            bars = _slice(perp[s], lo, hi)
            if len(bars) >= 2:
                rs.append(bars[-1][1] / bars[0][1] - 1)
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)
    return mkt


def deployed_capital_per_notional():
    """True deployed capital per 1.0 unit of carry notional (both legs)."""
    return 1.0 + (1.0 / PERP_LEVERAGE) + MARGIN_BUFFER


def analyze(monthly, cm, mkt):
    def mkey(t):
        d = _dt.datetime.utcfromtimestamp(t / 1000)
        return (d.year, d.month)
    up = sum(r["net_bps"] for _, t, r in cm if mkt.get(mkey(t), 0) >= 0)
    dn = sum(r["net_bps"] for _, t, r in cm if mkt.get(mkey(t), 0) < 0)
    prof, by_year, comp = {}, {}, {"funding": 0.0, "basis": 0.0, "trans": 0.0, "rehedge": 0.0}
    for s, t, r in cm:
        if r["net_bps"] > 0:
            prof[s] = prof.get(s, 0) + r["net_bps"]
        yy = _dt.datetime.utcfromtimestamp(t / 1000).year
        by_year[yy] = round(by_year.get(yy, 0) + r["net_bps"], 0)
        comp["funding"] += r["funding_bps"]; comp["basis"] += r["basis_bps"]
        comp["trans"] += r["trans_bps"]; comp["rehedge"] += r["rehedge_bps"]
    tot = sum(prof.values())
    yrs = (END[0] - TEST_START[0]) + (END[1] - TEST_START[1]) / 12.0
    mean_month_bps = (sum(monthly) / len(monthly)) if monthly else 0.0
    # yield on single-leg notional vs true deployed capital
    ann_singleleg_pct = round(mean_month_bps * 12 / 100.0, 3)
    dep = deployed_capital_per_notional()
    ann_deployed_pct = round((mean_month_bps * 12 / 100.0) / dep, 3)
    return {
        "monthly_basket": stats(monthly),
        "monthly_boot_ci_5_95_bps": boot_ci(monthly),
        "annual_yield_singleleg_pct": ann_singleleg_pct,
        "true_deployed_capital_per_notional": round(dep, 3),
        "annual_yield_on_true_deployed_capital_pct": ann_deployed_pct,
        "coinmonth_net_up_market_bps": round(up, 0),
        "coinmonth_net_down_market_bps": round(dn, 0),
        "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
        "net_bps_by_year": by_year,
        "pnl_decomposition_bps": {k: round(v, 0) for k, v in comp.items()},
    }


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    os.makedirs(cache, exist_ok=True)
    funding = load_funding(cache)
    spot = load_klines(cache, SPOT_URL, "spot8h")
    perp = load_klines(cache, PERP_URL, "perp8h")
    mkt = market_proxy(perp)

    out = {
        "note": ("Funding-carry v3: HONEST EXECUTION model. Intra-month 8h funding path on drifting "
                 "perp notional + true two-leg delta-neutral MtM (drift) + per-leg fills (spot & perp "
                 "separately) + both-leg transition cost + capital/margin efficiency. No mid-position "
                 "churn (v2 design preserved). OOS 2025-01..2026-06. PAPER only; REAL=NO-GO."),
        "sign_check": sign_check(funding, perp),
        "capital_model": {
            "perp_leverage": PERP_LEVERAGE, "margin_buffer_frac": MARGIN_BUFFER,
            "deployed_per_1.0_notional": round(deployed_capital_per_notional(), 3),
            "explanation": ("spot leg fully funded (1.0) + perp initial margin (1/L) + idle buffer "
                            "to survive adverse short moves. Yield on this, not single-leg."),
        },
        "data_coverage": {s: {"funding_ev": len(funding[s]), "spot_8h_bars": len(spot[s]),
                              "perp_8h_bars": len(perp[s])} for s in SYMBOLS},
    }

    for hedge_label, rehedge in (("no_rehedge", False), ("daily_rehedge", True)):
        out[hedge_label] = {}
        for scen, fills in FILL_SCENARIOS.items():
            monthly, cm = run(funding, spot, perp, fills, rehedge)
            out[hedge_label][scen] = analyze(monthly, cm, mkt)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
```

---

## 8. Zdrojový kód: funding_carry_robustness.py

```python
#!/usr/bin/env python3
"""Funding-carry robustness — the SKEPTIC BATTERY applied to the first surviving lead.

Prior leads (donchian/xsec momentum) passed a naive walk-forward, then a skeptic battery
refuted them: bootstrap CI spanned zero, profit concentrated in one year (2024 beta), wins only
in up-markets (`RESEARCH_LONGHORIZON_FINDINGS.md`). Funding-carry v2 (`funding_carry_v2.py`)
reportedly PASSES that battery. This script tries HARD to break it with the SAME rigor plus the
extra requirements that funding-carry specifically invites:

  1. PURGED NESTED WALK-FORWARD. The v2 basket filter (trailing-3mo funding > 0.20 bp/8h) is
     causal, but the OOS window is a single fixed 2025-01 split. We (a) verify no look-ahead in
     the filter, (b) sweep the split date across every month 2024-06..2025-06 and require the edge
     to survive out-of-sample regardless of where we cut, and (c) add a >=1-month embargo (the
     holding horizon) so the trailing window that selects month M never overlaps the tested month.

  2. BLOCK / CLUSTER BOOTSTRAP by funding regime episode. Monthly carry returns inside one funding
     regime are autocorrelated; iid bootstrap (what v2 uses) overstates significance. We report the
     CI under a circular block bootstrap and the EFFECTIVE sample size (Neff = N * (1-rho)/(1+rho)
     from lag-1 autocorrelation). 15 monthly points is already thin; correlated => even fewer.

  3. EXTENDED HISTORY. Attempt to pull funding + spot/perp back to 2020 where Binance has it, to add
     pre-2023 regimes (2021 bull, 2022 bear/LUNA/FTX). Report what actually downloaded.

  4. NEGATIVE-FUNDING REGIME STRESS. Quantify, per month, "rich funding" (basket non-empty) vs
     "empty basket" (filter emptied it -> strategy flat, no loss). Locate/construct the lowest-funding
     slice and confirm the filter empties the basket rather than forcing bad carry. Report the % of
     the sample that is rich vs empty.

  5. GO-THRESHOLD SCORECARD (charter RESEARCH_PIVOT_CHARTER.md):
     OOS PF>=1.20; expectancy>0 with >=+2-3bp reserve after realistic cost; cluster-bootstrap 95% CI
     lower>0; >=200 OOS fills; stable in >=2 regimes; no symbol>50% of profit. The 15-coin-month unit
     is FAR below 200 fills -> flagged explicitly, with a discussion of whether a finer unit is legit.

Reuses funding_carry_v2's loaders/model verbatim (same numbers), then subjects them to the battery.
REAL trading = absolute NO-GO. Offline paper research on public data only. Every number is OOS.

Usage: python3 funding_carry_robustness.py [cache_dir]
"""
from __future__ import annotations
import datetime as _dt
import json
import math
import random
import sys

# Reuse v2's model verbatim so numbers match the reported lead exactly.
from funding_carry_v2 import (
    SYMBOLS, BREAKEVEN_BPS_PER_8H, COST_RT_BPS,
    load_funding, load_daily, SPOT_URL, PERP_URL,
    ms, nextm, prevm, month_ret, month_funding, trailing_avg_funding,
)

# Extended-history months to ATTEMPT (Binance USDM funding starts ~2019-09 for BTC; varies by symbol).
EXT_MONTHS = [f"{y}-{m:02d}" for y in (2020, 2021, 2022) for m in range(1, 13)]


# ----------------------------------------------------------------------------------------------
# Core carry model, parameterised by TEST window so we can sweep the split (check 1).
# Faithful to funding_carry_v2.run(), but ALSO returns per-month basket occupancy + exit-cost
# handling made explicit (v2's exit-cost loop body was a dead `pass`; we charge it correctly here).
# ----------------------------------------------------------------------------------------------
def carry_run(funding, spot, perp, cost, test_start, end, breakeven=BREAKEVEN_BPS_PER_8H):
    """Monthly-rebalanced delta-neutral carry over [test_start, end].
    Returns dict with monthly_net list, tagged coin-months, and per-month basket occupancy."""
    monthly, cm, occupancy = [], [], []
    held_prev = set()
    y, m = test_start
    while (y, m) <= end:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        lo3 = ms(*prevm(y, m, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > breakeven:
                basket.append(s)
        held = set(basket)
        month_pnls = []
        for s in basket:
            f_bps = month_funding(funding[s], lo, hi) * 1e4
            sr, pr = month_ret(spot[s], lo, hi), month_ret(perp[s], lo, hi)
            basis_bps = ((sr - pr) * 1e4) if (sr is not None and pr is not None) else 0.0
            trans = 0.0
            if s not in held_prev:
                trans += cost / 2.0
            net = f_bps + basis_bps - trans
            month_pnls.append(net)
            cm.append((s, lo, net))
        exit_cost = len(held_prev - held) * (cost / 2.0)
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls) - exit_cost / max(1, len(month_pnls)))
            occupancy.append((y, m, len(basket), True))
        else:
            # empty basket -> strategy flat this month (no loss). Record 0 for a continuous series.
            occupancy.append((y, m, 0, False))
        held_prev = held
        y, m = nextm(y, m)
    return {"monthly": monthly, "cm": cm, "occupancy": occupancy}


def basic_stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "mean_bps": round(sum(vals) / n, 2), "total_bps": round(sum(vals), 1),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


# ----------------------------------------------------------------------------------------------
# Check 2: block bootstrap + effective sample size
# ----------------------------------------------------------------------------------------------
def lag1_autocorr(x):
    n = len(x)
    if n < 3:
        return 0.0
    mu = sum(x) / n
    denom = sum((v - mu) ** 2 for v in x)
    if denom == 0:
        return 0.0
    num = sum((x[i] - mu) * (x[i - 1] - mu) for i in range(1, n))
    return num / denom


def effective_n(x):
    rho = lag1_autocorr(x)
    n = len(x)
    if rho <= -0.999:
        return n
    neff = n * (1.0 - rho) / (1.0 + rho)
    return max(1.0, min(float(n), neff))


def iid_boot_ci(vals, B=5000, seed=7, lo=0.025, hi=0.975):
    n = len(vals)
    if n < 6:
        return None
    rng = random.Random(seed)
    ms_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(ms_[int(lo * B)], 2), round(ms_[int(hi * B)], 2)


def block_boot_ci(vals, block, B=5000, seed=7, lo=0.025, hi=0.975):
    """Circular block bootstrap: resample contiguous blocks of length `block` to preserve
    within-regime autocorrelation. Wraps around (circular) so every index is eligible."""
    n = len(vals)
    if n < 6:
        return None
    rng = random.Random(seed)
    nblocks = math.ceil(n / block)
    means = []
    for _ in range(B):
        sample = []
        for _ in range(nblocks):
            start = rng.randrange(n)
            for k in range(block):
                sample.append(vals[(start + k) % n])
        sample = sample[:n]
        means.append(sum(sample) / n)
    means.sort()
    return round(means[int(lo * B)], 2), round(means[int(hi * B)], 2)


# ----------------------------------------------------------------------------------------------
# Check 1: split-date sweep (purged nested walk-forward robustness)
# ----------------------------------------------------------------------------------------------
def split_sweep(funding, spot, perp, cost, end):
    """Re-run the carry with TEST_START swept across many months. If the +edge only exists for
    the fixed 2025-01 cut, this exposes it. Embargo is inherent: the trailing-3mo selection window
    for month M ends at M's start (< M), so it never sees month M's realised carry (no look-ahead)."""
    results = {}
    for (yy, mm) in [(2024, 6), (2024, 9), (2024, 12), (2025, 1), (2025, 3), (2025, 6)]:
        if (yy, mm) > end:
            continue
        r = carry_run(funding, spot, perp, cost, (yy, mm), end)
        st = basic_stats(r["monthly"])
        results[f"split_{yy}-{mm:02d}"] = {
            "n_months": st.get("n", 0), "mean_bps": st.get("mean_bps"),
            "win_rate": st.get("win_rate"), "pf": st.get("pf"),
        }
    return results


# ----------------------------------------------------------------------------------------------
# Check 3: extended history load (best-effort)
# ----------------------------------------------------------------------------------------------
def load_extended(cache):
    """Load funding/spot/perp for 2020-2022 by monkeypatching MONTHS in the v2 loaders' scope.
    Returns (funding, spot, perp, coverage) where coverage reports what actually downloaded."""
    import funding_carry_v2 as v2
    orig = v2.MONTHS
    v2.MONTHS = EXT_MONTHS
    try:
        f = v2.load_funding(cache)
        s = v2.load_daily(cache, SPOT_URL, "spotd")
        p = v2.load_daily(cache, PERP_URL, "perpd")
    finally:
        v2.MONTHS = orig
    coverage = {}
    for sym in SYMBOLS:
        fpts = len(f.get(sym, []))
        earliest = None
        if f.get(sym):
            earliest = _dt.datetime.utcfromtimestamp(min(t for t, _ in f[sym]) / 1000).strftime("%Y-%m")
        coverage[sym] = {"funding_points": fpts, "earliest_funding": earliest,
                         "spot_days": len(s.get(sym, {})), "perp_days": len(p.get(sym, {}))}
    return f, s, p, coverage


def carry_run_extended(funding, spot, perp, cost, start, end):
    """Same model but no dependence on TEST_START constant; used for the extended regime."""
    return carry_run(funding, spot, perp, cost, start, end)


# ----------------------------------------------------------------------------------------------
# Check 4: negative-funding regime stress + rich-vs-empty occupancy
# ----------------------------------------------------------------------------------------------
def occupancy_report(occ):
    total = len(occ)
    rich = sum(1 for *_, active in occ if active)
    empty = total - rich
    sizes = [sz for *_h, sz, active in occ if active]
    return {
        "months_total": total,
        "months_rich_basket": rich,
        "months_empty_basket_flat": empty,
        "pct_rich": round(rich / total, 3) if total else None,
        "avg_basket_size_when_rich": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "min_basket_size": min(sizes) if sizes else 0,
        "max_basket_size": max(sizes) if sizes else 0,
    }


# ----------------------------------------------------------------------------------------------
# Assemble battery
# ----------------------------------------------------------------------------------------------
def analyze_scenario(funding, spot, perp, cost, test_start, end, market):
    r = carry_run(funding, spot, perp, cost, test_start, end)
    monthly, cm = r["monthly"], r["cm"]
    st = basic_stats(monthly)

    # up/down market neutrality (from perp equal-weight monthly return sign) on coin-months
    def mkey(t):
        d = _dt.datetime.utcfromtimestamp(t / 1000)
        return (d.year, d.month)
    up = sum(v for _, t, v in cm if market.get(mkey(t), 0) >= 0)
    dn = sum(v for _, t, v in cm if market.get(mkey(t), 0) < 0)
    n_up = sum(1 for _, t, v in cm if market.get(mkey(t), 0) >= 0)
    n_dn = sum(1 for _, t, v in cm if market.get(mkey(t), 0) < 0)

    # symbol concentration (gross profit share) and per-year
    prof, by_year = {}, {}
    for s, t, v in cm:
        if v > 0:
            prof[s] = prof.get(s, 0) + v
        yy = _dt.datetime.utcfromtimestamp(t / 1000).year
        by_year[yy] = round(by_year.get(yy, 0) + v, 1)
    tot = sum(prof.values())

    rho = lag1_autocorr(monthly)
    neff = effective_n(monthly)
    # block length ~ ceil(sqrt(N)) is a standard rule of thumb; also try a regime-scale block of 3.
    blk = max(2, round(math.sqrt(len(monthly)))) if monthly else 2

    return {
        "monthly_basket_stats": st,
        "n_coin_month_fills": len(cm),
        "iid_boot_ci95_bps": iid_boot_ci(monthly),
        "block_boot_ci95_bps_blk_sqrtN": block_boot_ci(monthly, blk),
        "block_boot_ci95_bps_blk3": block_boot_ci(monthly, 3),
        "lag1_autocorr_monthly": round(rho, 3),
        "effective_n_months": round(neff, 2),
        "raw_n_months": len(monthly),
        "coinmonth_net_up_market_bps": round(up, 1),
        "coinmonth_net_down_market_bps": round(dn, 1),
        "n_coinmonths_up": n_up, "n_coinmonths_down": n_dn,
        "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
        "top_symbol": max(prof, key=prof.get) if prof else None,
        "net_bps_by_year": by_year,
        "occupancy": occupancy_report(r["occupancy"]),
    }


def market_monthly(perp, start, end):
    mkt = {}
    y, m = start
    while (y, m) <= end:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = [month_ret(perp[s], lo, hi) for s in SYMBOLS]
        rs = [x for x in rs if x is not None]
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)
    return mkt


def go_scorecard(base):
    """Map the base-cost scenario onto the charter GO thresholds -> PASS/FAIL each."""
    st = base["monthly_basket_stats"]
    ci = base["block_boot_ci95_bps_blk3"] or base["iid_boot_ci95_bps"]
    pf = st.get("pf")
    mean = st.get("mean_bps")
    checks = []
    checks.append(("OOS PF >= 1.20", pf, isinstance(pf, (int, float)) and pf >= 1.20))
    checks.append(("expectancy > 0 with >= +2-3bp reserve after cost",
                   f"{mean} bp/coin-month" if mean is not None else None,
                   mean is not None and mean >= 2.0))
    checks.append(("cluster-bootstrap 95% CI lower > 0",
                   ci, ci is not None and ci[0] > 0))
    checks.append((">= 200 OOS fills",
                   base["n_coin_month_fills"], base["n_coin_month_fills"] >= 200))
    yrs = base["net_bps_by_year"]
    pos_years = sum(1 for v in yrs.values() if v > 0)
    checks.append(("stable in >= 2 regimes (>=2 positive years)",
                   yrs, pos_years >= 2))
    up, dn = base["coinmonth_net_up_market_bps"], base["coinmonth_net_down_market_bps"]
    checks.append(("market-neutral (positive in up AND down markets)",
                   {"up": up, "down": dn}, up > 0 and dn > 0))
    mss = base["max_symbol_profit_share"]
    checks.append(("no symbol > 50% of profit",
                   mss, mss is not None and mss <= 0.50))
    passed = sum(1 for *_x, ok in checks if ok)
    return {
        "checks": [{"threshold": t, "value": v, "PASS": ok} for t, v, ok in checks],
        "passed": passed, "total": len(checks),
    }


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    end = (2026, 6)

    funding = load_funding(cache)
    spot = load_daily(cache, SPOT_URL, "spotd")
    perp = load_daily(cache, PERP_URL, "perpd")
    market = market_monthly(perp, (2025, 1), end)

    out = {"note": ("Skeptic battery on funding-carry v2 — the SAME rigor that refuted "
                    "donchian/xsec momentum, plus purged-WF split sweep, block bootstrap w/ "
                    "effective-N, extended history, and negative-funding stress. REAL=NO-GO; "
                    "all OOS on public data.")}

    # --- main OOS scenarios (base 30 / stress 40) ---
    out["scenarios"] = {}
    for scen, cost in COST_RT_BPS.items():
        out["scenarios"][scen] = analyze_scenario(funding, spot, perp, cost, (2025, 1), end, market)

    # --- Check 1: split-date sweep (base cost) ---
    out["check1_split_sweep_base"] = split_sweep(funding, spot, perp, COST_RT_BPS["base"], end)

    # --- Check 3: extended history ---
    try:
        ef, es, ep, cov = load_extended(cache)
        out["check3_extended_coverage"] = cov
        # find earliest month with >=1 symbol having funding+prices, run carry from there to 2022-12
        earliest_year = min((int(v["earliest_funding"][:4]) for v in cov.values()
                             if v["earliest_funding"]), default=None)
        if earliest_year is not None:
            # merge extended + main funding/prices so trailing window has continuity
            mf = {s: sorted(set(ef.get(s, []) + funding.get(s, []))) for s in SYMBOLS}
            msp = {s: {**es.get(s, {}), **spot.get(s, {})} for s in SYMBOLS}
            mpp = {s: {**ep.get(s, {}), **perp.get(s, {})} for s in SYMBOLS}
            ext_start = (2021, 1)   # allow 2020 as trailing warmup
            ext_end = (2022, 12)
            emkt = market_monthly(mpp, ext_start, ext_end)
            out["check3_extended_carry_2021_2022"] = analyze_scenario(
                mf, msp, mpp, COST_RT_BPS["base"], ext_start, ext_end, emkt)
        else:
            out["check3_extended_carry_2021_2022"] = "no extended funding data downloaded"
    except Exception as e:
        out["check3_extended_error"] = repr(e)

    # --- Check 4: negative-funding / occupancy already inside each scenario; surface a summary ---
    base = out["scenarios"]["base"]
    out["check4_negative_funding_stress"] = {
        "occupancy_base": base["occupancy"],
        "interpretation": ("empty-basket months => strategy flat (0), never forced into bad carry. "
                           "pct_rich = fraction of sample that actually earned carry."),
    }

    # --- Check 2 surfaced: effective N + block vs iid CI (base) ---
    out["check2_block_bootstrap_base"] = {
        "raw_n_months": base["raw_n_months"],
        "lag1_autocorr": base["lag1_autocorr_monthly"],
        "effective_n_months": base["effective_n_months"],
        "iid_boot_ci95": base["iid_boot_ci95_bps"],
        "block_boot_ci95_blk3": base["block_boot_ci95_bps_blk3"],
        "block_boot_ci95_blk_sqrtN": base["block_boot_ci95_bps_blk_sqrtN"],
    }

    # --- GO scorecard (base cost) ---
    out["GO_scorecard_base"] = go_scorecard(base)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
```

---

*Konec balíčku. Všech 8 sekcí odpovídá přesně tomu, co `EXTERNAL_AUDIT_PROMPT_v9.md` cituje
jménem ("Cite our artifacts by name"). REAL trading = absolutní NO-GO nezávisle na čemkoli výše.*
