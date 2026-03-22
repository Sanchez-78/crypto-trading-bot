from src.services.pattern_cluster import PatternCluster


class MetaAgent:
    def __init__(self):
        self.bias = 0.0
        self.patterns = {}
        self.cluster_stats = {}

        self.cluster = PatternCluster()

        # 📊 stats
        self.last_stats = {
            "winrate": 0.5,
            "avg_profit": 0.0,
            "patterns": 0,
        }

        self.total_trades = 0
        self.wins = 0

        # 🔥 stabilita
        self.alpha = 0.01  # EMA rychlost

    # ─────────────────────────────
    # 🎯 DECISION ENGINE
    # ─────────────────────────────
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

        # 🔥 regime bonus
        if regime == "BULL":
            conf += 0.1
        elif regime == "BEAR":
            conf += 0.1

        # 🔥 cluster pattern
        key = self.cluster.build(f, action)

        if key in self.patterns:
            stats = self.cluster_stats.get(key, {"count": 1, "profit": 0})
            avg = stats["profit"] / max(stats["count"], 1)
            conf += avg

        # 🔥 bias
        conf += self.bias
        conf = max(0, min(conf, 1))

        return action, conf

    # ─────────────────────────────
    # ⚡ EVENT LEARNING (FIXED)
    # ─────────────────────────────
    def learn_from_trade(self, trade):
        profit = trade.get("profit", 0)
        result = trade.get("result", "LOSS")

        self.total_trades += 1

        # 🔥 win jako 0/1 (FIX)
        win = 1 if result == "WIN" else 0

        if win:
            self.wins += 1

        # 🔥 bias update (jemnější + damping)
        step = 0.003

        if win:
            self.bias += step
        else:
            self.bias -= step

        # damping
        self.bias *= 0.995
        self.bias = max(-0.3, min(self.bias, 0.3))

        # 🔥 CLUSTER LEARNING
        f = trade.get("features", {})
        action = trade.get("signal")

        key = self.cluster.build(f, action)

        # pattern score
        if key not in self.patterns:
            self.patterns[key] = 0

        self.patterns[key] += profit
        self.patterns[key] = max(-1, min(self.patterns[key], 1))

        # 📊 cluster stats
        if key not in self.cluster_stats:
            self.cluster_stats[key] = {"count": 0, "profit": 0}

        self.cluster_stats[key]["count"] += 1
        self.cluster_stats[key]["profit"] += profit

        # 🔥 EMA STATS (FIX)
        self.last_stats["winrate"] = (
            self.last_stats["winrate"] * (1 - self.alpha) + win * self.alpha
        )

        self.last_stats["avg_profit"] = (
            self.last_stats["avg_profit"] * (1 - self.alpha) + profit * self.alpha
        )

        # clamp
        self.last_stats["winrate"] = max(0, min(1, self.last_stats["winrate"]))

        self.last_stats["patterns"] = len(self.patterns)

    # ─────────────────────────────
    # 📊 PROGRESS
    # ─────────────────────────────
    def get_progress(self):
        # 🔥 early phase ochrana
        if self.total_trades < 30:
            return {
                "score": 0,
                "status": "learning...",
                "trades": self.total_trades,
            }

        score = int(self.last_stats["winrate"] * 100)

        return {
            "score": score,
            "winrate": round(self.last_stats["winrate"], 3),
            "avg_profit": round(self.last_stats["avg_profit"], 5),
            "patterns": len(self.patterns),
            "bias": round(self.bias, 3),
            "trades": self.total_trades,
        }

    # ─────────────────────────────
    # 🔥 DEBUG: TOP CLUSTERS
    # ─────────────────────────────
    def print_top_clusters(self, n=5):
        top = sorted(
            self.cluster_stats.items(),
            key=lambda x: x[1]["profit"],
            reverse=True
        )[:n]

        print("\n🔥 TOP CLUSTERS:")
        for k, v in top:
            avg = v["profit"] / max(v["count"], 1)
            print(f"{k} | count={v['count']} avg={round(avg,4)}")