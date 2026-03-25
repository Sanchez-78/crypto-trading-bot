from src.core.event_bus import subscribe, publish
from src.services.learning_event import update_metrics
from src.services.realtime_decision_engine import update_from_trade
import random

print("💰 TRADE EXECUTOR READY")


# =========================
# EXECUTE TRADE
# =========================
def handle_signal(signal):
    if signal is None:
        print("⛔ Signal blocked")
        return

    try:
        print("🚀 TRADE EXECUTOR TRIGGERED")

        symbol = signal.get("symbol")
        action = signal.get("action")
        price = signal.get("price")
        confidence = signal.get("confidence", 0.5)

        if price is None:
            print("❌ Missing price → skip")
            return

        # =========================
        # SIMULACE TRADE (zatím)
        # =========================
        trade = {
            "symbol": symbol,
            "action": action,
            "price": price,
            "confidence": confidence,
            "features": signal.get("features", {})
        }

        print(f"💰 EXECUTING {action} {symbol} @ {price:.2f} | conf={confidence:.2f}")

        # fake výsledek (zatím)
        outcome = random.random()

        if outcome > 0.5:
            profit = random.uniform(0.001, 0.01)
            result = "WIN"
        else:
            profit = -random.uniform(0.001, 0.01)
            result = "LOSS"

        result_data = {
            "result": result,
            "profit": profit
        }

        print(f"📊 RESULT: {result} | PnL={profit:.4f}")

        # =========================
        # UPDATE SYSTEMŮ
        # =========================
        update_metrics(trade, result_data)
        update_from_trade(trade, result_data)

        # =========================
        # EVENT
        # =========================
        publish("trade_executed", {
            **trade,
            **result_data
        })

    except Exception as e:
        print("❌ Trade error:", e)


# =========================
# SUBSCRIBE
# =========================
subscribe("signal_created", handle_signal)