from src.core.event_bus import subscribe, publish
from src.services.decision_engine import evaluate_signal
import random

last_price = {}
history = {}


# =========================
# HELPER: EMA
# =========================
def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = values[0]

    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)

    return ema_val


# =========================
# HELPER: RSI
# =========================
def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
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
# EVENT: PRICE TICK
# =========================
@subscribe("price_tick")
def on_price_tick(data):
    symbol = data.get("symbol")
    price = data.get("price")

    if not symbol or price is None:
        return

    # uložit historii
    if symbol not in history:
        history[symbol] = []

    history[symbol].append(price)

    if len(history[symbol]) > 100:
        history[symbol] = history[symbol][-100:]

    prices = history[symbol]

    # =========================
    # FEATURES
    # =========================
    ema_short = ema(prices, 5)
    ema_long = ema(prices, 20)
    rsi_val = rsi(prices)

    if ema_short is None or ema_long is None or rsi_val is None:
        return

    features = {
        "ema_short": ema_short,
        "ema_long": ema_long,
        "rsi": rsi_val
    }

    # =========================
    # SIGNAL LOGIC
    # =========================
    action = None

    if ema_short > ema_long and rsi_val < 70:
        action = "BUY"
    elif ema_short < ema_long and rsi_val > 30:
        action = "SELL"

    if not action:
        return

    signal = {
        "symbol": symbol,
        "action": action,
        "confidence": 0.6,
        "price": price,
        "features": features
    }

    # =========================
    # 🧠 DECISION ENGINE
    # =========================
    signal = evaluate_signal(signal)

    if signal is None:
        print("❌ Signal rejected by decision engine")
        return

    print(f"🚀 SIGNAL: {signal}")

    publish("signal_created", signal)