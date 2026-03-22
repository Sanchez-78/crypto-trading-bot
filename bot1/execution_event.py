from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED


def on_price_tick(data):
    features = data

    # jednoduchá strategie (napojíš bandit později)
    if features["trend"] != "UP":
        return

    signal = "BUY"
    confidence = 0.7

    # 🔥 REGIME DETEKCE
    if features["volatility"] > 0.7:
        regime = "VOLATILE"
    elif features["trend"] == "UP":
        regime = "TREND"
    else:
        regime = "RANGE"

    # 🔥 FEATURE BUCKET
    vol = features["volatility"]
    vol_bucket = "HIGH" if vol > 0.7 else "MID" if vol > 0.3 else "LOW"

    event_bus.publish(SIGNAL_CREATED, {
        "signal": signal,
        "confidence": confidence,
        "features": features,
        "strategy": "TREND",
        "regime": regime,
        "meta": {
            "feature_bucket": f"{features['trend']}_{vol_bucket}",
            "confidence_raw": confidence
        }
    })


event_bus.subscribe(PRICE_TICK, on_price_tick)