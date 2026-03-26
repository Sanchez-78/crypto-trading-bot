from src.core.event_bus import subscribe, publish
from src.services.learning_event import track_generated, track_filtered

prices = {}
_last_action = {}  # debounce: skip repeat signal for same symbol+direction


def rsi_calc(p):
    gains, losses = [], []
    for i in range(1, len(p)):
        d = p[i] - p[i-1]
        (gains if d > 0 else losses).append(abs(d))
    ag = sum(gains[-14:]) / 14 if gains else 1
    al = sum(losses[-14:]) / 14 if losses else 1
    rs = ag / al if al else 1
    return 100 - (100 / (1 + rs))


def atr_calc(p, n=14):
    diffs = [abs(p[i] - p[i-1]) for i in range(1, len(p))]
    return sum(diffs[-n:]) / n if diffs else 1


def on_price(data):
    track_generated()

    s, p = data["symbol"], data["price"]
    prices.setdefault(s, []).append(p)

    if len(prices[s]) < 30:
        return

    # Keep buffer bounded
    if len(prices[s]) > 100:
        prices[s] = prices[s][-100:]

    hist = prices[s]
    ema_s = sum(hist[-5:]) / 5
    ema_l = sum(hist[-20:]) / 20
    rsi = rsi_calc(hist)
    atr = atr_calc(hist)
    vol = atr / p if p else 0
    ema_diff = ema_s - ema_l

    # Require minimum movement to avoid noise in flat market
    if vol < 0.0003:
        track_filtered()
        return

    # EMA crossover with RSI confirmation (not overbought/oversold)
    if ema_diff > 0 and rsi < 65:
        action = "BUY"
    elif ema_diff < 0 and rsi > 35:
        action = "SELL"
    else:
        track_filtered()
        return

    # Debounce: don't spam same direction for the same symbol
    if _last_action.get(s) == action:
        track_filtered()
        return
    _last_action[s] = action

    # Confidence: EMA separation relative to ATR (how strong is the crossover)
    confidence = min(abs(ema_diff) / (atr * 2), 1.0) if atr else 0.1

    signal = {
        "symbol": s,
        "action": action,
        "price": p,
        "confidence": confidence,
        "features": {
            "ema_diff": ema_diff,
            "rsi": rsi,
            "volatility": vol
        }
    }

    short = s.replace("USDT", "")
    icon = "🟢" if action == "BUY" else "🔴"
    print(f"  {icon} {short} ${p:,.4f} | EMA:{ema_s:.2f}/{ema_l:.2f} RSI:{rsi:.0f} vol:{vol:.4f} → {action} ({confidence:.0%})")

    from src.services.realtime_decision_engine import evaluate_signal
    signal = evaluate_signal(signal)

    if signal:
        publish("signal_created", signal)
    else:
        track_filtered()


subscribe("price_tick", on_price)
