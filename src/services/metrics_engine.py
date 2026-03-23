import numpy as np

class MetricsEngine:

    def compute(self, trades):
        if not trades:
            return {}

        profits = [t["evaluation"]["profit"] for t in trades]
        wins = [p for p in profits if p > 0]

        # -------------------------
        # Performance
        # -------------------------
        winrate = len(wins)/len(profits)
        avg_profit = np.mean(profits)
        profit_factor = (sum([p for p in profits if p>0])/abs(sum([p for p in profits if p<0]))) if any([p<0 for p in profits]) else np.mean(profits)
        expectancy = (winrate * np.mean(wins or [0])) + ((1-winrate) * np.mean([p for p in profits if p<0] or [0]))

        # -------------------------
        # Risk
        # -------------------------
        equity = np.cumsum(profits)
        peak = np.maximum.accumulate(equity)
        drawdown = equity - peak
        max_dd = np.min(drawdown)

        # -------------------------
        # Learning trend
        # -------------------------
        mid = len(profits)//2
        improvement = np.mean(profits[mid:]) - np.mean(profits[:mid])
        if improvement > 0.001:
            trend = "IMPROVING"
        elif improvement < -0.001:
            trend = "WORSENING"
        else:
            trend = "STABLE"

        # -------------------------
        # Strategy & Regime
        # -------------------------
        strategy_perf = {}
        for t in trades:
            s = t.get("strategy","UNKNOWN")
            strategy_perf.setdefault(s, []).append(t["evaluation"]["profit"])
        strategy_stats = {s: {"winrate":sum(1 for x in v if x>0)/len(v),
                              "avg_profit":np.mean(v),
                              "trades":len(v)} for s,v in strategy_perf.items()}

        regime_perf = {}
        for t in trades:
            r = t.get("regime","UNKNOWN")
            regime_perf.setdefault(r, []).append(t["evaluation"]["profit"])
        regime_stats = {r: {"winrate":sum(1 for x in v if x>0)/len(v),
                            "avg_profit":np.mean(v),
                            "trades":len(v)} for r,v in regime_perf.items()}

        # -------------------------
        # Confidence calibration
        # -------------------------
        conf_bins = {"low":[],"mid":[],"high":[]}
        for t in trades:
            c = t.get("confidence_used",0)
            p = t["evaluation"]["profit"]
            if c<0.4: conf_bins["low"].append(p)
            elif c<0.7: conf_bins["mid"].append(p)
            else: conf_bins["high"].append(p)
        conf_stats = {k: np.mean(v) if v else 0 for k,v in conf_bins.items()}

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
                "max_loss_streak": self.max_loss_streak(profits)
            },
            "learning": {
                "improvement": improvement,
                "trend": trend
            },
            "strategy": strategy_stats,
            "regime": regime_stats,
            "confidence": conf_stats
        }

    def max_loss_streak(self, profits):
        max_streak = 0
        current = 0
        for p in profits:
            if p<=0:
                current +=1
                max_streak = max(max_streak,current)
            else:
                current = 0
        return max_streak