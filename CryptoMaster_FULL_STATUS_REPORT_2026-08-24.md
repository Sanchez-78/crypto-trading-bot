# CryptoMaster HF-Quant 5.0 — Plný stavový report pro externí audit

**Datum:** 24. 8. 2026, ~08:00 UTC
**Režim:** PAPER only (`TRADING_MODE=paper_train`/`paper_live`)
**REAL trading:** **ABSOLUTNÍ NO-GO** — vynuceno na úrovni importu modulu
(`_enforce_paper_safe_mode()`, `paper_trade_executor.py:44-82`), ne jen konfigurací
**Cíl projektu:** Win Rate > 50 % **A** pozitivní paper P&L, poctivě (žádné metric-gaming)
**Live commit na serveru:** `25c231d` (Hetzner VPS, `root@78.47.2.198`, systemd `cryptomaster.service`)

---

## 0. Shrnutí — je cíl splněn?

**NE.** Aktuální recent-100 metriky (viz Sekce 2) ukazují WR 30 %, PF 0,587, čistý P&L
záporný. Lifetime metriky (9788 obchodů) ukazují PF 0,66, expectancy záporná. Bot je
funkční, stabilní a aktivně obchoduje, ale **ekonomicky ještě neprokazuje edge**. Tento
report je čestný snímek stavu, ne prezentace úspěchu — v souladu s projektovým pravidlem
"no metric-gaming" dodržovaným napříč celým výzkumným obloukem.

Nejnovější dvě opravy (viz Sekce 3) odstranily dva samostatné, živě potvrzené bugy
(admission deadlock a duplicitní obchody), ale ani jedna z nich sama o sobě neřeší
základní ekonomickou otázku — obě jsou hygienické/integritní opravy, ne edge-generující
změny.

---

## 1. Architektura (stručně)

```
market_stream.py (WebSocket) → event_bus.py → signal_generator.py / signal_engine.py
    → realtime_decision_engine.py (Bayesovská kalibrace + EV gating)
    → paper_trade_executor.py (lifecycle pozic, ~4700 řádků, jediná funkce otevírající
      pozice: open_paper_position())
    → risk_engine.py (jen pro REAL cestu, nedosažitelná v paper režimu)
Stav: Firestore (obchody/metriky) + Redis (hydratace) + lokální cache.sqlite
Dashboard: Flask služba (`cryptomaster-dashboard.service`), čte learning JSON + cache.sqlite
```

Klíčové admission cesty do `open_paper_position()`:
- **RDE_TAKE** — hlavní EV-gated cesta (`realtime_decision_engine.py`), vždy nese
  `training_bucket == explore_bucket` (stejná hodnota).
- **P0.3C reroute** (`trade_executor.py:2982`) — RDE-odmítnuté signály přesměrované do
  evidence-collection, nese `training_bucket` (typicky `A_STRICT_TAKE`).
- **P0.8+ pipeline** (`p0_8_plus_live_pipeline.py`) — nová evidence-only strategie,
  nastavuje oba bucket fieldy.
- **PAPER_STARVATION_DISCOVERY** (`paper_training_sampler.py`) — bootstrapovací
  exploration, vlastní dedupe mechanika (`_recent_dedupe`).
- **P0_GATE** (`_on_signal_created()`, `paper_trade_executor.py:4611`) — legacy cesta bez
  bucket atribuce, spouštěná na každý `signal_created` event.

---

## 2. Aktuální živé metriky (SSH-verifikováno, 24.8.2026 ~07:57 UTC)

| Metrika | Hodnota | Poznámka |
|---|---|---|
| **Recent-100 Win Rate** | **30,0 %** | cíl je >50 % — nesplněno |
| **Recent-100 Profit Factor** | **0,587** (pct-basis) / 0,614 (usd-basis) | <1 = ztrátový |
| **Recent-100 čisté P&L** | **−5,40 %** / −1,06 USD | záporné |
| **Recent-100 rozpad** | 30 výher / 46 proher / 24 flat (n=100) | |
| **Lifetime PF** (9788 obchodů) | **0,662** | skutečný kumulativní součet (opraveno 2026-08-14, dřív to byla mylně "rolling100" hodnota) |
| **Lifetime expectancy** | **−0,0259** | záporná |
| **Exit distribuce (lifetime)** | TIMEOUT 6272, SL 1333, TP 957, scratch 0 | TIMEOUT dominuje (64 %) |
| **Otevřené pozice** | 9 | aktivně obchoduje |
| **Uzavřeno dnes** | 100 | |
| **Firebase kvóta** | 605/50 000 reads (1,2 %), 29/20 000 writes (0,15 %) | zdravé, reset denně 07:00 UTC |
| **Service uptime** | od 07:35:49 UTC (0 restartů) | žádné CRITICAL/ERROR mimo přechodný WebSocket ping/pong timeout (běžné, self-healing) |
| **Doporučení dashboardu** | ČEKAT (`recommendation: "ČEKAT"`) | systém sám signalizuje "nezasahovat/čekat" |

**Poznámka k TIMEOUT dominanci:** 64 % všech uzavřených obchodů za celou dobu skončilo
TIMEOUT (ne TP ani SL) — to je dlouhodobě zdokumentovaný, nevyřešený vzorec (viz Sekce 4).

---

## 3. Opravy provedené v tomto sezení (chronologicky, s live-verifikací)

Všechny opravy prošly stejnou disciplínou: forenzní evidence → paralelní review
(`reviewer-agent` adversariálně, `trading-safety-agent` PASS/FAIL) → mutation-killed
regresní testy → gated deploy (`hetzner-deploy-apply.yml`, PLAN pak DEPLOY) → live
verifikace.

### 3.1 Admission deadlock (commit `fc1f73d`)
**Nález:** `_route_training_sample_through_p0_rde()` měl natvrdo zakódovanou podmínku
(`symbol in {"ETHUSDT"} and regime in {"BULL_TREND","BEAR_TREND"}`) místo volání skutečné
`P0SegmentEVGate.is_eligible_for_evidence_collection()` logiky — ~17,5 hodiny reálného
admission deadlocku (jen ETHUSDT admitován, ostatní symboly trvale blokované).
**Live dopad:** `closed_today` 0→55 během 15 minut po deployi.

### 3.2 Duplicitní obchody — bucketed cesta (commit `b921d54`, P1.1AV)
**Nález:** `_check_exploration_exposure_caps()` počítal otevřené pozice podle
`explore_bucket` samotného, ale kandidáti přes P0.3C reroute nesou `training_bucket`
s `explore_bucket=None` → limity byly strukturální no-op. Živě potvrzeno: 13 téměř
identických SOLUSDT pozic během 1,86 s.
**Oprava:** `_position_effective_bucket()` = `training_bucket or explore_bucket`.
**Live dopad:** limity teď reálně blokují (`max_open_per_symbol`/`max_open_per_bucket`
firing continuously na `A_STRICT_TAKE` kandidáty).

### 3.3 Duplicitní obchody — unbucketed cesta (commit `5b22812`/`3a294cd`, P1.1AW)
**Nález:** `_on_signal_created()`'s P0_GATE větev (bez bucket atribuce) obchází veškerou
exposure-cap ochranu zcela podle původního návrhu; `signal_generator.py` publikuje signál
na každý tick bez debounce → sub-sekundové bursty duplicitních pozic. Živě potvrzeno: až
4 téměř identické ETHUSDT pozice do 0,9 s.
**Oprava:** 5s cooldown per (symbol, side), scoped na `reason=="P0_GATE"`.
**Live dopad:** duplicita 0,27 s po sobě jdoucí byla zablokována; **známé omezení** —
5s okno nezachytí odstupy ~8s (potvrzeno i v tomto reportu, Sekce 2 dotaz: 1 shluk
v posledních 25 min, odstup 8s) — to je záměrné chování, ne regrese, sledováno pro
případné rozšíření okna.

### 3.4 Vedlejší nález (stejný cyklus): log observability bug
`_on_signal_created()` logoval nepodmíněné `[SIGNAL_OPENED] ... SUCCESS` i při
zablokovaném vstupu. Post-deploy odhaleno: starý log lhal v **~99,8 %** případů (1231×
"SUCCESS" logováno oproti jen 3 skutečně otevřeným pozicím za 2h okno). Opraveno —
teď loguje pravdivý `[SIGNAL_BLOCKED] status=... reason=...`.

### 3.5 Zamítnutá oprava (cyklus 108) — pro transparentnost
Pokus opravit `PAPER_STARVATION_DISCOVERY`'s 900s idle-safety-valve
(`_update_starvation_discovery_idle()`) byl **zamítnut vlastním review procesem** předtím,
než se dostal do commitu — nalezen hlubší dead-code bug (funkce nikdy nevolána, sedí za
nepodmíněným `return` z jiné, 3 měsíce starší změny). Oprava by paradoxně natrvalo
vypnula ochranu proti opakovanému admitování do už-prokázaně-špatných segmentů. Zdokumentováno,
nevrácen žádný kód do repozitáře. Zůstává otevřený, nevyřešený nález pro budoucí cyklus.

---

## 4. Známé otevřené problémy (neopravené, transparentně přiznané)

1. **Dead-code v idle-tracking** (`paper_training_sampler.py`) — viz 3.5. `last_eligible_
   entry_ts` je fakticky natrvalo zamrzlé na čas startu procesu; safety-valve proti
   opakovanému admission stallu nikdy nemůže vystřelit. Nebyl důvod k urgentní opravě
   (aktuální stall protection funguje správně z jiného mechanismu), ale je to reálná mezera.
2. **TIMEOUT dominance (64 % všech exitů)** — bot většinou čeká na časový limit místo TP/SL
   zásahu, což naznačuje, že TP/SL geometrie nebo hold-time nejsou dobře sladěné s
   realizovanými pohyby ceny. Historicky vyšetřováno (cost-floor invariant), ale ne
   plně vyřešeno vzhledem k aktuálnímu WR.
3. **Dashboard freeze recurrence** — dashboard služba (samostatná od `cryptomaster.service`)
   opakovaně zamrzá na hodiny (naposledy ~48 min před dnešním deployem), zdokumentovaný,
   nevyřešený gap, mitigovaný jen best-effort restartem při každém deploy.
4. **`_SYMBOL_CAPS` bez rozumného defaultu** — chybějící symbol spadá na 999, což je
   fakticky "bez limitu". Vedlejší nález z cyklu 109, vědomě neopravováno mimo rozsah.
5. **`buy_enforcement`/`sell_enforcement`** (V10.16 diverzifikační mechanismus) — potvrzeno
   jako funguje-podle-návrhu, ale možný budoucí limitér throughputu, nevyšetřeno do hloubky.

---

## 5. Bezpečnostní záruky (opakovaně nezávisle ověřeno tento sezení)

- **REAL trading:** vynuceno na úrovni importu modulu (`_enforce_paper_safe_mode()`),
  ne jen env proměnnou — nemůže být obejito jednotlivým callerem.
- Každá tento-sezení oprava byla `trading-safety-agent`em nezávisle ověřena jako
  **paper-only scope**, **fail-closed při výjimce**, a **žádné oslabení existující
  reálné-obchodování brány**.
- Firebase kvóta zdravá (viz Sekce 2), reset denně 07:00 UTC, quota-guard mechanismus
  funkční.

---

## 6. Souběžné výzkumné vlákno — funding-carry (uzavřeno tento sezení)

Nezávisle na live-bot cyklech proběhlo kolo 9 externího auditu delta-neutral funding-carry
strategie (`CryptoMaster_EXTERNAL_AUDIT_REPORT_v9.md`, commit `25c231d`). **Verdikt: NO-GO**
na stavbu nové perp-leg infrastruktury — tým vlastními daty tvrdě selhal na vlastním
předem schváleném prahu (≥200 fillů, efektivní N≈7,8) a definiční vlastnost leadu
(market-neutralita) se zhroutila pod poctivějším execution modelem. Hypotéza není
prohlášena za mrtvou, observation-only sběr dat může pokračovat zdarma. Toto NEOVLIVŇUJE
live paper-trading bota — je to samostatné, uzavřené výzkumné vlákno.

---

## 7. Otevřené otázky pro externího auditora

1. Je TIMEOUT-dominance (64 % exitů) sama o sobě dostatečný signál k dalšímu vyšetřování
   TP/SL geometrie, nebo je nutné počkat na větší vzorek po dnešních opravách?
2. S recent-100 WR 30 % a lifetime PF 0,66 — je aktuální admission logika (P0.3B/P0.3C
   segment-gating) stále tou správnou strategií, nebo je čas na fundamentálnější
   přehodnocení EV-gatingu samotného?
3. Dead-code nález v idle-tracking (Sekce 4.1) — souhlasí auditor s rozhodnutím neopravovat
   ho urgentně, vzhledem k tomu, že aktuální ochrana funguje jiným mechanismem?

**REAL trading zůstává absolutní NO-GO nezávisle na jakémkoli závěru tohoto reportu.**
