from src.services.fx_service import get_usd_to_czk


class MetaAgent:
    def __init__(self):
        self.bias = 0.0
        self.patterns = {}

        self.usd_to_czk = 23.0
        self.account_size = 1000

        self.last_stats = {
            "winrate": 0,
            "avg_profit": 0,
            "patterns": 0
        }

        print("🧠 MetaAgent ready (STATE-DRIVEN)")

    # ---------------- DECISION ----------------
    def decide(self, features):
        price = features.get("price", 0)
        if not price:
            return "HOLD", 0.0

        m15 = features.get("m15_trend", 0)
        h1 = features.get("h1_trend", 0)
        h4 = features.get("h4_trend", 0)

        vol = (
            features.get("m15_volatility", 0) +
            features.get("h1_volatility", 0) +
            features.get("h4_volatility", 0)
        )

        regime = features.get("market_regime", "RANGE")
        trend_score = m15 + h1 + h4

        # BASE
        if trend_score >= 2:
            action = "BUY"
            confidence = 0.6
        elif trend_score <= -2:
            action = "SELL"
            confidence = 0.6
        else:
            action = "HOLD"
            confidence = 0.3

        # REGIME LOGIC
        if regime == "BULL":
            if action == "BUY":
                confidence += 0.15
            elif action == "SELL":
                confidence -= 0.1

        elif regime == "BEAR":
            if action == "SELL":
                confidence += 0.15
            elif action == "BUY":
                confidence -= 0.1

        elif regime == "RANGE":
            if action != "HOLD":
                confidence -= 0.15

        elif regime == "VOLATILE":
            confidence *= 0.7

        # PATTERN MEMORY
        key = f"{regime}_{trend_score}_{vol}_{action}"
        if key in self.patterns:
            confidence += self.patterns[key]

        confidence += self.bias
        confidence = max(0, min(confidence, 1))

        return action, confidence

    # ---------------- LEARNING ----------------
    def learn_from_history(self, trades):
        if not trades:
            return

        self.usd_to_czk = get_usd_to_czk()

        wins = [t for t in trades if t.get("result") == "WIN"]
        losses = [t for t in trades if t.get("result") == "LOSS"]

        total = len(wins) + len(losses)
        if total == 0:
            return

        winrate = len(wins) / total

        profits = [t.get("profit", 0) for t in trades]
        avg_profit = sum(profits) / len(profits) if profits else 0

        # GLOBAL BIAS
        self.bias = (winrate - 0.5) * 0.6 + avg_profit * 3
        self.bias = max(-0.4, min(self.bias, 0.4))

        # PATTERN LEARNING
        for t in trades:
            f = t.get("features", {})
            action = t.get("signal")
            result = t.get("result")

            if not f or not action or result not in ["WIN", "LOSS"]:
                continue

            m15 = f.get("m15_trend", 0)
            h1 = f.get("h1_trend", 0)
            h4 = f.get("h4_trend", 0)

            vol = (
                f.get("m15_volatility", 0) +
                f.get("h1_volatility", 0) +
                f.get("h4_volatility", 0)
            )

            regime = f.get("market_regime", "RANGE")
            trend_score = m15 + h1 + h4

            key = f"{regime}_{trend_score}_{vol}_{action}"

            if key not in self.patterns:
                self.patterns[key] = 0.0

            profit = t.get("profit", 0)

            reward = profit * 3
            self.patterns[key] += reward
            self.patterns[key] = max(-0.5, min(self.patterns[key], 0.5))

        # 🔥 STATE ONLY (no print)
        self.last_stats = {
            "winrate": winrate,
            "avg_profit": avg_profit,
            "patterns": len(self.patterns)
        }

    # ---------------- PROGRESS STATE ----------------
    def get_progress(self):
        winrate = self.last_stats.get("winrate", 0)
        avg_profit = self.last_stats.get("avg_profit", 0)
        patterns = len(self.patterns)

        score = (
            winrate * 50 +
            max(min(avg_profit * 1000, 25), -25) +
            min(patterns, 25)
        )

        score = max(0, min(int(score), 100))

        return {
            "winrate": round(winrate, 3),
            "avg_profit": round(avg_profit, 5),
            "patterns": patterns,
            "bias": round(self.bias, 3),
            "score": score
        }