"""
Learning Optimizer V10.15m - Adaptive parameter tuning based on trade results

Learns from trades database and optimizes:
1. TP/SL zone sizes per symbol/regime
2. Position sizing based on recent PF
3. Symbol blacklist/whitelist based on win rate
4. Entry filtering based on worst-performing regimes
"""

import sqlite3
import logging
import os
from typing import Dict, List, Tuple
from collections import defaultdict

log = logging.getLogger(__name__)

class LearningOptimizer:
    """Analyze trades and recommend parameter adjustments"""

    def __init__(self, db_path: str = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'):
        self.db_path = db_path
        self.min_trades_for_decision = 5  # Need 5+ trades to make a decision

    def analyze_and_optimize(self) -> Dict:
        """Analyze database and return optimization recommendations"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 1. Analyze overall metrics
            overall = self._get_overall_metrics(c)

            # 2. Analyze per symbol
            per_symbol = self._analyze_per_symbol(c)

            # 3. Analyze per regime
            per_regime = self._analyze_per_regime(c)

            # 4. Generate recommendations
            recommendations = self._generate_recommendations(overall, per_symbol, per_regime)

            conn.close()

            return {
                'overall': overall,
                'per_symbol': per_symbol,
                'per_regime': per_regime,
                'recommendations': recommendations,
            }
        except Exception as e:
            log.error(f"[LEARNING_OPTIMIZER_ERROR] Failed to analyze: {e}")
            return {}

    def _get_overall_metrics(self, c) -> Dict:
        """Get overall trading metrics"""
        c.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
                   AVG(pnl_pct) as avg_pnl_pct,
                   SUM(pnl_usd) as net_pnl,
                   SUM(CASE WHEN exit_reason = 'TIMEOUT' THEN 1 ELSE 0 END) as timeout_count
            FROM trades
        ''')
        row = c.fetchone()

        total = row[0] or 0
        wins = row[1] or 0
        losses = row[2] or 0
        avg_pnl_pct = (row[3] or 0) * 100
        net_pnl = row[4] or 0.0
        timeout_count = row[5] or 0

        pf = wins / (losses + 0.0001) if losses > 0 else (1.0 if wins > 0 else 0.0)
        wr = (wins / total * 100) if total > 0 else 0.0
        timeout_pct = (timeout_count / total * 100) if total > 0 else 0.0

        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate_pct': wr,
            'profit_factor': pf,
            'avg_pnl_pct': avg_pnl_pct,
            'net_pnl_usd': net_pnl,
            'timeout_exits_pct': timeout_pct,
        }

    def _analyze_per_symbol(self, c) -> Dict[str, Dict]:
        """Analyze performance per symbol"""
        c.execute('''
            SELECT symbol, COUNT(*) as count,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
                   AVG(pnl_pct) as avg_pnl_pct,
                   SUM(pnl_usd) as net_pnl
            FROM trades GROUP BY symbol
        ''')

        result = {}
        for row in c.fetchall():
            symbol = row[0]
            count = row[1] or 0
            wins = row[2] or 0
            losses = row[3] or 0
            avg_pnl_pct = (row[4] or 0) * 100
            net_pnl = row[5] or 0.0

            pf = wins / (losses + 0.0001) if losses > 0 else (1.0 if wins > 0 else 0.0)
            wr = (wins / count * 100) if count > 0 else 0.0

            result[symbol] = {
                'trades': count,
                'win_rate': wr,
                'profit_factor': pf,
                'avg_pnl_pct': avg_pnl_pct,
                'net_pnl': net_pnl,
            }

        return result

    def _analyze_per_regime(self, c) -> Dict[str, Dict]:
        """Analyze performance per market regime"""
        c.execute('''
            SELECT regime, COUNT(*) as count,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
                   AVG(pnl_pct) as avg_pnl_pct
            FROM trades GROUP BY regime
        ''')

        result = {}
        for row in c.fetchall():
            regime = row[0]
            count = row[1] or 0
            wins = row[2] or 0
            losses = row[3] or 0
            avg_pnl_pct = (row[4] or 0) * 100

            pf = wins / (losses + 0.0001) if losses > 0 else (1.0 if wins > 0 else 0.0)
            wr = (wins / count * 100) if count > 0 else 0.0

            result[regime] = {
                'trades': count,
                'win_rate': wr,
                'profit_factor': pf,
                'avg_pnl_pct': avg_pnl_pct,
            }

        return result

    def _generate_recommendations(self, overall: Dict, per_symbol: Dict, per_regime: Dict) -> List[str]:
        """Generate optimization recommendations based on analysis"""
        recommendations = []

        # 1. Check if too many TIMEOUT exits
        if overall['timeout_exits_pct'] > 80:
            recommendations.append(
                f"🔴 CRITICAL: {overall['timeout_exits_pct']:.1f}% exits are TIMEOUT. "
                f"TP/SL zones too tight or timeout too short. Increase TP/SL zone BPS or timeout_s."
            )

        # 2. Check if all trades are losses
        if overall['win_rate_pct'] == 0.0 and overall['total_trades'] >= 3:
            recommendations.append(
                f"🔴 CRITICAL: {overall['total_trades']} trades, 0% win rate. "
                f"Entry signals are BROKEN. Check signal_engine calibration."
            )

        # 3. Per-symbol blacklist
        for symbol, metrics in per_symbol.items():
            if metrics['trades'] >= 3 and metrics['profit_factor'] < 0.5:
                recommendations.append(
                    f"⚠️ {symbol}: {metrics['trades']} trades, PF={metrics['profit_factor']:.2f}x. "
                    f"Consider disabling or reducing position size."
                )

        # 4. Per-regime analysis
        for regime, metrics in per_regime.items():
            if metrics['trades'] >= 3 and metrics['win_rate'] == 0.0:
                recommendations.append(
                    f"⚠️ {regime}: {metrics['trades']} trades, 0% WR. "
                    f"Bot performs poorly in {regime}. Add regime filter or reduce size."
                )

        # 5. Position sizing recommendation
        if overall['profit_factor'] < 0.7 and overall['total_trades'] >= 5:
            recommendations.append(
                f"💡 Position size too large. PF={overall['profit_factor']:.2f}x (target: ≥1.0x). "
                f"Reduce PAPER_POSITION_SIZE_USD by 50%."
            )

        # 6. Learning readiness
        if overall['total_trades'] < 50:
            recommendations.append(
                f"📊 Need {50 - overall['total_trades']} more trades for statistical significance. "
                f"Current: {overall['total_trades']} trades."
            )

        if not recommendations:
            if overall['profit_factor'] >= 1.05:
                recommendations.append("✅ BOT PERFORMING WELL: PF ≥ 1.05x. Continue current configuration.")
            else:
                recommendations.append("📈 Monitor performance. Insufficient data for strong recommendations.")

        return recommendations

    def get_learning_report(self) -> str:
        """Generate human-readable learning report"""
        analysis = self.analyze_and_optimize()

        if not analysis:
            return "[LEARNING_OPTIMIZER] No trades in database yet."

        overall = analysis.get('overall', {})
        per_symbol = analysis.get('per_symbol', {})
        per_regime = analysis.get('per_regime', {})
        recommendations = analysis.get('recommendations', [])

        report = f"""
╔════════════════════════════════════════════════════════════════════╗
║                   LEARNING OPTIMIZER REPORT                        ║
╚════════════════════════════════════════════════════════════════════╝

📊 OVERALL METRICS:
  • Total Trades: {overall.get('total_trades', 0)}
  • Win Rate: {overall.get('win_rate_pct', 0):.1f}%
  • Profit Factor: {overall.get('profit_factor', 0):.2f}x
  • Avg PnL per trade: {overall.get('avg_pnl_pct', 0):.6f}%
  • Net PnL: ${overall.get('net_pnl_usd', 0):.8f}
  • Timeout Exits: {overall.get('timeout_exits_pct', 0):.1f}%

📈 PER-SYMBOL BREAKDOWN:
"""
        for symbol, metrics in per_symbol.items():
            report += f"  {symbol}:\n"
            report += f"    Trades: {metrics['trades']}\n"
            report += f"    Win Rate: {metrics['win_rate']:.1f}%\n"
            report += f"    PF: {metrics['profit_factor']:.2f}x\n"
            report += f"    Avg PnL: {metrics['avg_pnl_pct']:.6f}%\n"

        report += f"\n🌍 PER-REGIME BREAKDOWN:\n"
        for regime, metrics in per_regime.items():
            report += f"  {regime}:\n"
            report += f"    Trades: {metrics['trades']}\n"
            report += f"    Win Rate: {metrics['win_rate']:.1f}%\n"
            report += f"    PF: {metrics['profit_factor']:.2f}x\n"

        report += f"\n💡 RECOMMENDATIONS:\n"
        for rec in recommendations:
            report += f"  {rec}\n"

        report += "\n"
        return report


# Singleton
_optimizer = None

def get_optimizer() -> LearningOptimizer:
    """Get global optimizer instance"""
    global _optimizer
    if _optimizer is None:
        _optimizer = LearningOptimizer()
    return _optimizer


def print_learning_report():
    """Print learning report to log"""
    optimizer = get_optimizer()
    report = optimizer.get_learning_report()
    log.info(report)
