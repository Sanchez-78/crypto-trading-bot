from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED

from src.services.learning_event import get_metrics

print("💰 TRADE EXECUTOR READY")


def on_signal(signal):
    try:
        metrics = get_metrics()

        # 🔥 dynamický threshold
        min_conf = 0.5 + (metrics["loss_streak"] * 0.05)

        if signal["confidence"] < min_conf:
            print(f"⛔ Trade skipped (low confidence {signal['confidence']:.2f} < {min_conf:.2f})")
            return

        trade = {
            "symbol": signal["symbol"],
            "action": signal["action"],
            "price": signal["price"],
            "confidence": signal["confidence"],
            "features": signal.get("features", {})
        }

        print("💰 TRADE EXECUTED:", trade)

        event_bus.publish(TRADE_EXECUTED, trade)

    except Exception as e:
        print("❌ Trade error:", e)


event_bus.subscribe(SIGNAL_CREATED, on_signal)