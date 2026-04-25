# V10.15 Mammon — Architecture Audit (Phase B)

**Date**: 2026-04-25  
**Scope**: Critical path for decision → execution → learning lifecycle  
**Depth**: Contracts, gates, persistence, fragility classification

---

## 1. Entrypoints & Runtime Flow

### Primary Entrypoints

| Entrypoint | Purpose | State | Notes |
|---|---|---|---|
| `bot2/main.py` | Bot runtime + dashboard loop | **STABLE** | `print_status()` every N cycles |
| `src/services/market_stream.py` | Binance WebSocket → event_bus | **STABLE** | Pub-sub via `event_bus.publish()` |
| `src/services/signal_generator.py` | Features + signal generation | **STABLE** | Subscribed to market tick |
| `src/services/realtime_decision_engine.py` | EV + gate evaluation | **STABLE** | Subscribed to signals |
| `src/services/trade_executor.py` | Order lifecycle + exits | **STABLE** | Subscribed to decisions |
| `src/services/learning_event.py` | Outcome tracking + metrics | **STABLE** | Bootstrap from Firebase |
| `src/services/firebase_client.py` | Firestore I/O + quota | **STABLE** | Quota system (V10.14) in place |
| `start.py` / `start_fresh.py` | Init + hydration | **STABLE** | Async bootstrap |

### Canonical Flow (Critical Path)

```
1. market_stream (WebSocket)
   ↓ event_bus.publish("market_tick", {symbol, price, time, ...})
   ↓
2. signal_generator (subscribed)
   ↓ computes: regime, ATR, MFE/MAE, confidence
   ↓ event_bus.publish("signal_created", {sym, side, conf, regime, ...})
   ↓
3. realtime_decision_engine (subscribed)
   ↓ computes: EV, score, gates (spread, freq, dd, loss_streak)
   ↓ decision = APPROVE | REJECT | BLOCK
   ↓ event_bus.publish("decision_made", {sym, decision, ev, score, ...})
   ↓
4. trade_executor (subscribed)
   ↓ if APPROVE: open position + set TP/SL/trailing/timeout
   ↓ monitors exit condition (TP, SL, trail, timeout, regime, stagnation)
   ↓ on close: compute profit, save to Firestore
   ↓ event_bus.publish("trade_closed", {sym, profit, close_reason, ...})
   ↓
5. learning_event (subscribed)
   ↓ update METRICS (trades, wins, losses, streaks, profit, etc.)
   ↓ store trade in _sym_stats, _regime_stats, _recent_results
   ↓ calibrator.update(outcome, prob)
   ↓
6. firebase_client (async)
   ↓ save trade + metrics to Firestore
   ↓ check quota, batch writes
   ↓
7. bot2/main.py (dashboard)
   ↓ print_status() → read METRICS + Firebase history
   ↓ render KPIs (WR, PnL, trend, calibration)
```

---

## 2. Signal Contract (signal_generator → RDE)

**Published as**: `"signal_created"` event  
**Dict schema**:

```python
{
    "symbol": str,           # "BTCUSDT"
    "side": str,             # "BUY" | "SELL"
    "confidence": float,     # 0.0–1.0 (model belief)
    "regime": str,           # "BULL_TREND" | "BEAR_TREND" | ...
    "atr": float,            # volatility (ATR)
    "mfe": float,            # max favorable excursion (%)
    "mae": float,            # max adverse excursion (%)
    "timestamp": float,      # unix time
    # optional:
    "features": dict,        # EMA, MACD, BB, RSI, ADX values (for audit)
    "conviction": float,     # internal signal strength
}
```

**Safety**: RDE must handle missing optional fields.

---

## 3. Decision Contract (RDE → Executor)

**Published as**: `"decision_made"` event  
**Decision dict schema**:

```python
{
    "symbol": str,
    "decision": str,         # "APPROVE" | "REJECT" | "BLOCK"
    "side": str,             # "BUY" | "SELL"
    "ev": float,             # raw EV
    "ev_after_coh": float,   # EV after coherence gate
    "ev_final": float,       # EV after threshold + auditor
    "score": float,          # composite gate health (0–1)
    "score_threshold": float, # current adaptive threshold
    "prob": float,           # win probability (calibrated)
    "rr": float,             # risk-reward ratio
    "regime": str,
    "confidence": float,     # from signal
    "gates": {
        "ev": bool,          # EV > threshold
        "spread": bool,      # bid-ask spread OK
        "frequency": bool,   # not overtrading
        "loss_streak": bool, # not in drawdown halt
        "regime_aligned": bool, # optional
        "coherence": bool,   # regime/EV alignment
    },
    "reject_reason": str,    # if REJECT: "EV-TOO-LOW" | "SPREAD-WIDE" | ...
    "timestamp": float,
}
```

---

## 4. Trade/Position Contract (Executor state)

**In-memory position object**:

```python
{
    "symbol": str,
    "side": str,             # "BUY" | "SELL"
    "entry_price": float,
    "size": float,
    "tp_price": float,       # take-profit level
    "sl_price": float,       # stop-loss level
    "tp_move": float,        # % above entry
    "sl_move": float,        # % below entry
    "is_trailing": bool,     # trailing stop active
    "trail_price": float,    # current trail reference
    "regime": str,           # regime at entry
    "confidence": float,     # from signal
    "opened_at": float,      # timestamp
    "mfe": float,            # running MFE
    "mae": float,            # running MAE
    "action": str,           # "BUY" | "SELL"
    "signal": dict,          # original signal dict (for audit)
}
```

**Closed trade (saved to Firestore)**:

```python
{
    "symbol": str,
    "side": str,
    "entry_price": float,
    "exit_price": float,
    "size": float,
    "regime": str,
    "confidence": float,
    "close_reason": str,     # "TP" | "SL" | "TRAIL_SL" | "TIMEOUT" | "SCRATCH_EXIT" | ...
    "timestamp": float,
    "closed_at": float,
    "gross_pnl": float,      # before fees
    "fee": float,
    "slippage": float,
    "net_pnl": float,        # gross - fees - slippage
    "profit": float,         # alias for net_pnl
    "result": str,           # "WIN" | "LOSS" | "FLAT" (canonical classification)
    "mfe": float,
    "mae": float,
    "ev": float,             # EV at decision time
    "ev_final": float,       # final EV (with auditor)
    "score": float,
    "rr": float,
    # Optional:
    "evaluation": {
        "profit": float,     # legacy nested format
    },
}
```

---

## 5. Gate Map (RDE Evaluation Order)

| Gate | Checks | Source | Failure Behavior |
|---|---|---|---|
| **EV threshold** | `ev_final > adaptive_threshold` | RDE calibration | REJECT if EV-TOO-LOW |
| **Coherence** | regime/side alignment + spread + signal strength | RDE | REJECT if misaligned |
| **Spread** | bid-ask spread ≤ threshold | market_stream | REJECT if SPREAD-WIDE |
| **Frequency** | trades in last 15min < 6 | learning_event | REJECT if OVERTRADING |
| **Drawdown halt** | drawdown < 40% of peak | learning_event | REJECT if DD-TOO-DEEP |
| **Loss streak** | consecutive losses < 5 | learning_event | REJECT if LOSS-STREAK |
| **Auditor factor** | sz_mult = auditor.get_position_size_mult() ≥ 0.7 | bot2/auditor.py | reduce size if < 0.7 |
| **Micro-trade mode** | if stalled: enter micro-trade adaptive mode | adaptive_recovery.py | change EV threshold dynamically |

**Gate order matters**: Coherence first (catches regime misalignment), then EV, then frequency.

---

## 6. Learning Map (Outcome → Metrics Update)

**Source of truth**: `learning_event.METRICS` (in-memory + periodically synced to Firestore)

**On trade close**:

```
1. Fetch closed trade from executor
2. Classify outcome:
   - if result="WIN" or (result="LOSS"): decisive
   - if close_reason in NEUTRAL_REASONS and abs(pnl) < 0.001: neutral (timeout)
   → outcome = WIN | LOSS | FLAT
3. Update METRICS:
   m["trades"] += 1
   m["wins"] += (outcome == "WIN")
   m["losses"] += (outcome == "LOSS")
   m["profit"] += pnl
   m["win_streak"] / m["loss_streak"] (streak tracking)
4. Update per-symbol + per-regime (session ring buffers)
5. Update _recent_results deque (last 50 outcomes)
6. calibrator.update(outcome, prob) — online WR tracker
7. Async save to Firebase (save_metrics_full)
```

**Canonical metric source** (V10.13x.1):
- `MetricsEngine.compute_canonical_trade_stats(closed_trades)` — reads Firebase history
- Returns: `{trades_total, wins, losses, flats, winrate, net_pnl, per_symbol, per_regime, ...}`
- Used by dashboard (print_status)

---

## 7. Persistence Map (Firebase I/O)

### Collections

| Collection | Purpose | Write frequency | Read frequency | Quota |
|---|---|---|---|---|
| `trades` | closed trades (full detail) | 1 per trade close | ~100 limit per render | 1 read per load_history |
| `trades_compressed` | archived old trades | batch | rare | archive |
| `metrics` | running KPIs (latest doc) | every trade + periodic | every status render | 1 read per render |
| `system/stats` | atomic counters (total trades, wins, losses) | every trade | bootstrap only | 1 read on startup |
| `model_state` | calibrator state (prob buckets) | after calibrator.update | bootstrap | 1 write per trade |
| `signals` | historical signal records | optional (low priority) | optional | optional |
| `config` | strategy thresholds | static | on startup | 1 read on startup |
| `portfolio` | open positions state | on position open/close | rebuild from executor | 1 write per trade |

### Quota System (V10.14)

```
Daily budget:
  - Reads: 50,000/day
  - Writes: 20,000/day

Per operation (typical):
  - load_history(limit=100): 1 read
  - load_stats(): 1 read
  - save_metrics_full + trade: 3 writes
  - save_batch(trades): 1 write per trade

Typical usage:
  - Startup bootstrap: ~10 reads
  - Per trade cycle: ~5 reads + ~3 writes
  - Per render: ~3 reads
  - Estimated: 1-3% of daily budget

Pre-flight checks:
  - _can_read(est_count) checks if operation allowed
  - _can_write(est_count) blocks if quota approaching
  - On 429 error: mark quota exhausted, use stale cache

Graceful degradation:
  - If quota exhausted: use cached METRICS
  - If Firebase unavailable: use in-session METRICS
  - No loss of trades (executor saves locally first)
```

---

## 8. Fragility Map (Risks & Contradictions)

### Contradiction: Per-Symbol Stats Sources

**Risk**: Dashboard shows different per-symbol WR depending on source.

```
Source A: session _sym_stats (updated on each close during session)
Source B: canonical per_symbol (from Firebase closed trades history)

Current fix (V10.13x.1):
  - Dashboard uses canonical ONLY (Source B)
  - Session _sym_stats is maintained but not displayed
  - Risk reduced to zero (unified source)

Remaining risk: if Firebase returns empty (quota/connection issue),
  canonical is empty → all per-symbol counts = 0 → section shows "N/A"
  But session _sym_stats might have data.
  
  Mitigation: not implemented yet; dashboard accepts this (shows N/A truthfully)
```

### Duplication: Decision State

**Risk**: Decision context exists in 3 places:
1. RDE's `_last_decision` (last decision made)
2. Executor's in-memory position (current entry state)
3. Firebase `portfolio` doc (async persistence)

**Current practice**: Executor is authoritative; Firebase is backup.  
**No risk** if executor state is always ahead of Firebase saves.  
**Risk if**: Firebase save fails and position is not recovered on restart.

**Mitigation**: Executor saves position to Redis immediately; Firebase is async.

### Side Effect: Calibrator State

**Risk**: Calibrator is updated during learning_event, but if Firebase write fails, 
state can diverge on restart.

```
Current: calibrator.update() is called from learning_event → state updated
         save_model_state() is async → might not persist
         
On restart: bootstrap_from_history() calls learning_event which calls calibrator.update()
           so recalibrated from history
           
Mitigation: acceptable (recalibration on restart costs 1-2 sec)
```

### Fragility: Event Bus At-Least-Once

**Risk**: Event bus uses deque(maxlen=2000) for dedup by `_event_id`.
- If event is not tagged with `_event_id`, it's never deduplicated.
- If processing is slow and 2000 events pass, old IDs are evicted.
- On Redis reconnect, same event might be re-delivered.

**Current**: Handlers must be idempotent.  
**Status**: Learning event and executor handle double-delivery gracefully (upsert pattern).  
**Risk if**: New handler doesn't check `_event_id` → potential double-execute.

---

## 9. Classification (Task Priority & Safety)

### SAFE_NOW (Stable, No Change Needed)

- `market_stream.py` — ingestion layer
- `signal_generator.py` — feature extraction
- `learning_event.py` — metrics state (already patched in V10.13x.1)
- `firebase_client.py` — quota system (V10.14 verified)
- `metrics_engine.py` — canonical stats (V10.13x.1 deployed)
- `bot2/main.py` — dashboard (V10.13x.1 + recent patches)
- Event bus contract — dedup logic, handlers
- Firebase collections & schema — stable

### CLAUDE_ONLY (Sensitive Logic)

- `realtime_decision_engine.py` — EV formula, gates, thresholds
- `trade_executor.py` — order routing, exit logic, TP/SL/trailing
- Exit pricing & timing — risk-critical
- Learning & calibration logic
- Firebase schema changes
- Any trading behavior change

### CODEX_SAFE (Pure Helpers)

- Dataclasses for DecisionFrame, OrderLifecycle, ErrorCode
- Serialization helpers (to_dict, from_dict)
- Enum definitions (DecisionState, GateType, ExitReason)
- Log format helpers (canonical_decision_log)
- Unit tests for pure helpers
- Documentation

### POSTPONE (Out of Scope)

- Refactor RDE architecture
- Change EV formula or thresholds
- Swap event bus for different pub-sub
- Firebase schema redesign
- Storage migration (trades compression)
- New infrastructure (Redis, DuckDB, etc.)

---

## 10. Audit Conclusion

**Overall Assessment**: ✅ **STABLE**

- **Entrypoints**: Clear, well-defined
- **Flow**: Linear and synchronous at critical points (decision → execution)
- **Contracts**: Well-documented (signal, decision, trade dicts)
- **Gates**: Explicit priority order, all implemented
- **Learning**: Unified source (canonical + session backup)
- **Persistence**: Quota-aware, graceful degradation
- **Fragility**: Documented, mitigations in place

**Risk Level**: LOW

- No architectural contradictions blocking observability patch
- Idempotent handlers reduce side-effect risk
- Firebase quota prevents runaway reads
- Event dedup prevents most double-executions

**Proceed to Phase C** — Compatibility map for Mammon observability helpers.
