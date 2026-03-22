import math
from collections import defaultdict


class LearningEngine:

    def __init__(self):
        self.bandit = defaultdict(lambda: {"n": 0, "reward": 0})
        self.conf_calibration = {}
        self.strategy_blame = defaultdict(float)
        self.regime_perf = defaultdict(list)

    # =========================
    # 🧠 BANDIT UPDATE
    # =========================
    def update_bandit(self, trades):
        total = sum(v["n"] for v in self.bandit.values()) + 1

        for t in trades:
            key = f"{t['regime']}_{t['strategy']}_{t['meta']['feature_bucket']}"
            reward = t["evaluation"]["profit"]

            self.bandit[key]["n"] += 1
            self.bandit[key]["reward"] += reward

    def compute_scores(self):
        scores = {}

        total = sum(v["n"] for v in self.bandit.values()) + 1

        for k, v in self.bandit.items():
            if v["n"] == 0:
                continue

            avg = v["reward"] / v["n"]
            bonus = math.sqrt(math.log(total) / v["n"])

            scores[k] = avg + bonus

        return scores

    # =========================
    # 🎯 CONFIDENCE CALIBRATION
    # =========================
    def calibrate_confidence(self, trades):
        buckets = defaultdict(lambda: {"wins": 0, "total": 0})

        for t in trades:
            c = round(t["meta"]["confidence_used"], 1)
            buckets[c]["total"] += 1

            if t["evaluation"]["result"] == "WIN":
                buckets[c]["wins"] += 1

        for c, d in buckets.items():
            if d["total"] > 5:
                self.conf_calibration[c] = d["wins"] / d["total"]

    # =========================
    # ⚖️ STRATEGY BLAME
    # =========================
    def update_strategy_blame(self, trades):
        for t in trades:
            self.strategy_blame[t["strategy"]] += t["evaluation"]["profit"]

    # =========================
    # 🌍 REGIME VALIDATION
    # =========================
    def update_regime_perf(self, trades):
        for t in trades:
            self.regime_perf[t["regime"]].append(t["evaluation"]["profit"])

    # =========================
    # 📊 EXPORT CONFIG
    # =========================
    def export_config(self):
        return {
            "bandit_scores": self.compute_scores(),
            "confidence_calibration": self.conf_calibration,
            "epsilon": 0.1
        }