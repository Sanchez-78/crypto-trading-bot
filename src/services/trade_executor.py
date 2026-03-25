from src.core.event_bus import subscribe, publish
from config import MAX_LOSS_STREAK, MIN_CONFIDENCE, MIN_VOLATILITY
from src.services.realtime_decision_engine import update_from_trade

loss_streaks = {}
active_trades = {}
MAX_ACTIVE_TRADES = 3


@subscribe("signal_created")
def handle_signal(signal):
    try:
        symbol = signal.get("symbol")

        if symbol not in loss_streaks:
            loss_streaks[symbol] = 0

        confidence = signal.get("confidence", 0.5)
        volatility = signal.get("features", {}).get("volatility", 0)

        if len(active_trades) >= MAX_ACTIVE_TRADES:
            return

        if confidence < MIN_CONFIDENCE:
            return

        if volatility < MIN_VOLATILITY:
            return

        if loss_streaks[symbol] >= MAX_LOSS_STREAK:
            return

        trade = {
            "symbol": symbol,
            "action": signal.get("action"),
            "price": signal.get("price"),
            "confidence": confidence,
            "features": signal.get("features", {})
        }

        active_trades[symbol] = trade

        print(f"🚀 TRADE: {trade}")

        result = simulate_trade_result(trade)

        print(f"📊 RESULT: {result}")

        # 🔥 UPDATE MEMORY (bez DB read!)
        update_from_trade(trade, result)

        if result["result"] == "WIN":
            loss_streaks[symbol] = 0
        else:
            loss_streaks[symbol] += 1

        active_trades.pop(symbol, None)

        publish("trade_executed", {
            "trade": trade,
            "result": result
        })

    except Exception as e:
        print("❌ Trade error:", e)


def simulate_trade_result(trade):
    import random

    win_prob = 0.45 + (trade["confidence"] * 0.4)
    is_win = random.random() < win_prob

    profit = random.uniform(0.002, 0.01)

    return {
        "result": "WIN" if is_win else "LOSS",
        "profit": profit if is_win else -profit
    }