"""
Learning Optimizer - V10.16
Auto-calibrates trading parameters based on closed trade performance.
"""

import logging
from typing import Dict
from src.services.local_learning_storage import get_storage

log = logging.getLogger(__name__)

def analyze_performance(symbol: str = None, min_trades: int = 10) -> Dict:
    """Analyze closed trades to determine performance."""
    storage = get_storage()
    trades = storage.get_trades(symbol=symbol) if symbol else storage.get_all_trades()

    if not trades or len(trades) < min_trades:
        return {'error': f'Insufficient trades (need {min_trades}, got {len(trades) if trades else 0})'}

    total = len(trades)
    wins = sum(1 for t in trades if t.get('pnl_pct', 0) > 0)
    losses = sum(1 for t in trades if t.get('pnl_pct', 0) < 0)

    pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)
    wr = wins / total if total > 0 else 0
    exp = sum(t.get('pnl_pct', 0) for t in trades) / total if total > 0 else 0

    # Exit distribution
    exit_dist = {}
    for t in trades:
        reason = t.get('exit_reason', 'UNKNOWN').upper()
        exit_dist[reason] = exit_dist.get(reason, 0) + 1

    return {
        'symbol': symbol or 'ALL',
        'total_trades': total,
        'win_rate': round(wr, 3),
        'profit_factor': round(pf, 2),
        'expectancy': round(exp, 4),
        'exit_dist': exit_dist
    }

def recommend_adjustments(performance: Dict) -> Dict:
    """Recommend parameter changes based on performance."""
    if 'error' in performance:
        return {'action': 'HOLD', 'reason': performance['error'], 'urgency': 'NORMAL'}

    pf = performance.get('profit_factor', 0.0)
    wr = performance.get('win_rate', 0.0)
    exit_dist = performance.get('exit_dist', {})
    timeout_rate = exit_dist.get('TIMEOUT', 0) / performance.get('total_trades', 1)

    if pf >= 1.05:
        return {'action': 'HOLD', 'reason': f'PF {pf:.2f}x healthy', 'urgency': 'NORMAL'}
    elif timeout_rate > 0.95:
        return {'action': 'PAUSE', 'reason': f'Timeout {timeout_rate:.1%} - TP/SL broken', 'urgency': 'CRITICAL'}
    elif pf < 0.5:
        return {'action': 'PAUSE', 'reason': f'PF {pf:.2f}x critical loss', 'urgency': 'CRITICAL'}
    else:
        return {'action': 'MONITOR', 'reason': f'PF {pf:.2f}x - monitoring', 'urgency': 'NORMAL'}

def maybe_analyze():
    """Call periodically to trigger analysis."""
    perf = analyze_performance(min_trades=5)
    if 'error' not in perf:
        adj = recommend_adjustments(perf)
        log.info(
            f"[LEARNING_OPTIMIZER] wr={perf['win_rate']:.1%} pf={perf['profit_factor']:.2f}x "
            f"exp={perf['expectancy']:.4f} action={adj['action']}"
        )
