import numpy as np

class MetricsEngine:

    @staticmethod
    def _trade_profit(trade):
        """
        Read profit from both legacy replay payloads and live Firestore history.

        Firestore trade history stores pnl at top level (`profit` / `pnl`),
        while some legacy evaluator/replay payloads nest it under
        `evaluation.profit`.
        """
        if "profit" in trade:
            return float(trade.get("profit") or 0.0)
        if "pnl" in trade:
            return float(trade.get("pnl") or 0.0)
        return float(trade.get("evaluation", {}).get("profit", 0.0) or 0.0)

    def compute(self, trades):
        if not trades:
            return {}

        profits = [self._trade_profit(t) for t in trades]
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
            strategy_perf.setdefault(s, []).append(self._trade_profit(t))
        strategy_stats = {s: {"winrate":sum(1 for x in v if x>0)/len(v),
                              "avg_profit":np.mean(v),
                              "trades":len(v)} for s,v in strategy_perf.items()}

        regime_perf = {}
        for t in trades:
            r = t.get("regime","UNKNOWN")
            regime_perf.setdefault(r, []).append(self._trade_profit(t))
        regime_stats = {r: {"winrate":sum(1 for x in v if x>0)/len(v),
                            "avg_profit":np.mean(v),
                            "trades":len(v)} for r,v in regime_perf.items()}

        # -------------------------
        # Confidence calibration
        # -------------------------
        conf_bins = {"low":[],"mid":[],"high":[]}
        for t in trades:
            c = t.get("confidence_used",0)
            p = self._trade_profit(t)
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

    # Reasons classified as neutral exits (not WIN/LOSS in WR denominator)
    _NEUTRAL_REASONS = frozenset({
        "timeout", "TIMEOUT_PROFIT", "TIMEOUT_FLAT", "TIMEOUT_LOSS",
        "SCRATCH_EXIT", "STAGNATION_EXIT",
    })

    def _classify_outcome(self, trade, profit):
        """Classify a closed trade as WIN / LOSS / FLAT.

        For trades with a result field (authoritative Firestore records): apply
        neutral-timeout exclusion first, then honour the stored result.
        For trades without a result field (legacy/backfill records): classify
        purely by profit direction — no neutral check (matches bootstrap_from_history
        which skips result-less trades entirely).
        """
        result = trade.get("result", "")
        if result:
            close_reason = trade.get("close_reason", "")
            if close_reason in self._NEUTRAL_REASONS and abs(profit) < 0.001:
                return "FLAT"
            if result == "WIN":
                return "WIN"
            if result == "LOSS":
                return "LOSS"
        # Fallback for trades without result field: classify by profit direction
        if profit > 0:
            return "WIN"
        if profit < 0:
            return "LOSS"
        return "FLAT"

    def compute_canonical_trade_stats(self, trades):
        """Single canonical source of truth for all dashboard metrics.

        Outcome classification uses the stored result field + neutral-timeout
        detection (matching learning_event logic) instead of an eps threshold.
        Returns comprehensive stats with reconciliation validation.
        """
        if not trades:
            return {
                'trades_total': 0, 'wins': 0, 'losses': 0, 'flats': 0,
                'winrate': 0.0, 'net_pnl': 0.0, 'gross_pnl': 0.0,
                'avg_profit': 0.0, 'profit_factor': 0.0, 'expectancy': 0.0,
                'best_trade': 0.0, 'worst_trade': 0.0,
                'per_symbol': {}, 'per_regime': {}, 'per_exit_type': {},
                'reconciliation': {'verified': True, 'alerts': []},
            }

        profits = []
        outcomes = []   # parallel list — same index as trades/profits

        for trade in trades:
            p = self._trade_profit(trade)
            profits.append(p)
            outcomes.append(self._classify_outcome(trade, p))

        wins   = outcomes.count("WIN")
        losses = outcomes.count("LOSS")
        flats  = outcomes.count("FLAT")

        net_pnl      = sum(profits)
        gross_pnl    = sum(p for p in profits if p > 0)
        trades_total = len(trades)
        avg_profit   = np.mean(profits) if profits else 0.0
        best_trade   = max(profits) if profits else 0.0
        worst_trade  = min(profits) if profits else 0.0

        decisive = wins + losses
        winrate  = wins / decisive if decisive > 0 else 0.0

        loss_sum      = abs(sum(p for p in profits if p < 0))
        profit_factor = gross_pnl / loss_sum if loss_sum > 0 else (gross_pnl if gross_pnl > 0 else 1.0)

        win_profits  = [p for p, o in zip(profits, outcomes) if o == "WIN"]
        loss_profits = [p for p, o in zip(profits, outcomes) if o == "LOSS"]
        expectancy   = (winrate * np.mean(win_profits or [0])) + \
                       ((1 - winrate) * np.mean(loss_profits or [0]))

        per_symbol = {}
        per_regime = {}
        per_exit_type = {}

        _okey = {"WIN": "wins", "LOSS": "losses", "FLAT": "flats"}

        for i, trade in enumerate(trades):
            p       = profits[i]
            outcome = outcomes[i]
            ok      = _okey[outcome]

            sym = trade.get("symbol", "UNKNOWN")
            if sym not in per_symbol:
                per_symbol[sym] = {"count": 0, "wins": 0, "losses": 0, "flats": 0, "net_pnl": 0.0}
            per_symbol[sym]["count"]   += 1
            per_symbol[sym]["net_pnl"] += p
            per_symbol[sym][ok]        += 1

            reg = trade.get("regime", "UNKNOWN")
            if reg not in per_regime:
                per_regime[reg] = {"count": 0, "wins": 0, "losses": 0, "flats": 0, "net_pnl": 0.0}
            per_regime[reg]["count"]   += 1
            per_regime[reg]["net_pnl"] += p
            per_regime[reg][ok]        += 1

            et = trade.get("close_reason", "UNKNOWN")
            if et not in per_exit_type:
                per_exit_type[et] = {"count": 0, "wins": 0, "losses": 0, "flats": 0,
                                     "net_pnl": 0.0, "avg_pnl": 0.0,
                                     "pct_of_total": 0.0, "pct_of_total_pnl": 0.0}
            per_exit_type[et]["count"]   += 1
            per_exit_type[et]["net_pnl"] += p
            per_exit_type[et][ok] += 1

        abs_net = abs(net_pnl) or 1.0
        for et, s in per_exit_type.items():
            c = s["count"]
            s["avg_pnl"]          = s["net_pnl"] / c if c > 0 else 0.0
            s["pct_of_total"]     = c / trades_total * 100 if trades_total > 0 else 0.0
            s["pct_of_total_pnl"] = abs(s["net_pnl"]) / abs_net * 100

        # Reconciliation
        alerts = []
        sym_sum  = sum(s["net_pnl"] for s in per_symbol.values())
        reg_sum  = sum(r["net_pnl"] for r in per_regime.values())
        sym_cnt  = sum(s["count"]   for s in per_symbol.values())
        reg_cnt  = sum(r["count"]   for r in per_regime.values())
        exit_cnt = sum(s["count"]   for s in per_exit_type.values())

        if abs(sym_sum - net_pnl) > 1e-9:
            alerts.append(f"symbol_pnl_mismatch:{sym_sum:.8f} vs {net_pnl:.8f}")
        if abs(reg_sum - net_pnl) > 1e-9:
            alerts.append(f"regime_pnl_mismatch:{reg_sum:.8f} vs {net_pnl:.8f}")
        if sym_cnt  != trades_total:
            alerts.append(f"symbol_count_mismatch:{sym_cnt} vs {trades_total}")
        if reg_cnt  != trades_total:
            alerts.append(f"regime_count_mismatch:{reg_cnt} vs {trades_total}")
        if exit_cnt != trades_total:
            alerts.append(f"exit_count_mismatch:{exit_cnt} vs {trades_total}")
        if wins + losses + flats != trades_total:
            alerts.append(f"outcome_sum_mismatch:{wins+losses+flats} vs {trades_total}")

        return {
            "trades_total": trades_total,
            "wins": wins, "losses": losses, "flats": flats,
            "winrate": winrate,
            "net_pnl": net_pnl, "gross_pnl": gross_pnl,
            "avg_profit": avg_profit,
            "best_trade": best_trade, "worst_trade": worst_trade,
            "profit_factor": profit_factor, "expectancy": expectancy,
            "per_symbol": per_symbol, "per_regime": per_regime,
            "per_exit_type": per_exit_type,
            "reconciliation": {"verified": not alerts, "alerts": alerts},
        }

    def compute_recent_window_stats(self, closed_trades, window=24):
        """Compute recent-window WR from canonical closed trades.

        Returns a dict with 'known' flag — callers must check known before
        rendering any metric to avoid printing fake zeros.
        """
        decisive = [
            t for t in closed_trades
            if t.get("result") in ("WIN", "LOSS")
            and not (t.get("close_reason", "") in self._NEUTRAL_REASONS
                     and abs(self._trade_profit(t)) < 0.001)
        ]
        recent = decisive[-window:]
        if not recent:
            return {"known": False, "window": 0, "wr": None, "avg_ev": None}
        wins   = sum(1 for t in recent if t.get("result") == "WIN")
        avg_ev = sum(float(t.get("ev") or 0.0) for t in recent) / len(recent)
        return {
            "known": True,
            "window": len(recent),
            "wr":     wins / len(recent),
            "avg_ev": avg_ev,
        }
