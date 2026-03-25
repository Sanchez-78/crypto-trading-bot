from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED

import random

print("📊 SIGNAL GENERATOR READY")

# =========================
# STORAGE
# =========================
price_history = []

MAX_HISTORY = 50


# =========================
# HELPERS
# =========================
def safe_ema(prices, period):
    if len(prices) < period:
        return None

    return sum(prices[-period:]) / period


def safe_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# =========================
# MAIN SIGNAL LOGIC
# =========================
def on_price_tick(data):
    try:
        price = data.get("price")

        # 🔥 HARD GUARD
        if price is None:
            print("❌ Missing price in market data:", data)
            return

        # =========================
        # STORE PRICE
        # =========================
        price_history.append(price)

        if len(price_history) > MAX_HISTORY:
            price_history.pop(0)

        # =========================
        # COMPUTE FEATURES
        # =========================
        ema_short = safe_ema(price_history, 5)
        ema_long = safe_ema(price_history, 15)
        rsi = safe_rsi(price_history)

        # 🔥 WAIT UNTIL READY
        if ema_short is None or ema_long is None or rsi is None:
            print("⏳ Waiting for indicators...")
            return

        # =========================
        # STRATEGY
        # =========================
        if ema_short > ema_long and rsi < 70:
            action = "BUY"
        elif ema_short < ema_long and rsi > 30:
            action = "SELL"
        else:
            action = random.choice(["BUY", "SELL"])

        confidence = 0.6 + random.random() * 0.2

        signal = {
            "symbol": data.get("symbol", "BTCUSDT"),
            "action": action,
            "price": price,
            "confidence": confidence,
            "features": {
                "ema_short": ema_short,
                "ema_long": ema_long,
                "rsi": rsi,
                "volatility": data.get("volatility", 0)
            }
        }

        print("🧠 SMART SIGNAL:", signal)

        event_bus.publish(SIGNAL_CREATED, signal)

    except Exception as e:
        print("❌ Handler error in generate_signal:", e)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(PRICE_TICK, on_price_tick)