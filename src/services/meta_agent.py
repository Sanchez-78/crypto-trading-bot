class MetaAgent:
    def __init__(self):
        self.bias = 0.0
        self.patterns = {}

        # 🔥 progress tracking
        self.last_stats = {
            "winrate": 0,
            "avg_profit": 0,
            "patterns": 0
        }

        print("🧠 MetaAgent ready (multi-tf + pattern + reward + progress)")

    # ---------------- DECISION ----------------
    def decide(self, features):
        try:
            price = features.get("price", 0)
            if not price:
                return "HOLD", 0.0

            # 🔥 SAFE TF LOAD
            m15 = features.get("m15_trend", 0)
            h1 = features.get("h1_trend", 0)
            h4 = features.get("h4_trend", 0)

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

            # ---------------- PATTERN BOOST ----------------
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

        # ---------------- PATTERN LEARNING ----------------
        for t in trades:
            features = t.get("features", {})
            action = t.get("signal")
            result = t.get("result")

            if not features or not action:
                continue

            if result not in ["WIN", "LOSS"]:
                continue

            # 🔥 SAFE LOAD
            m15 = features.get("m15_trend", 0)
            h1 = features.get("h1_trend", 0)
            h4 = features.get("h4_trend", 0)

            vol = (
                features.get("m15_volatility", 0)
                + features.get("h1_volatility", 0)
                + features.get("h4_volatility", 0)
            )

            trend_score = m15 + h1 + h4
            key = f"{trend_score}_{vol}_{action}"

            if key not in self.patterns:
                self.patterns[key] = 0.0

            # 🔥 PROFIT-BASED LEARNING
            profit = t.get("profit", 0)

            if result == "WIN":
                self.patterns[key] += 0.02 + profit * 2
            else:
                self.patterns[key] -= 0.02 + abs(profit) * 2

            self.patterns[key] = max(-0.3, min(self.patterns[key], 0.3))

        print(
            f"🧠 Learning | winrate={round(winrate,2)} "
            f"bias={round(self.bias,3)} "
            f"patterns={len(self.patterns)}"
        )

        # 🔥 PROGRESS OUTPUT
        self.print_progress(winrate, avg_profit)

    # ---------------- PROGRESS ----------------
    def print_progress(self, winrate, avg_profit):
        prev = self.last_stats

        def trend(new, old):
            if new > old:
                return "↑"
            elif new < old:
                return "↓"
            return "="

        # 🔥 SCORE
        score = (
            winrate * 50 +
            max(min(avg_profit * 1000, 25), -25) +
            min(len(self.patterns), 25)
        )

        score = max(0, min(int(score), 100))

        print("\n📊 PROGRESS:")
        print(f"winrate: {round(winrate,3)} {trend(winrate, prev['winrate'])}")
        print(f"avg_profit: {round(avg_profit,5)} {trend(avg_profit, prev['avg_profit'])}")
        print(f"patterns: {len(self.patterns)} {trend(len(self.patterns), prev['patterns'])}")
        print(f"bias: {round(self.bias,3)}")

        print(f"score: {self.color_score(score)}/100")
        print(self.progress_bar(score))

        self.last_stats = {
            "winrate": winrate,
            "avg_profit": avg_profit,
            "patterns": len(self.patterns)
        }

    # ---------------- COLOR SCORE ----------------
    def color_score(self, score):
        if score < 30:
            return f"\033[91m{score}\033[0m"  # red
        elif score < 50:
            return f"\033[93m{score}\033[0m"  # yellow
        elif score < 70:
            return f"\033[94m{score}\033[0m"  # blue
        else:
            return f"\033[92m{score}\033[0m"  # green

    # ---------------- PROGRESS BAR ----------------
    def progress_bar(self, score):
        total = 20
        filled = int(score / 100 * total)

        if score < 30:
            color = "\033[91m"  # red
        elif score < 50:
            color = "\033[93m"  # yellow
        elif score < 70:
            color = "\033[94m"  # blue
        else:
            color = "\033[92m"  # green

        reset = "\033[0m"

        bar = ""
        for i in range(total):
            if i < filled:
                bar += f"{color}█{reset}"
            else:
                bar += "-"

        return f"[{bar}] {score}%"