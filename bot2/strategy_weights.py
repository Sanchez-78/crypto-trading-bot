from collections import defaultdict
from src.services.firebase_client import load_all_signals


class StrategyWeights:

    def __init__(self):
        self.weights = defaultdict(lambda: 1.0)

    def update(self):
        signals = load_all_signals()

        performance = defaultdict(lambda: {"win": 0, "loss": 0})

        for s in signals:
            strategy = s.get("strategy")
            result = s.get("result")

            # ❗ ochrana (důležité)
            if not strategy or result not in ["WIN", "LOSS"]:
                continue

            if result == "WIN":
                performance[strategy]["win"] += 1
            else:
                performance[strategy]["loss"] += 1

        for strat, data in performance.items():
            total = data["win"] + data["loss"]

            if total == 0:
                continue

            winrate = data["win"] / total
            weight = 0.5 + winrate

            if total < 5:
                weight = 1.0

            self.weights[strat] = weight

        print("🧠 Strategy weights:", dict(self.weights))

        return dict(self.weights)