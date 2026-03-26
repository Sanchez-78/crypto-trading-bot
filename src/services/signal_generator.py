from src.core.event_bus import subscribe, publish
from src.services.learning_event import track_generated, track_filtered

prices = {}

def rsi_calc(p):
    gains, losses = [], []
    for i in range(1, len(p)):
        d = p[i] - p[i-1]
        (gains if d > 0 else losses).append(abs(d))
    ag = sum(gains[-14:]) / 14 if gains else 1
    al = sum(losses[-14:]) / 14 if losses else 1
    rs = ag / al if al else 1
    return 100 - (100 / (1 + rs))

def on_price(data):
    track_generated()

    s, p = data["symbol"], data["price"]
    prices.setdefault(s, []).append(p)

    if len(prices[s]) < 30:
        return

    ema_s = sum(prices[s][-5:]) / 5
    ema_l = sum(prices[s][-20:]) / 20
    rsi = rsi_calc(prices[s])
    vol = abs(prices[s][-1] - prices[s][-2]) / prices[s][-2]

    if ema_s > ema_l and rsi < 65:
        action = "BUY"
    elif ema_s < ema_l and rsi > 35:
        action = "SELL"
    else:
        track_filtered()
        return

    signal = {
        "symbol": s,
        "action": action,
        "price": p,
        "confidence": abs(ema_s - ema_l) / ema_l,
        "features": {
            "ema_diff": ema_s - ema_l,
            "rsi": rsi,
            "volatility": vol
        }
    }

    from src.services.realtime_decision_engine import evaluate_signal
    signal = evaluate_signal(signal)

    if signal:
        publish("signal_created", signal)
    else:
        track_filtered()

subscribe("price_tick", on_price)