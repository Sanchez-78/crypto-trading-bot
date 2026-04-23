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

    def compute_canonical_trade_stats(self, trades):
        """
        Single canonical source of truth for all metrics.

        Input: List of closed trade dicts with 'evaluation.profit' field
        Outcome Classification:
        - WIN if profit > +0.0001
        - LOSS if profit < -0.0001
        - FLAT otherwise

        Returns comprehensive stats dict with reconciliation validation.
        """
        if not trades:
            return {
                'trades_total': 0,
                'wins': 0,
                'losses': 0,
                'flats': 0,
                'winrate': 0.0,
                'net_pnl': 0.0,
                'gross_pnl': 0.0,
                'avg_profit': 0.0,
                'profit_factor': 0.0,
                'expectancy': 0.0,
                'per_symbol': {},
                'per_regime': {},
                'per_exit_type': {},
                'reconciliation': {'verified': True, 'alerts': []}
            }

        # Extract profits and classify outcomes
        eps = 0.0001
        outcomes = {}
        profits = []

        for trade in trades:
            profit = trade.get('evaluation', {}).get('profit', 0)
            profits.append(profit)

            if profit > eps:
                outcomes[id(trade)] = 'WIN'
            elif profit < -eps:
                outcomes[id(trade)] = 'LOSS'
            else:
                outcomes[id(trade)] = 'FLAT'

        # Count outcomes
        wins = sum(1 for o in outcomes.values() if o == 'WIN')
        losses = sum(1 for o in outcomes.values() if o == 'LOSS')
        flats = sum(1 for o in outcomes.values() if o == 'FLAT')

        # Basic stats
        net_pnl = sum(profits)
        gross_pnl = sum(p for p in profits if p > 0)
        trades_total = len(trades)
        avg_profit = np.mean(profits) if profits else 0.0

        # Winrate (exclude flats from denominator)
        trades_with_outcome = wins + losses
        winrate = wins / trades_with_outcome if trades_with_outcome > 0 else 0.0

        # Profit factor
        loss_sum = abs(sum(p for p in profits if p < 0))
        profit_factor = gross_pnl / loss_sum if loss_sum > 0 else (gross_pnl if gross_pnl > 0 else 1.0)

        # Expectancy
        expectancy = (winrate * np.mean([p for p in profits if p > eps] or [0])) + \
                     ((1 - winrate) * np.mean([p for p in profits if p < -eps] or [0]))

        # Per-symbol stats
        per_symbol = {}
        for trade in trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            profit = trade.get('evaluation', {}).get('profit', 0)
            outcome = outcomes[id(trade)]

            if symbol not in per_symbol:
                per_symbol[symbol] = {'count': 0, 'wins': 0, 'losses': 0, 'flats': 0, 'net_pnl': 0}

            per_symbol[symbol]['count'] += 1
            per_symbol[symbol]['net_pnl'] += profit
            if outcome == 'WIN':
                per_symbol[symbol]['wins'] += 1
            elif outcome == 'LOSS':
                per_symbol[symbol]['losses'] += 1
            else:
                per_symbol[symbol]['flats'] += 1

        # Per-regime stats
        per_regime = {}
        for trade in trades:
            regime = trade.get('regime', 'UNKNOWN')
            profit = trade.get('evaluation', {}).get('profit', 0)
            outcome = outcomes[id(trade)]

            if regime not in per_regime:
                per_regime[regime] = {'count': 0, 'wins': 0, 'losses': 0, 'flats': 0, 'net_pnl': 0}

            per_regime[regime]['count'] += 1
            per_regime[regime]['net_pnl'] += profit
            if outcome == 'WIN':
                per_regime[regime]['wins'] += 1
            elif outcome == 'LOSS':
                per_regime[regime]['losses'] += 1
            else:
                per_regime[regime]['flats'] += 1

        # Per-exit-type stats
        per_exit_type = {}
        for trade in trades:
            exit_type = trade.get('close_reason', 'UNKNOWN')
            profit = trade.get('evaluation', {}).get('profit', 0)
            outcome = outcomes[id(trade)]

            if exit_type not in per_exit_type:
                per_exit_type[exit_type] = {'count': 0, 'wins': 0, 'losses': 0, 'flats': 0, 'net_pnl': 0, 'avg_pnl': 0}

            per_exit_type[exit_type]['count'] += 1
            per_exit_type[exit_type]['net_pnl'] += profit
            if outcome == 'WIN':
                per_exit_type[exit_type]['wins'] += 1
            elif outcome == 'LOSS':
                per_exit_type[exit_type]['losses'] += 1
            else:
                per_exit_type[exit_type]['flats'] += 1

        # Calculate average PnL and contribution % for exit types
        for exit_type in per_exit_type:
            count = per_exit_type[exit_type]['count']
            per_exit_type[exit_type]['avg_pnl'] = per_exit_type[exit_type]['net_pnl'] / count if count > 0 else 0
            per_exit_type[exit_type]['pct_of_total'] = (count / trades_total * 100) if trades_total > 0 else 0

        # Reconciliation validation
        alerts = []
        sum_symbol_pnl = sum(s['net_pnl'] for s in per_symbol.values())
        sum_regime_pnl = sum(r['net_pnl'] for r in per_regime.values())

        if abs(sum_symbol_pnl - net_pnl) > 0.00001:
            alerts.append(f"per_symbol_pnl_mismatch: {sum_symbol_pnl} vs {net_pnl}")

        if abs(sum_regime_pnl - net_pnl) > 0.00001:
            alerts.append(f"per_regime_pnl_mismatch: {sum_regime_pnl} vs {net_pnl}")

        if wins + losses + flats != trades_total:
            alerts.append(f"outcome_count_mismatch: {wins + losses + flats} vs {trades_total}")

        return {
            'trades_total': trades_total,
            'wins': wins,
            'losses': losses,
            'flats': flats,
            'winrate': winrate,
            'net_pnl': net_pnl,
            'gross_pnl': gross_pnl,
            'avg_profit': avg_profit,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'per_symbol': per_symbol,
            'per_regime': per_regime,
            'per_exit_type': per_exit_type,
            'reconciliation': {
                'verified': len(alerts) == 0,
                'alerts': alerts,
            }
        }