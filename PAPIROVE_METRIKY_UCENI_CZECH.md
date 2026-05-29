# V5 PAPÍROVÉ Bot - Metriky Učení a Úspěchu

## Přehled
V5 PAPÍROVÉ Bot nyní expozuje komplexní metriky učení a úspěchu obchodování skrze API endpoint `/metrics/learning-history`. Všechna data obsahují detailní timestampy pro kompletní auditní trail a analýzu.

## Co je dostupné?

### 1. Detailní Historie Každé Transakcije

Pro každou uzavřenou transakci máte:

#### Identifikace
- `trade_id` - Unikátní ID transakce
- `symbol` - Obchodovaný pár (BTCUSDT, ETHUSDT, atd.)
- `entry_side` - Směr (BUY nebo SELL)

#### Časy (ISO8601 formát, UTC)
- `entry_timestamp` - Přesný čas vstupu (např. "2026-05-29T12:34:15Z")
- `exit_timestamp` - Přesný čas výstupu (např. "2026-05-29T12:45:30Z")
- `hold_seconds` - Kolik sekund byla pozice držena (675 vteřin = 11 minut)

#### Ceny a Velikost
- `entry_price` - Cena vstupu (73258.55 pro BTC)
- `exit_price` - Cena výstupu
- `qty` - Objem obchodu (0.1 BTC)
- `entry_notional_usd` - Nominální hodnota vstupu v USD

#### Zisk/Ztráta (PnL)
- `gross_pnl_usd` - Zisk před náklady (16.50 USD)
- `gross_pnl_pct` - Zisk v procentech (0.225%)
- `net_pnl_usd` - Skutečný zisk po všech nákladech (15.30 USD)
- `net_pnl_pct` - Zisk po nákladech v procentech (0.209%)

#### Rozpad Nákladů
- `entry_fee_usd` - Poplatek za vstup (0.65 USD)
- `exit_fee_usd` - Poplatek za výstup (0.55 USD)
- `funding_cost_usd` - Náklady na financování během držení (0.00 USD)
- `total_costs_usd` - Celkové náklady (1.20 USD)

#### Výsledek
- `outcome` - WIN, LOSS, nebo FLAT

### Příklad jedné transakce:
```json
{
  "trade_id": "trade_a1b2c3d4",
  "symbol": "BTCUSDT",
  "entry_side": "BUY",
  "entry_price": 73258.55,
  "exit_price": 73350.25,
  "qty": 0.1,
  "entry_timestamp": "2026-05-29T12:34:15Z",
  "exit_timestamp": "2026-05-29T12:45:30Z",
  "hold_seconds": 675,
  "gross_pnl_usd": 16.50,
  "gross_pnl_pct": 0.225,
  "net_pnl_usd": 15.30,
  "net_pnl_pct": 0.209,
  "total_costs_usd": 1.20,
  "entry_fee_usd": 0.65,
  "exit_fee_usd": 0.55,
  "funding_cost_usd": 0.00,
  "entry_notional_usd": 7325.86,
  "outcome": "WIN"
}
```

---

## 2. Metriky Úspěšnosti PO SYMBOLECH (měna/pár)

Pro každý obchodovaný symbol (BTC, ETH, BNB, atd.) máte:

- `trades_closed` - Kolik transakcí bylo zavřeno
- `wins` - Počet výherních transakcí
- `losses` - Počet prohrávajících
- `flats` - Počet neutrálních (bez zisku/ztráty)
- `win_rate` - Procento výher (0.67 = 67%)
- `total_pnl_usd` - Celkový zisk pro symbol
- `avg_pnl_per_trade` - Průměrný zisk na transakci
- `total_fees_usd` - Celkové poplatky pro symbol
- `best_trade_pnl_usd` - Největší jednoho výhra
- `worst_trade_pnl_usd` - Největší jednoho ztráta

### Příklad shrnutí za BTCUSDT:
```json
{
  "symbol": "BTCUSDT",
  "trades_closed": 3,
  "wins": 2,
  "losses": 1,
  "flats": 0,
  "win_rate": 0.67,
  "total_pnl_usd": 22.50,
  "avg_pnl_per_trade": 7.50,
  "total_fees_usd": 1.20,
  "best_trade_pnl_usd": 15.30,
  "worst_trade_pnl_usd": -3.25
}
```

---

## 3. Celkové Metriky Portfolia

Agregované údaje přes všechny symboly:

- `total_trades_closed` - Celkem uzavřených transakcí (9)
- `total_wins` - Celkem výher (6)
- `total_losses` - Celkem proher (2)
- `total_flats` - Celkem neutrálních (1)
- `win_rate` - Celkové procento výher (0.67 = 67%)
- `total_net_pnl_usd` - Celkový čistý zisk (45.75 USD)
- `total_fees_usd` - Celkové poplatky zaplacené (3.50 USD)
- `avg_pnl_per_trade` - Průměrný zisk na transakci (5.08 USD)
- `timestamp` - Čas sberu dat (ISO8601)

---

## Jak Získat Tato Data?

### HTTP Endpoint
```
GET http://váš-server:5000/metrics/learning-history
```

### Odpověď obsahuje:
1. Celkové metriky (výše)
2. `per_symbol_summary` - Metriky pro každý symbol
3. `closed_trades` - Pole s detaily každé transakcije

### Příklad požadavku (curl):
```bash
curl -X GET http://localhost:5000/metrics/learning-history
```

### Příklad v Androidu (Kotlin):
```kotlin
val learning = api.getLearningHistory()

// Zobrazit celkové metriky
println("Celkový zisk: ${learning.total_net_pnl_usd} USD")
println("Úspěšnost: ${learning.win_rate * 100}%")
println("Uzavřeno transakcí: ${learning.total_trades_closed}")

// Zobrazit metriky pro každý symbol
learning.per_symbol_summary.forEach { (symbol, metrics) ->
    println("$symbol: ${metrics.trades_closed} trades, ${metrics.win_rate * 100}% win rate")
}

// Procházet historii všech transakcí
learning.closed_trades.forEach { trade ->
    println("${trade.symbol}: ${trade.outcome} ${trade.net_pnl_usd} USD")
}
```

---

## Analýzy Které Nyní Můžete Dělat

### 1. Analýza Podle Času
```kotlin
// Třídit transakce podle entry_timestamp
val tradesByTime = learning.closed_trades.sortedBy { it.entry_timestamp }

// Vypočítat win rate za poslední hodinu
val lastHour = Instant.now().minusSeconds(3600)
val recentTrades = tradesByTime.filter { 
    Instant.parse(it.entry_timestamp) > lastHour 
}
val recentWinRate = recentTrades.count { it.outcome == "WIN" } / recentTrades.size.toFloat()
```

### 2. Analýza Podle Symbolu
```kotlin
// Najít symbol s největší výhrou
val bestSymbol = learning.per_symbol_summary
    .maxByOrNull { it.value.total_pnl_usd }
```

### 3. Analýza Nákladů
```kotlin
// Jaké procento zisku snědly poplatky?
val feePercentage = learning.total_fees_usd / learning.total_net_pnl_usd * 100
// Výsledek: 7.6% - poplatky sní 7.6% zisku
```

### 4. Analýza Doby Držení
```kotlin
// Průměrná doba držení pozice
val avgHoldSeconds = learning.closed_trades
    .map { it.hold_seconds }
    .average()
```

### 5. Detekce Best/Worst Trades
```kotlin
val bestTrade = learning.closed_trades.maxByOrNull { it.net_pnl_usd }
val worstTrade = learning.closed_trades.minByOrNull { it.net_pnl_usd }

println("Nejlepší trade: ${bestTrade?.trade_id} +${bestTrade?.net_pnl_usd} USD")
println("Nejhorší trade: ${worstTrade?.trade_id} ${worstTrade?.net_pnl_usd} USD")
```

---

## Integrace do Android Aplikace

### Doporučená Frekvence Aktualizace
- **Celkové metriky**: Každých 2-3 sekund (z `/metrics`)
- **Historie učení**: Každých 10 sekund (z `/metrics/learning-history`)

### Příklad UI Layoutu
```
┌─────────────────────────────┐
│  CELKOVÉ STATISTIKY         │
├─────────────────────────────┤
│ Celkový PnL: 45.75 USD ✓    │
│ Úspěšnost: 67% (6 výher)    │
│ Transakcí: 9 (2 ztráty)     │
│ Poplatky: 3.50 USD (7.6%)   │
└─────────────────────────────┘

┌─────────────────────────────┐
│  PER-SYMBOL SHRNUTÍ         │
├─────────────────────────────┤
│ BTCUSDT: 67% win, +22.50 USD│
│ ETHUSDT: 67% win, +18.25 USD│
│ BNBUSDT: 67% win, +5.00 USD │
└─────────────────────────────┘

┌─────────────────────────────┐
│  HISTORIE TRANSAKCÍ         │
├─────────────────────────────┤
│ ✓ BTC 12:34-12:45 +15.30 USD│
│ ✓ ETH 12:50-13:05 +7.10 USD │
│ ○ BNB 13:10-13:20 -1.08 USD │
│ ✗ BTC 14:00-14:15 -3.25 USD │
│ ... (5 dalších) ...         │
└─────────────────────────────┘
```

---

## Technické Detaily

### Endpoint: GET /metrics/learning-history

**Status kódy:**
- `200 OK` - Data úspěšně vrácena
- `503 Service Unavailable` - Collector není inicializován (bot se spouští)

**Data types:**
- Ceny: float (s desítkovou tečkou)
- Procenta: float (0.67 = 67%)
- Timestampy: ISO8601 string, UTC, s 'Z' suffixem
- Durace: integer sekund

**Příklad kompletní odpovědi:**
```json
{
  "total_trades_closed": 9,
  "total_wins": 6,
  "total_losses": 2,
  "total_flats": 1,
  "win_rate": 0.67,
  "total_net_pnl_usd": 45.75,
  "total_fees_usd": 3.50,
  "avg_pnl_per_trade": 5.08,
  "per_symbol_summary": { /* ... */ },
  "closed_trades": [ /* ... */ ],
  "timestamp": "2026-05-29T13:25:00Z"
}
```

---

## Shrnutí

Nyní máte **kompletní viditelnost** do papírového obchodování:
- ✅ **Časové razítka**: Každá transakce má přesný čas vstupu a výstupu
- ✅ **Úspěšnost**: Procento výher, počty win/loss/flat
- ✅ **Zisk/Ztráta**: Bruto i netto (po nákladech)
- ✅ **Náklady**: Detailní rozpad (entry fee, exit fee, funding)
- ✅ **Per-symbol**: Analýza každého obchodovaného páru
- ✅ **Historie**: Úplná sada všech uzavřených transakcí
- ✅ **Analýzy**: Můžete počítat win rate po čase, best/worst trades, atd.

Vše je dostupné přes jeden API endpoint na http://váš-server:5000/metrics/learning-history
