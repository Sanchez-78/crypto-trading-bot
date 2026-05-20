# CryptoMaster Android Metrics Contract

**Version:** 1.0  
**Date:** 2026-05-20  
**Status:** Documentation Contract (No Implementation Yet)

---

## Executive Summary

This document defines the complete metrics contract between the CryptoMaster backend and the Android app. It specifies:

- **10 Android app screens** with required metrics
- **Metric definitions** (Czech labels, data sources, update frequencies, priorities)
- **JSON schema proposals** for data transfer
- **Card layout templates** for consistent UI
- **Safety rules** for live app polling vs. offline-only analysis
- **State handling** (empty, error, loading, stale)

**Critical Rule:** This is a **specification contract only**. No Android code, no Firebase writes, no backend changes. Pure documentation.

---

## Part 1: Data Sources & Safety Rules

### 1.1 Safe Data Sources

| Source | Safety | Update Freq | Polling Safe? | Notes |
|--------|--------|-------------|---------------|-------|
| **Firebase Realtime** | Live edge case data | ~1-10 sec | ✅ YES (read-only) | Trades, positions, status |
| **Firebase Periodic** | Aggregated metrics | ~30-60 sec | ✅ YES (low volume) | Metrics snapshots, KPIs |
| **Log JSON exports** | Historical/offline | On-demand | ❌ NO | Use for research reports only |
| **Audit script output** | Diagnostic only | On-demand | ❌ NO | Backend engineers only |
| **Quality reports** | Offline analysis | On-demand | ❌ NO | Research dashboard only |

### 1.2 Polling Safety Limits (Firebase)

- **Max concurrent listeners:** 5
- **Max listener update frequency:** 1 request per 2 seconds (300 req/min = 432K/day max)
- **Fallback caching:** If quota exhausted, use last known state (30 min TTL)
- **Offline mode:** Show "Quota Exhausted" banner, disable real-time updates

### 1.3 Offline-Only Metrics

These metrics should **never be polled from Android app**:

- Trade audit counts (use historical snapshot instead)
- Log parsing statistics
- Backend diagnostic logs
- Learning model internals
- Research quality reports (show download link only)

---

## Part 2: Android App Screens (10 Screens)

Each screen definition includes:
- **Screen name** (English + Czech)
- **Purpose**
- **Required metrics** (internal key → Czech label)
- **Priority** (MUST / SHOULD / NICE)
- **Data source & frequency**

---

### Screen 1: Dashboard (Přehled)

**Purpose:** Home screen. Bot status at a glance. Real-time updates.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `idle_seconds` | Doba v klidu | Jak dlouho bot nekonal obchody | Firebase metrics | 10s | MUST | Gauge | ⚠️ > 3600s |
| `paper_trades_live_30m` | Papír. obchody (30 min) | Počet papírových obchodů za poslední 30 minut | Firebase metrics | 30s | MUST | Counter | 🟢 ≥1, 🟡 0, 🔴 unavailable |
| `live_real_trades_30m` | Živé obchody (30 min) | Počet živých/skutečných obchodů za poslední 30 minut | Firebase metrics | 30s | MUST | Counter | 🟢 ≥1, 🟡 0 |
| `global_trades_total` | Celkem obchodů | Kumulativní počet všech obchodů od spuštění | Firebase metrics | 60s | SHOULD | Counter | None |
| `regime_current` | Aktuální režim | Tržní režim: BULL_TREND, BEAR_TREND, RANGING, QUIET, HIGH_VOL | Firebase/signal | 5s | MUST | Label | None |
| `open_positions_count` | Otevřené pozice | Počet aktuálně otevřených papírových pozic | Firebase | 10s | MUST | Counter | ⚠️ > 5 |
| `bot_health` | Zdraví bota | Stav: healthy, degraded, critical, offline | Firebase status | 30s | MUST | Status | 🔴 offline/critical |
| `last_signal_age_seconds` | Věk posledního signálu | Kolik sekund od posledního signálu | Firebase | 10s | SHOULD | Gauge | ⚠️ > 600s |
| `firebase_quota_usage_pct` | Kvóta Firebase | Procento denního limitu Firebase spotřebeno | Local calc | 300s | NICE | Gauge | ⚠️ > 80%, 🔴 > 95% |

**Layout:** 2-column grid with 3 summary cards + 1 status bar

---

### Screen 2: Robot Status (Stav Robota)

**Purpose:** Detailed bot health, trading mode, enabled/disabled systems.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `trading_mode` | Obchodní režim | live_real, paper_live, paper_train, replay_train | Firebase config | 60s | MUST | Label | None |
| `paper_train_enabled` | Papír. trénink aktivní | Je papírový trénink aktivní? | Firebase | 60s | MUST | Toggle | None |
| `decision_engine_alive` | RDE živý | Je realtime decision engine aktivní? | Firebase heartbeat | 30s | MUST | Status | 🔴 offline > 120s |
| `paper_sampler_alive` | Sampler živý | Je paper training sampler aktivní? | Firebase heartbeat | 30s | MUST | Status | 🔴 offline > 120s |
| `learning_monitor_alive` | Monitor živý | Je learning monitor aktivní? | Firebase heartbeat | 30s | MUST | Status | 🔴 offline > 120s |
| `risk_engine_alive` | Risk engine živý | Je risk engine aktivní? | Firebase heartbeat | 30s | MUST | Status | 🔴 offline > 120s |
| `last_startup_timestamp` | Poslední spuštění | Čas posledního startu | Firebase | 3600s | SHOULD | DateTime | None |
| `uptime_seconds` | Provozní doba | Jak dlouho běží od startu | Calculated | 60s | SHOULD | Duration | None |
| `cpu_percent` | CPU | Procesorová zátěž (%) | System metrics | 60s | NICE | Gauge | ⚠️ > 80% |
| `memory_percent` | Paměť | Využití paměti (%) | System metrics | 60s | NICE | Gauge | ⚠️ > 85% |
| `disk_percent` | Disk | Využití disku (%) | System metrics | 600s | NICE | Gauge | ⚠️ > 90% |

**Layout:** Status grid + system health section + uptime badge

---

### Screen 3: Open Positions (Otevřené Pozice)

**Purpose:** Real-time list of open paper/live trades. Drill down to details.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `position_id` | ID pozice | Unique trade ID | Firebase | RT | MUST | Label | None |
| `symbol` | Symbol | BTC/USDT, ETH/USDT, atd. | Firebase | RT | MUST | Label | None |
| `side` | Směr | BUY nebo SELL | Firebase | RT | MUST | Label | None |
| `entry_price` | Cena vstupu | Vstupní cena obchodu | Firebase | RT | MUST | Price | None |
| `current_price` | Aktuální cena | Poslední tržní cena | Firebase/feed | 5s | MUST | Price | None |
| `unrealized_pnl_pct` | Nerealizovaný výnos | Procento zisku/ztráty před uzavřením | Calculated | 5s | MUST | Gauge | 🟢 >0, 🔴 <0 |
| `tp_price` | Cíl (TP) | Take-profit cena | Firebase | RT | MUST | Price | None |
| `sl_price` | Stoploss (SL) | Stoploss cena | Firebase | RT | MUST | Price | None |
| `time_held_seconds` | Doba v obchodu | Kolik sekund je pozice otevřena | Calculated | 10s | SHOULD | Duration | ⚠️ > hold_limit |
| `hold_limit_seconds` | Limit času | Maximální čas v obchodu | Firebase | RT | SHOULD | Duration | None |
| `mfe_pct` | MFE | Max favorable excursion (%) | Calculated | 10s | NICE | Gauge | None |
| `mae_pct` | MAE | Max adverse excursion (%) | Calculated | 10s | NICE | Gauge | None |
| `regime` | Režim | Tržní režim při vstupu | Firebase | RT | SHOULD | Label | None |
| `bucket` | Bucket | Kvalitní bucket obchodu | Firebase | RT | SHOULD | Label | None |

**Layout:** List of cards (one per position), swipeable for details drawer

---

### Screen 4: Trade History (Historie Obchodů)

**Purpose:** Paginated historical trades. Filters by date range, symbol, outcome.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `trade_id` | ID obchodu | Unique trade identifier | Firebase | Static | MUST | Label | None |
| `symbol` | Symbol | BTC/USDT, ETH/USDT | Firebase | Static | MUST | Label | None |
| `side` | Směr | BUY / SELL | Firebase | Static | MUST | Label | None |
| `outcome` | Výsledek | WIN / LOSS / FLAT / TIMEOUT | Firebase | Static | MUST | Label | 🟢 WIN, 🔴 LOSS, 🟡 FLAT |
| `entry_price` | Vstup | Cena vstupu | Firebase | Static | MUST | Price | None |
| `exit_price` | Výstup | Cena výstupu | Firebase | Static | MUST | Price | None |
| `net_pnl_pct` | Výnos % | Čistý procent zisku/ztráty | Firebase | Static | MUST | Gauge | 🟢 >0, 🔴 <0 |
| `net_pnl_usdt` | Výnos USDT | Čistý zisk/ztráta v USDT | Firebase | Static | SHOULD | Price | None |
| `fee_drag_pct` | Poplatek % | Kolik procent vzaly poplatky | Firebase | Static | SHOULD | Gauge | ⚠️ > 0.1% |
| `hold_seconds` | Čas pozice | Jak dlouho trvala pozice | Firebase | Static | MUST | Duration | None |
| `touched_tp` | Dotkl TP? | Dosáhla cílové ceny? | Firebase | Static | NICE | Toggle | None |
| `touched_sl` | Dotkl SL? | Dosáhla stoploss ceny? | Firebase | Static | NICE | Toggle | None |
| `timestamp_entry` | Čas vstupu | Timestamp vstupu | Firebase | Static | SHOULD | DateTime | None |
| `timestamp_exit` | Čas výstupu | Timestamp výstupu | Firebase | Static | SHOULD | DateTime | None |

**Layout:** Scrollable list with filtering sidebar, expandable rows for details

---

### Screen 5: Learning Monitor (Monitor Učení)

**Purpose:** Paper training progress. Closed trades count, model calibration, bucket stats.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `paper_trades_closed_total` | Uzavřeno papír. obchodů | Kolik papírových obchodů jsme uzavřeli celkem | Firebase | 60s | MUST | Counter | ⚠️ < 10 (starvation) |
| `paper_trades_closed_24h` | Uzavřeno za 24h | Kolik papírových obchodů uzavřeno za posledních 24h | Firebase | 300s | SHOULD | Counter | 🟢 ≥ 5 |
| `learning_bucket_active` | Aktivní bucket | Jaký je aktuální výcvikový bucket | Firebase | 60s | MUST | Label | None |
| `model_calibration_status` | Kalibrace modelu | healthy / degraded / insufficient_data | Firebase | 300s | SHOULD | Status | 🟡 degraded, 🔴 insufficient |
| `tp_sl_calibration_quality` | Kvalita TP/SL | Procento správně kalibrovaných | Firebase | 300s | SHOULD | Gauge | 🟢 > 80%, 🟡 60-80%, 🔴 < 60% |
| `recent_win_rate_pct` | Win rate (poslední) | Procento výher za poslední uzavřené obchody | Firebase | 300s | SHOULD | Gauge | 🟢 > 55%, 🟡 40-55%, 🔴 < 40% |
| `ev_quality_score` | Kvalita EV | 0-100, jak dobré jsou naše EV odhady | Firebase | 300s | NICE | Gauge | 🟢 > 70 |
| `cost_edge_bypass_count` | Obchody s bypass | Kolik obchodů jsme provedli s cost-edge bypass | Firebase | 60s | NICE | Counter | ⚠️ > paper_trades_closed_24h * 0.2 |
| `geometry_calibrated_pct` | Geometrie kalibrována | Procento obchodů s kalibrovanou geometrií | Firebase | 300s | NICE | Gauge | 🟢 > 90% |

**Layout:** Summary cards (4) + progress bars + trend sparklines

---

### Screen 6: Signal Quality (Kvalita Signálu)

**Purpose:** EV distribution, signal sources, regime quality, anomaly detection.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `signals_generated_1h` | Signálů za 1h | Kolik signálů jsme vygenerovali za poslední hodinu | Firebase metrics | 60s | SHOULD | Counter | 🟢 > 2, 🟡 1-2, 🔴 0 |
| `signals_rejected_negative_ev` | Odmítnuty (neg EV) | Počet odmítnutých signálů kvůli negativnímu EV | Firebase metrics | 60s | SHOULD | Counter | None |
| `signals_rejected_risk` | Odmítnuty (risk) | Počet odmítnutých signálů kvůli risk filtru | Firebase metrics | 60s | SHOULD | Counter | None |
| `signals_accepted_1h` | Přijaté za 1h | Kolik signálů bylo přijato za poslední hodinu | Firebase metrics | 60s | SHOULD | Counter | 🟢 > 0, 🟡 0 |
| `ev_distribution_mean` | Průměrné EV | Průměrné expected value přijatých signálů | Firebase metrics | 60s | NICE | Gauge | 🟢 > 0.5% |
| `ev_distribution_min` | Min EV | Minimální EV přijatých signálů | Firebase metrics | 60s | NICE | Gauge | None |
| `ev_distribution_max` | Max EV | Maximální EV přijatých signálů | Firebase metrics | 60s | NICE | Gauge | None |
| `signal_source_breakdown` | Zdroje signálů | Procento signálů z každého zdroje (%) | Firebase metrics | 300s | NICE | Pie Chart | None |
| `anomaly_count_1h` | Anomálie za 1h | Počet detekovaných anomálií za poslední hodinu | Firebase metrics | 60s | NICE | Counter | ⚠️ > 3 |

**Layout:** KPI cards (3 top row) + EV distribution chart + source pie chart + anomaly list

---

### Screen 7: Economic Attribution (Ekonomická Atribuce)

**Purpose:** Why do trades win/lose? Attribution analysis. Offline research data available.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `attribution_mode` | Režim dat | live (poslední 10), historical (offline report) | Local | Static | MUST | Toggle | None |
| `wins_via_tp` | Výhry přes TP | Počet výher kdy jsme dosáhli cílové ceny | Firebase | 300s | SHOULD | Counter | None |
| `wins_via_timeout` | Výhry timeout | Počet výher kde čas vypršel | Firebase | 300s | NICE | Counter | None |
| `losses_via_sl` | Ztráty přes SL | Počet ztrát kdy jsme dosáhli stoploss | Firebase | 300s | SHOULD | Counter | None |
| `losses_via_timeout` | Ztráty timeout | Počet ztrát kde čas vypršel | Firebase | 300s | NICE | Counter | None |
| `loss_reason_wrong_direction` | Ztráty (směr) | Procento ztrát kvůli chybného směru | Firebase | 300s | SHOULD | Gauge | None |
| `loss_reason_fee_dominated` | Ztráty (poplatek) | Procento ztrát kde poplatky zdecimovaly výnos | Firebase | 300s | SHOULD | Gauge | ⚠️ > 20% |
| `loss_reason_slippage` | Ztráty (slip) | Procento ztrát kvůli slippage | Firebase | 300s | NICE | Gauge | None |
| `offline_report_available` | Offline report | Je dostupný podrobný kvalitační report? | Local file | Static | NICE | Link | None |

**Layout:** Attribution toggle + stacked bar chart (wins/losses breakdown) + reason list + "View Report" button

---

### Screen 8: Risk & Health (Riziko & Zdraví)

**Purpose:** Position risk, exposure limits, health checks, warnings.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `exposure_current_pct` | Aktuální expozice | Procento z max expozičního limitu | Firebase | 10s | MUST | Gauge | 🟡 > 75%, 🔴 > 95% |
| `exposure_limit_pct` | Max expozice | Maximální povolená expozice (%) | Firebase config | 3600s | SHOULD | Label | None |
| `position_count_current` | Počet pozic | Kolik máme aktuálně otevřených pozic | Firebase | 10s | MUST | Counter | 🟡 > 3, 🔴 > 5 |
| `position_limit_max` | Max pozic | Maximální povolený počet otevřených pozic | Firebase config | 3600s | SHOULD | Label | None |
| `per_symbol_exposure_max` | Max na symbol | Největší expozice na jeden symbol (%) | Firebase metrics | 30s | SHOULD | Gauge | ⚠️ > 50% of limit |
| `unrealized_loss_max_pct` | Největší ztráta | Největší nerealizovaná ztráta (%) | Calculated | 10s | SHOULD | Gauge | 🔴 < -5% |
| `margin_used_pct` | Marže použitá | Procento použité marže (pokud je k dispozici) | Firebase | 30s | NICE | Gauge | ⚠️ > 70% |
| `health_check_status` | Zdravotní kontrola | passed / warning / critical | Firebase | 60s | MUST | Status | 🔴 critical |
| `health_warnings` | Varování | Seznam aktuálních varování | Firebase | 60s | SHOULD | List | None |
| `last_risk_recalc_age_seconds` | Věk výpočtu | Kolik sekund od poslední kalkulace rizika | Firebase | 10s | NICE | Duration | ⚠️ > 60s |

**Layout:** Exposure gauge (large) + limit bar + health status badge + position counter + warnings list

---

### Screen 9: Firebase / Quota / System (Firebase / Kvóta / Systém)

**Purpose:** Backend health for developers. Firebase quota, system status, diagnostic info.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `firebase_connection_status` | Spojení Firebase | connected / reconnecting / offline | Firebase | RT | MUST | Status | 🔴 offline |
| `firebase_reads_today` | Čtení dnes | Počet přečtených dokumentů dnes | Firebase | 300s | SHOULD | Counter | 🟡 > 40K, 🔴 > 48K |
| `firebase_writes_today` | Zápisy dnes | Počet zapsaných dokumentů dnes | Firebase | 300s | SHOULD | Counter | 🟡 > 16K, 🔴 > 19K |
| `firebase_quota_reset_eta` | Reset v | Čas do resetování kvóty (hod:min) | Calculated | 3600s | SHOULD | TimeLeft | None |
| `firebase_reads_remaining` | Zbývá čtení | Zbývající čtení na dnešní den | Calculated | 300s | NICE | Counter | 🟡 < 10K, 🔴 < 2K |
| `firebase_writes_remaining` | Zbývá zápisy | Zbývající zápisy na dnešní den | Calculated | 300s | NICE | Counter | 🟡 < 4K, 🔴 < 1K |
| `system_uptime_days` | Provoz (dny) | Jak dlouho je server spuštěný (dny) | System | 3600s | NICE | Duration | None |
| `system_last_deploy` | Poslední deploy | Čas posledního nasazení | System | 3600s | NICE | DateTime | None |
| `backend_api_latency_ms` | Latence API | Střední latence API volání (ms) | Telemetry | 60s | SHOULD | Gauge | ⚠️ > 200ms, 🔴 > 500ms |
| `diagnostics_available` | Diagnostika | Je k dispozici podrobná diagnostika? | System | Static | NICE | Link | None |

**Layout:** Status grid (3x2) + quota bars + reset timer + API latency chart + diagnostic link

---

### Screen 10: Offline Research Reports (Offline Výzkumné Reporty)

**Purpose:** Access to offline quality reports and analysis. Links, download info, summaries.

| Metric Key | Czech Label | Czech Explanation | Source | Freq | Priority | Type | Thresholds |
|---|---|---|---|---|---|---|---|
| `report_type` | Typ reportu | quality_report / regime_analysis / symbol_breakdown | Local file | Static | MUST | Label | None |
| `report_generated_timestamp` | Vygenerován | Čas generování reportu | File metadata | Static | MUST | DateTime | None |
| `report_dataset_size` | Velikost datasetu | Počet obchodů v reportu | JSON | Static | SHOULD | Counter | 🔴 < 10 |
| `report_date_range` | Rozsah dat | Od-Do datum obchodů v reportu | JSON | Static | SHOULD | DateRange | None |
| `report_win_rate` | Win rate | Procento výher v datasetu | JSON | Static | SHOULD | Gauge | None |
| `report_mean_pnl` | Průměrný PnL | Průměrný čistý výnos obchodu (%) | JSON | Static | SHOULD | Gauge | None |
| `report_symbol_count` | Symbolů v reportu | Kolik různých symbolů je v datasetu | JSON | Static | NICE | Counter | None |
| `report_file_path` | Cesta k souboru | Místní cesta k .md a .json souboru | Local | Static | MUST | Label | None |
| `report_download_size_mb` | Velikost download | Kolik MB je exportní soubor | File metadata | Static | NICE | Size | None |
| `quality_warnings` | Varování kvality | Seznam potenciálních problémů (malý dataset, atd.) | JSON | Static | SHOULD | List | None |

**Layout:** Report cards (stacked) with summary metrics + drill-down to details + download button + export options

---

## Part 3: JSON Schema Proposals

### 3.1 Dashboard Snapshot (`dashboard_snapshot`)

**Usage:** Cached snapshot of dashboard metrics. Sent from backend ~every 30 seconds. Includes only MUST metrics.

```json
{
  "snapshot_id": "uuid",
  "timestamp_generated": 1716144000.5,
  "timestamp_cache_valid_until": 1716144030.5,
  "trading_mode": "paper_train",
  "bot_health": "healthy",
  
  "realtime_metrics": {
    "idle_seconds": 523,
    "paper_trades_live_30m": 2,
    "live_real_trades_30m": 0,
    "global_trades_total": 847,
    "regime_current": "BULL_TREND",
    "open_positions_count": 1,
    "last_signal_age_seconds": 45
  },
  
  "system_metrics": {
    "firebase_quota_usage_pct": 31.2,
    "firebase_connection_ok": true,
    "backend_latency_ms": 145,
    "uptime_seconds": 3720
  },
  
  "alerts": [
    {
      "severity": "warning",
      "code": "LONG_IDLE",
      "message_en": "Bot idle for 8+ minutes",
      "message_cz": "Bot je v klidu již 8+ minut"
    }
  ]
}
```

### 3.2 Position Detail (`position_snapshot`)

**Usage:** Full position data. Sent on open, updated every 10 seconds while open.

```json
{
  "position_id": "paper_123_btc_buy_1716144000",
  "symbol": "BTC/USDT",
  "side": "BUY",
  "entry_price": 67000.0,
  "entry_timestamp": 1716144000.5,
  "current_price": 67350.5,
  "current_timestamp": 1716144045.5,
  
  "targets": {
    "tp_price": 68000.0,
    "sl_price": 65500.0,
    "hold_limit_seconds": 300
  },
  
  "performance": {
    "unrealized_pnl_pct": 0.52,
    "unrealized_pnl_usdt": 350.0,
    "mfe_pct": 1.8,
    "mae_pct": -0.3,
    "time_held_seconds": 45,
    "time_remaining_seconds": 255
  },
  
  "metadata": {
    "regime": "BULL_TREND",
    "bucket": "C_WEAK_EV_TRAIN",
    "source": "training_sampler"
  },
  
  "warnings": [
    {
      "code": "NEAR_TP",
      "message_en": "Price within 50 pips of TP",
      "message_cz": "Cena je blízko cílové ceny"
    }
  ]
}
```

### 3.3 Trade History Record (`trade_record`)

**Usage:** Individual historical trade. Read-only from Firebase.

```json
{
  "trade_id": "paper_847_eth_sell_1716143500",
  "symbol": "ETH/USDT",
  "side": "SELL",
  "outcome": "WIN",
  "mode": "paper_train",
  
  "entry": {
    "price": 3500.0,
    "timestamp": 1716143500.0,
    "regime": "BEAR_TREND",
    "bucket": "C_WEAK_EV_TRAIN"
  },
  
  "exit": {
    "price": 3450.0,
    "timestamp": 1716143700.0,
    "reason": "tp_hit"
  },
  
  "economics": {
    "gross_move_pct": -1.43,
    "fee_drag_pct": 0.08,
    "net_pnl_pct": -1.51,
    "net_pnl_usdt": -52.85,
    "mfe_pct": 0.0,
    "mae_pct": -1.5
  },
  
  "barriers": {
    "tp_price": 3450.0,
    "sl_price": 3630.0,
    "touched_tp": true,
    "touched_sl": false,
    "timeout": false,
    "hold_seconds": 200
  }
}
```

### 3.4 Learning Monitor Snapshot (`learning_monitor_snapshot`)

**Usage:** Paper training progress. Updated every 60 seconds.

```json
{
  "snapshot_id": "uuid",
  "timestamp": 1716144000.5,
  "paper_training_enabled": true,
  
  "closed_trades": {
    "total": 847,
    "last_24h": 12,
    "last_7d": 89,
    "win_rate_recent_pct": 51.4
  },
  
  "calibration": {
    "status": "healthy",
    "tp_sl_quality_pct": 87.3,
    "model_ev_quality_score": 78,
    "geometry_calibrated_pct": 92.1
  },
  
  "active_bucket": {
    "name": "C_WEAK_EV_TRAIN",
    "open_count": 1,
    "cost_edge_bypass_active": false
  },
  
  "starvation_status": {
    "is_starvation_detected": false,
    "idle_since_seconds": 523,
    "probe_lifetime_closed": 0
  }
}
```

### 3.5 System Health (`system_health_snapshot`)

**Usage:** Backend health. Firebase quota, uptime, API latency. Updated every 60 seconds.

```json
{
  "snapshot_id": "uuid",
  "timestamp": 1716144000.5,
  
  "firebase": {
    "connection_ok": true,
    "reads_today": 12450,
    "reads_limit_daily": 50000,
    "reads_remaining": 37550,
    "writes_today": 4230,
    "writes_limit_daily": 20000,
    "writes_remaining": 15770,
    "quota_reset_seconds_remaining": 43200
  },
  
  "system": {
    "uptime_seconds": 3720,
    "last_deploy_timestamp": 1716100000,
    "cpu_percent": 42.3,
    "memory_percent": 65.1,
    "disk_percent": 58.7
  },
  
  "api": {
    "latency_ms_median": 145,
    "latency_ms_p99": 280,
    "error_rate_pct": 0.1
  },
  
  "health_checks": [
    {
      "name": "decision_engine_heartbeat",
      "ok": true,
      "age_seconds": 5
    },
    {
      "name": "paper_sampler_heartbeat",
      "ok": true,
      "age_seconds": 8
    }
  ]
}
```

---

## Part 4: Android Card Layout Template

All metrics displayed in reusable card components. Standard layouts:

### 4.1 KPI Card (Simple Metric)

```
┌─────────────────────────────────┐
│  Czech Label (Doba v klidu)     │  ← Title (10pt, #333)
├─────────────────────────────────┤
│                                 │
│        523 seconds              │  ← Value (28pt, bold, color-coded)
│                                 │
│  Czech explanation text          │  ← Help text (9pt, #666)
└─────────────────────────────────┘
```

- **Width:** 45% (2-column grid) or 100% (single column)
- **Height:** 80dp
- **Corner radius:** 8dp
- **Shadow:** elevation 2dp
- **Padding:** 12dp

### 4.2 Progress Card (Gauge/Percentage)

```
┌─────────────────────────────────┐
│  Czech Label                    │
│  Current: 31.2% | Limit: 50K   │  ← Context
├─────────────────────────────────┤
│ █████████░░░░░░░░░░░░░░░░░░░░░│  ← Progress bar
│ 12,450 / 50,000 reads          │  ← Numeric
└─────────────────────────────────┘
```

- **Bar color:** 🟢 < 70%, 🟡 70-85%, 🔴 > 85%
- **Bar height:** 6dp
- **Corner radius:** 3dp

### 4.3 Status Card (Indicator)

```
┌─────────────────────────────────┐
│  Czech Label                    │
├─────────────────────────────────┤
│  🟢 Connected                   │  ← Status dot (8dp) + label
│  since 47 seconds ago           │  ← Age
└─────────────────────────────────┘
```

- **Dot colors:** 🟢 OK, 🟡 Warning, 🔴 Critical, ⚫ Offline
- **Dot size:** 8dp
- **Animation:** Pulse if critical

### 4.4 List Card (Multiple Items)

```
┌─────────────────────────────────┐
│  Czech Label (Открытые позиции) │
├─────────────────────────────────┤
│  BTC/USDT (BUY)  +0.52%  🟢     │  ← Item 1
│  ETH/USDT (SELL) -1.51% 🔴      │  ← Item 2
│  [Scroll for more...]           │
└─────────────────────────────────┘
```

- **Item height:** 36dp
- **Separator:** 0.5dp divider (#E8E8E8)
- **Max height:** 3 items visible, scroll for more

### 4.5 Chart Card (Trend/Distribution)

```
┌─────────────────────────────────┐
│  Czech Label (Attribution)      │
├─────────────────────────────────┤
│   Wins (70%) │ ████████░░        │  ← Stacked bar
│   Losses(30%)│ ███░░░░░░░░░░░    │
│                                 │
│   TP Hit: 35  | SL Hit: 12      │  ← Legend
└─────────────────────────────────┘
```

- **Chart height:** 100dp (for bars), 120dp (for pie)
- **Colors:** Predefined palette (see Part 5)
- **Legend:** 8pt, below chart

---

## Part 5: Color & State Rules

### 5.1 Metric State Colors

| State | Hex Color | Usage | Icon |
|-------|-----------|-------|------|
| **Healthy/OK** | #4CAF50 (green) | > threshold, ok status | ✓ or 🟢 |
| **Warning** | #FFC107 (amber) | approaching limit, degraded | ⚠️ or 🟡 |
| **Critical** | #F44336 (red) | exceeded limit, offline | ✗ or 🔴 |
| **Offline/Unknown** | #9E9E9E (gray) | no data, not connected | ⊗ or ⚫ |
| **Neutral** | #2196F3 (blue) | informational, no threshold | ℹ️ or 🔵 |

### 5.2 Win/Loss/Outcome Colors

| Outcome | Hex Color | Usage |
|---------|-----------|-------|
| **WIN** | #4CAF50 (green) | Successful trade |
| **LOSS** | #F44336 (red) | Failed trade |
| **FLAT** | #FFC107 (amber) | Minimal move |
| **TIMEOUT** | #9C27B0 (purple) | No exit before timeout |

### 5.3 Empty/Error/Loading States

#### Empty State
```
┌─────────────────────────────────┐
│                                 │
│        🚫 No data yet            │
│    Waiting for first trade...   │
│                                 │
│    [Refresh] button             │
└─────────────────────────────────┘
```

- **Icon:** 48dp, #BDBDBD
- **Text:** 14pt, #9E9E9E
- **Button:** 36dp, secondary style

#### Error State
```
┌─────────────────────────────────┐
│  ⚠️  Connection Lost             │  ← Error icon (red)
│  Firebase quota exhausted       │
│  Using cached data (30min old)  │
│                                 │
│  [Retry] [Offline Mode]         │
└─────────────────────────────────┘
```

- **Background:** light red (#FFEBEE)
- **Icon:** 24dp, #F44336
- **Text:** 13pt, #D32F2F
- **Buttons:** Primary + Secondary

#### Loading State
```
┌─────────────────────────────────┐
│  Czech Label                    │
├─────────────────────────────────┤
│  ⟳ Loading metrics...           │  ← Spinner animation
│                                 │
│  Updating... (2/5 sections)     │  ← Progress indicator
└─────────────────────────────────┘
```

- **Spinner:** 24dp, rotating, #2196F3
- **Duration:** max 5 seconds before error state
- **Fallback:** Show stale data with "updating..." badge

### 5.4 Stale Data Badge

```
[⏱️ Stale: 2 min old]  ← Badge on card when data > TTL
```

- **Background:** #FFEBEE
- **Text:** 10pt, #D32F2F, italic
- **Position:** top-right corner of card
- **Show when:** data age > 2x normal update frequency

---

## Part 6: Live Polling vs. Offline-Only Safety

### 6.1 Safe for Live Polling (Android Can Subscribe)

✅ **Real-time metrics** (listener + 1-2 sec updates):
- Current price movements
- Open position P&L
- Regime changes
- Bot heartbeats
- Active trade entries/exits

✅ **Periodic metrics** (cache + 30-60 sec updates):
- Dashboard snapshot
- Closed trade count
- Learning progress
- System health
- API latency

**Max concurrent listeners:** 5  
**Max listener frequency:** 1 req per 2 sec per screen  
**Cache fallback:** If quota exhausted, show last snapshot (30 min TTL)

### 6.2 Offline-Only (Android Cannot Fetch)

❌ **Never poll directly from Android:**
- Trade audit log counts
- Log parsing statistics
- Diagnostic internals
- Model architecture details
- Research quality reports
- Offline backtests

**Instead:**
- ✅ Provide download links for offline reports (user manually downloads)
- ✅ Cache summary metrics in dashboard snapshot
- ✅ Show "Report Available" badge with timestamp
- ✅ Allow local viewing of .md/.json after download

### 6.3 Quota Protection Strategy

**Level 1 - Prevent Overuse:**
```
if (firebase_writes_remaining < 2000) {
  disable_live_updates()  // Switch to 5-min cache
  show_banner("High quota usage, using cached data")
}
```

**Level 2 - Handle Exhaustion:**
```
if (quota_exhausted_today()) {
  use_local_cache_only()  // All data >= 30 min old
  show_banner("Quota exhausted, viewing cached snapshot")
  disable_write_operations()
}
```

**Level 3 - Next Day Recovery:**
```
if (hours_until_quota_reset() < 2) {
  countdown_visible()  // Show "Reset in 48 min"
  warn_user_of_incoming_reset()
}
```

---

## Part 7: Screen Wireframe Hierarchy

```
Android App Navigation
│
├─ Dashboard (Home)
│  └ 8 KPI cards + 2 alerts + 1 open positions preview
│
├─ Robot Status
│  └ 11 status cards (modes, heartbeats, system)
│
├─ Open Positions
│  └ List view (swipeable cards) + detail drawer
│
├─ Trade History
│  └ Paginated list + filters (date, symbol, outcome)
│
├─ Learning Monitor
│  └ Summary cards (4) + progress bars (3) + sparklines
│
├─ Signal Quality
│  └ KPI cards (3) + EV chart + source pie + anomalies list
│
├─ Economic Attribution
│  └ Toggle (live/offline) + stacked bars + reasons list
│
├─ Risk & Health
│  └ Exposure gauge (large) + health status + warnings list
│
├─ Firebase/Quota/System
│  └ Status grid (3x2) + quota bars + reset timer + latency chart
│
└─ Offline Research Reports
   └ Report cards (stacked) + drill-down + download buttons
```

---

## Part 8: Implementation Roadmap (Not Yet Done)

### Phase 1: Data Contract (Current)
- ✅ Define 10 screens
- ✅ Define all metrics
- ✅ JSON schema proposals
- ✅ Card layouts & colors
- ✅ Safety rules

### Phase 2: Backend API (Later)
- Firebase collection structure
- Real-time listener setup
- Cache strategy implementation
- Quota protection enforcement

### Phase 3: Android UI (Later)
- Fragment implementations
- RecyclerView adapters
- LiveData/ViewModel setup
- Theme/colors integration

### Phase 4: Integration Tests (Later)
- E2E data flow tests
- Quota exhaustion simulation
- Offline mode testing
- Chart rendering tests

---

## Part 9: Czech UI Guidelines

### 9.1 Label Format Rules

- **Short labels:** max 24 characters (KPI cards)
- **Full labels:** max 40 characters (section headers)
- **Help text:** max 60 characters, single line if possible
- **No abbreviations** unless universally known (EV, TP, SL, PnL, MFE, MAE, API, CPU, ATM ok)
- **Numbers format:** Use space as thousands separator (50 000, not 50000)
- **Percent format:** Always with % symbol (31.2%, not 31.2)
- **Time format:** HH:MM:SS for durations, ISO 8601 for timestamps
- **Currency format:** 1 234.56 USDT (space thousands, comma decimals if in Czech locale)

### 9.2 Czech Terminology (Consistent)

| English | Czech | Abbreviation | Usage |
|---------|-------|--------------|-------|
| Trade | Obchod | - | Individual trade |
| Open position | Otevřená pozice | - | Live position |
| Closed trade | Uzavřený obchod | - | Historical trade |
| Outcome | Výsledek | - | WIN/LOSS/FLAT |
| Take-profit | Cílová cena, TP | TP | Price target |
| Stop-loss | Stoploss, SL | SL | Loss limit |
| Entry price | Vstupní cena | - | Trade open price |
| Exit price | Výstupní cena | - | Trade close price |
| Entry timestamp | Čas vstupu | - | When entered |
| Exit timestamp | Čas výstupu | - | When exited |
| Unrealized P&L | Nerealizovaný výnos | - | Open position result |
| Fee drag | Poplatek, drag | - | Fee impact |
| MFE | Max příznivý pohyb | MFE | Max favorable excursion |
| MAE | Max nepříznivý pohyb | MAE | Max adverse excursion |
| Regime | Režim | - | Market mode (BULL/BEAR/etc) |
| Bucket | Bucket | - | Trade category |
| Calibration | Kalibrace | - | Parameter tuning |
| Win rate | Procento výher | - | % of winning trades |
| Expected value | Očekávaná hodnota | EV | Expected trade result |

---

## Part 10: Implementation Notes for Android Team

### 10.1 Data Binding Pattern

Use LiveData + ViewModel for all screen data:

```kotlin
// ViewModel
class DashboardViewModel : ViewModel() {
    val dashboardSnapshot: LiveData<DashboardSnapshot> = ...
    val alerts: LiveData<List<Alert>> = ...
    val selectedTab: LiveData<Int> = ...
}

// View
dashboardViewModel.dashboardSnapshot.observe(viewLifecycleOwner) { snapshot ->
    updateMetricsCards(snapshot)
}
```

### 10.2 Error & Empty State Handling

```kotlin
when {
    snapshot == null && isLoading -> showLoadingState()
    snapshot == null && error != null -> showErrorState(error)
    snapshot?.realtime_metrics == null -> showEmptyState()
    else -> showData(snapshot)
}
```

### 10.3 Offline Mode

```kotlin
// Check quota before updating
if (!firebase.canRead(metricsPath)) {
    useLocalCache()
    showBanner("Offline mode active - cached data from ${cacheAge} ago")
}
```

### 10.4 Theming

Use Material 3 color system:
- **Primary:** #2196F3 (accent color for CTAs)
- **Secondary:** #1976D2 (alternative highlight)
- **Error:** #F44336 (critical states)
- **Surface:** #FAFAFA (light mode), #121212 (dark mode)
- **On Surface:** #212121 (light mode), #FFFFFF (dark mode)

### 10.5 Accessibility (WCAG 2.1 AA)

- All colored indicators must have icon/text fallback
- Min text size: 12pt (14pt preferred)
- Touch targets: min 48dp
- Color contrast: min 4.5:1
- All charts must have data table alternative
- Screen reader labels for all metrics

---

## Appendix: Metric Sources Reference

| Source | Endpoint | Method | Frequency | Cost |
|--------|----------|--------|-----------|------|
| **Firebase Realtime** | `/metrics/dashboard` | Listen + subscribe | 10s-1m | 0.5 read/sec |
| **Firebase Periodic** | `/trades/closed/*` | Query | 30-60s | 1-2 reads |
| **Export JSONL** | `/offline/paper_training_dataset.jsonl` | Download | On-demand | 1 read |
| **Quality Report** | `/offline/quality_report.md/.json` | Download | On-demand | 1 read |
| **Audit Script** | `scripts/p11ag_quality_audit.sh` | SSH exec | Manual | Local only |
| **System Metrics** | `/proc/stat` | File read | 60s | Local only |

---

## Sign-Off

**Contract Author:** CryptoMaster Backend Team  
**Target App:** CryptoMaster Android v1.0  
**Effective Date:** 2026-05-20  
**Review Cycle:** Every 30 days or on trading logic changes

**Next Steps:**
1. ✅ Android team reviews and comments
2. ⏭️ Backend implements Firebase schema
3. ⏭️ Android team builds UI components
4. ⏭️ Integration testing
5. ⏭️ Production release

---

**End of Android Metrics Contract v1.0**
