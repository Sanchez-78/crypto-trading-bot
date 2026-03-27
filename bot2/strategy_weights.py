from collections import defaultdict
from src.services.firebase_client import load_history

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
        perf   = defaultdict(lambda: {"win": 0, "loss": 0, "timeout": 0})

        for t in trades:
            strat  = t.get("strategy") or t.get("regime")
            sym    = t.get("symbol", "")
            result = t.get("result")
            reason = t.get("close_reason", "")
            if not strat or result not in ("WIN", "LOSS"):
                continue
            perf[strat]["win" if result == "WIN" else "loss"] += 1
            if reason == "timeout":
                perf[strat]["timeout"] += 1
            # sym×regime key for finer resolution
            if sym:
                sk = f"{strat}_{sym}"
                perf[sk]["win" if result == "WIN" else "loss"] += 1

        updated = dict(_DEFAULTS)
        for key, data in perf.items():
            total = data["win"] + data["loss"]
            if total < 5:
                continue
            wr             = data["win"] / total
            timeout_ratio  = data["timeout"] / total
            # Penalise regimes with high timeout rate (dead signals going nowhere)
            updated[key]   = round((0.5 + wr) * max(0.5, 1 - timeout_ratio), 3)

        self.weights = updated
        regime_only  = {k: f"{v:.2f}" for k, v in updated.items() if k in _DEFAULTS}
        print("🧠 Strategy weights:", regime_only)
        return dict(self.weights)
