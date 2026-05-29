# V5 PAPER Bot - Learning & Success Metrics

## Overview
The V5 PAPER Bot now exposes comprehensive learning and trading success metrics through the `/metrics/learning-history` API endpoint. All data includes detailed timestamps for complete audit trail and analysis.

## Learning History Endpoint

**URL:** `GET http://your-server:5000/metrics/learning-history`

### Complete Trade History Data Structure

Each closed trade includes:
- **Trade Identification**: `trade_id`, `symbol`, `entry_side` (BUY/SELL)
- **Entry Details**: `entry_price`, `entry_timestamp` (ISO8601)
- **Exit Details**: `exit_price`, `exit_timestamp` (ISO8601), `hold_seconds` (duration)
- **Quantity & Notional**: `qty`, `entry_notional_usd`
- **Profitability Metrics**:
  - `gross_pnl_usd`: Profit before costs
  - `gross_pnl_pct`: Percentage profit before costs
  - `net_pnl_usd`: Profit after all costs
  - `net_pnl_pct`: Percentage profit after all costs
  - `outcome`: WIN / LOSS / FLAT
- **Cost Breakdown**:
  - `entry_fee_usd`: Exchange fee on entry
  - `exit_fee_usd`: Exchange fee on exit
  - `funding_cost_usd`: Perpetual funding cost during hold
  - `total_costs_usd`: Sum of all costs

### Per-Symbol Success Summary

For each trading symbol, the response includes:
- **Trade Counts**: `trades_closed`, `wins`, `losses`, `flats`
- **Success Rate**: `win_rate` (percentage of winning trades)
- **PnL Metrics**:
  - `total_pnl_usd`: Sum of all net profits for symbol
  - `avg_pnl_per_trade`: Average profit per trade
  - `total_fees_usd`: Total fees paid across all symbol trades
  - `best_trade_pnl_usd`: Largest single win
  - `worst_trade_pnl_usd`: Largest single loss

### Overall Learning Metrics

Portfolio-wide aggregates:
- **Total Trades**: `total_trades_closed`, `total_wins`, `total_losses`, `total_flats`
- **Success Rate**: `win_rate` (overall winning percentage)
- **Total Return**: `total_net_pnl_usd` (sum of all net profits)
- **Cost Analysis**: `total_fees_usd` (total transaction costs)
- **Average Performance**: `avg_pnl_per_trade` (mean profit per trade)

### Example Response Format

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
  "per_symbol_summary": {
    "BTCUSDT": {
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
    },
    "ETHUSDT": { ... },
    "BNBUSDT": { ... }
  },
  "closed_trades": [
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
    },
    { ... more trades ... }
  ],
  "timestamp": "2026-05-29T13:25:00Z"
}
```

## Usage in Android App

### Kotlin Integration

```kotlin
// Fetch learning history
viewModelScope.launch {
    try {
        val learning = api.getLearningHistory()
        
        // Display overall metrics
        binding.totalWins.text = "Wins: ${learning.total_wins}"
        binding.winRate.text = "Win Rate: ${(learning.win_rate ?: 0f) * 100}%"
        binding.totalPnL.text = "Total PnL: $${learning.total_net_pnl_usd}"
        
        // Display per-symbol breakdown
        learning.per_symbol_summary.forEach { (symbol, summary) ->
            displaySymbolMetrics(symbol, summary)
        }
        
        // Display detailed trade history
        learning.closed_trades.forEach { trade ->
            displayTradeHistoryItem(trade)
        }
        
    } catch (e: Exception) {
        showError("Failed to load learning metrics: ${e.message}")
    }
}
```

### Key Analysis Points

1. **Per-Trade Analysis**: Each trade timestamp pair allows:
   - Hold duration analysis (short-term vs swing trades)
   - Cost impact on profitability
   - Entry/exit price comparison for slippage analysis

2. **Per-Symbol Performance**: Identify:
   - Which symbols have highest win rate
   - Which symbols generate most profit
   - Symbol-specific risk (best/worst trades)

3. **Trend Detection**: With timestamps, can calculate:
   - Win rate over time periods
   - Average hold duration evolution
   - Cost efficiency improvement over time

4. **Fee Analysis**: Total costs broken down by:
   - Entry vs exit fees
   - Funding costs (important for long holds)
   - Percentage of profit consumed by fees

## API Update Frequency

Recommended polling interval: **Every 10 seconds**

For real-time trading display, combine with:
- `/metrics` (every 2-3 seconds) - Current status
- `/metrics/learning-history` (every 10 seconds) - Historical analysis

## Integration with Other Metrics

**Complete Dashboard Flow:**
```
Dashboard (/metrics) → Shows current status, open positions, signals
  ↓
Trading Details (/metrics/trading) → Shows entry/exit statistics
  ↓
Learning History (/metrics/learning-history) → Shows complete trade-by-trade analysis
```

## Data Consistency

- Timestamps are in UTC (ISO8601 format)
- All timestamps from same request represent consistent snapshot
- Closed trades are immutable after exit
- Per-symbol summaries are calculated fresh on each request
- No caching - always current state of broker's closed_trades

## Error Handling

```kotlin
// 503 Service Unavailable - Collector not initialized
// Returns: {"error": "Collector not initialized"}

// 200 OK - Always returns valid LearningHistory structure
// Even if no trades closed yet, returns structure with zeros
```

## Example Android UI Flow

1. **Summary Tab**
   - Total PnL, Win Rate, Trade Count
   - Per-symbol cards (BTC, ETH, BNB, etc.)

2. **History Tab**
   - Trade-by-trade list with timestamps
   - Color-coded outcomes (green=WIN, red=LOSS, gray=FLAT)
   - Sortable by: date, symbol, PnL, hold duration

3. **Analytics Tab**
   - Best/worst trades per symbol
   - Average metrics (hold time, PnL, costs)
   - Pie charts: wins vs losses, PnL by symbol

## Summary

V5 PAPER Learning API provides:
- ✅ Complete trade history with all entry/exit timestamps
- ✅ Per-symbol success breakdown (win rate, PnL, fees)
- ✅ Detailed cost analysis (entry fee, exit fee, funding)
- ✅ Trade outcome classification (WIN/LOSS/FLAT)
- ✅ All metrics needed for Android dashboard display
