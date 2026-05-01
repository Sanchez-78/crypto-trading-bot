# CryptoMaster HF-Quant 5.0 — Komplexní Bug Report

> **Datum analýzy:** 2026-05-01  
> **Branch:** `claude/code-analysis-bug-report-6PcEa`  
> **Analyzovaný log:** `bot.log` (157 558 řádků)  
> **Celkem nalezených problémů:** 40+ (8 katastrofální, 8 kritické, 10 vysoké, 14 střední/nízké)

---

## Shrnutí z runtime logu

Před detailním popisem bugů — data z `bot.log` jasně ukazují, **kde systém selhává v praxi**:

| Metrika | Hodnota | Interpretace |
|---------|---------|--------------|
| Dokončených obchodů | 81 | Bot obchoduje |
| Win Rate všech párů | **0 %** | Učení nefunguje |
| Expected Value všech párů | **0.000** | P&L se nezaznamenává |
| FAST_FAIL_SOFT_BOOTSTRAP bloků | **1 406** | Uvízlý v bootstrapu navždy |
| OFI_TOXIC bloků | **799** | Signály blokované OFI |
| FORCED signals | **449** | Bot používá náhodné fallback signály |
| Redis FLUSH_LM_REDIS_NONE | **81** | Learning data se ztrácejí |
| WebSocket disconnectů | **63** | Nestabilní datový feed |
| Latency varování (>50ms SLA) | **20** | Max naměřeno 1 206 ms (24× překročení SLA) |
| Defense efficiency | **0.0** | Exit ochrana nefunguje |

**Kořenová příčina kaskády:** `portfolio_manager.py` generuje P&L jako `random.uniform(-1, 1)` → vše co závisí na skutečném P&L (učení, bandit, WR, EV) dostává šum → bot nikdy nevyjde z bootstrap módu → 1 406 FAST_FAIL bloků → generuje FORCED signály jako náhrada → systém se točí v kruhu.

---

## CATASTROPHIC — Okamžité selhání systému

---

### BUG-001 · Falešný P&L — `src/services/portfolio_manager.py:36`

**Závažnost:** 🔴 CATASTROPHIC  
**Ověřeno v logu:** Ano — všechny páry `ev: 0.0`, `wr: 0%` po 81 obchodech

```python
# CHYBA — aktuální kód:
profit = random.uniform(-1, 1)   # Náhodné číslo mezi -100% a +100% !!

# FIX:
entry_price = trade.get("price", 0)
current_price = trade.get("current_price", entry_price)
if entry_price > 0:
    profit = (current_price - entry_price) / entry_price
else:
    profit = 0.0
trade["profit"] = profit
```

**Dopad:** Celý learning pipeline (bandit, WR, EV, kalibrace) dostává náhodná data. Bot se nikdy nenaučí nic reálného. Způsobuje 1 406 FAST_FAIL_SOFT_BOOTSTRAP bloků v logu — systém uvízl v bootstrap navždy.

---

### BUG-002 · Neexistující funkce — `src/services/smart_exit_guard.py:79`

**Závažnost:** 🔴 CATASTROPHIC  
**Ověřeno:** `grep "def evaluate_smart_exit\|def evaluate_position_exit" src/services/smart_exit_engine.py`

```python
# CHYBA — guard volá funkci která NEEXISTUJE:
return _smart_exit_module.evaluate_smart_exit(...)   # AttributeError!

# V smart_exit_engine.py je definována pouze:
def evaluate_position_exit(...):   # linka 704
```

**FIX** — přidat alias na konec `smart_exit_engine.py`:
```python
evaluate_smart_exit = evaluate_position_exit
```

**Dopad:** Smart exit engine NIKDY nepracuje. Guard vždy zachytí `AttributeError` a vrátí `None` → bot spoléhá pouze na hardcoded TP/SL/timeout. V logu: `defense.efficiency = 0.0`, `wall_exits = 0`.

---

### BUG-003 · Dimensionální nesoulad v trailing stopu — `src/services/trailing_stop.py:25,39`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — porovnává % s absolutní cenou:
profit = (current_price - entry) / entry    # profit = 0.05  (5%, bezrozměrné)
if profit > atr * self.break_even_trigger:  # atr = 500.0 USD × 1.0 = 500.0 !!
    sl = max(sl, entry)                     # 0.05 > 500.0  → NIKDY NENASTANE

# FIX — normalizovat ATR na procenta:
atr_pct = atr / entry
if profit > atr_pct * self.break_even_trigger:
    sl = max(sl, entry)
```

Stejná chyba na řádku 39 pro SELL větev (`profit > atr * self.break_even_trigger`).

**Dopad:** Break-even stop-loss se nikdy nespustí. Bot nikdy nechrání zisky posunem SL na vstupní cenu.

---

### BUG-004 · Obrácená logika TP tightening — `src/core/exit_optimizer.py:116`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — "tighten" TP ho ve skutečnosti VZDÁLÍ od ceny:
# Příklad: current=100, tp=110
tight_tp = current + (tp - current) * 0.7   # = 100 + 10*0.7 = 107  (DÁLE než current!)

# FIX — přiblížit TP k current ceně (30% vzdálenosti, ne 70%):
tight_tp = current + (tp - current) * 0.3   # = 100 + 10*0.3 = 103  (BLÍŽE k exitu)
```

**Dopad:** Při dlouhých obchodech bot nastavuje TP dále, místo aby usnadnil exit. Pozice se drží déle → větší ztráty při reverzu.

---

### BUG-005 · SHORT ignorováno v exit optimizéru — `src/core/exit_optimizer.py:95`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — předpokládá vždy LONG:
if current > entry:
    analysis["reason"] = "PROFITABLE"   # Pro SHORT je current > entry ZTRÁTA!

# FIX:
direction = trade.get("direction", "LONG")
is_profitable = (
    (direction == "LONG" and current > entry) or
    (direction == "SHORT" and current < entry)
)
if is_profitable:
    analysis["reason"] = "PROFITABLE"
```

**Dopad:** Všechny SHORT pozice jsou označeny jako ztrátové i při správném pohybu ceny → předčasné uzavírání ziskových SHORT obchodů.

---

### BUG-006 · ADX vrací konstantní pole — `src/core/strategy_executor.py:257`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — celé pole má jednu hodnotu z prvního periodu:
smoothed_tr  = np.mean(tr[:period])       # Průměr POUZE prvních `period` barů
smoothed_plus = np.mean(plus_dm[:period])
di_plus = (smoothed_plus / smoothed_tr) * 100
dx = (np.abs(di_plus - di_minus) / (di_plus + di_minus)) * 100
adx = np.full(len(close), dx)            # Stejná hodnota pro VŠECHNY svíčky!

# FIX — správné Wilderovo vyhlazení:
def _adx(self, high, low, close, period):
    high_diff = np.diff(high)
    low_diff  = -np.diff(low)
    plus_dm   = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm  = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    tr = np.maximum(
        np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1])),
        np.abs(low[1:] - close[:-1])
    )
    if len(tr) < period:
        return np.zeros(len(close))

    # Wilderovo vyhlazení pro každý bar
    atr_arr  = np.zeros(len(tr))
    pdm_arr  = np.zeros(len(tr))
    mdm_arr  = np.zeros(len(tr))
    atr_arr[period-1]  = np.sum(tr[:period])
    pdm_arr[period-1]  = np.sum(plus_dm[:period])
    mdm_arr[period-1]  = np.sum(minus_dm[:period])
    for i in range(period, len(tr)):
        atr_arr[i] = atr_arr[i-1] - (atr_arr[i-1] / period) + tr[i]
        pdm_arr[i] = pdm_arr[i-1] - (pdm_arr[i-1] / period) + plus_dm[i]
        mdm_arr[i] = mdm_arr[i-1] - (mdm_arr[i-1] / period) + minus_dm[i]

    with np.errstate(divide='ignore', invalid='ignore'):
        di_plus  = np.where(atr_arr > 0, (pdm_arr / atr_arr) * 100, 0)
        di_minus = np.where(atr_arr > 0, (mdm_arr / atr_arr) * 100, 0)
        denom    = di_plus + di_minus
        dx       = np.where(denom > 0, (np.abs(di_plus - di_minus) / denom) * 100, 0)

    adx_arr = np.zeros(len(tr))
    if len(dx) >= period:
        adx_arr[2*period-2] = np.mean(dx[period-1:2*period-1])
        for i in range(2*period-1, len(dx)):
            adx_arr[i] = (adx_arr[i-1] * (period - 1) + dx[i]) / period

    result = np.zeros(len(close))
    result[1:] = adx_arr
    return result
```

**Dopad:** Trend strength indikátor ukazuje stejnou hodnotu pro celou historii → signály confidence jsou postaveny na nesmyslném vstupu.

---

### BUG-007 · Obrácená logika severity — `src/core/adaptive_ev.py:140-149`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — logika je obráceně:
diff = self.base_threshold - self.current_threshold
# diff > 0 = threshold byl SNÍŽEN (relaxováno) = systém je pod tlakem
# diff < 0 = threshold byl ZVÝŠEN (zpřísněno) = systém je v pohodě

if diff < 0:           # zpřísněno → označí jako "STRICT"  ✓ SPRÁVNĚ
    return "STRICT"
elif diff < 0.01:      # NIKDY NEDOSAŽITELNÉ (diff<0 pokryto výše)
    return "NORMAL"
elif diff < 0.03:
    return "RELAXED"
else:
    return "CRITICAL"

# FIX — správné pořadí:
if diff <= 0:
    return "NORMAL"       # threshold nebyl snížen
elif diff < 0.01:
    return "RELAXED"
elif diff < 0.03:
    return "CRITICAL"
else:
    return "EXTREME"
```

**Dopad:** Stav severity se vyhodnocuje opačně → bot nesprávně eskaluje nebo deeskaluje riziko.

---

### BUG-008 · Chybné signatury funkcí — `bot2/learning_engine.py:158,180`

**Závažnost:** 🔴 CATASTROPHIC

```python
# CHYBA — standalone funkce mají self parametr:
def update_features(self, features, reward, learning_rate=0.01):
    # Volání: update_features(features_dict, 0.5)
    # → self = features_dict, features = 0.5, reward = CHYBÍ → TypeError!
    self.feature_weights[f] += learning_rate * reward   # AttributeError na dict!

def learn_bias(self, batch):
    self.bias += 0.01 * avg_reward   # self.bias neexistuje!

# FIX — přidat jako metody třídy LearningEngine:
class LearningEngine:
    # ... stávající metody ...

    def update_features(self, features, reward, learning_rate=0.01):
        if not hasattr(self, 'feature_weights'):
            self.feature_weights = {}
        for f in features:
            self.feature_weights.setdefault(f, 0.0)
            self.feature_weights[f] += learning_rate * reward

    def learn_bias(self, batch):
        if not hasattr(self, 'bias'):
            self.bias = 0.0
        avg_reward = sum(r for _, _, r, _ in batch) / max(len(batch), 1)
        self.bias += 0.01 * avg_reward
```

**Dopad:** Feature weight learning a bias update jsou zcela nefunkční. Volání způsobí `TypeError` nebo `AttributeError`.

---

## CRITICAL — Způsobují špatná obchodní rozhodnutí

---

### BUG-009 · Špatný výpočet max drawdown — `src/core/strategy.py:54-57`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — peak = maximum jednoho obchodu, ne peak equity:
cumsum = sum(self.trade_history)       # celkový P&L
peak   = max(self.trade_history)       # max JEDNOHO obchodu ← ŠPATNĚ
dd     = abs(min(0, cumsum - peak))

# Příklad: obchody = [+5%, -10%, +3%]
# cumsum = -2%, peak = 5% (největší obchod)
# dd = abs(min(0, -2% - 5%)) = 7%   ← ŠPATNĚ
# Správně: peak equity = +5%, valley = +5%-10% = -5%, dd = 10%

# FIX — správný výpočet:
def _update_max_drawdown(self):
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in self.trade_history:
        cumulative += pnl
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
    self.max_drawdown = max_dd
```

**Dopad:** Fitness score strategie je postaven na nesprávném drawdown → genetický algoritmus špatně selektuje strategie.

---

### BUG-010 · RSI ignoruje ztráty — `src/core/strategy_executor.py:216-217`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — multiplikátor (1 if delta<0 else 0) zeruje ztráty:
avg_gain = (avg_gain*(period-1) + (1 if delta[i-1]>0 else 0)*delta[i-1]) / period
avg_loss = (avg_loss*(period-1) + (1 if delta[i-1]<0 else 0)*abs(delta[i-1])) / period
# Pro delta=-5: (1 if -5<0 else 0)*(-5) = 1*(-5) = -5  ← ZÁPORNÉ DO avg_gain!
# Logika je sice pokusem o Wilderovo vyhlazení, ale je implementována chybně

# FIX — správné Wilderovo RSI vyhlazení:
for i in range(period, len(prices)):
    if i > period:
        gain = max(delta[i-1], 0)
        loss = max(-delta[i-1], 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    rs  = avg_gain / avg_loss if avg_loss > 0 else float('inf')
    rsi = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100
    rsi_values.append(rsi)
```

**Dopad:** RSI je chronicky nadhodnocený → signály pro BUY na oversold a SELL na overbought jsou nepřesné.

---

### BUG-011 · Confidence může přesáhnout 1.0 — `src/core/strategy_executor.py:287`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — násobení může překročit 1.0:
confidence = base_confidence * rsi_adj * regime_mult
# Pokud regime_mult = dna.uptrend_bias = 1.2 → confidence = 0.9 * 0.9 * 1.2 = 0.972 (ok)
# Ale: base=1.0 * rsi_adj=0.9 * regime_mult=1.2 = 1.08 → oversized pozice!

# FIX — clamp na [0.1, 1.0] (řádek 288 to dělá, ale jen v _calculate_confidence):
# Ověřit že VŠECHNA místa volající position_size přes confidence mají clamp
position_size = np.clip(confidence * self.dna.kelly_fraction, 0.0, 1.0)
```

---

### BUG-012 · Špatný výpočet P&L bez poplatků — `shared/bot1/trade_manager.py:28`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — P&L ignoruje trading fees:
pnl = (exit_price - entry) / entry   # Chybí odečtení poplatků (typicky 0.1% × 2)

# FIX:
FEE_RATE = 0.001   # 0.1% maker/taker
pnl = (exit_price * (1 - FEE_RATE) - entry * (1 + FEE_RATE)) / entry
```

**Dopad:** Všechna P&L čísla jsou optimisticky nadhodnocená o 0.2%. Strategie s malou hranou se jeví jako ziskové.

---

### BUG-013 · UCB1 formula — `src/services/strategy_learner.py:69`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — total zahrnuje všechny strategie, ne jen pulls dané strategie:
total = sum(self._n[ctx].values()) + 1   # +1 zabraňuje log(0), ale je ad-hoc
confidence = np.sqrt(2 * np.log(total) / n)

# FIX — standard UCB1:
total_pulls = sum(self._n[ctx].values())
for s in self.strategies:
    n = self._n[ctx][s]
    if n == 0:
        scores[s] = float("inf")   # Neprozkoumaná strategie → priorita
    else:
        mean = np.mean(self._arms[ctx][s]) if self._arms[ctx][s] else 0.0
        scores[s] = mean + np.sqrt(np.log(max(1, total_pulls)) / n)
```

---

### BUG-014 · Session hour overlap — `src/services/strategy_learner.py:28-32`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — EU a US session se překrývají v 13:00-15:59:
SESSIONS = {
    "asia":   (0, 8),
    "europe": (8, 16),   # ← zahrnuje 13-15
    "us":    (13, 22),   # ← zahrnuje 13-15 také
}
# Výsledek: hodina 14 → vždy "europe", nikdy "us" (první match vyhraje)

# FIX — bez překryvu:
SESSIONS = {
    "asia":    (0,  8),
    "europe":  (8,  13),
    "overlap": (13, 16),   # Explicitní překrytí jako vlastní session
    "us":      (16, 22),
    "night":   (22, 24),
}
```

---

### BUG-015 · Race condition v trade_manager — `shared/bot1/trade_manager.py:20-37`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — TOCTOU: čti → zkontroluj → piš bez atomicity:
trade = ref.get().to_dict()        # Read
if trade is None: return False     # Check
# ... výpočty ...
ref.update({"pnl": pnl, ...})      # Write ← jiný process mohl mezitím změnit dokument

# FIX — Firestore transakce:
@db.transaction
def update_trade(transaction, ref):
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists:
        return False
    transaction.update(ref, {"pnl": pnl, "status": "CLOSED", ...})
```

---

### BUG-016 · Fitness se neaktualizuje v GA — `src/core/genetic_optimizer.py:150`

**Závažnost:** 🟠 CRITICAL

```python
# CHYBA — offspring dostanou fitness=0.0 a nikdy nejsou re-evaluovány:
child = Strategy(dna=child_dna, generation=parent.generation + 1)
# child.fitness = 0.0 (default) — nikdy se nepočítá v evolve_population()

# FIX — vyžadovat fitness funkci nebo zdokumentovat:
# Volající kód musí volat child.record_trade() nebo nastavit fitness externě.
# Přidat assertion:
assert callable(fitness_fn), "evolve_population() requires external fitness_fn"
for child in new_population:
    child.fitness = fitness_fn(child)
```

---

## HIGH — Memory leaky a thread safety

---

### BUG-017 · Neomezený event_log — `src/core/event_bus_v2.py:26`

**Závažnost:** 🟡 HIGH

```python
# CHYBA:
self.event_log = []   # Roste donekonečna — 24/7 bot → OOM

# FIX:
from collections import deque
self.event_log = deque(maxlen=50_000)   # Poslední 50k eventů
```

---

### BUG-018 · Špatný index "nejslabšího" — `src/core/genetic_pool.py:157`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — last index ≠ nejslabší (populace není seřazena):
weakest_idx = len(self.population) - 1   # Náhodná strategie, ne nejhorší!

# FIX:
weakest_idx = min(range(len(self.population)),
                  key=lambda i: self.population[i].fitness)
```

---

### BUG-019 · global_best se neinicializuje v prvním cyklu — `src/core/genetic_pool.py:165`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — první generace se přeskočí:
if self.global_best is not None:   # None při prvním volání → přeskočí!
    current_best = max(...)
    if current_best.fitness > self.global_best.fitness:
        self.global_best = copy.deepcopy(current_best)

# FIX:
current_best = max(self.population, key=lambda s: s.fitness)
if self.global_best is None or current_best.fitness > self.global_best.fitness:
    self.global_best = copy.deepcopy(current_best)
```

---

### BUG-020 · Neomezená Q-table — `src/core/rl_agent.py:61`

**Závažnost:** 🟡 HIGH

```python
# CHYBA:
self.q_table = {}   # Roste s každým novým stavem → memory leak po hodinách

# FIX — LRU eviction:
from collections import OrderedDict
self.q_table = OrderedDict()
self.max_q_table_size = 50_000

# V replay(), po update:
if len(self.q_table) > self.max_q_table_size:
    self.q_table.popitem(last=False)   # Odstraní nejstarší stav
```

---

### BUG-021 · Žádný train/val split — `src/services/ml_model.py:90`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — model se trénuje na 100% dat:
model.fit(X, y)   # Žádná validace → přetrénování!

# FIX:
from sklearn.model_selection import train_test_split
if len(X) >= 50:
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        early_stopping_rounds=10,
        verbose=False
    )
else:
    model.fit(X, y)   # Málo dat → trénovat vše
```

---

### BUG-022 · Thread safety — `src/services/ofi_guard.py:38-48`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — _price_ticks dict není thread-safe:
_price_ticks: dict[str, deque] = {}

def update_price(sym, price):
    if sym not in _price_ticks:          # Thread A čte
        _price_ticks[sym] = deque(...)   # Thread B také čte → dvě inicializace!
    _price_ticks[sym].append(price)      # Race condition!

# FIX:
import threading
_ofi_lock = threading.Lock()

def update_price(sym: str, price: float) -> None:
    with _ofi_lock:
        if sym not in _price_ticks:
            _price_ticks[sym] = deque(maxlen=_WINDOW + 1)
        _price_ticks[sym].append(float(price))

def ofi(sym: str) -> float:
    with _ofi_lock:
        hist = list(_price_ticks.get(sym, deque()))
    # ... výpočet mimo lock
```

---

### BUG-023 · Thread safety — `src/services/pair_quarantine.py:37-78`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — TOCTOU race condition:
if key in self.quarantined_pairs:
    if now >= self.quarantined_pairs[key]["until_ts"]:
        del self.quarantined_pairs[key]   # Thread A maže
    else:
        return True, ...                  # Thread B čte smazaný klíč → KeyError!

# FIX — přidat lock do __init__:
def __init__(self):
    self.quarantined_pairs = {}
    self._lock = threading.Lock()

def check_and_quarantine(self, ...):
    with self._lock:
        # ... celá logika uvnitř locku
```

---

### BUG-024 · Thread safety — `bot2/auditor.py:20-28`

**Závažnost:** 🟡 HIGH

```python
# CHYBA — globální proměnné bez zámku:
_position_size_mult = 1.0
_cooldown = 0
# Modifikované z run_audit() bez synchronizace → race condition

# FIX:
import threading
_auditor_lock = threading.Lock()

def run_audit():
    global _position_size_mult, _cooldown, ...
    with _auditor_lock:
        # ... celá logika
```

---

### BUG-025 · Redis data loss — potvrzeno logem

**Závažnost:** 🟡 HIGH  
**Výskyt v logu:** 81× `[FLUSH_LM_REDIS_NONE] ... - Redis client is None, data LOST`

```
WARNING:src.services.state_manager:[FLUSH_LM_REDIS_NONE] BTCUSDT/BULL_TREND - Redis client is None, data LOST
WARNING:src.services.state_manager:[FLUSH_LM_REDIS_NONE] SOLUSDT/BEAR_TREND - Redis client is None, data LOST
```

**Příčina:** Redis není dostupný (`Error 22 connecting to localhost:6379. Vzdálený počítač odmítl síťové připojení.`). Learning state se po každém restartu ztrácí.  
**FIX:** Nastavit Redis na Railway/produkčním serveru nebo implementovat fallback na disk persistence.

---

### BUG-026 · Latency SLA překročení — potvrzeno logem

**Závažnost:** 🟡 HIGH  
**Výskyt v logu:** 20× varování, max 1 206 ms (SLA = 50 ms = 24× překročení)

```
WARNING: [LATENCY_WARN] on_price processing time: 1206.20ms (SLA: 50ms)
WARNING: [LATENCY_WARN] on_price processing time: 1124.19ms (SLA: 50ms)
```

**Příčina:** `on_price()` tick handler provádí synchronní Firebase/Redis I/O v hot path. HF bot vyžaduje <50ms zpracování.  
**FIX:** Přesunout všechny I/O operace do asynchronní fronty. Tick handler musí pouze aktualizovat in-memory struktury.

---

## MEDIUM — Logické chyby a špatná konfigurace

---

### BUG-027 · Cooldown nikdy neklesá — `bot2/stabilizer.py:23`

```python
# CHYBA — nastaví cooldown = 3, ale nikde se nesnižuje:
self.cooldown = 3
return {"signal": "HOLD", "cooldown": self.cooldown}
# Příště: self.cooldown je stále 3!

# FIX:
def update(self, signals):
    if self.cooldown > 0:
        self.cooldown -= 1
        return {"signal": "HOLD", "reason": "cooldown"}
    # ... zbytek logiky
```

---

### BUG-028 · Boundary overlap v kalibraci — `src/services/probability_calibration.py:148`

```python
# CHYBA — hodnota 0.55 padá do dvou bucketů (první match vyhraje):
# Bucket 1: raw_p_min=0.45, raw_p_max=0.55  ← zahrnuje 0.55
# Bucket 2: raw_p_min=0.55, raw_p_max=0.60  ← zahrnuje 0.55

# FIX — použít exkluzivní horní mez:
if bucket.raw_p_min <= raw_p < bucket.raw_p_max:   # < místo <=
```

---

### BUG-029 · Stale calibration dat — `src/services/probability_calibration.py:164`

```python
# CHYBA — bucket s nedostatkem dat si ZACHOVÁ staré empirical_p:
if total < min_samples_per_bucket:
    continue   # Stará hodnota zůstane! Může být z úplně jiného trhového režimu.

# FIX — resetovat na neutrální prior:
if total < min_samples_per_bucket:
    bucket.empirical_p = (bucket.raw_p_min + bucket.raw_p_max) / 2.0
    continue
```

---

### BUG-030 · Fake HTTP 451 check — `src/services/market_stream.py:148`

```python
# CHYBA — dead code, HTTPError je vyhozena PŘED dosažením tohoto řádku:
resp = urlopen(url)   # Pokud status=451 → HTTPError, nikdy nepokračuje
if resp.status == 451:   # ← NIKDY NEDOSAŽITELNÉ

# FIX — smazat řádky 148-150, geo-block je zpracován v except bloku
```

---

### BUG-031 · CoinGecko rate limit — `src/services/market_stream.py:265,290`

```python
# CHYBA — fallback na CoinGecko s intervalem 2s místo 30s:
# Komentář říká rate limit je 2 req/min = 30s interval
# Ale při přepnutí na CoinGecko se nastaví poll_interval = 2.0s → 429!

# FIX:
if consecutive_errors >= 5 and not use_cg:
    use_cg = True
    poll_interval = 30.0   # Respektovat rate limit
    consecutive_errors = 0
```

---

### BUG-032 · Unbounded memory — `bot2/learning_engine.py`

```python
# CHYBA — defaultdict roste bez omezení:
self.bandit = defaultdict(lambda: {"n": 0, "reward": 0})
self.strategy_blame = defaultdict(float)
self.regime_perf = defaultdict(list)   # ← list roste neomezeně!

# FIX pro regime_perf:
MAX_REGIME_HISTORY = 500
for regime in self.regime_perf:
    if len(self.regime_perf[regime]) > MAX_REGIME_HISTORY:
        self.regime_perf[regime] = self.regime_perf[regime][-MAX_REGIME_HISTORY:]
```

---

### BUG-033 · Neomezený _corr_memory — `src/services/risk_engine.py:107`

```python
# CHYBA — dict párů symbolů roste neomezeně:
_corr_memory: dict[tuple, deque] = {}
# Se 100 symboly = 4 950 párů, každý s deque → memory leak

# FIX — periodicky čistit páry bez aktivního obchodování:
def _cleanup_corr_memory():
    active = set(get_active_symbols())   # Páry s otevřenými pozicemi
    stale = [k for k in _corr_memory if k[0] not in active and k[1] not in active]
    for k in stale:
        del _corr_memory[k]
```

---

### BUG-034 · Diversity threshold neškáluje — `src/core/genetic_pool.py:147`

```python
# CHYBA — hardcoded threshold pro jakoukoli velikost populace:
if diversity < 5:   # Pro populaci 100 je 5 unikátních = 95% duplikace!

# FIX — relativní threshold:
min_diversity = max(3, len(self.population) // 4)
if diversity < min_diversity:
    # inject random strategies
```

---

## MEDIUM — daily_log_fix_prompt_bot

---

### BUG-035 · Parser ignoruje FORCED signály — `daily_log_fix_prompt_bot/src/.../parser.py`

```python
# CHYBA — FORCED signály se nezapočítávají do metrik:
SIGNAL_PATTERN = r"signal.*created|signal_created"
# "Generated FORCED signal SHORT" neodpovídá → 449 FORCED signálů je neviditelných

# FIX — rozšířit pattern:
SIGNAL_PATTERN = r"signal.*created|signal_created|FORCED signal"
# Přidat metriku:
self.metrics["forced_signals"] = 0
# V _parse_line:
if re.search(r"FORCED signal", line, re.IGNORECASE):
    self.metrics["forced_signals"] += 1
```

---

### BUG-036 · Issue detector nedetekuje Bootstrap deadlock

```python
# CHYBA — bot může běžet donekonečna v bootstrap módu (EV=0, WR=0):
# Žádný detektor na FAST_FAIL_SOFT_BOOTSTRAP > 100

# FIX — přidat do issue_detector.py:
def _detect_bootstrap_deadlock(self, raw_logs: str) -> None:
    count = raw_logs.count("FAST_FAIL_SOFT_BOOTSTRAP")
    if count > 100:
        self.issues.append(Issue(
            id="BOOTSTRAP_DEADLOCK",
            severity=Severity.CRITICAL,
            confidence=0.95,
            title=f"Bootstrap deadlock: {count}× FAST_FAIL_SOFT_BOOTSTRAP",
            evidence=[f"Bot uvízl v bootstrap módu, EV=0 a WR=0% pro všechny páry"],
            probable_root_cause="P&L se nezaznamenává správně → learning nikdy nedosáhne min_pair_n",
            recommended_fix="Zkontrolovat portfolio_manager.py P&L výpočet a Redis připojení",
            likely_files=["src/services/portfolio_manager.py", "src/services/learning_event.py"],
            validation_steps=["Ověřit ev != 0.0 v logu", "Ověřit Redis dostupnost"],
        ))
```

---

### BUG-037 · Žádná detekce data loss (Redis FLUSH_LM_REDIS_NONE)

```python
# FIX — přidat do issue_detector.py:
def _detect_data_loss(self, raw_logs: str) -> None:
    count = raw_logs.count("FLUSH_LM_REDIS_NONE")
    if count > 5:
        self.issues.append(Issue(
            id="REDIS_DATA_LOSS",
            severity=Severity.HIGH,
            confidence=1.0,
            title=f"Learning data loss: {count}× Redis FLUSH skipped",
            evidence=[f"{count} learning state saves dropped due to Redis=None"],
            probable_root_cause="Redis server nedostupný; learning state se ztrácí po restartu",
            recommended_fix="Nakonfigurovat Redis na Railway nebo přidat disk fallback",
            likely_files=["src/services/state_manager.py"],
            validation_steps=["Ověřit Redis URL v ENV", "Zkontrolovat Railway Redis addon"],
        ))
```

---

### BUG-038 · Žádná detekce latency SLA

```python
# FIX — přidat do issue_detector.py:
def _detect_latency_violations(self, raw_logs: str) -> None:
    import re
    matches = re.findall(r"LATENCY_WARN.*?(\d+\.\d+)ms", raw_logs)
    if matches:
        values = [float(m) for m in matches]
        max_ms = max(values)
        self.issues.append(Issue(
            id="LATENCY_SLA_BREACH",
            severity=Severity.HIGH if max_ms > 500 else Severity.MEDIUM,
            confidence=1.0,
            title=f"Latency SLA překročena: max {max_ms:.0f}ms (SLA=50ms)",
            evidence=[f"{len(matches)} porušení, max={max_ms:.0f}ms"],
            probable_root_cause="Synchronní I/O (Firebase/Redis) v on_price() hot path",
            recommended_fix="Přesunout I/O do asynchronní fronty mimo tick handler",
            likely_files=["src/services/trade_executor.py"],
            validation_steps=["Profilovat on_price() funkci", "Změřit Firebase latency"],
        ))
```

---

## Prioritizovaný plán oprav

### Fáze 1 — Opravit datový základ (bez toho nic nefunguje)

| # | Bug | Soubor | Dopad |
|---|-----|--------|-------|
| 1 | BUG-001 | `portfolio_manager.py:36` | Fake P&L → vše se učí ze šumu |
| 2 | BUG-025 | `state_manager.py` + Redis config | 81× data loss → restart = reset |
| 3 | BUG-008 | `learning_engine.py:158,180` | TypeError → feature learning crashuje |

### Fáze 2 — Opravit exit logiku (přímo ovlivňuje P&L)

| # | Bug | Soubor | Dopad |
|---|-----|--------|-------|
| 4 | BUG-002 | `smart_exit_guard.py:79` + `smart_exit_engine.py` | Smart exit nefunguje |
| 5 | BUG-003 | `trailing_stop.py:25,39` | Break-even nikdy nespustí |
| 6 | BUG-004 | `exit_optimizer.py:116` | TP tightening obráceně |
| 7 | BUG-005 | `exit_optimizer.py:95` | SHORT pozice špatně hodnoceny |

### Fáze 3 — Opravit indikátory (ovlivňuje kvalitu signálů)

| # | Bug | Soubor | Dopad |
|---|-----|--------|-------|
| 8 | BUG-006 | `strategy_executor.py:257` | ADX konstantní = trend blind |
| 9 | BUG-010 | `strategy_executor.py:216` | RSI nadhodnocený |
| 10 | BUG-009 | `strategy.py:54` | Drawdown výpočet špatný |
| 11 | BUG-007 | `adaptive_ev.py:140` | Severity obrácená |

### Fáze 4 — Opravit learning systém (pro učící se bot)

| # | Bug | Soubor | Dopad |
|---|-----|--------|-------|
| 12 | BUG-016 | `genetic_optimizer.py:150` | GA offspring = fitness 0 |
| 13 | BUG-018 | `genetic_pool.py:157` | Špatný weakest index |
| 14 | BUG-019 | `genetic_pool.py:165` | global_best init chybí |
| 15 | BUG-020 | `rl_agent.py:61` | Q-table memory leak |
| 16 | BUG-021 | `ml_model.py:90` | Overfitting |
| 17 | BUG-013 | `strategy_learner.py:69` | UCB1 formula špatná |

### Fáze 5 — Thread safety a stabilita

| # | Bug | Soubor | Dopad |
|---|-----|--------|-------|
| 18 | BUG-022 | `ofi_guard.py:38` | Race condition |
| 19 | BUG-023 | `pair_quarantine.py:37` | KeyError crash |
| 20 | BUG-024 | `auditor.py:20` | Race condition |
| 21 | BUG-017 | `event_bus_v2.py:26` | OOM memory leak |
| 22 | BUG-026 | `trade_executor.py` | 24× SLA překročení |

### Fáze 6 — daily_log_fix_prompt_bot

| # | Bug | Soubor |
|---|-----|--------|
| 23 | BUG-035 | `parser.py` — FORCED signály |
| 24 | BUG-036 | `issue_detector.py` — Bootstrap deadlock |
| 25 | BUG-037 | `issue_detector.py` — Redis data loss |
| 26 | BUG-038 | `issue_detector.py` — Latency SLA |

---

## Závěr

Bot v současném stavu **obchoduje, ale neučí se**. Kořenová příčina je `random.uniform(-1,1)` v portfolio_manager — vše ostatní je kaskádový efekt. Po opravě Fáze 1 bot poprvé začne sbírat reálná learning data. Fáze 2-3 zajistí, že signály a exits jsou korektní. Fáze 4 aktivuje genetický algoritmus a RL systém. Po všech opravách bude bot poprvé schopen skutečně se učit z obchodních výsledků.

---

*Report vygenerován: 2026-05-01 | Větev: `claude/code-analysis-bug-report-6PcEa`*

---

## Session 2 — Deep Analysis: "Bot Not Trading" (2026-05-01)

### Root Cause Chain

**BUG-045** was the root cause of "bot not trading". The full causal chain:

1. `print_status()` called every 10s in main loop → `load_history(limit=500)` on every call
2. Cache keyed at `HISTORY_LIMIT=100-200` → 500 > 200 → **always cache miss**
3. 500 reads × 8,640 calls/day = **4.3 million reads/day** → quota exhausted in ~11 minutes
4. 429 error → `_mark_quota_exhausted()` → `_FIREBASE_READ_DEGRADED = True`
5. `should_skip_noncritical_write()` had no time gate (BUG-042) → permanent True → metrics writes stop
6. `probe_quota_recovered()` detected recovery but never cleared flags (BUG-043) → degradation permanent
7. Safe mode active → `should_skip_entry()` returns True → **all new positions blocked**
8. On restart: cycle repeats (quota bomb fires again in 11 minutes)

### BUG-039 — `regime` NameError in SCRATCH_EXIT handler

**File:** `src/services/learning_event.py:347`  
**Symptom:** Every SCRATCH_EXIT silently fails; scratch forensics never recorded; scratch rate always 0.  
**Root cause:** `regime = signal.get("regime", "RANGING")` defined at line 360 but used at line 347 inside the SCRATCH_EXIT block → `NameError` swallowed by bare `except Exception`.  
**Fix:** Moved `regime` assignment before the SCRATCH_EXIT block.  
**Commit:** `c4ebdf0`

---

### BUG-040 — `_logging` not imported in `learning_event.py`

**File:** `src/services/learning_event.py`  
**Symptom:** `NameError: name '_logging' is not defined` in SCRATCH_EXIT except handler; exception swallowed silently.  
**Root cause:** `_logging` alias used in except clause but never imported at module level.  
**Fix:** Added `import logging as _logging` at top of file.  
**Commit:** `c4ebdf0`

---

### BUG-041 — `_slim_trade()` stores regime in strategy field

**File:** `src/services/firebase_client.py:412`  
**Symptom:** Strategy field in all Firestore trade documents always contains regime value ("RANGING"/"TRENDING"), not actual strategy name. Per-strategy performance analytics permanently corrupted.  
**Root cause:** `"strategy": trade.get("regime", "RANGING")` — copied regime key instead of strategy key.  
**Fix:** `"strategy": trade.get("strategy", trade.get("regime", "RANGING"))`.  
**Commit:** `c4ebdf0`

---

### BUG-042 — Write degradation has no time gate (permanent block after any 429)

**File:** `src/services/firebase_client.py:270`  
**Symptom:** After any 429 error, `should_skip_noncritical_write()` returns True forever; metrics writes stop permanently until bot restart. Bot's learning data stops accumulating.  
**Root cause:** `should_skip = _FIREBASE_WRITE_DEGRADED or writes_pct >= 95` — `_FIREBASE_WRITE_DEGRADED` never re-checked against `_FIREBASE_DEGRADED_UNTIL` expiry timestamp.  
**Fix:** `is_write_degraded = _FIREBASE_WRITE_DEGRADED and (now < _FIREBASE_DEGRADED_UNTIL)`.  
**Commit:** `c4ebdf0`

---

### BUG-043 — `probe_quota_recovered()` detects recovery but never clears flags

**File:** `src/services/firebase_client.py`  
**Symptom:** Firebase recovers from 429 → probe succeeds → `_FIREBASE_READ_DEGRADED` stays True → safe mode never clears → entries blocked permanently until restart.  
**Root cause:** Successful probe returned `True` without resetting the three degradation globals.  
**Fix:** Added on successful probe:
```python
_FIREBASE_READ_DEGRADED = False
_FIREBASE_WRITE_DEGRADED = False
_FIREBASE_DEGRADED_UNTIL = 0
```
**Commit:** `c4ebdf0`

---

### BUG-044 — `save_metrics_full()` reconciliation uses cache-miss limit

**File:** `src/services/firebase_client.py`  
**Symptom:** Every metrics save (every 300s) triggers a 500-doc Firestore read → up to 144k reads/day from reconciliation alone.  
**Root cause:** `load_history(limit=500)` hardcoded in reconciliation path; cache stores at HISTORY_LIMIT (100-200) → limit mismatch → always miss.  
**Fix:** Changed to `load_history(limit=HISTORY_LIMIT)`.  
**Commit:** `c4ebdf0`

---

### BUG-045 — `print_status()` quota storm: ROOT CAUSE of bot not trading

**File:** `bot2/main.py`  
**Symptom:** Firebase quota exhausted in ~11 minutes after startup → safe mode → all entries blocked → 0 trades.  
**Root cause:** `print_status()` called every 10s in main loop with `load_history(limit=500)` inside. Cache keyed at HISTORY_LIMIT=100-200 → always miss → 500 reads × 8,640/day = **4.3M reads/day**.  
**Fix:** Changed to `load_history(limit=HISTORY_LIMIT)`.  
**Commit:** `d540585`

---

### BUG-046 — `daily_budget_report()` uses hardcoded 500 in formula

**File:** `src/services/firebase_client.py`  
**Symptom:** Budget report printed "≤43,200 reads/day" while actual was 4.3 million. Operator had no visibility into quota exhaustion.  
**Root cause:** `r_hist = 500 * (86400 // HISTORY_TTL)` — used hardcoded 500 instead of HISTORY_LIMIT; didn't reflect actual cache miss rate.  
**Fix:** `r_hist = HISTORY_LIMIT * (86400 // ht)`; added ≤45k budget check with ✅/⚠️ indicators.  
**Commit:** `d540585`

---

### Cache TTL Extension (Quota Mitigation)

**File:** `src/services/firebase_client.py`  
**Commit:** `d540585`

| Parameter | PERF_MODE Before | PERF_MODE After | Normal Before | Normal After |
|-----------|-----------------|-----------------|---------------|--------------|
| `HISTORY_TTL` | 300s | 600s | 21600s | 43200s |
| `WEIGHTS_TTL` | 120s | 300s | 7200s | 14400s |
| `SIGNALS_TTL` | 600s | 1200s | 7200s | 14400s |

**Projected daily reads after all fixes:**
- Normal mode: ~200 reads/day ✅ (was ~4,300,000)
- PERF_MODE: ~18,900 reads/day ✅

---

### BUG-047 — `lm_economic_health()` calls `load_history(limit=500)` (quota storm #2)

**File:** `src/services/learning_monitor.py:864`  
**Symptom:** Every ECON health check (60s cache TTL) → 500-doc Firestore read → always cache miss (cache at 100-200) → additional ~720 reads/day, and amplified if cache TTL is lower.  
**Root cause:** `load_history(limit=500)` hardcoded inside `lm_economic_health()`.  
**Fix:** Changed to `load_history(limit=HISTORY_LIMIT)` with `HISTORY_LIMIT` imported from `firebase_client`.  
**Commit:** *(current)*

---

### BUG-048 — `net_pnl` shadow variable causes false ECON BAD on every restart

**File:** `src/services/learning_monitor.py:878,922`  
**Symptom:** Status = "BAD" immediately after restart even if Firestore has profitable trade history. Deadlock: ECON BAD blocks new trades, but trades are needed to populate in-memory METRICS and escape ECON BAD.  
**Root cause:**
- Line 878: `net_pnl = pf_meta["net_pnl"]` (canonical, correct)
- Line 922: `net_pnl = METRICS.get("net_pnl_total", 0.0)` → **overwrites** with in-memory value (resets to 0.0 on restart)
- Line 949: `profit_factor < 1.0 AND net_pnl <= 0` → 0.0 ≤ 0 → always True on cold start → status = "BAD"

**Fix:** Removed line 922; preserved canonical `net_pnl` from `pf_meta["net_pnl"]` throughout.  
**Commit:** *(current)*

---

### BUG-049 — `wins`/`losses` shadow variables corrupt `overall_wr` in ECON health

**File:** `src/services/learning_monitor.py:885-894`  
**Symptom:** `overall_wr` computed from in-memory METRICS (0 on restart) instead of canonical Firestore history. Trend calculation compares recent trades to wrong baseline → spurious "DECLINING" trend.  
**Root cause:**
- Lines 885-886: `wins = pf_meta["wins"]`, `losses = pf_meta["losses"]` (canonical)
- Lines 893-894: `wins = METRICS.get("wins", 0)`, `losses = METRICS.get("losses", 0)` → **overwrite** with in-memory (0 on restart)
- Line 894-896: `overall_wr = wins / decisive` → uses METRICS values (0/0 = 0.0)

**Fix:** Removed lines 893-894; `decisive` and `overall_wr` now computed from canonical wins/losses.  
**Commit:** *(current)*

---

### Remaining Blocking Conditions (by design)

After all 49 bugs fixed, these conditions can still block trading and are **intentional**:

| Condition | Gate | Threshold | How to clear |
|-----------|------|-----------|--------------|
| Cold start | Global trades | < 100 | Accumulate trades |
| Cold start | Min pair trades | Any pair < 15 | All pairs reach 15 trades |
| FAST_FAIL_HARD | WR + EV | WR < 5% AND EV ≤ 0 | Downgraded to SOFT during cold start |
| ECON BAD entry | ev | < 0.045 | Improve signal quality |
| ECON BAD entry | score | < 0.22 | Improve signal quality |
| ECON BAD entry | win_prob | < 0.54 | Improve signal quality |
| Firebase safe mode | Any | `is_db_degraded_safe_mode()` | Waits for Firebase recovery (60s check) |
| MAX_POSITIONS | Open positions | ≥ 3 | Wait for position to close |
| Tier 4 pair block | WR | n ≥ 30, WR < 10% | Improve pair win rate |

*Session 2 analysis completed: 2026-05-01 | Bugs BUG-039 to BUG-049*
