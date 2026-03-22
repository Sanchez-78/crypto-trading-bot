class MetaAgent:
    def __init__(self):
        self.bias = 0.0
        self.patterns = {}
        self.last_stats = {"winrate": 0, "avg_profit": 0, "patterns": 0}

    def decide(self, f):
        trend = f.get("trend_strength", 0)
        regime = f.get("market_regime", "RANGE")

        if trend > 0.002:
            action = "BUY"
            conf = 0.6
        elif trend < -0.002:
            action = "SELL"
            conf = 0.6
        else:
            return "HOLD", 0.2

        if regime == "BULL":
            conf += 0.1
        elif regime == "BEAR":
            conf += 0.1

        key = f"{regime}_{round(trend,2)}_{action}"

        if key in self.patterns:
            conf += self.patterns[key]

        conf += self.bias
        conf = max(0, min(conf, 1))

        return action, conf

    def learn_from_history(self, trades):
        if not trades:
            return

        wins = [t for t in trades if t["result"] == "WIN"]
        total = len(trades)

        winrate = len(wins) / total
        avg_profit = sum(t["profit"] for t in trades) / total

        self.bias = (winrate - 0.5) * 0.6 + avg_profit * 3

        self.last_stats = {
            "winrate": winrate,
            "avg_profit": avg_profit,
            "patterns": len(self.patterns),
        }

    def learn_from_compressed(self, trades):
        if not trades:
            return

        wins = [t for t in trades if t["result"] == "WIN"]
        total = len(trades)

        winrate = len(wins) / total
        avg_profit = sum(t["profit"] for t in trades) / total

        self.bias += (winrate - 0.5) * 0.2

        for t in trades:
            f = t["f"]
            key = f"{f['r']}_{round(f['t'],2)}_{t['signal']}"

            if key not in self.patterns:
                self.patterns[key] = 0

            self.patterns[key] += t["profit"]
            self.patterns[key] = max(-1, min(self.patterns[key], 1))

    def get_progress(self):
        score = int(self.last_stats["winrate"] * 100)
        return {**self.last_stats, "score": score, "bias": round(self.bias, 3)}