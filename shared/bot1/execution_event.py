from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED

def on_price_tick(data):
    for symbol, f in data.items():

        if "trend" not in f:
            print(f"❌ Missing trend for {symbol}")
            continue

        features = {
            "price": f["price"],
            "trend": f["trend"],
            "volatility": f["volatility"]
        }

        if features["trend"] == "UP":
            signal = "BUY"
            confidence = 0.6 + features["volatility"]
            regime = "TREND"
        else:
            signal = "HOLD"
            confidence = 0.5
            regime = "RANGE"

        print(f"🧠 SIGNAL → {symbol} {signal}")

        event_bus.publish(SIGNAL_CREATED, {
            "symbol": symbol,
            "signal": signal,
            "features": features,
            "confidence": confidence,
            "strategy": "TREND",
            "regime": regime
        })

event_bus.subscribe_once(PRICE_TICK, on_price_tick)