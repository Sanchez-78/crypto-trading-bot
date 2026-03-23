import random


class MarketProvider:

    def get_features(self):
        return {
            "symbol": "BTCUSDT",
            "price": random.uniform(100, 110),

            "trend": random.choice(["BULL", "BEAR"]),
            "regime": random.choice(["BULL_TREND", "BEAR_TREND", "RANGE"]),
            "volatility": random.choice(["LOW", "NORMAL", "HIGH"]),

            "atr_m15": random.uniform(0.001, 0.01),
            "momentum": random.uniform(-1, 1),
            "volume": random.uniform(0, 1),
        }