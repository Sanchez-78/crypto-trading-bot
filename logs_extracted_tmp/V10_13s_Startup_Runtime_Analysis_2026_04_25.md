# V10.13s / V10.13t / V10.13x — analýza startup + runtime logu (2026-04-25)

## Executive summary

Tahle verze je lepší než předchozí, protože už jasně ukazuje:

- startup pipeline proběhne až do live režimu
- Firebase init funguje
- warmup z Binance funguje
- `V10.13x RECON` dává konzistentní rozpad `500 = 75 + 26 + 399`
- health už není mrtvá konstanta typu `0.001 [BAD]`, ale má rozklad:
  - `Health: 0.334 [GOOD]`
  - `Edge: 0.001`
  - `Conv: 0.000`
  - `Stab: 1.000`
  - `Breadth: 0.333`

Současně ale log potvrzuje, že systém ještě není plně sjednocený a že stále existují 4 hlavní problémy:

1. startup state mismatch / maturity mismatch
2. dashboard truth je lepší, ale runtime internals stále ukazují více “pravd” zároveň
3. scratch exit ekonomika je pořád hlavní brzda
4. některé logy ukazují duplicated / noisy behavior

---

## Co je zjevně opravené

### 1. Firebase chyba už není skutečný problém

Na začátku je:

- `Firebase initialized ✓`
- `Daily budget report done ✓`
- `[Firebase] connected`

To znamená, že Firebase není rozbitý.

Ta hláška:

- `WARNING:root: 🔴 CRITICAL: Firebase reads: 100/50,000 (0.2%)`

je zjevně špatně klasifikovaný warning.

#### Proč
- 100 z 50 000 je jen 0.2 % limitu
- to není critical stav
- je to maximálně info/debug/quota trace

#### Závěr
Tohle není Firebase problém.
Tohle je log-level / wording bug v quota monitoringu.

---

### 2. Startup pipeline běží korektně

Log ukazuje plný boot bez fatální chyby:

- event bus handlers
- self-healing
- genetic algorithm
- async learning flush worker
- Firebase
- budget report
- hydration from Redis
- trade history load
- bootstrap
- warmup indicators
- websocket live

To je velmi důležité, protože dřív byly problémy už ve startu.

**Závěr:** boot sekvence je funkční.

---

### 3. Warmup a WebSocket live fungují

Máme:

- `Warmup done: 7 from Binance + 0 synthetic`
- `MARKET LIVE (WebSocket bookTicker)`

To potvrzuje, že:
- data feed je živý
- trh je napojený
- systém se dostal do live loopu

---

### 4. Negative EV hard enforcement teď opravdu funguje

V logu několikrát:

- `Rejected negative/zero EV ... hard enforcement of EV-only principle`
- `decision=REJECT_NEGATIVE_EV ev=-0.0348 ≤ 0`
- `decision=REJECT_NEGATIVE_EV ev=-0.0399 ≤ 0`

To je dobré znamení.

#### Praktický význam
Dříve systém často pouštěl i slabé / pochybné obchody přes soft logic.
Teď je vidět, že minimálně část těchto případů je tvrdě blokována.

**Závěr:** EV-only enforcement vypadá aktivně a správně.

---

## Co zůstává problém

### 1. Startup state není opravdu sjednocený

Tohle je nejdůležitější technický problém v logu.

#### Důkaz
Log ukazuje víc různých “počtů obchodů” najednou:

- `[7/7a] Loaded 100 trades ✓`
- `Bootstrap: 7467 obchodů`
- `[V10.13x RECON] trades=500`
- `completed_trades: 100`
- `Maturity computed: trades=0 bootstrap=True cold_start=True`

To je čtyřvrstvý konflikt:

- **100** = learning/runtime subset
- **500** = reconciled dashboard set
- **7467** = stale/global/full historical bootstrap layer
- **0** = unified maturity result after correction

#### Proč je to problém
I když dashboard pro uživatele vypadá dobře, interní rozhodování může stále čerpat z jiných vrstev dat.

To je vidět tady:

- `STATE MISMATCH DETECTED — stale global state after reset`
- `global_completed_trades=7467 (stale)`
- `effective_completed_trades=100 (from learning state)`
- `→ Clearing stale global metrics`

To je dobrý safeguard, ale zároveň to potvrzuje, že:
- stale global state pořád vzniká
- až za běhu je detekován a opravován

#### Nejhorší indikátor
Po opravě mismatch dostaneš:

- `Maturity computed: trades=0 bootstrap=True cold_start=True`

To je velmi podezřelé, protože:
- effective_completed_trades = 100
- dashboard reconciliation = 500
- ale maturity oracle nastaví trades = 0

**Závěr:** unified maturity oracle ještě není skutečně unified. Je tam bug nebo chybná precedence zdrojů.

---

### 2. Duplicate event subscription vypadá podezřele

Ve startu je:

- `Subscribed: signal_created -> handle_signal`
- `Subscribed: price_tick -> on_price`
- `Subscribed: price_tick -> on_price`

`price_tick -> on_price` je přihlášené dvakrát.

#### Riziko
To může znamenat:
- dvojité volání handleru
- dvojnásobný noise v logu
- duplicate decisions / duplicate signal evaluation
- nebo aspoň zbytečný overhead

Nemusí to být nutně fatální, pokud event bus deduplikuje interně, ale z logu to nevypadá čistě.

**Závěr:** zkontrolovat, zda se `on_price` neregistruje dvakrát.

---

### 3. Dashboard truth je lepší, ale ekonomika je stále slabá

Tady je hlavní ekonomický závěr:

- `WR_canonical 74.3%`
- `Profit Factor 0.67x`
- `Zisk (uzavrene) -0.00077747`

To pořád znamená totéž co dřív:

- rozhodující WR vypadá dobře
- ale peníze se ve výsledku nevydělávají

#### Hlavní důvod
- `SCRATCH_EXIT 399`
- `80% obch`
- `net -0.00124254`
- `95% exits scratch`

To je stále dominantní brzda systému.

Pozitivní exity:

- `PARTIAL_TP_25 net +0.00058564`
- `MICRO_TP net +0.00002037`
- `wall_exit net +0.00002412`

Negativní scratch flow to celé přetlačí.

**Závěr:** `V10.13x` zlepšil metriky, ale nevyřešil hlavní obchodní problém: systém stále příliš často zavírá do scratch / flat ekonomiky.

---

### 4. Health je lepší, ale stále trochu kosmetický

Nový blok:

- `Health: 0.334 [GOOD]`
- `Edge: 0.001`
- `Conv: 0.000`
- `Stab: 1.000`
- `Breadth: 0.333`

To je určitě lepší než staré:
- `Health: 0.001 [BAD]`

Protože aspoň vidíš složky health.

Ale zároveň:

- `Conv: 0.000`
- warning: `low_convergence: only 0/6 pairs converged`

To znamená, že label `GOOD` je trochu optimistický.

#### Interpretace
Health formula je nyní čitelnější, ale ještě není úplně intuitivní:
- dobrá stabilita a nějaká breadth vytáhnou health nahoru
- i když convergence je nulová
- a edge je skoro nulová

**Závěr:** health decomposition je lepší, ale finální label `GOOD` je zatím možná příliš benevolentní.

---

### 5. Execution engine a dashboard nejsou ve stejné “fázi času”

Dashboard říká:

- `WR_canonical 74.3%`
- `Obchody 500`

Ale execution engine současně ukazuje:

- `Sharpe: 0.000 | WR: 0.00% | Edge: 0.00000`

To není nutně bug samo o sobě.
Spíš to vypadá, že:

- dashboard = historický reconciled summary
- execution engine = current-session/live runtime stats

Ale pro člověka je to matoucí.

**Závěr:** je potřeba jasně rozlišit:
- historical system stats
- current session stats
- live open-book stats

Teď se to všechno zobrazuje vedle sebe a vypadá to jako rozpor.

---

### 6. Pre-live audit je užitečný, ale zatím příliš hlučný

Audit ukazuje:

- `Trades audited: 20`
- `Passed to execution: 14`
- `Blocked: 6`
- `[CI] PASS`

To je super.

Ale současně vypisuje hodně interních replay rozhodnutí, která dost zahlcují log:
- opakované `decision=TAKE`
- opakované `coherence`
- opakované bootstrap threshold zprávy

**Závěr:** audit je dobrý nástroj, ale zaslouží si kompaktnější summary režim.

---

## Co je teď podle logu nejdůležitější

### Priorita 1 — opravit unified maturity / source-of-truth

Tohle bych řešil jako první.

#### Proč
Dokud systém neví, jestli má:
- 0 trades
- 100 trades
- 500 trades
- nebo 7467 trades

tak nikdy nebudeš mít plně důvěryhodné:
- bootstrap logic
- threshold relaxace
- health
- maturity
- cold_start chování

#### Cíl
Zavést jedinou canonical funkci, která vrátí:

- historical_trades_reconciled
- runtime_completed_trades
- maturity_trades_used_for_logic
- source
- ts

A všechny subsystémy musí používat právě její výstup.

---

### Priorita 2 — odstranit stale global state už před startem live loopu

Teď se stale state:
- načte
- detekuje
- až pak čistí

Lepší by bylo:
- reset/normalize udělat dřív
- a do `main event loop` nikdy nevstoupit se stale globály

---

### Priorita 3 — fixnout severity Firebase quota hlášky

Tahle hláška je špatná:

- `CRITICAL: Firebase reads: 100/50,000 (0.2%)`

Správně by to mělo být něco jako:
- `INFO: Firebase reads: 100/50,000 (0.2%)`
- nebo `DEBUG: quota trace`

Jinak to mate a vypadá to jako reálný problém.

---

### Priorita 4 — ověřit duplicate subscription

Zkontrolovat:
- kde se registruje `price_tick -> on_price`
- proč je v logu dvakrát
- zda skutečně nedochází k duplicitní evaluaci

---

### Priorita 5 — dál tlačit SCRATCH_EXIT forensic vrstvu

Tohle zůstává obchodně nejcennější směr.

Z logu je pořád evidentní:

- `scratch 95%`
- `SCRATCH_EXIT 399`
- `net -0.00124254`

Dokud tohle nepitváš detailněji, nebude systém ekonomicky zdravý.

---

## Doporučený další patch

## V10.13s.1 — Canonical State & Maturity Fix

### Cíl
Odstranit rozpory mezi:
- startup bootstrap
- runtime learning state
- dashboard reconciliation
- maturity oracle

### Patch obsah

#### 1. Canonical state snapshot
Vytvořit jednu funkci, např.:
- `get_canonical_runtime_state()`

která vrací:

- `trades_reconciled`
- `trades_runtime`
- `trades_history_total`
- `trades_for_maturity`
- `cold_start`
- `bootstrap`
- `source_used`
- `state_consistent`

#### 2. Maturity oracle fix
Zakázat stav, kdy:
- runtime má data
- dashboard má data
- ale maturity vrátí `trades=0`

Tohle musí být explicitně zalogováno jako bug.

#### 3. Startup normalization
Před live loopem:
- clear stale globals
- sync metrics
- sync learning counters
- sync maturity inputs

#### 4. Firebase quota log severity fix
Přemapovat severity podle skutečného procenta limitu.

Např.:
- `<50%` info
- `50–80%` warning
- `>80%` high warning
- `>95%` critical

#### 5. Event bus duplicate guard
Při subscribe:
- logovat, pokud handler už existuje
- nebo duplicitní registraci odmítnout

---

## Doporučený následný patch po tom

## V10.13s.2 — Scratch Exit Forensics

Až po canonical state fixu.

Obsah:
- scratch by symbol
- scratch by regime
- scratch by hold time
- scratch by MFE/MAE
- scratch after positive excursion
- scratch after fees/slippage
- scratch activation reasons

---

## Krátký verdict

### Co je dobré
- Firebase funguje
- boot funguje
- websocket funguje
- EV-only blokace funguje
- dashboard reconciliation je lepší
- health decomposition je lepší

### Co je špatně
- maturity/source-of-truth stále není sjednocený
- stale global state stále vzniká
- duplicate subscription je podezřelá
- scratch exit ekonomika stále zabíjí PnL
- některé logy jsou hlučné a matoucí

### Nejlepší další krok
Nejdřív opravit canonical state + maturity.
Potom teprve dál řezat `SCRATCH_EXIT` ekonomiku.
