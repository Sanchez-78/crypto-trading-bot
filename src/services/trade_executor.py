from src.core.event_bus import subscribe, publish

# =========================
# RISK MANAGEMENT
# =========================
loss_streak = 0
MAX_LOSS_STREAK = 3
MIN_CONFIDENCE = 0.55


# =========================
# EVENT: SIGNAL CREATED
# =========================
@subscribe("signal_created")
def handle_signal(signal):
    global loss_streak

    try:
        print("⚡ TRADE EXECUTOR TRIGGERED")

        if not signal:
            print("⚠️ Empty signal")
            return

        # =========================
        # RISK FILTERS
        # =========================

        confidence = signal.get("confidence", 0.5)

        if confidence < MIN_CONFIDENCE:
            print(f"⚠️ Low confidence ({confidence:.2f}) → skip")
            return

        if loss_streak >= MAX_LOSS_STREAK:
            print(f"🛑 SKIP TRADE (loss streak: {loss_streak})")
            return

        # =========================
        # VALIDACE
        # =========================
        price = signal.get("price")
        if price is None:
            print("❌ Missing price in signal")
            return

        symbol = signal.get("symbol", "UNKNOWN")
        action = signal.get("action", "HOLD")

        # =========================
        # EXECUTION (SIMULACE)
        # =========================
        trade = {
            "symbol": symbol,
            "action": action,
            "price": price,
            "confidence": confidence,
            "features": signal.get("features", {})
        }

        print(f"🚀 TRADE EXECUTED: {trade}")

        # =========================
        # FAKE RESULT (SIMULACE)
        # =========================
        result = simulate_trade_result(trade)

        print(f"📊 RESULT: {result}")

        # =========================
        # LOSS STREAK UPDATE
        # =========================
        if result.get("result") == "WIN":
            loss_streak = 0
        else:
            loss_streak += 1

        print(f"📉 Loss streak: {loss_streak}")

        # =========================
        # EVENTY
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
# SIMULACE TRADE
# =========================
def simulate_trade_result(trade):
    """
    Jednoduchá simulace výsledku.
    Později nahradíš real tradingem nebo backtest logikou.
    """

    import random

    # můžeš vylepšit podle trendu / RSI
    win_probability = 0.5 + (trade["confidence"] - 0.5)

    is_win = random.random() < win_probability

    profit = random.uniform(0.001, 0.01)

    return {
        "result": "WIN" if is_win else "LOSS",
        "profit": profit if is_win else -profit
    }