# Cycle 20: Root Cause Analysis — Market Stream Price Feed

## Summary

Cycle 19 showed that despite fixing TP/SL distance display, P&L **degraded 100x** (-$0.09 → -$8.19) and TP exits remained 0. Investigation revealed:

**PRIMARY FINDING: last_price is frozen at entry_price on all open positions.**

Example from Cycle 19 API:
```
Position: BTCUSDT BUY entry_price=66580.00 last_price=66580.00 hold_s=508
Position: ETHUSDT BUY entry_price=1795.76 last_price=1795.76 hold_s=438
Position: SOLUSDT SELL entry_price=208.00 last_price=208.00 hold_s=226
```

All show: `current_price == entry_price` exactly, no movement over 500+ seconds.

## Root Cause Chain

1. **TP/SL evaluation (paper_trade_executor.py:1930-1934)** requires `current_price` to diverge from entry
   - If price doesn't move, TP/SL never fires
   - Everything times out at 600s with pnl_pct ≈ 0 (no edge)

2. **update_paper_positions() updates last_price (line 1911)** only if:
   - `symbol_prices` dict contains live price for symbol
   - `current_price > 0` (guard at line 1904)
   
3. **on_price(data) feeds symbol_prices via _price_cache (trade_executor.py:3029)**
   - Registers on "price_tick" event
   - Accumulates prices in dict keyed by symbol

4. **market_stream.py publishes price_tick (line 62)** only if:
   - Binance REST API returns valid `bidPrice` and `askPrice` (line 157)
   - Both bid > 0 and ask > 0 (guard at line 157)
   - Fallback: CoinGecko returns midprice (line 226)

5. **If market_stream publishes 0 prices or no prices:**
   - on_price never fires or fires with 0 price
   - _price_cache stays empty or contains 0s
   - update_paper_positions() skips positions (continue at line 1905)
   - last_price never updates
   - Positions sit at entry_price until timeout

## Diagnostic Evidence

**Cycle 18 logs would show:**
```
[UPDATE_PAPER_DEBUG] Called XXXx in last 10s, prices=7
```
This says "7 symbols in cache" — caches ARE being populated.

**BUT Cycle 19 shows:**
- `last_price == entry_price` on 25+ positions
- No [TP_SL_HIT] logs (line 1938 never fires)
- 42/44 closes are TIMEOUT, 2 are SL (no TP)

**Possible Scenario:** Binance REST API is blocked/returning 0 prices → market_stream falls back to CoinGecko → CoinGecko returns same price (no change) → on_price fires with price = entry_price → positions never move.

## Next Cycle Action (Cycle 21)

1. **Check market_stream logs:**
   ```bash
   journalctl -u cryptomaster.service --since "30 min ago" | grep -E "Binance|CoinGecko|_dispatch|price_tick"
   ```
   - Did Binance poll succeed?
   - Did CoinGecko fallback trigger?
   - Are prices changing or static?

2. **Check update_paper_positions debug log:**
   ```bash
   journalctl | grep "UPDATE_PAPER_DEBUG"
   ```
   - How many prices arrive per call?
   - Are prices > 0?

3. **If market_stream is broken:**
   - Reconnect Binance WebSocket (use it instead of REST poll)
   - Verify CoinGecko API is accessible
   - Add logging to market_stream._dispatch to see drop rate

4. **If prices ARE flowing but still equal entry_price:**
   - May be price staleness issue in market_stream caching
   - May be symbol mismatch (e.g., "BTC" vs "BTCUSDT")
   - Add explicit log: `track_price()` and compare to entry_price

## Files Involved

- `src/services/market_stream.py` — Price feed publisher
- `src/services/trade_executor.py:3029` — on_price hook
- `src/services/paper_trade_executor.py:1832` — update_paper_positions()
- `simple_dashboard.py:175` — Dashboard display (COSMETIC FIX APPLIED)
