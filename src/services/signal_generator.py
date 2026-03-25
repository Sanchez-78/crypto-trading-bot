from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED

print("📊 SIGNAL GENERATOR (SMART) READY")

price_history = []
MAX_HISTORY = 50


def ema(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    gains, losses = [], []

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


def on_price_tick(data):
    try:
        price = data.get("price")
        if price is None:
            return

        price_history.append(price)
        if len(price_history) > MAX_HISTORY:
            price_history.pop(0)

        ema_short = ema(price_history, 5)
        ema_long = ema(price_history, 15)
        rsi_val = rsi(price_history)

        if ema_short is None or ema_long is None or rsi_val is None:
            return

        # =========================
        # 🎯 SCORING SYSTEM
        # =========================
        score = 0

        if ema_short > ema_long:
            score += 1
        else:
            score -= 1

        if rsi_val < 30:
            score += 1
        elif rsi_val > 70:
            score -= 1

        # =========================
        # 🚫 FILTER (NO RANDOM!)
        # =========================
        if score >= 1 and rsi_val < 65:
            action = "BUY"
        elif score <= -1 and rsi_val > 35:
            action = "SELL"
        else:
            return  # ❗ žádný trade

        confidence = min(0.5 + abs(score) * 0.25, 0.9)

        signal = {
            "symbol": data.get("symbol", "BTCUSDT"),
            "action": action,
            "price": price,
            "confidence": confidence,
            "features": {
                "ema_short": ema_short,
                "ema_long": ema_long,
                "rsi": rsi_val,
                "score": score,
                "volatility": data.get("volatility", 0)
            }
        }

        print("🧠 SMART SIGNAL:", signal)

        event_bus.publish(SIGNAL_CREATED, signal)

    except Exception as e:
        print("❌ Signal error:", e)


event_bus.subscribe(PRICE_TICK, on_price_tick)