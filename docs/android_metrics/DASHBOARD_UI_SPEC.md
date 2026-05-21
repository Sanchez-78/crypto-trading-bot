# CryptoMaster Android - Specifikace UI Dashboardu

**Verze:** 1.0  
**Cílová platforma:** Android  
**Jazyk UI:** Čeština  
**Refresh:** Real-time + manual refresh  

---

## Architektura Aplikace

Aplikace má **5 hlavních záložek** na spodní navigaci (bottom tab bar):

1. **Dashboard** (Domů)
2. **Obchody** (Trading history & open positions)
3. **Učení** (Learning metrics)
4. **Signály** (Signal pipeline)
5. **Diagnostika** (Advanced diagnostics)

---

## Tab 1: Dashboard (Domů)

Přehled stavu robota na jedné obrazovce.

### Horní panel - Bot Status (fixed sticky header)

```
┌─────────────────────────────────────────┐
│  🤖 CryptoMaster Bot          12:34:56  │
│  [Status Badge] [Mode Badge] [Quota %]   │
└─────────────────────────────────────────┘
```

**Obsah:**
- Bot logo / ikona
- Status badge (Běží ✓ / Paused ⏸ / Chyba ❌) - barvy (green/yellow/red)
- Trading mode (live_real 🔴 / paper_train 🟢 / paper_live 🟡)
- Uptime "12h 34m"
- Last heartbeat "< 5s ago" nebo "OFFLINE"
- Quota progress bar (50% green → 80% yellow → 95% red)

### Karta 1: Zdraví robota

```
┌─────────────────────┐
│ ZDRAVÍ ROBOTA       │
├─────────────────────┤
│ Status: Běží ✓      │
│ Mode: live_real 🔴  │
│ Uptime: 12h 34m     │
│ Git: abc1234        │
│ Market: Připojen ⚡ │
│ Firestore: OK ✓     │
└─────────────────────┘
```

**Akce:** Tap na kartu → detail view se všemi health metricskami

### Karta 2: Trading Summary (Hlavní metriky)

```
┌─────────────────────┐
│ OBCHODOVÁNÍ         │
├─────────────────────┤
│ Obchodů: 127        │
│ Live: 12            │
│ Otevřeno: 3         │
│ Úspěšnost: 55.2% ✓  │
│ Zisk: +12.34% ⬆️    │
│ Max pokles: -8.5%   │
│ Poslední: před 5m   │
└─────────────────────┘
```

**Obsah:**
- Total trades (all)
- Live trades (live_real only)
- Open positions count
- Winrate % (green >55%, yellow 45-55%, red <45%)
- Net PnL % (green if positive)
- Max drawdown % (red if significant)
- Last trade time (relative)

**Akce:** Tap → Historical trades detail

### Karta 3: Learning Health

```
┌─────────────────────┐
│ UČENÍ ROBOTA        │
├─────────────────────┤
│ LM Trades: 184      │
│ Health: 78% ✓       │
│ Cold-start: Hotovo  │
│ Poslední update: 2m │
└─────────────────────┘
```

**Obsah:**
- LM total trades count
- Learning health %
- Cold-start status (Active / Done)
- Last LM update time

**Akce:** Tap → Detailed learning breakdown per symbol/regime

### Karta 4: Market Status

```
┌─────────────────────┐
│ TRŽNÍ DATA          │
├─────────────────────┤
│ Feed: WebSocket ⚡  │
│ Poslední cena: 1s   │
│ Aktivní symboly: 5  │
│ Bid-ask spred: 0.01%│
└─────────────────────┘
```

**Obsah:**
- Feed status (WebSocket / Fallback / Offline)
- Last price age (seconds)
- Active symbols / Total symbols
- Average spread %
- Per-symbol status table (collapsible)

### Karta 5: Firestore Quota

```
┌─────────────────────┐
│ FIRESTORE KVÓTA     │
├─────────────────────┤
│ Čtení: 12,456/50k   │
│ Zbývá: 75% 🟢       │
│ Zápisy: 5,123/20k   │
│ Zbývá: 74% 🟢       │
│ Reset: 09:00 (7h)   │
└─────────────────────┘
```

**Obsah:**
- Read count / limit
- Read % progress bar
- Write count / limit
- Write % progress bar
- Next reset time (countdown)
- Status badge (Normal / Warning / Exhausted)

**Akce:** Tap → Firestore usage history (chart)

### Spodní část - Alerts / Warnings

```
┌─────────────────────┐
│ ⚠️ VAROVÁNÍ          │
├─────────────────────┤
│ • Drawdown halt     │
│   aktivní (-8.5%)   │
│ • Risk budget       │
│   zbývá 15%         │
└─────────────────────┘
```

**Obsah:**
- List aktivních varování (Critical > Warning > Info)
- Barvy: red (critical), yellow (warning), gray (info)
- Max 5 posledních warnings (scroll na vice)

---

## Tab 2: Obchody (Trading)

Detailní pohled na otevřené pozice a historii obchodů.

### Section 1: Otevřené pozice (Live obchody)

```
OTEVŘENÉ POZICE (3)
┌──────────────────────┐
│ BTCUSDT | BUY        │
│ Entry: 42,500        │
│ Current: 42,650 ⬆️   │
│ PnL: +0.35% 🟢       │
│ Hold: 5m 23s         │
│ TP: 42,800 (0.7%)    │
│ SL: 42,300 (-0.5%)   │
│ Bucket: C_WEAK_EV    │
│ Size: $500           │
└──────────────────────┘
┌──────────────────────┐
│ ETHUSDT | SELL       │
│ Entry: 2,350         │
│ Current: 2,340 ⬇️    │
│ PnL: -0.43% 🔴       │
│ Hold: 2m 15s         │
│ TP: 2,320 (1.3%)     │
│ SL: 2,380 (-1.3%)    │
│ Bucket: D_NEG_PROBE  │
│ Size: $400           │
└──────────────────────┘
```

**Obsah na pozici:**
- Symbol + Side (BUY/SELL)
- Entry price
- Current price + direction arrow
- Unrealized PnL % (barva based on sign)
- Hold time
- TP/SL levels s distancí %
- Regime + Bucket
- Size in USD
- Distance to TP / SL (progress bar)

**Akce:**
- Tap na pozici → Detail view s full order history a price chart
- Long-press → Možnost ručně zavřít (pokud enabled)
- Swipe-right → Quick actions

---

### Section 2: Trade History (Completed trades)

Scrollovatelný list posledních N obchodů.

```
HISTORIA OBCHODŮ (127)
Filtr: [Všechny ▼] [30 dní ▼]

┌──────────────────────┐
│ #1245 BTCUSDT BUY    │
│ Entry: 42,500        │
│ Exit: 42,750         │
│ PnL: +0.59% 🟢       │
│ Hold: 12m 30s        │
│ Exit reason: TP      │
│ MFE: +1.2%  MAE: -0.3%
│ Date: 2026-05-19 14:32
└──────────────────────┘

┌──────────────────────┐
│ #1244 ETHUSDT SELL   │
│ Entry: 2,350         │
│ Exit: 2,340          │
│ PnL: -0.43% 🔴       │
│ Hold: 5m 45s         │
│ Exit reason: Timeout │
│ MFE: +0.1%  MAE: -1.2%
│ Date: 2026-05-19 14:15
└──────────────────────┘
```

**Obsah na obchodu:**
- Trade ID
- Symbol + Side
- Entry/Exit prices
- PnL % (barva)
- Hold time
- Exit reason (TP / SL / Timeout / Manual)
- MFE / MAE (max favorable/adverse move)
- Timestamp

**Filtry:**
- Mode: Live / Paper / All
- Time range: 24h / 7d / 30d / All
- Status: Win / Loss / Flat

**Akce:**
- Tap → Detail view s:
  - Full order details
  - Entry/exit candles
  - Attribution analysis (fee, direction, volatility)
  - Learning metrics (bucket, calibration status)

---

## Tab 3: Učení (Learning)

LearningMonitor state a progress.

### Section 1: Learning Overview

```
STAV UČENÍ
┌─────────────────────┐
│ LM Trades: 184      │
│ Health: 78% ✓       │
│ Cold-start: Done ✓  │
│ Vůči live: 92%      │
└─────────────────────┘
```

### Section 2: Per-Symbol Learning Stats

```
STATISTIKY PER SYMBOL
┌──────────────────────────┐
│ BTCUSDT                  │
│ Trades: 52               │
│ Win-rate: 56% ✓          │
│ Avg PnL: +0.23%          │
│ Sample quality: 92%      │
│ EV estimate: +0.15%      │
└──────────────────────────┘

┌──────────────────────────┐
│ ETHUSDT                  │
│ Trades: 38               │
│ Win-rate: 52%            │
│ Avg PnL: +0.08%          │
│ Sample quality: 78%      │
│ EV estimate: +0.05%      │
└──────────────────────────┘
```

**Obsah:**
- Symbol
- Number of trades
- Win-rate %
- Avg PnL per trade
- Sample quality score (data sufficiency)
- EV estimate

**Akce:**
- Tap na symbol → Detailed learning breakdown (per regime)

### Section 3: Regime Breakdown

```
REŽIMY (na BTCUSDT)
┌───────────────────────┐
│ TRENDING              │
│ Trades: 32            │
│ WR: 58% ✓             │
│ Avg: +0.28%           │
│ Confidence: 87%       │
└───────────────────────┘

┌───────────────────────┐
│ CHOPPY                │
│ Trades: 20            │
│ WR: 52%               │
│ Avg: +0.14%           │
│ Confidence: 64%       │
└───────────────────────┘
```

**Obsah:**
- Regime name
- Trade count
- Win-rate
- Avg PnL
- Confidence (% to recommend tuning)

---

## Tab 4: Signály (Signals)

Real-time signal flow monitoring.

### Section 1: Signal Stats

```
GENERACE SIGNÁLŮ
┌─────────────────────┐
│ Dnes: 247 signálů   │
│ Přijato: 12 (4.8%)  │
│ Zamítáno: 235       │
│ Zamítnutí míra: 95% │
│ Poslední: před 2s   │
└─────────────────────┘
```

**Obsah:**
- Total signals today
- Accepted signals
- Rejected signals
- Reject rate %
- Last signal time

### Section 2: Rejection Breakdown

```
DŮVODY ZAMÍTNUTÍ
┌────────────────────┐
│ Negative EV: 145   │
│   (58%)            │
│ Score gate: 67     │
│   (27%)            │
│ Risk block: 18     │
│   (7%)             │
│ Other: 5 (2%)      │
└────────────────────┘
```

**Obsah:** Pie chart + list rejection reasons

### Section 3: Recent Signals (Live stream)

```
POSLEDNÍ SIGNÁLY (real-time)
┌───────────────────────┐
│ 14:32 BTCUSDT BUY     │
│ EV: +0.24% ✓          │
│ Decision: TAKE ✓      │
│ Score: 0.78           │
│ Confidence: 87%       │
│ Age: 0s (LIVE)        │
└───────────────────────┘

┌───────────────────────┐
│ 14:31 ETHUSDT BUY     │
│ EV: -0.12% ❌         │
│ Decision: REJECT      │
│ Reason: NEGATIVE_EV   │
│ Age: 1s               │
└───────────────────────┘
```

**Obsah:**
- Symbol + Side
- EV value
- Decision + status
- Score
- Rejection reason (if rejected)
- Time (age)

**Akce:**
- Auto-scroll new signals
- Tap na signal → Detail s full analysis
- Filter by acceptance / rejection

---

## Tab 5: Diagnostika (Advanced)

Pro diagnostiku a debug.

### Section 1: State Mismatches

```
STATE MISMATCHES
┌─────────────────────┐
│ LM Mismatch: 0 ✓    │
│ Firebase Sync: OK   │
│ Paper vs Live: OK   │
│ Quota vs Reality: OK│
└─────────────────────┘
```

### Section 2: Error Logs

```
RECENT ERRORS
┌────────────────────┐
│ [ERROR] 14:25      │
│ Trade timeout      │
│ Trade #1243        │
│ Hold 305s > 300s   │
│ Force-closed       │
└────────────────────┘

┌────────────────────┐
│ [WARNING] 14:10    │
│ Quota warning      │
│ Reads: 45,000/50k  │
│ 90% exhausted      │
└────────────────────┘
```

**Obsah:**
- Timestamp
- Log level (ERROR / WARNING / INFO)
- Message
- Relevant trade/symbol
- Action taken

### Section 3: Audit Results

```
POSLEDNÍ AUDIT
┌──────────────────────┐
│ Čas: 2026-05-19 14:00
│ Okno: 60 minut       │
│                      │
│ PAPER TRAINING       │
│ Entries: 48          │
│ Closed: 3            │
│ Win-rate: 66% ✓      │
│ Econ attrib:         │
│ - Fee: 40%           │
│ - Dir: 35%           │
│ - Vol: 25%           │
│                      │
│ LEARNING             │
│ Total: 184 trades    │
│ Health: 78%          │
│ State mismatch: 0 ✓  │
│                      │
│ MARKET               │
│ Downtime: 0s         │
│ Feed status: WebSocket
│                      │
│ QUOTA                │
│ Reads: 12,456/50k    │
│ Zbývá: 75%           │
└──────────────────────┘
```

**Obsah:** Nejnovější audit report (agregovaný z p11ag_quality_audit.sh)

**Akce:**
- Refresh audit (spustí manualně skript)
- Download audit report (JSON/CSV)

---

## Globální Features

### Refresh Behavior

- **Auto refresh:** Všechny tab se refreshují každých 10-30 sekund (konfigurovatelné)
- **Real-time:** Dashboard a Signals tab pushují nová data ihned
- **Manual refresh:** Pull-to-refresh na všech tabech
- **Freshness indicator:** Malá ikona "5s ago" / "Updated" u každé metriky

### Empty / Offline States

```
╔────────────────────╗
│  🤖 Offline        │
│                    │
│  Bot neodpovídá    │
│  Poslední kontakt: │
│  12m 34s zpět      │
│                    │
│  [Reconnect]       │
│  [Settings]        │
╚────────────────────╝
```

### Error States

```
╔────────────────────╗
│  ⚠️ Chyba          │
│                    │
│  Firestore error   │
│  429 Too Many Reqs │
│                    │
│  [Retry]           │
│  [Offline Mode]    │
╚────────────────────╝
```

### Settings (in app menu)

- Refresh rate (10s / 30s / 60s)
- Auto-scroll signals (on/off)
- Push notifications (enabled/disabled)
- Offline cache (enable/disable)
- Time zone
- Language (CS / EN)
- Security PIN / biometric lock

---

## Performance & Quota Management

### API Calls Per Minute

- **Dashboard:** 1 call/10s (6 calls/min)
- **Trading:** 1 call/10s (6 calls/min)
- **Learning:** 1 call/30s (2 calls/min)
- **Signals:** Real-time stream (WebSocket) or 1 call/5s
- **Diagnostics:** Manual only

**Total:** ~15-20 Firebase reads/min normal operation
**Daily:** ~21,600-28,800 reads = well within 50k daily limit

### Caching Strategy

- **Hot data (< 5 min old):** Cache locally
- **Warm data (< 1 hour):** Cache with expiry
- **Cold data (trades history):** Paginate on demand
- **Offline cache:** Last known state (5 min TTL)

---

**Konec UI specifikace V1.0**
