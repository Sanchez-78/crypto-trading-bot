from src.core.event_bus import subscribe, publish
from config import MAX_LOSS_STREAK, MIN_CONFIDENCE, MIN_VOLATILITY

# per-symbol tracking
loss_streaks = {}
active_trades = {}
MAX_ACTIVE_TRADES = 3


@subscribe("signal_created")
def handle_signal(signal):
    try:
        print("⚡ TRADE EXECUTOR TRIGGERED")

        if not signal:
            return

        symbol = signal.get("symbol")
        confidence = signal.get("confidence", 0.5)
        volatility = signal.get("features", {}).get("volatility", 0)

        # init symbol state
        if symbol not in loss_streaks:
            loss_streaks[symbol] = 0

        # =========================
        # GLOBAL PORTFOLIO LIMIT
        # =========================
        if len(active_trades) >= MAX_ACTIVE_TRADES:
            print("🛑 MAX ACTIVE TRADES REACHED")
            return

        # =========================
        # FILTERS
        # =========================
        if confidence < MIN_CONFIDENCE:
            print(f"⚠️ Low confidence {symbol}")
            return

        if volatility < MIN_VOLATILITY:
            print(f"⚠️ Low volatility {symbol}")
            return

        if loss_streaks[symbol] >= MAX_LOSS_STREAK:
            print(f"🛑 SKIP {symbol} (loss streak)")
            return

        price = signal.get("price")
        if price is None:
            return

        # =========================
        # EXECUTE
        # =========================
        trade = {
            "symbol": symbol,
            "action": signal.get("action"),
            "price": price,
            "confidence": confidence,
            "features": signal.get("features", {})
        }

        active_trades[symbol] = trade

        print(f"🚀 TRADE EXECUTED: {trade}")

        result = simulate_trade_result(trade)

        print(f"📊 RESULT: {result}")

        # =========================
        # UPDATE LOSS STREAK
        # =========================
        if result["result"] == "WIN":
            loss_streaks[symbol] = 0
        else:
            loss_streaks[symbol] += 1

        print(f"📉 {symbol} loss streak: {loss_streaks[symbol]}")

        # remove active trade
        active_trades.pop(symbol, None)

        # =========================
        # EVENTS
        # =========================
        publish("trade_executed", {
            "trade": trade,
            "result": result
        })

        publish("evaluation_done", {
            "trade": trade,
            "result": result
        })

    except Exception as e:
        print("❌ Trade error:", e)


# =========================
# SIMULATION (IMPROVED)
# =========================
def simulate_trade_result(trade):
    import random

    confidence = trade["confidence"]

    # edge podle confidence
    win_prob = 0.45 + (confidence * 0.4)

    is_win = random.random() < win_prob

    base_profit = random.uniform(0.002, 0.01)

    return {
        "result": "WIN" if is_win else "LOSS",
        "profit": base_profit if is_win else -base_profit
    }

def evaluate_signal(signal):
    history = get_cached_history()

    symbol = signal.get("symbol")
    action = signal.get("action")
    features = signal.get("features", {})

    relevant = [
        t for t in history
        if t.get("symbol") == symbol
        and t.get("action") == action
    ]

    if len(relevant) < 5:
        return signal

    similar = []

    for t in relevant:
        sim = similarity(features, t.get("features", {}))
        if sim > 0.6:
            similar.append(t)

    if len(similar) < 3:
        signal["confidence"] *= 0.9
        return signal

    wins = sum(1 for t in similar if t.get("result") == "WIN")
    losses = sum(1 for t in similar if t.get("result") == "LOSS")

    total = wins + losses
    winrate = wins / total if total else 0.5
    avg_profit = sum(t.get("profit", 0) for t in similar) / total

    print(f"🧠 WR={winrate:.2f} N={total} PnL={avg_profit:.4f}")

    if winrate < 0.45 or avg_profit < 0:
        return None

    signal["confidence"] *= (0.5 + winrate)
    signal["confidence"] = min(signal["confidence"], 1.0)

    return signal