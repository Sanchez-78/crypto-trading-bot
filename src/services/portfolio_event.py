from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, TRADE_CLOSED, PRICE_TICK

# =========================
# STATE
# =========================
open_trades = {}

print("📊 Portfolio service initialized")


# =========================
# OPEN TRADE
# =========================
def handle_signal(data):
    try:
        symbol = data["symbol"]
        price = data["features"]["price"]

        print(f"\n📥 SIGNAL RECEIVED: {symbol}")

        # pokud už máme trade → skip
        if symbol in open_trades:
            print(f"⚠️ Trade already open for {symbol}, skipping")
            return

        trade = {
            "symbol": symbol,
            "entry_price": price,
            "steps": 0,
            "max_pnl": 0,
            "min_pnl": 0,
            "strategy": data.get("strategy"),
            "regime": data.get("regime"),
            "confidence": data.get("confidence")
        }

        open_trades[symbol] = trade

        print(f"📈 OPEN {symbol}")
        print(f"   entry: {price:.4f}")
        print(f"   strategy: {trade['strategy']}")
        print(f"   regime: {trade['regime']}")
        print(f"   confidence: {trade['confidence']:.2f}")

        event_bus.publish(TRADE_OPENED, trade)

    except Exception as e:
        print(f"❌ handle_signal error: {e}")


# =========================
# TRACK & CLOSE TRADE
# =========================
def on_price(data):
    try:
        if not open_trades:
            print("⚪ No open trades")
            return

        print(f"\n🔄 PRICE UPDATE for open trades ({len(open_trades)})")

        for symbol, trade in list(open_trades.items()):

            if symbol not in data:
                print(f"⚠️ No price for {symbol}")
                continue

            trade["steps"] += 1

            current_price = data[symbol]["price"]
            entry = trade["entry_price"]

            pnl = (current_price - entry) / entry

            # track extremes
            trade["max_pnl"] = max(trade["max_pnl"], pnl)
            trade["min_pnl"] = min(trade["min_pnl"], pnl)

            print(f"⏳ {symbol}")
            print(f"   step: {trade['steps']}")
            print(f"   price: {current_price:.4f}")
            print(f"   pnl: {pnl:.5f}")
            print(f"   max: {trade['max_pnl']:.5f}")
            print(f"   min: {trade['min_pnl']:.5f}")

            # =========================
            # CLOSE CONDITIONS (DEBUG)
            # =========================
            reason = None

            if trade["steps"] >= 5:
                reason = "TIME_EXIT"

            elif pnl > 0.002:
                reason = "TAKE_PROFIT"

            elif pnl < -0.002:
                reason = "STOP_LOSS"

            # =========================
            # CLOSE TRADE
            # =========================
            if reason:
                result = "WIN" if pnl > 0 else "LOSS"

                print(f"\n❌ CLOSE {symbol}")
                print(f"   reason: {reason}")
                print(f"   pnl: {pnl:.5f}")
                print(f"   duration: {trade['steps']} ticks")

                event_bus.publish(TRADE_CLOSED, {
                    "trade": trade,
                    "pnl": pnl,
                    "result": result,
                    "reason": reason
                })

                del open_trades[symbol]

    except Exception as e:
        print(f"❌ on_price error: {e}")


# =========================
# DEBUG STATE MONITOR
# =========================
def debug_state():
    print("\n📊 CURRENT PORTFOLIO STATE")
    print(f"Open trades: {len(open_trades)}")

    for symbol, t in open_trades.items():
        print(f" - {symbol}: entry={t['entry_price']} steps={t['steps']}")


# =========================
# SUBSCRIPTIONS (FIXED)
# =========================
event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price)

print("✅ Portfolio event subscriptions ready")