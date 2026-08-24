# CryptoMaster HF-Quant 5.0 — Externí audit, kolo 9

**Předmět:** rozsah + interpretace cíle pro delta-neutral funding-carry (perp short leg)
**Auditovaný stav:** `EXTERNAL_AUDIT_PROMPT_v9.md`, `RESEARCH_FUNDING_CARRY_FINDINGS.md`,
`scripts/research/funding_carry_v3.py`, `scripts/research/funding_carry_robustness.py`
(commit `cef00a0`)
**Datum:** 24. 8. 2026
**Režim:** PAPER only
**REAL trading:** **ABSOLUTNÍ NO-GO** (nezávisle na výsledku tohoto verdiktu)

---

# 0. Konečný verdikt

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

---

# 1. Co jsem ověřoval nezávisle (ne jen převzal ze shrnutí)

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

---

# 2. Q1 — Je delta-neutral perp-carry PAPER track v rozsahu?

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

---

# 3. Q2 — Je ~2 %/rok (headline) / ~0,7–1,3 %/rok (v3, skutečný kapitál) přijatelné čtení cíle?

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

---

# 4. Q3 — Čistí evidence bar, nebo je to thin-sample comfort v market-neutral přestrojení?

**Odpověď: thin-sample comfort, s poctivým sebeodhalením — přesně to, co battery měl odhalit.**

Rozdíl oproti donchian/xsec (RESEARCH_LONGHORIZON_FINDINGS.md) je reálný a stojí za
zaznamenání: bootstrap CI **nepřekračuje nulu** ani v konzervativním scénáři (`[+0,5;
+16,7]bp`), zatímco donchian/xsec měly CI `[−26,+196]` / `[−37,+196]` — kategoricky odlišný
výsledek. Toto NENÍ stejné selhání jako u price-only rodin a nemělo by se tak zjednodušeně
prezentovat.

Ale "CI nepřesahuje nulu" a "clears the evidence bar" nejsou totéž, když **efektivní N je
≈7,8** — s tak malým N je i CI-positive výsledek přesně ten typ artefaktu, který charta bod 4
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

---

# 5. Provozní rozhodnutí

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

---

# 6. Omezení tohoto auditu

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
