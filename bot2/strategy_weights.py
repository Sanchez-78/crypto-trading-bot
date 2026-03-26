from collections import defaultdict
from src.services.firebase_client import load_history

# Default weights — always returned so weights are never empty
_DEFAULTS = {
    "BULL_TREND":  1.0,
    "BEAR_TREND":  1.0,
    "RANGING":     1.0,
    "QUIET_RANGE": 1.0,
    "HIGH_VOL":    1.0,
}


class StrategyWeights:

    def __init__(self):
        self.weights = dict(_DEFAULTS)

    def update(self):
        trades = load_history()
        perf   = defaultdict(lambda: {"win": 0, "loss": 0})

        for t in trades:
            # strategy field was stored as regime in _slim_trade
            strat  = t.get("strategy") or t.get("regime")
            result = t.get("result")
            if not strat or result not in ("WIN", "LOSS"):
                continue
            perf[strat]["win" if result == "WIN" else "loss"] += 1

        updated = dict(_DEFAULTS)
        for strat, data in perf.items():
            total = data["win"] + data["loss"]
            if total < 5:
                updated[strat] = 1.0
                continue
            wr = data["win"] / total
            updated[strat] = round(0.5 + wr, 3)

        self.weights = updated
        print("🧠 Strategy weights:", {k: f"{v:.2f}" for k, v in self.weights.items()})
        return dict(self.weights)
