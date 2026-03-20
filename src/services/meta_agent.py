class MetaAgent:
    def __init__(self):
        self.bias = 0.0
        self.patterns = {}
        print("🧠 MetaAgent ready (multi-tf + pattern)")

    # ---------------- DECISION ----------------
    def decide(self, features):
        try:
            price = features.get("price", 0)
            if not price:
                return "HOLD", 0.0

            # 🔥 TF DATA
            m15 = features.get("m15_trend")
            h1 = features.get("h1_trend")
            h4 = features.get("h4_trend")

            m15_vol = features.get("m15_volatility", 0)
            h1_vol = features.get("h1_volatility", 0)
            h4_vol = features.get("h4_volatility", 0)

            # ---------------- TREND CONSENSUS ----------------
            trend_score = m15 + h1 + h4

            if trend_score >= 2:
                action = "BUY"
                confidence = 0.6
            elif trend_score <= -2:
                action = "SELL"
                confidence = 0.6
            else:
                action = "HOLD"
                confidence = 0.3

            # ---------------- VOLATILITY ----------------
            vol_score = m15_vol + h1_vol + h4_vol
            confidence += vol_score * 0.05

            # ---------------- PATTERN ----------------
            key = f"{trend_score}_{vol_score}_{action}"
            if key in self.patterns:
                confidence += self.patterns[key]

            # ---------------- HOLD PENALTY ----------------
            if action == "HOLD":
                confidence -= 0.1

            # ---------------- GLOBAL BIAS ----------------
            confidence += self.bias

            confidence = max(0.0, min(confidence, 1.0))

            return action, confidence

        except Exception as e:
            print("❌ MetaAgent error:", e)
            return "HOLD", 0.0

    # ---------------- LEARNING ----------------
    def learn_from_history(self, trades):
        if not trades:
            return

        wins = [t for t in trades if t.get("result") == "WIN"]
        losses = [t for t in trades if t.get("result") == "LOSS"]

        total = len(wins) + len(losses)
        if total == 0:
            return

        winrate = len(wins) / total

        profits = [t.get("profit", 0) for t in trades if t.get("profit") is not None]
        avg_profit = sum(profits) / len(profits) if profits else 0

        # 🔥 GLOBAL LEARNING
        self.bias = (winrate - 0.5) * 0.5
        self.bias += avg_profit * 2
        self.bias = max(-0.3, min(self.bias, 0.3))

        # 🔥 PATTERN LEARNING
        for t in trades:
            features = t.get("features", {})
            action = t.get("signal")
            result = t.get("result")

            if not features or not action or not result:
                continue

            m15 = features.get("m15_trend")
            h1 = features.get("h1_trend")
            h4 = features.get("h4_trend")

            vol = (
                features.get("m15_volatility", 0)
                + features.get("h1_volatility", 0)
                + features.get("h4_volatility", 0)
            )

            trend_score = m15 + h1 + h4
            key = f"{trend_score}_{vol}_{action}"

            if key not in self.patterns:
                self.patterns[key] = 0.0

            if result == "WIN":
                self.patterns[key] += 0.02
            else:
                self.patterns[key] -= 0.02

            self.patterns[key] = max(-0.3, min(self.patterns[key], 0.3))

        print(
            f"🧠 Learning | winrate={round(winrate,2)} "
            f"bias={round(self.bias,3)} "
            f"patterns={len(self.patterns)}"
        )