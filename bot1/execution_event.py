from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED


# =========================
# SIGNAL GENERATION
# =========================
def on_price_tick(data):
    try:
        # data = {
        #   "BTCUSDT": {"price":..., "trend":..., "volatility":...},
        #   ...
        # }

        for symbol, f in data.items():

            # =========================
            # VALIDACE (hlavní fix!)
            # =========================
            if "price" not in f or "trend" not in f or "volatility" not in f:
                print(f"⚠️ Missing fields for {symbol}: {f}")
                continue

            features = {
                "price": f["price"],
                "trend": f["trend"],
                "volatility": f["volatility"]
            }

            # =========================
            # SIMPLE STRATEGY (TREND)
            # =========================
            if features["trend"] == "UP":
                signal = "BUY"
                confidence = 0.6 + features["volatility"]
                regime = "TREND"
            else:
                signal = "HOLD"
                confidence = 0.5
                regime = "RANGE"

            # =========================
            # DEBUG
            # =========================
            print(f"🔹 SIGNAL: {symbol} {signal} | price={features['price']:.2f} | trend={features['trend']} | vol={features['volatility']:.4f}")

            # =========================
            # EVENT → další pipeline
            # =========================
            event_bus.publish(SIGNAL_CREATED, {
                "symbol": symbol,
                "signal": signal,
                "features": features,
                "confidence": confidence,
                "strategy": "TREND",
                "regime": regime,
                "meta": {}
            })

    except Exception as e:
        print(f"❌ execution error: {e}")


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(PRICE_TICK, on_price_tick)