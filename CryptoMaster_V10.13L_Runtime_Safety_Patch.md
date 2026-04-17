# CryptoMaster — V10.13L Safety Patch Proposal
_Date: 2026-04-17_

## Cíl

Navrhnout **další bezpečnostní patch** po V10.13k, který řeší hlavní aktuální riziko:

- proces běží, ale trading pipeline je interně rozbitá,
- watchdog/self-heal dál snižuje prahy a zapíná exploraci,
- vzniká falešný dojem, že bot je „živý“, i když je live path nefunkční,
- dashboard pak míchá **strategický stall** a **runtime failure**.

Tento patch je zaměřený na **bezpečné chování při chybě**, ne na agresivnější obchodování.

---

# Kontext po V10.13k

Poslední implementovaný patch opravil tři konkrétní bugy:

## V10.13k — již opraveno
1. **Exit reason casing mismatch**
   - `trade_executor.py` ukládal close reason přes `.lower()`
   - `bot2/main.py` a `learning_event.py` čekaly uppercase klíče
   - dopad: smart-exit statistiky vypadaly jako nula i když exit path reálně běžel

2. **Scratch exit byl strukturálně nedosažitelný**
   - `SCRATCH_MIN_AGE_S = 180`
   - `min_timeout = 120`
   - scratch se kontroloval dřív, ale nikdy nedosáhl věku → timeout ho vždy předběhl

3. **Regime nebyl předán do smart exit evaluace**
   - micro-TP používal base threshold místo regime-adaptive thresholdu

## Očekávaný efekt V10.13k
- `micro > 0`
- `scratch > 0`
- `t_flat` by měl klesnout
- exit telemetry konečně začne odpovídat realitě

---

# Aktuální bezpečnostní problém

Z posledních logů vychází, že po předchozích změnách vznikal tento vzor:

- žádné obchody po posledním patchi,
- watchdog a self-heal reagují jako na stall,
- ale v logu zároveň byla runtime chyba:
  - `unexpected indent (smart_exit_engine.py, line 416)`
- tedy:
  - **nešlo o čistý tržní stall**
  - šlo o **poruchu execution/live path**

To je nebezpečné, protože systém:
- snižuje filtry,
- přidává exploraci,
- mění režim řízení rizika,
- ale kořen problému je syntaktická/runtime chyba.

To může vést k:
- chybným recovery akcím,
- nečitelnému stavu,
- riziku nekonzistentního chování po částečné obnově.

---

# Návrh: V10.13L — Runtime Safety State & Fail-Closed Recovery

## Hlavní myšlenka

Když live pipeline selže kvůli chybě modulu nebo event handleru, bot nesmí předstírat normální provoz.

Místo toho má přejít do **explicitního safety state**:

- **TRADING_DISABLED_RUNTIME_FAULT**
- bez otevírání nových pozic,
- bez dalších adaptive threshold relaxací,
- s jasnou diagnostikou,
- s možností běžet pouze:
  - monitoring,
  - správa otevřených pozic,
  - hard TP/SL/timeout fallback.

---

# Co patch zavádí

## 1. Jednotný runtime fault registry

Nový modul:

`src/services/runtime_fault_registry.py`

Úloha:
- centralizovaně evidovat chyby kritických komponent,
- držet stav:
  - `OK`
  - `DEGRADED`
  - `FAULTED`
- poskytovat jednoduché API pro ostatní vrstvy.

### Návrh API
```python
mark_fault(component: str, error: str, severity: str = "hard")
clear_fault(component: str)
has_hard_fault() -> bool
get_fault_snapshot() -> dict
is_trading_allowed() -> bool
```

### Kritické komponenty
- `smart_exit_engine`
- `trade_executor`
- `realtime_decision_engine`
- `signal_generator`
- `market_stream`
- `boot_guardian`
- `event_dispatch`

### Pravidla
- hard syntax/import/runtime chyba v kritické komponentě ⇒ `FAULTED`
- transient websocket reconnect ⇒ ne hard fault
- trading allowed pouze pokud:
  - není žádný hard fault,
  - event breaker není tripnutý,
  - heartbeat není v broken stavu

---

## 2. Fail-closed gate před otevřením každého obchodu

V `trade_executor.py` a/nebo centrálním open path přidat guard:

```python
if not runtime_fault_registry.is_trading_allowed():
    log.warning("OPEN_BLOCKED_RUNTIME_FAULT")
    return None
```

### Smysl
Když je porouchaná část pipeline:
- žádné nové pozice,
- žádné „zkusíme to i tak“,
- žádné maskování problému přes exploration.

To je nejdůležitější safety změna v celém patchi.

---

## 3. Oddělení “STALL” vs “RUNTIME_FAULT”

Aktuálně watchdog interpretuje dlouhé bezobchodní období jako stall a snaží se systém uvolnit.

To je správně jen tehdy, když:
- pipeline opravdu běží,
- ticks přicházejí,
- kandidáti vznikají,
- RDE rozhoduje,
- execution path je zdravá.

### Nové pravidlo
Self-heal smí snižovat prahy jen pokud:

- heartbeat potvrzuje aktivní live path,
- není hard runtime fault,
- event breaker není tripnutý.

Jinak:

- žádné další snižování thresholdů,
- žádné další exploration boosty,
- místo toho:
  - `SELF_HEAL_SKIPPED_RUNTIME_FAULT`
  - `SYSTEM_STATE=FAULTED`

### To zabrání tomuto anti-patternu:
> smart_exit spadne → watchdog sníží thresholdy na 0 → systém vypadá agresivně “opravený”, ale ve skutečnosti je rozbitý.

---

## 4. Safety mode pro otevřené pozice

I při `FAULTED` stavu musí systém bezpečně spravovat existující pozice.

### Režim `DEGRADED_EXIT_ONLY`
Pokud je porucha v ne-kritické části exit logiky:
- nové pozice zakázat,
- otevřené pozice spravovat přes jednoduchý fallback:
  - hard TP
  - hard SL
  - max timeout
  - optional break-even po určitém zisku

### Režim `FULL_FAULT_LOCK`
Pokud je porucha v samotném execution/exits dispatchi:
- nové pozice zakázat,
- opakovaně logovat kritický alert,
- nespouštět exploration,
- označit systém jako vyžadující restart / fix.

---

## 5. Fault-aware dashboard

Do `bot2/main.py` přidat sekci:

```text
SAFETY STATE
------------
State: FAULTED
Trading: DISABLED
Reason: smart_exit_engine syntax/runtime fault
Open positions mode: DEGRADED_EXIT_ONLY
Self-heal relaxations: PAUSED
```

### Přínos
Uživatel okamžitě uvidí:
- že nejde o běžný stall,
- že bot záměrně neotevírá obchody,
- proč,
- co ještě běží.

---

## 6. Fault-aware telemetry counters

Doplnit metriky:

```python
fault_counts = {
    "runtime_fault_open_blocked": 0,
    "runtime_fault_exit_fallback_used": 0,
    "runtime_fault_self_heal_paused": 0,
    "runtime_fault_cycles": 0,
}
```

A samostatný snapshot:

```json
"runtime_safety": {
  "state": "FAULTED",
  "trading_allowed": false,
  "open_positions_mode": "DEGRADED_EXIT_ONLY",
  "faults": {
    "smart_exit_engine": "unexpected indent line 416"
  }
}
```

---

# Proč je ten patch potřeba právě teď

Z logů jsou vidět tyto signály:

## 1. Dlouhý stall
- poslední obchod 15h+
- watchdog zvyšuje exploration
- systém přechází do extrémních recovery módů

## 2. Runtime chyba v kritickém modulu
- `unexpected indent (smart_exit_engine.py, line 416)`

## 3. Self-heal reaguje, i když live path byla porouchaná
To je přesně stav, kdy systém potřebuje:
- **tvrdé odlišení „není co obchodovat“ vs „neumíme bezpečně obchodovat“**

---

# Priority implementace

## P0 — implementovat hned
1. `runtime_fault_registry.py`
2. hard gate před open order
3. self-heal pause při runtime fault
4. dashboard stav `FAULTED / DEGRADED / OK`

## P1 — velmi vhodné
5. degraded exit-only mode
6. fault counters + snapshot
7. alert při fault trvajícím déle než X minut

## P2 — doplnění
8. fault persistence do JSON state / db
9. auto-clear fault pouze po N zdravých cyklech
10. rozlišení hard vs soft component faults

---

# Přesná specifikace patch chování

## Stav OK
- trading povolen
- self-heal aktivní
- adaptive thresholds aktivní
- plná exit logika aktivní

## Stav DEGRADED
- trading otevření nových pozic zakázán nebo omezen
- otevřené pozice spravovány fallbackem
- self-heal threshold relaxace pozastavena
- diagnostika běží dál

## Stav FAULTED
- nové pozice zakázány
- žádná adaptive relaxace
- žádná exploration eskalace
- pouze monitoring + bezpečný position management
- silný alert v dashboardu i logu

---

# Návrh commit message

```text
V10.13L: runtime safety state + fail-closed trading gate + fault-aware self-heal
```

---

# Doporučené acceptance criteria

Patch je hotový pouze pokud platí vše:

## A. Když kritický modul spadne
- bot explicitně přejde do `FAULTED`
- nové pozice se neotevřou
- dashboard ukáže důvod

## B. Když běží runtime fault
- watchdog už dál nesnižuje EV/score thresholdy
- exploration se dál nenafukuje

## C. Když jsou otevřené pozice
- systém je stále umí bezpečně uzavřít fallbackem

## D. Když se komponenta zotaví
- fault se nesmí smazat okamžitě po jednom úspěšném ticku
- clear až po stabilním recovery okně, např. 30–60 s bez chyby

---

# Doplňkové návrhy zlepšení po V10.13L

## 1. Exit path unit tests
Zejména:
- reason casing
- scratch vs timeout ordering
- regime-aware thresholds
- fallback hard TP/SL path
- degraded exit mode

## 2. “No silent except” audit
Projít kritické moduly a odstranit místa, kde se chyba jen zaloguje, ale nepropíše do safety state.

## 3. Candidate-flow invariant
Pokud:
- ticks > 0
- prices fresh
- thresholds = 0
- a přesto kandidáti = 0 po dlouhou dobu,
tak vyhlásit samostatný alert:
- `CANDIDATE_GENERATION_FAILURE`

## 4. Pair quarantine
DOT má z logů zjevně velmi slabé výsledky.
Přidat možnost:
- dočasně vypnout pár po kombinaci:
  - velmi nízké WR,
  - negativní EV,
  - loss cluster opakování.

To je ale až sekundární. Přednost má fail-closed safety.

---

# Shrnutí

## Co už opravilo V10.13k
- smart exit telemetry konečně může ukazovat pravdu
- scratch je dosažitelný
- micro-TP používá správný regime

## Co má řešit další patch
Ne další „víc obchodů“, ale:
- **bezpečné chování při runtime poruše**
- **zákaz falešné autorecovery, když je pipeline interně rozbitá**
- **jasný fault state místo tichého chaosu**

## Nejlepší další patch
**V10.13L — Runtime Safety State & Fail-Closed Recovery**

To je teď nejvyšší priorita, protože chrání systém před nejhorším typem selhání:
> proces běží, logy jedou, watchdog se snaží pomáhat, ale obchodní pipeline je rozbitá.

---

# Doporučení pro Claude

Implementuj patch **inkrementálně**:

1. přidej `runtime_fault_registry.py`
2. napoj `boot_guardian`, `event_exception_breaker`, `live_path_heartbeat`, `smart_exit_guard`
3. zablokuj nové openy při hard fault
4. pozastav self-heal relaxace při hard fault
5. přidej dashboard sekci `SAFETY STATE`
6. až potom přidej degraded exit-only mode

Nedělej velký refactor. Cíl je **spolehlivý fail-closed patch**, ne architektonická revoluce.
