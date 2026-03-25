from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED

from src.services.learning_event import is_ready

print("💰 TRADE EXECUTOR READY")


def handle_signal(signal):
    print("💰 TRADE EXECUTOR TRIGGERED")

    try:
        # =========================
        # SAFE DATA EXTRACTION
        # =========================
        symbol = signal.get("symbol")
        action = signal.get("action")
        price = signal.get("price")
        confidence = signal.get("confidence", 0)
        features = signal.get("features", {})

        # ❌ FIX: missing price
        if price is None:
            print("❌ Missing price in signal:", signal)
            return

        # =========================
        # LEARNING MODE LOGIC
        # =========================
        if not is_ready():
            print("📚 FORCE TRADE (learning mode)")
        else:
            print("🚀 REAL TRADE MODE")

        # =========================
        # SIMULATED TRADE
        # =========================
        trade = {
            "symbol": symbol,
            "action": action,
            "price": price,
            "confidence": confidence,
            "features": features,
        }

        print("💰 TRADE EXECUTED:", trade)

        # =========================
        # 🔥 BONUS: PUBLISH EVENT
        # =========================
        event_bus.publish(TRADE_EXECUTED, trade)

    except Exception as e:
        print("❌ Handler error in handle_signal:", e)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(SIGNAL_CREATED, handle_signal)