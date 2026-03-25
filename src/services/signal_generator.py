from src.core.event_bus import subscribe, publish
from src.services.realtime_decision_engine import evaluate_signal

last_prices = {}


@subscribe("price_tick")
def on_price_tick(data):
    try:
        symbol = data.get("symbol")
        price = data.get("price")

        if symbol is None or price is None:
            return

        prev_price = last_prices.get(symbol)
        last_prices[symbol] = price

        if prev_price is None:
            return

        # LOGIKA
        action = "BUY" if price > prev_price else "SELL"

        if not action:
            return  # 🔥 žádný DB call

        signal = {
            "symbol": symbol,
            "action": action,
            "price": price,
            "confidence": 0.6,
            "features": {
                "volatility": data.get("volatility", 0),
                "trend": data.get("trend")
            }
        }

        # 🔥 DECISION ENGINE
        signal = evaluate_signal(signal)

        if signal is None:
            print("❌ Rejected by DB")
            return

        print(f"📡 SIGNAL: {signal}")

        publish("signal_created", signal)

    except Exception as e:
        print("❌ Signal error:", e)