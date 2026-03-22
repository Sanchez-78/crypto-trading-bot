import math

class FeatureEngine:
    def __init__(self):
        self.history = {}

    def update(self, s, p):
        self.history.setdefault(s, []).append(p)
        if len(self.history[s]) > 100:
            self.history[s].pop(0)

    def _ema(self, h, n):
        if len(h) < n:
            return h[-1]
        k = 2 / (n + 1)
        ema = h[-n]
        for x in h[-n:]:
            ema = x * k + ema * (1 - k)
        return ema

    def _std(self, h, n):
        if len(h) < n:
            return 0
        w = h[-n:]
        m = sum(w) / n
        return (sum((x - m) ** 2 for x in w) / n) ** 0.5

    def build(self, s):
        h = self.history.get(s, [])
        if not h:
            return {"price": 0}

        price = h[-1]

        if len(h) < 10:
            return {
                "price": price,
                "trend_strength": 0,
                "vol_10": 0,
                "momentum": 0,
                "market_regime": "RANGE",
            }

        ema_fast = self._ema(h, 5)
        ema_slow = self._ema(h, 20)

        trend = (ema_fast - ema_slow) / price
        vol = self._std(h, 10) / price
        momentum = (h[-1] - h[-5]) / h[-5]

        if trend > 0.002:
            regime = "BULL"
        elif trend < -0.002:
            regime = "BEAR"
        elif vol < 0.001:
            regime = "RANGE"
        else:
            regime = "VOLATILE"

        return {
            "price": price,
            "trend_strength": trend,
            "vol_10": vol,
            "momentum": momentum,
            "market_regime": regime,
        }