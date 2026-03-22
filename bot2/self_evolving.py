import random


class SelfEvolvingSystem:

    def __init__(self):
        self.params = {
            "risk_multiplier": 1.0,
            "confidence_boost": 1.0,
            "exploration": 0.3
        }

    # =========================
    # 🧠 EVOLVE (NOW RETURNS SUGGESTIONS)
    # =========================
    def evolve(self, performance):
        winrate = performance.get("winrate", 0)
        profit = performance.get("profit", 0)
        confidence_quality = performance.get("confidence_quality", 0.5)

        print("🧬 Evolving with:", performance)

        update = {}

        # =========================
        # 📈 GOOD PERFORMANCE
        # =========================
        if winrate > 50 and profit > 0 and confidence_quality > 0.6:
            update["risk_multiplier"] = 1.05
            update["confidence_boost"] = 1.02
            update["exploration"] = 0.95

        # =========================
        # 📉 BAD PERFORMANCE
        # =========================
        else:
            update["risk_multiplier"] = 0.9
            update["confidence_boost"] = 0.95
            update["exploration"] = 1.05

        # =========================
        # 🎲 MUTATION (proposal only)
        # =========================
        if random.random() < 0.1:
            key = random.choice(list(self.params.keys()))
            update[key] = random.uniform(0.9, 1.1)
            print(f"🧬 Mutation suggestion on {key}")

        print("🧬 Suggested params:", update)

        return update