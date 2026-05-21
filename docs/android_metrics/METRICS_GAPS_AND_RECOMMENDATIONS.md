# Metriky - Mezery a Doporučení

**Verze:** 1.0  
**Cíl:** Identifikovat chybějící metriky, které by zlepšily Android app  
**Status:** Doporučení (ne implementace)  

---

## 1. Kanonický Dashboard Snapshot

### Gap: Canonical dashboard snapshot missing

**Současný problém:**
- Android musí čist 6-10 jednotlivých Firestore dokumentů pro vykreslení Dashboard tabu
- Čte `/bot_config/health`, `/trading_summary/live_real`, `/trading_summary/paper_train`, `/open_positions`, `/market_health/feed_status`, `/learning_state/canonical`, `/quota_metrics/status`
- Při každé refresh = 7 reads, i když se žádné údaje nezměnily

**Dopad na Android app:**
- Vyšší latence (paralelně čít 7 dokumentů = čekat na nejpomalejší)
- Vyšší kvóta spot (7 reads/10s = 40k+ reads/den jen na Dashboard)
- Horší offline experience (musí cachovat 7 zdrojů)

**Současný workaround:**
- Cachovat lokálně s TTL 10-30s
- Paralelní reads s Promise.all()
- Fallback na stálá data, pokud jedno čtení selže

**Doporučený zdroj:**
Vytvořit jeden kanonický dokument `/dashboard_snapshot`:

```json
{
  "timestamp": 1716129600000,
  "bot_health": {
    "status": "running",
    "uptime_seconds": 45000,
    "last_heartbeat_ts": 1716129598000,
    "git_head": "abc1234",
    "error_count_recent": 0
  },
  "trading": {
    "live_real": {
      "total_trades": 127,
      "closed_trades": 12,
      "open_count": 3,
      "winrate_pct": 55.2,
      "net_pnl_pct": 12.34,
      "max_drawdown_pct": 8.5
    },
    "paper_train": {
      "total_trades": 185,
      "winrate_pct": 66.5,
      "entry_count": 48
    }
  },
  "market": {
    "feed_status": "connected",
    "last_price_tick_ts": 1716129598500,
    "active_symbols": 5,
    "avg_spread_pct": 0.015
  },
  "learning": {
    "lm_total_trades": 184,
    "health_pct": 78,
    "cold_start_active": false
  },
  "quota": {
    "read_count_day": 12456,
    "read_quota_pct": 75,
    "state": "normal"
  }
}
```

**Doporučená budoucí bot-side změna:**
- Bot poté se změní `/dashboard_snapshot` jedním dokumentem
- Toto snižuje Android čtení z 7 na 1 na 10s
- Úspora: 40k reads/den
- Latence: 10x lepší (1 read místo 7 paralelních)

**Risk:**
- Vyžaduje bot-side změnu (malá - agregace do jednoho doc)
- Zvýší bot-side writes o 0.5k/den (zanedbatelné)

**Priority:** P1 (vysoký dopad na Android)

**Implementovat nyní?** NE - není kritické, ale přidělte si to na plán Phase 2.

---

## 2. Learning Health Persistence

### Gap: Learning health not cleanly persisted

**Současný problém:**
- `lm_health()` je funkce v `learning_monitor.py` - počítá se v paměti
- Android musí se spoléhat na `/learning_state/canonical` obsahující jen surová data
- Uživatel neví přesně, jak "zdravé" je učení bez čtení zdrojového kódu

**Dopad na Android app:**
- Není jasné "learning health" číslo k zobrazení na Dashboard
- App musí si sám spočítat nebo odhadnout
- Nemůže vidět komponenty zdraví (sample size, stability, atd)

**Současný workaround:**
- Android čte `lm_total_trades` a odhaduje:
  - `health_pct = min(100, (lm_total_trades / 100) * 100)` (zjednodušuje se)
  - To není přesné vs. bot's `lm_health()`

**Doporučený zdroj:**
Bot by měl psát zdravotní metriky do `/learning_state/health`:

```json
{
  "timestamp": 1716129600000,
  "health_pct": 78,
  "components": {
    "sample_sufficiency": 85,        // % vzorků (100 = dostatek)
    "stability": 72,                 // Variance je nízká?
    "regime_coverage": 92,           // Máme data pro všechny režimy?
    "recent_quality": 68,            // Poslední trades byly kvalitní?
    "convergence": 81                // Jsou výsledky stabilní?
  },
  "cold_start_active": false,
  "warmup_progress_pct": 95,         // % k vyjití z cold-start
  "recommended_action": "monitor",   // "none" / "monitor" / "pause_and_retrain"
  "notes": "Health je dobrá. 95% z cold-startu."
}
```

**Doporučená budoucí bot-side změna:**
- Po LM update, bot vypočítá `lm_health()` a zapíše do `/learning_state/health`
- Jedna nová write/10min (zanedbatelný dopad)
- Android má jasné "health %" na zobrazení

**Risk:**
- Bot-side write (malý - 1 doc/10min)
- Vyžaduje kód v `learning_monitor.py` pro zápis

**Priority:** P1

**Implementovat nyní?** NE - nice-to-have, ale doporučit na Phase 2.

---

## 3. Signal Pipeline Counters Availability

### Gap: Signal statistics only in logs

**Současný problém:**
- Počty raw_signals, accepted, rejected jsou viditelné jen v journalctl logu
- Nejsou persisted v Firestore
- Android musí parsovat systemd logs (nepohodlné, bezpečnostní riziko)
- Nelze implementovat signal statistics tab bez logu access

**Dopad na Android app:**
- Signals tab nelze implementovat bez SSH/shell access
- Android musí mít přístup na /var/log/journal (security hole)
- Nelze vidět historii signálů bez ručního logu parsování

**Současný workaround:**
- Android se připojí na bot přes SSH → čte journalctl
- NEBO bot vystavuje gRPC endpoint s log stream
- NEBO bot periodicky zapíše shrnutí do Firestore

**Doporučený zdroj:**
Bot by měl psát signal summary do `/signal_summary/today`:

```json
{
  "timestamp": 1716129600000,
  "window_minutes": 60,
  "total_signals": 247,
  "accepted_signals": 12,
  "rejected_signals": 235,
  "reject_rate_pct": 95.1,
  "last_signal_ts": 1716129599000,
  "last_accept_ts": 1716129550000,
  "reject_breakdown": {
    "REJECT_NEGATIVE_EV": 145,
    "REJECT_SCORE_GATE": 67,
    "REJECT_RISK_BLOCK": 18,
    "REJECT_OTHER": 5
  }
}
```

Hod by měl také udržovat `/signal_stream/recent_signals` jako poslední N signálů (cyklování):

```json
{
  "signals": [
    {
      "timestamp": 1716129599000,
      "symbol": "BTCUSDT",
      "side": "BUY",
      "decision": "TAKE",
      "ev": 0.0024,
      "score": 0.78,
      "reason": "accepted"
    },
    {
      "timestamp": 1716129598000,
      "symbol": "ETHUSDT",
      "side": "BUY",
      "decision": "REJECT",
      "ev": -0.0012,
      "score": 0.45,
      "reason": "REJECT_NEGATIVE_EV"
    }
  ]
}
```

**Doporučená budoucí bot-side změna:**
- Vybrat čas z RDE decision logs, agregovat do `/signal_summary/today` každých 10 minut
- Zapsat poslední 50 signálů do `/signal_stream/recent_signals` v reálném čase
- 2 writes/10min (malý dopad)

**Risk:**
- Bot-side write (malý)
- Dodávka historických signálů (jenom dnes, ne historické data)

**Priority:** P1 (vysoký dopad na Android - umožňuje Signals tab)

**Implementovat nyní?** NE - doporučit Phase 2.

---

## 4. Attribution History Storage

### Gap: Recent attribution only in journal logs

**Současný problém:**
- Attribution analýza (fee-dominated, wrong-direction, timeout, atd) je počítana v logu
- Není persisted v Firestore
- Android nemůže zobrazit "why did we lose?" bez logu parsování

**Dopad na Android app:**
- Trade detail view nemůže zobrazit attribution analysis
- Uživatel neví, proč trades failed (fee? volatility? špatný signal?)
- Learning diagnostics tab nemůže zobrazit dominant attribution

**Současný workaround:**
- Android si odvodí z trade fields (entry/exit/fee) lokálně
- Nebo přistupuje k logu (nepohodlné)

**Doporučený zdroj:**
Bot by měl zapsat attribution do každého trade dokumentu:

```json
{
  "trade_id": "uuid-123",
  "... existing fields ...",
  "attribution": {
    "category": "fee_dominated_move",  // enum
    "fee_drag_pct": 0.18,
    "gross_move_pct": 0.42,
    "net_pnl_pct": 0.24,
    "explanation": "Ztráta byla dominantně způsobena fee dragem (0.18%), brutto gain byl 0.42%."
  }
}
```

A agregovaně v `/paper_training/attribution_summary`:

```json
{
  "timestamp": 1716129600000,
  "window_hours": 24,
  "total_trades_attributed": 47,
  "breakdown": {
    "fee_dominated_move": { "count": 19, "pct": 40 },
    "wrong_direction": { "count": 16, "pct": 34 },
    "tp_too_far_for_mfe": { "count": 8, "pct": 17 },
    "timeout_near_tp": { "count": 3, "pct": 6 },
    "normal_win": { "count": 1, "pct": 2 }
  },
  "dominant_attribution": "fee_dominated_move",
  "dominant_pct": 40,
  "sample_size_sufficient": true
}
```

**Doporučená budoucí bot-side změna:**
- V `paper_trade_executor.py`, na exit: počítá attribution a zapísá do trade doc
- Agreguje do `/paper_training/attribution_summary` každých 10 minut
- 1 write per trade + 1 aggregate write/10min

**Risk:**
- Bot-side write (malý - per trade + agregace)
- Vyžaduje attribution logic v bot (už existuje v logu, jen zápis do Firestore)

**Priority:** P2 (schop learning insights)

**Implementovat nyní?** NE - nice-to-have Phase 2.

---

## 5. Firestore vs Log Source Mismatch

### Gap: Canonical state divergence

**Současný problém:**
- Bot může mít v paměti `lm_count = 184` trades
- Firestore má `/trades` collection s 150 dokumenty
- Android čte 150 z Firestore, ale bot vykázal 184
- State mismatch není viditelný v Android app

**Dopad na Android app:**
- Zobrazí se `/trades` count z Firestore (150) místo canonical LM count (184)
- Uživatel vidí nekonzistentní metriky
- Nejasné, zda je bot broken nebo jen Firebase zaostává

**Současný workaround:**
- Android preferuje `lm_total_trades` z `/learning_state/canonical` před Firestore count
- Ale uživatel nevidí, že je mismatch

**Doporučený zdroj:**
Bot by měl monitorovat a logovat mismatches:

```
[LM_FIRESTORE_MISMATCH] canonical_lm=184 firestore_trades=150 gap=34 reason=async_writes
```

Android by měl sledovat varovací log a zobrazit:

```
⚠️ Zpožděný zápis: 34 trades čeká na zápis do Firestore
   (Norm.) Databáze je zaostávající za bot paměť.
   Obnovit v 60s.
```

**Doporučená budoucí bot-side změna:**
- Po každé LM update, zkontrolovat `count(Firestore trades)` vs `lm_total_trades`
- Pokud gap > 5, log warning
- Zlepšit async write pipeline v firebase_client.py

**Risk:**
- Bot-side monitoring (low cost)
- Nelze garantovat synchronizaci (je to inherentní async design)

**Priority:** P2 (debug help)

**Implementovat nyní?** Částečně - bot by měl logovat, Android by měl monitoring; Phase 2.

---

## 6. Per-Symbol/Regime Learning Summary

### Gap: Learning breakdown not easily accessible

**Současný problém:**
- Android musí si sám rozdělit `/learning_state/canonical` po symbolech/režimech
- `lm_count_by_symbol_regime` je raw dict bez agregovaných metriken
- Nemůže vidět "Learning for BTCUSDT:TRENDING je excellent, ale ETHUSDT:CHOPPY je slabý"

**Dopad na Android app:**
- Learning tab nemůže snadno zobrazit "health per symbol"
- Uživatel nevidí, pro které symboly je model dobrý / špatný
- Nemůže diagnostikovat "proč selhává na ETHUSDT?"

**Současný workaround:**
- Android si sám počítá per-symbol health z raw dat
- Hádá, která data jsou "good enough" pro tuning

**Doporučený zdroj:**
Bot by měl psát `/learning_state/per_symbol`:

```json
{
  "BTCUSDT": {
    "regimes": {
      "TRENDING": {
        "trade_count": 32,
        "winrate_pct": 58,
        "avg_pnl_pct": 0.28,
        "sample_quality": 92,
        "confidence": "high",
        "ev_estimate": 0.15,
        "ready_for_tuning": true
      },
      "CHOPPY": {
        "trade_count": 20,
        "winrate_pct": 52,
        "avg_pnl_pct": 0.14,
        "sample_quality": 64,
        "confidence": "medium",
        "ev_estimate": 0.05,
        "ready_for_tuning": false
      }
    },
    "summary": {
      "total_trades": 52,
      "overall_winrate": 56,
      "health": 85,
      "recommendation": "Monitor. CHOPPY regime needs more samples."
    }
  },
  "ETHUSDT": { ... }
}
```

**Doporučená budoucí bot-side změna:**
- Bot bereits počítá toto v `lm_health()` a `lm_convergence()` - jenom zapíše do Firestore
- 1 write per LM update (5-10 minut)

**Risk:**
- Bot-side write (low cost)

**Priority:** P1 (vysoký dopad na Learning tab)

**Implementovat nyní?** NE - Phase 2.

---

## 7. Open Position State Only in Local JSON

### Gap: paper_open_positions.json not in Firestore

**Současný problém:**
- Open positions bot jsou v `/data/paper_open_positions.json` lokálně
- Android nemůže přistoupit bez SSH/SCP
- Pokud bot restartuje, stav se ztratí
- Nelze implementovat Android monitoring otevřených paper pozic

**Dopad na Android app:**
- Paper training tab nemůže zobrazit "current paper positions"
- Uživatel neví, jaké paper trades jsou otevřené
- Nemohlby vidět paper PnL v reálném čase

**Současný workaround:**
- Bot by měl synchronizovat `/paper_open_positions.json` s Firestore
- Android čte `/open_positions` (live) a `/paper_open_positions` (papír)

**Doporučený zdroj:**
Bot by měl zrcadlit lokální JSON do `/paper_open_positions` collection v Firestore:

```firestore path
/paper_open_positions/{trade_id}
- trade_id
- symbol
- side
- entry_price
- current_price (aktualizuje se každých 5 minut)
- entry_ts
- pnl_pct
- tp/sl
- bucket
- ... (shodné fields s live open_positions)
```

**Doporučená budoucí bot-side změna:**
- V `paper_trade_executor.py`, po změně paper position: sync do Firestore
- 1-2 writes per trade opening/closing

**Risk:**
- Bot-side write (low cost)
- Duplikace stavu (JSON + Firestore)

**Priority:** P1 (umožňuje paper training monitoring)

**Implementovat nyní?** NE - Phase 2.

---

## Summary: Gaps vs Priority

| Gap | Priority | Effort | Dopad | Phase |
|-----|----------|--------|-------|-------|
| Canonical dashboard snapshot | P1 | Low | 40k reads/den savings | Phase 2 |
| Learning health persistence | P1 | Low | Health % visibility | Phase 2 |
| Signal pipeline counters | P1 | Medium | Signals tab possible | Phase 2 |
| Attribution storage | P2 | Medium | Learning insights | Phase 2 |
| Firestore/LM mismatch monitoring | P2 | Low | Debug help | Phase 2 |
| Per-symbol learning summary | P1 | Low | Learning breakdown | Phase 2 |
| Paper positions in Firestore | P1 | Low | Paper training monitoring | Phase 2 |

---

## Phase 2 Implementation Checklist

```
[ ] Kanondynamic Dashboard Snapshot
  [ ] Design /dashboard_snapshot schema
  [ ] Bot writes aggregated snapshot every 10s
  [ ] Android reads 1 doc instead of 7
  [ ] Verify 40k reads/day savings
  
[ ] Learning Health Persistence
  [ ] Bot komputes lm_health() components
  [ ] Bot writes to /learning_state/health
  [ ] Android displays health_pct + components
  [ ] Test on 100+ trades
  
[ ] Signal Pipeline Counters
  [ ] Bot aggregates signal counts every 10min
  [ ] Bot writes to /signal_summary/today
  [ ] Bot writes last 50 signals to /signal_stream
  [ ] Android implements Signals tab
  [ ] Test signal stream freshness
  
[ ] Attribution Storage
  [ ] Bot calculates attribution on trade close
  [ ] Bot writes to trade doc + aggregate doc
  [ ] Android displays attribution in trade detail
  [ ] Verify attribution accuracy
  
[ ] Per-Symbol Learning
  [ ] Bot computes per-symbol/regime metrics
  [ ] Bot writes to /learning_state/per_symbol
  [ ] Android implements symbol breakdown view
  [ ] Test confidence indicators
  
[ ] Paper Positions in Firestore
  [ ] Bot syncs /data/paper_open_positions.json to Firestore
  [ ] Android reads /paper_open_positions collection
  [ ] Test paper position refresh rate
  [ ] Verify offline cache works
```

---

**Konec Gaps & Recommendations V1.0**
