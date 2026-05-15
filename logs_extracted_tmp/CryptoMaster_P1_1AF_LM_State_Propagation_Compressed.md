# CryptoMaster P1.1AF — Fix Paper Closed Trade Learning State Propagation

## Context
P1.1AE odblokoval paper training entry/exit smyčku. Produkce už ukazuje:

```text
[PAPER_TRAIN_ENTRY] ...
[PAPER_EXIT] ... training_bucket=C_WEAK_EV_TRAIN
[LEARNING_UPDATE] ok=True source=paper_closed_trade ...
```

Ale Learning Monitor pořád reportuje:

```text
[!] LEARNING: health=0.0000 [BAD]
Total trades in LM: 0
```

Důkaz mismatch:

```text
07:07:23 [LEARNING_UPDATE] ok=True ... BTCUSDT ... outcome=LOSS
07:07:27 LEARNING: Total trades in LM: 0
```

Verdikt: entry/exit už funguje. Nový blocker je LM state propagation/counting. `LEARNING_UPDATE ok=True` neznamená, že se změnil stejný canonical `LearningMonitor` stav, ze kterého health/report počítá `Total trades in LM`.

---

## Hard Rules
- Neměnit live/real trading safety.
- Neměnit entry gates, cost_edge gate, TP/SL, timeout duration, sizing, RDE decision logic.
- Fixovat pouze learning ingest/state propagation, bucket mapping a diagnostiku.
- `ok=True` smí znamenat pouze skutečnou mutaci canonical LM state.

---

## Goal
Každý paper close musí projít touto cestou:

```text
PAPER_EXIT -> LEARNING_UPDATE ok=True -> LM canonical total +1 -> health report Total trades in LM +1
```

Po 4 paper exitech musí report ukázat:

```text
Total trades in LM: 4
```

---

## Files to Inspect
- `src/services/trade_executor.py`
- `src/services/learning_monitor.py`
- modul, který vlastní/instancuje `learning_monitor`
- modul, který tiskne:
  - `[!] LEARNING: health=...`
  - `Total trades in LM: 0`
  - `Hydrated pairs: ...`
- stores/fields:
  - `lm_pnl_hist`
  - `lm_count`
  - `closed_trades`
  - `canonical_closed_trades`
  - per `(symbol, regime)` stats
  - Firebase write/readback path, pokud existuje

---

## Root Cause to Prove
Najdi přesně, kde se loguje:

```text
[LEARNING_UPDATE] ok=True source=paper_closed_trade
```

a porovnej to s objektem/stavem, který čte health/report.

Očekávaná chyba je jedna z těchto:
1. paper close zapisuje do jiné instance `LearningMonitor`,
2. update vrací `ok=True`, ale nemutuje canonical counters,
3. update jde jen do Firebase/trades logu, zatímco health čte in-memory LM,
4. `paper_closed_trade` je ignorován kvůli field mappingu,
5. report počítá jen real/canonical closed trades a ignoruje paper training trades.

---

## Required Fix

### 1. Single source of truth
`source=paper_closed_trade` musí aktualizovat stejný canonical LM state, který používá health/report.

Musí se aktualizovat:
- global total trade count,
- per `(symbol, regime)` count,
- canonical PnL history,
- outcome history,
- bucket/training bucket,
- recent trades buffer, pokud existuje,
- calibration input, pokud je používán pro health.

Nesmí být nutný Firebase readback, aby se in-memory health změnil.

### 2. Make `ok=True` real
Pokud state není skutečně změněn, update nesmí vrátit/logovat `ok=True`.

Použij:

```text
[LEARNING_UPDATE] ok=False source=paper_closed_trade reason=state_not_mutated ...
```

když canonical count/pnl history zůstane stejný.

### 3. Add post-update canonical state log
Po každém paper learning update loguj:

```text
[LM_STATE_AFTER_UPDATE] source=paper_closed_trade symbol=BTCUSDT regime=BULL_TREND bucket=C_WEAK_EV_TRAIN total_trades=1 pair_n=1 pnl_hist_len=1 updated=True
```

Pokud `ok=True`, ale total se nezměnil:

```text
[LM_UPDATE_MISMATCH] ok=True but canonical_total_unchanged before=0 after=0 symbol=BTCUSDT regime=BULL_TREND bucket=C_WEAK_EV_TRAIN
```

### 4. Fix bucket mapping on paper exit
Aktuálně produkce ukazuje:

```text
[PAPER_EXIT] ... bucket=None training_bucket=C_WEAK_EV_TRAIN
```

Oprav na:

```text
[PAPER_EXIT] ... bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
```

Kompatibilita: když staré pozice mají jen `training_bucket`, nastav `bucket = training_bucket`.

### 5. Fix SIGNAL_RAW score log only
Stále se loguje:

```text
[SIGNAL_RAW] ... score=0.000
```

i když canonical decision má:

```text
score_raw=0.1850
```

Oprav pouze logging field mapping. Neměnit rozhodovací logiku.

Expected:

```text
[SIGNAL_RAW] symbol=BTCUSDT side=BUY regime=BULL_TREND ev=0.0348 p=0.50 score=0.185
```

---

## Tests Required
Přidej regresní testy:

1. `paper_closed_trade` incrementuje canonical LM total.
2. `paper_closed_trade` incrementuje per `(symbol, regime)` count.
3. `LEARNING_UPDATE ok=True` nastane jen při reálné state mutaci.
4. `LM_UPDATE_MISMATCH` se loguje, pokud mock update nemutuje state.
5. health/report čte stejný state, do kterého paper update zapisuje.
6. `bucket` se doplní z `training_bucket`, když je missing/None.
7. `SIGNAL_RAW` loguje canonical score, ne 0.000.
8. live/real behavior unchanged.

Spusť full test suite.

---

## Acceptance Criteria
Po deploy musí logy ukázat:

```text
[PAPER_EXIT] ... bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
[LEARNING_UPDATE] ok=True source=paper_closed_trade ...
[LM_STATE_AFTER_UPDATE] ... total_trades=1 pair_n=1 updated=True
```

V dalším health reportu:

```text
Total trades in LM: 1
```

Po 4 paper exitech:

```text
Total trades in LM: 4
```

Nesmí se objevit:

```text
[LM_UPDATE_MISMATCH]
```

---

## Production Verification Commands

```bash
sudo journalctl -u cryptomaster --since "20 min ago" --no-pager \
| grep -E "PAPER_EXIT|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|LM_UPDATE_MISMATCH|Total trades in LM"
```

```bash
sudo journalctl -u cryptomaster --since "20 min ago" --no-pager | grep -c "PAPER_EXIT"
sudo journalctl -u cryptomaster --since "20 min ago" --no-pager | grep -c "LEARNING_UPDATE.*ok=True"
sudo journalctl -u cryptomaster --since "20 min ago" --no-pager | grep -c "LM_STATE_AFTER_UPDATE"
```

Expected after first close:

```text
PAPER_EXIT count >= 1
LEARNING_UPDATE ok=True count >= 1
LM_STATE_AFTER_UPDATE count >= 1
Total trades in LM >= 1
```

---

## Final Commit Message
```text
P1.1AF: Fix paper closed trade propagation into canonical LearningMonitor state
```
