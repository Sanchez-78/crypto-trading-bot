# Android Firebase Contract

Firestore paths the Android app may read. The bot writes; the app reads only.

---

## Main dashboard document

```
app_metrics/latest
```

The bot writes this document every 30–300 s (throttled, semantic-hash deduped).
The app should listen with `addSnapshotListener` or poll on resume.

---

## Trade history

```
trades  orderBy(timestamp desc).limit(100)
```

Android must not query unlimited trades or recompute dashboard KPIs from raw trades.
All KPIs are pre-computed and ready in `app_metrics/latest`.

---

## Document schema — `app_metrics/latest`

```json
{
  "schema_version": "app_metrics_v1",
  "generated_at": 1746000000.0,
  "source": "cryptomaster_bot",

  "runtime": {
    "trading_mode": "paper_train",
    "paper_mode": true,
    "live_allowed": false,
    "paper_training_enabled": true,
    "safe_mode": false,
    "safe_mode_reason": "",
    "git_sha": "",
    "branch": "",
    "version": ""
  },

  "health": {
    "firebase_available": true,
    "firebase_read_degraded": false,
    "firebase_write_degraded": false,
    "quota_reads": 0,
    "quota_reads_limit": 50000,
    "quota_reads_pct": "0.0%",
    "quota_writes": 0,
    "quota_writes_limit": 20000,
    "quota_writes_pct": "0.0%",
    "reconciliation_verified": true,
    "alerts": []
  },

  "kpis": {
    "all_time_source": "system_stats",
    "window_source": "load_history",

    "trades_total_all_time": 0,
    "wins_all_time": 0,
    "losses_all_time": 0,
    "timeouts_all_time": 0,
    "decisive_trades_all_time": 0,
    "winrate_all_time": 0.0,

    "window_trades": 0,
    "window_wins": 0,
    "window_losses": 0,
    "window_flats": 0,
    "window_decisive_trades": 0,
    "window_winrate": 0.0,

    "profit_factor": 1.0,
    "net_pnl": 0.0,
    "gross_pnl": 0.0,
    "expectancy": 0.0,
    "avg_profit": 0.0,
    "best_trade": 0.0,
    "worst_trade": 0.0,
    "drawdown": 0.0,
    "last_trade_ts": 0.0,
    "since_last_trade_s": null
  },

  "window": {
    "source": "load_history",
    "limit": 500,
    "count": 0,
    "note": "Breakdowns are based on this recent window unless marked otherwise."
  },

  "learning": {
    "progress_to_ready": 0.0,
    "data_maturity": 0.0,
    "edge_detected": false,
    "confidence_momentum": "UNKNOWN",
    "next_milestone": "",
    "hydration_source": "unknown",
    "paper_train_entries_1h": 0,
    "paper_train_closed_1h": 0,
    "paper_train_learning_updates_1h": 0
  },

  "open_positions": {
    "count": 0,
    "items": []
  },

  "symbols_scope": "window",
  "symbols": {},

  "regimes_scope": "window",
  "regimes": {},

  "exits_scope": "window",
  "exits": {},

  "recommendations": {},

  "recent": {
    "recent_window_known": false,
    "recent_window": 0,
    "recent_winrate": null,
    "recent_avg_ev": null
  },

  "app_context_cs": {
    "trades_total_all_time": "Celkový počet uzavřených obchodů z atomického počítadla. Není to jen posledních 500 obchodů.",
    "window_trades": "Počet obchodů v posledním načteném okně pro detailní statistiky.",
    "winrate_all_time": "Úspěšnost z all-time WIN/LOSS počtů, pokud jsou dostupné.",
    "window_winrate": "Úspěšnost v posledním okně obchodů.",
    "profit_factor": "Poměr hrubých zisků vůči hrubým ztrátám. Nad 1.0 systém vydělává, nad 1.5 je zdravější.",
    "net_pnl": "Součet čistého PnL v posledním metrickém okně.",
    "expectancy": "Průměrný očekávaný výsledek jednoho obchodu podle historie v okně.",
    "open_positions": "Aktuálně otevřené paper/live pozice.",
    "recommendation": "Poslední signál bota pro daný symbol. Není to finanční doporučení.",
    "scope": "Symboly, režimy a exity jsou window-scoped, pokud není výslovně uvedeno jinak."
  }
}
```

---

## Field notes

| Field | Scope | Source |
|---|---|---|
| `kpis.trades_total_all_time` | All-time | `system/stats` counter |
| `kpis.window_trades` | Last ≤500 trades | `load_history(limit=500)` |
| `kpis.winrate_all_time` | All-time | computed from all-time wins/losses |
| `kpis.window_winrate` | Window | computed from window trades |
| `kpis.profit_factor` | Window | gross wins / gross losses |
| `kpis.net_pnl` | Window | sum of trade P&L |
| `symbols.*` | Window-scoped | see `symbols_scope` field |
| `regimes.*` | Window-scoped | see `regimes_scope` field |
| `exits.*` | Window-scoped | see `exits_scope` field |
| `recommendations.*` | Real-time | last signal per symbol, may be HOLD |

---

## Czech dashboard labels

```
Počet obchodů celkem         kpis.trades_total_all_time
Obchody v posledním okně     kpis.window_trades
Úspěšnost celkem             kpis.winrate_all_time
Úspěšnost v okně             kpis.window_winrate
Profit factor                kpis.profit_factor
Čistý PnL                    kpis.net_pnl
Otevřené pozice              open_positions.count
Poslední signál              recommendations.<symbol>.action
Doporučení bota              recommendations.<symbol>.action (stale → HOLD)
Režim bota                   runtime.trading_mode
Zdraví Firebase              health.firebase_available
Quota čtení                  health.quota_reads_pct
Quota zápisů                 health.quota_writes_pct
```

---

## Rules for Android app

```
MUST NOT: write trading decisions
MUST NOT: query unlimited trades
MUST NOT: recompute dashboard KPIs from raw trade list
MUST: read KPIs from kpis.* fields only
MUST: treat symbols/regimes/exits breakdowns as window-scoped
MUST: check schema_version field before parsing (current: app_metrics_v1)
```

---

## Kotlin DTO reference (optional)

```kotlin
data class AppMetricsKpis(
    val tradesTotal: Long = 0,
    val winsAllTime: Long = 0,
    val winrateAllTime: Double = 0.0,
    val windowTrades: Long = 0,
    val windowWinrate: Double = 0.0,
    val profitFactor: Double = 1.0,
    val netPnl: Double = 0.0,
    val expectancy: Double = 0.0,
    val sinceLastTradeS: Double? = null
)

data class AppMetricsRuntime(
    val tradingMode: String = "paper_live",
    val paperMode: Boolean = true,
    val liveAllowed: Boolean = false,
    val safeMode: Boolean = false
)
```

---

## Write throttle

- `APP_METRICS_MIN_WRITE_INTERVAL_S` (default 30 s) — minimum between writes
- `APP_METRICS_HEARTBEAT_INTERVAL_S` (default 300 s) — forced write even if unchanged
- Writes skip if Firebase is in degraded mode
- Unchanged snapshots skip (semantic hash, excluding `generated_at` and `age_s` fields)
