from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED
from src.services.firebase_client import save_trade
from bot2.learning_event import is_ready

print("💰 Trade Executor READY")


def on_signal(signal):
    print("💰 TRADE EXECUTOR TRIGGERED")

    # 🔥 DOČASNĚ POVOL TRADING (learning mode)
    if not is_ready():
        print("⚠️ FORCE TRADE (learning mode)")

    # 🔥 FIX: features safe
    features = signal.get("features", {})

    trade = {
        "symbol": signal.get("symbol"),
        "action": signal.get("action"),
        "price": signal.get("price"),
        "confidence": signal.get("confidence"),
        "features": features
    }

    print("💰 TRADE EXECUTED:", trade)

    save_trade(trade)

    event_bus.publish(TRADE_EXECUTED, trade)


event_bus.subscribe(SIGNAL_CREATED, on_signal)