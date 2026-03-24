from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED
from src.services.firebase_client import save_signal

print("📡 Signal Generator (SMART) READY")

prices = []

EMA_SHORT = 5
EMA_LONG = 14
RSI_PERIOD = 14


# =========================
# INDICATORS
# =========================
def ema(data, period):
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    ema_val = data[0]
    for price in data[1:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(data, period=14):
    if len(data) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period if gains else 0
    avg_loss = sum(losses[-period:]) / period if losses else 0

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# =========================
# SIGNAL LOGIC
# =========================
def generate_signal(price):
    prices.append(price)

    if len(prices) < EMA_LONG:
        return None

    ema_s = ema(prices[-EMA_LONG:], EMA_SHORT)
    ema_l = ema(prices[-EMA_LONG:], EMA_LONG)
    rsi_val = rsi(prices, RSI_PERIOD)

    if not ema_s or not ema_l or not rsi_val:
        return None

    # =========================
    # STRATEGY
    # =========================
    if ema_s > ema_l and rsi_val < 70:
        action = "BUY"
        confidence = 0.6 + (ema_s - ema_l) / ema_l

    elif ema_s < ema_l and rsi_val > 30:
        action = "SELL"
        confidence = 0.6 + (ema_l - ema_s) / ema_l

    else:
        return None

    confidence = min(max(confidence, 0.55), 0.9)

    return {
        "symbol": "BTC",
        "action": action,
        "confidence": confidence,
        "price": price,
        "features": {
            "ema_short": ema_s,
            "ema_long": ema_l,
            "rsi": rsi_val
        }
    }


# =========================
# EVENT
# =========================
def on_price_tick(data):
    print("📡 RAW:", data)

    if isinstance(data, dict) and "BTC" in data:
        price = data["BTC"].get("price")
    else:
        return

    print("📡 PRICE:", price)

    signal = generate_signal(price)

    if signal:
        print("🚀 SMART SIGNAL:", signal)

        save_signal(signal)
        event_bus.publish(SIGNAL_CREATED, signal)


event_bus.subscribe(PRICE_TICK, on_price_tick)