import numpy as np


class MetricsEngine:

    def compute(self, trades):
        if not trades:
            return {}

        profits = [t["evaluation"]["profit"] for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        # =========================
        # 📊 BASIC
        # =========================
        winrate = len(wins) / len(profits)
        avg_profit = np.mean(profits)

        profit_factor = (
            abs(sum(wins) / sum(losses)) if losses else 999
        )

        expectancy = (winrate * np.mean(wins or [0])) + \
                     ((1 - winrate) * np.mean(losses or [0]))

        # =========================
        # 📉 DRAWDOWN
        # =========================
        equity = np.cumsum(profits)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak)
        max_dd = np.min(drawdown)

        # =========================
        # 🔥 LOSS STREAK
        # =========================
        max_streak = 0
        current = 0

        for p in profits:
            if p <= 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0

        # =========================
        # 🧠 LEARNING PROGRESS
        # =========================
        mid = len(profits) // 2

        first_half = profits[:mid]
        second_half = profits[mid:]

        def avg(x):
            return np.mean(x) if x else 0

        improvement = avg(second_half) - avg(first_half)

        if improvement > 0.001:
            trend = "IMPROVING"
        elif improvement < -0.001:
            trend = "WORSENING"
        else:
            trend = "STABLE"

        # =========================
        # 🎯 STRATEGY PERFORMANCE
        # =========================
        strategy_perf = {}

        for t in trades:
            s = t.get("strategy", "UNKNOWN")
            p = t["evaluation"]["profit"]

            strategy_perf.setdefault(s, []).append(p)

        strategy_stats = {
            s: {
                "winrate": sum(1 for x in v if x > 0) / len(v),
                "avg_profit": np.mean(v),
                "trades": len(v)
            }
            for s, v in strategy_perf.items()
        }

        # =========================
        # 🌊 REGIME PERFORMANCE
        # =========================
        regime_perf = {}

        for t in trades:
            r = t.get("regime", "UNKNOWN")
            p = t["evaluation"]["profit"]

            regime_perf.setdefault(r, []).append(p)

        regime_stats = {
            r: {
                "winrate": sum(1 for x in v if x > 0) / len(v),
                "avg_profit": np.mean(v),
                "trades": len(v)
            }
            for r, v in regime_perf.items()
        }

        # =========================
        # 🧠 CONFIDENCE CALIBRATION
        # =========================
        conf_bins = {"low": [], "mid": [], "high": []}

        for t in trades:
            c = t.get("confidence_used", 0)

            if c < 0.4:
                conf_bins["low"].append(t["evaluation"]["profit"])
            elif c < 0.7:
                conf_bins["mid"].append(t["evaluation"]["profit"])
            else:
                conf_bins["high"].append(t["evaluation"]["profit"])

        conf_stats = {
            k: np.mean(v) if v else 0
            for k, v in conf_bins.items()
        }

        # =========================
        # FINAL OUTPUT
        # =========================
        return {
            "performance": {
                "winrate": winrate,
                "avg_profit": avg_profit,
                "profit_factor": profit_factor,
                "expectancy": expectancy,
                "trades": len(trades)
            },
            "risk": {
                "max_drawdown": max_dd,
                "max_loss_streak": max_streak
            },
            "learning": {
                "improvement": improvement,
                "trend": trend
            },
            "strategy": strategy_stats,
            "regime": regime_stats,
            "confidence": conf_stats
        }