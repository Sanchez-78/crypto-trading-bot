# V5 Android Metrics Contract

## Overview

This document specifies the complete metrics contract for CryptoMaster V5 Android application. All metrics are published to Firebase in the `v5_metrics` and `v5_dashboard` collections and are consumed by the Android app.

**Key Principles:**
- All metric values published to Firebase must be current (< 5 seconds old)
- Czech language labels and descriptions required for operator UI
- Read cost tracking: each metric documents its Firebase cost
- Metrics organized by tab in Android app (5 tabs total)
- Real-time vs. periodically updated metrics clearly labeled

---

## Tab 1: Dashboard

### Overview Metrics

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `dashboard.epoch_id` | Current Epoch | Aktuální Epocha | ID běžící trénovací epochy | string | text | 1/min | 1 read |
| `dashboard.mode` | Trading Mode | Režim Obchodování | "PAPER" (vždy) | string | enum | 1/session | 0 reads |
| `dashboard.paper_only` | Paper Only Flag | Příznak Pouze Papír | true (vždy) | bool | flag | 1/session | 0 reads |
| `dashboard.open_positions_count` | Open Positions | Otevřené Pozice | Počet současně otevřených pozic | count | number | 1/sec | 1 read |
| `dashboard.open_notional_usd` | Open Notional | Otevřená Notionální Hodnota | Celková USD hodnota otevřených pozic | USD | currency | 1/sec | 1 read |
| `dashboard.open_unrealized_pnl_usd` | Unrealized P&L | Nerealizovaný Zisk/Ztráta | Aktuální nerealizovaný P&L across all open positions | USD | currency | 1/sec | 1 read |
| `dashboard.open_unrealized_pnl_pct` | Unrealized P&L % | Nerealizovaný Zisk/Ztráta % | Nerealizovaný P&L as % of entry notional | percent | number | 1/sec | 1 read |

### Daily Statistics

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `daily.trades_opened` | Entries Today | Vstupy Dnes | Počet otevřených pozic dnes | count | number | 1/min | 1 read |
| `daily.trades_closed` | Closes Today | Zavření Dnes | Počet uzavřených obchodů dnes | count | number | 1/min | 1 read |
| `daily.wins` | Winning Trades | Vítězné Obchody | Počet obchodů s pozitivním P&L | count | number | 1/min | 1 read |
| `daily.losses` | Losing Trades | Prohraté Obchody | Počet obchodů se zápornýmPnL | count | number | 1/min | 1 read |
| `daily.flats` | Breakeven Trades | Neutrální Obchody | Počet obchodů s ~0 P&L | count | number | 1/min | 1 read |
| `daily.win_rate_pct` | Win Rate | Procento Vítězství | (wins / total) * 100 | percent | number | 1/min | 0 reads |
| `daily.net_pnl_usd` | Daily P&L | Denní Zisk/Ztráta | Čistý P&L po všech poplatcích dnes | USD | currency | 1/min | 1 read |
| `daily.gross_pnl_usd` | Gross P&L | Hrubý P&L | P&L před poplatky a financováním | USD | currency | 1/min | 1 read |
| `daily.fees_pct_sum` | Total Fees | Celkové Poplatky | Součet všech poplatků jako % vstupu | percent | number | 1/min | 1 read |

---

## Tab 2: Trading Activity

### Current Trade Details

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `trade.last_trade_id` | Last Trade ID | ID Poslední Pozice | ID poslední uzavřené pozice | string | text | 1/sec | 0 reads |
| `trade.last_symbol` | Last Symbol | Poslední Symbol | BTCUSDT, ETHUSDT, apod. | string | enum | 1/sec | 0 reads |
| `trade.last_entry_price` | Last Entry Price | Poslední Vstupní Cena | Cena vstupu poslední pozice | price | currency | 1/sec | 0 reads |
| `trade.last_exit_price` | Last Exit Price | Poslední Výstupní Cena | Cena výstupu poslední pozice | price | currency | 1/sec | 0 reads |
| `trade.last_pnl_usd` | Last Trade P&L | P&L Poslední Pozice | Čistý P&L poslední obchodu | USD | currency | 1/sec | 0 reads |
| `trade.last_pnl_pct` | Last Trade P&L % | P&L Poslední Pozice % | P&L jako % vstupní notionální hodnoty | percent | number | 1/sec | 0 reads |
| `trade.last_hold_seconds` | Last Hold Time | Doba Držení Poslední | Kolik sekund byla pozice otevřena | seconds | number | 1/sec | 0 reads |

### Per-Position Details

For each open position, publish:
- `position.{trade_id}.symbol`
- `position.{trade_id}.side` (BUY/SELL)
- `position.{trade_id}.entry_price`
- `position.{trade_id}.current_mid_price`
- `position.{trade_id}.unrealized_pnl_pct`
- `position.{trade_id}.target_profit_pct`
- `position.{trade_id}.stop_loss_pct`
- `position.{trade_id}.tp_price`
- `position.{trade_id}.sl_price`
- `position.{trade_id}.time_held_seconds`

---

## Tab 3: Strategy Performance

### Strategy Summary

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `strategy.active_strategy` | Active Strategy | Aktivní Strategie | ID aktuálně používané strategie | string | enum | 1/min | 0 reads |
| `strategy.{id}.total_trades` | Strategy Trades | Obchody Strategie | Celkový počet obchodů touto strategií | count | number | 1/min | 1 read |
| `strategy.{id}.win_rate_pct` | Strategy Win Rate | Procento Vítězství | % vítězných obchodů | percent | number | 1/min | 0 reads |
| `strategy.{id}.profit_factor` | Profit Factor | Profit Faktor | wins / losses ratio | ratio | number | 1/min | 0 reads |
| `strategy.{id}.net_expectancy_bps` | Expectancy | Očekávání | Čistá hodnota v basis points | bps | number | 1/min | 0 reads |
| `strategy.{id}.max_drawdown_pct` | Max Drawdown | Max Pokles | Největší snížení od vrcholu | percent | number | 1/min | 1 read |

---

## Tab 4: Firebase Quota & Health

### Quota Status

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `quota.state` | Quota State | Stav Kvóty | NORMAL/WARNING/DEGRADED/CRITICAL/HARD_STOP | string | enum | 1/min | 1 read |
| `quota.daily_reads_remaining` | Reads Remaining | Zbývajících Čtení | Zbývá čtení dnes (z 50,000 denně) | count | number | 1/min | 1 read |
| `quota.daily_writes_remaining` | Writes Remaining | Zbývajících Zápis | Zbývá zápisů dnes (z 20,000 denně) | count | number | 1/min | 1 read |
| `quota.days_until_reset` | Days Until Reset | Dní Do Resetování | Dní do resetování denní kvóty | days | number | 1/day | 0 reads |
| `quota.reset_time_utc` | Reset Time | Čas Resetování | Čas resetování (Midnight PT = 9:00 CET) | datetime | text | 1/session | 0 reads |

### Feed Health

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `health.feed_connected` | Feed Status | Stav Zdroje Dat | true/false | bool | flag | 1/sec | 0 reads |
| `health.symbols_with_data` | Symbols Online | Symboly Online | Počet symbolů se čerstvými daty | count | number | 1/sec | 1 read |
| `health.firebase_connected` | Firebase Status | Stav Firebase | true/false (read from control doc ping) | bool | flag | 1/min | 1 read |
| `health.stale_events_rejected` | Stale Events | Zastaralé Události | Počet zamítnutých zastaralých eventů | count | number | 1/min | 0 reads |

---

## Tab 5: REAL Readiness (Informational)

### Readiness Gates

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `readiness.state` | Readiness State | Stav Připravenosti | 10-state enum (NOT_READY → REAL_REVIEW_READY) | string | enum | 1/min | 1 read |
| `readiness.state_label_cs` | Status (Czech) |状态（捷克語） | Human-readable Czech status message | string | text | 1/min | 0 reads |
| `readiness.eligible_closes` | Eligible Closes | Kvalifikované Zavření | current / required (e.g., "250/300") | count | text | 1/min | 0 reads |
| `readiness.days_of_data` | Days of Data | Dní Dat | current / required (e.g., "5/7") | days | text | 1/min | 0 reads |
| `readiness.expectancy_bps` | Expectancy | Očekávání | Current net expectancy in bps | bps | number | 1/min | 0 reads |
| `readiness.profit_factor` | Profit Factor | Profit Faktor | Current profit factor | ratio | number | 1/min | 0 reads |
| `readiness.max_drawdown_pct` | Max Drawdown | Max Pokles | Current maximum drawdown % | percent | number | 1/min | 1 read |
| `readiness.blocking_reasons_cs` | Issues | Problémy | Array of blocking reasons in Czech | list | text | 1/min | 0 reads |

### Control & Safety

| Metric ID | Display Name (EN) | Display Name (CZ) | Definition (CZ) | Unit | Type | Update Freq | Read Cost |
|-----------|------------------|-------------------|-----------------|------|------|-------------|-----------|
| `control.paper_only` | Paper Mode Only | Režim Pouze Papír | true (always) | bool | flag | 1/session | 0 reads |
| `control.real_orders_allowed` | Real Orders Allowed | REAL Obchody Povoleny | false (always) | bool | flag | 1/session | 0 reads |
| `control.entries_enabled` | Entries Enabled | Vstupy Povoleny | true/false (can be disabled by operator) | bool | flag | 1/min | 1 read |

---

## Publish Schedule

### Real-time (every second, ~1 sec)
- Dashboard open positions and notional
- Current market prices and spreads
- Feed health (symbol count, connection status)

### Frequent (every minute)
- Daily statistics (trades, win rate, P&L)
- Strategy performance aggregates
- Quota status and remaining
- Readiness evaluation
- Control flags

### Periodic (every 5 minutes)
- Max drawdown recalculation
- Historical performance aggregates

### On-demand
- Individual closed trade details (when trade closes)
- Position entry/exit details (when position opens/closes)

---

## Firebase Collection Structure

All metrics published to:

```
v5_dashboard/
  current/
    - epoch_id
    - mode
    - open_positions_count
    - ... (all dashboard metrics)

v5_metrics/
  {metric_id}/
    - value
    - timestamp
    - last_update

v5_quota/
  {quota_date_pt}/
    - state
    - reads_remaining
    - writes_remaining
    - ... (quota metrics)

v5_readiness/
  current/
    - state
    - state_label_cs
    - eligible_closes
    - ... (readiness metrics)
```

---

## Android UI Design (5 Tabs)

### Tab 1: Dashboard
- Large: Open Positions Count
- Large: Open Notional USD
- Card: Daily Win Rate %
- Card: Daily P&L USD
- Card: Daily Trades Closed
- Status: Feed connected?
- Status: Quota state

### Tab 2: Trading Activity
- Last closed trade summary (entry/exit price, P&L)
- List of open positions with live unrealized P&L
- Each position shows: symbol, entry price, current mid, P&L %
- Each position shows: TP price, SL price, seconds held

### Tab 3: Strategy Performance
- Active strategy name
- Total trades, win rate, profit factor, expectancy
- Max drawdown graph (last 30 days)

### Tab 4: Health & Quota
- Feed status (connected/disconnected)
- Firebase quota gauge (reads/writes remaining)
- Quota state indicator (NORMAL/WARNING/DEGRADED/CRITICAL/HARD_STOP)
- Stale events counter
- Reset time countdown

### Tab 5: REAL Readiness
- Large status message in Czech
- 6 gates (eligible closes, days data, expectancy, PF, drawdown, accounting)
- Each gate shows: current / required, PASS/FAIL
- Blocking reasons (if any) in Czech
- Note: "Paper Only - REAL Orders Disabled"

---

## Testing Checklist

- [ ] All metrics publish successfully to Firebase
- [ ] All Czech labels render correctly in Android app
- [ ] Real-time metrics update within 1 second
- [ ] Quota status reflects actual remaining budget
- [ ] Readiness state machine transitions correctly
- [ ] Dashboard displays open positions without stale data
- [ ] Tab 4 quota gauge shows correct state colors
- [ ] All read costs sum to < 200 reads/minute

