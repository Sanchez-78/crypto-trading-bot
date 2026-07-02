#!/usr/bin/env python3
"""
Initialize learning database with historical patch data.
Seeds the system with the 6 experiments from the current mission.
"""

from src.services.strategy_learning import StrategyLearningDB

def init_learning_data():
    """Load the 6 experiments we've already done into the learning database."""

    db = StrategyLearningDB()

    # Historical experiments from the extended mission
    experiments = [
        {
            'cycle_number': 3,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0030,
            'new_value': 0.0040,
            'change_reason': 'attempted_tightening',
            'wr_before': 54.05,
            'pnl_before': 25.24,
            'timeout_exits_before': 19,
            'trades_count_before': 96,
            'wr_after': 49.47,
            'pnl_after': 25.23,
            'timeout_exits_after': 19,
            'trades_count_after': 95,
            'success': False,
            'outcome': 'FAILURE'
        },
        {
            'cycle_number': 6,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0040,
            'new_value': 0.0035,
            'change_reason': 'sweet_spot_search',
            'wr_before': 49.47,
            'pnl_before': 25.23,
            'timeout_exits_before': 19,
            'trades_count_before': 95,
            'wr_after': 54.65,
            'pnl_after': 25.27,
            'timeout_exits_after': 9,
            'trades_count_after': 86,
            'success': True,
            'outcome': 'SUCCESS'
        },
        {
            'cycle_number': 14,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0035,
            'new_value': 0.0050,
            'change_reason': 'emergency_conservative',
            'wr_before': 54.65,
            'pnl_before': 25.27,
            'timeout_exits_before': 9,
            'trades_count_before': 86,
            'wr_after': 44.78,
            'pnl_after': 25.23,
            'timeout_exits_after': 36,
            'trades_count_after': 113,
            'success': False,
            'outcome': 'CRITICAL'
        },
        {
            'cycle_number': 18,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0050,
            'new_value': 0.0035,
            'change_reason': 'recovery_attempt',
            'wr_before': 44.78,
            'pnl_before': 25.23,
            'timeout_exits_before': 36,
            'trades_count_before': 134,
            'wr_after': 56.18,
            'pnl_after': 25.27,
            'timeout_exits_after': 9,
            'trades_count_after': 86,
            'success': True,
            'outcome': 'SUCCESS_BREAKTHROUGH'
        },
        {
            'cycle_number': 22,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0035,
            'new_value': 0.0050,
            'change_reason': 'volatility_adjustment',
            'wr_before': 56.18,
            'pnl_before': 25.27,
            'timeout_exits_before': 9,
            'trades_count_before': 86,
            'wr_after': 44.12,
            'pnl_after': 25.23,
            'timeout_exits_after': 59,
            'trades_count_after': 136,
            'success': False,
            'outcome': 'CRITICAL_REGRESSION'
        },
        {
            'cycle_number': 24,
            'parameter': 'entry_gate_pct',
            'old_value': 0.0050,
            'new_value': 0.0060,
            'change_reason': 'emergency_maximum_conservative',
            'wr_before': 44.12,
            'pnl_before': 25.23,
            'timeout_exits_before': 59,
            'trades_count_before': 136,
            'wr_after': 54.65,
            'pnl_after': 25.27,
            'timeout_exits_after': 9,
            'trades_count_after': 86,
            'success': True,
            'outcome': 'EMERGENCY_RECOVERY'
        }
    ]

    print("Loading historical experiments into learning database...")
    for exp in experiments:
        db.record_experiment(exp)
        db.update_rule_from_experiment(exp)
        print(f"  ✓ Cycle {exp['cycle_number']}: {exp['parameter']} "
              f"{exp['old_value']:.4f}→{exp['new_value']:.4f}: {exp['outcome']}")

    # Add known failures to blacklist
    blacklist_entries = [
        {
            'parameter': 'entry_gate_pct',
            'value': 0.0040,
            'reason': 'too_strict - killed_entries - wr_drops_4.58pct',
            'days': 30
        },
        {
            'parameter': 'entry_gate_pct',
            'value': 0.0050,
            'reason': 'allows_bad_entries - position_accumulation - timeout_spike',
            'days': 14  # Can retry after 2 weeks in emergency
        }
    ]

    print("\nAdding known failures to blacklist...")
    for entry in blacklist_entries:
        db.add_to_blacklist(entry['parameter'], entry['value'], entry['reason'], entry['days'])
        print(f"  ✓ Blacklisted: {entry['parameter']}={entry['value']:.4f} ({entry['days']}d)")

    # Print learning statistics
    stats = db.get_statistics()
    print("\n" + "="*60)
    print("LEARNING DATABASE INITIALIZED")
    print("="*60)
    print(f"Total experiments recorded: {stats['total_experiments']}")
    print(f"Successful outcomes: {stats['successful']} ({stats['success_rate_pct']}%)")
    print(f"Blacklisted strategies: {stats['blacklisted_strategies']}")
    print(f"Learned rules: {stats['learned_rules']}")
    print("\nLEARNED RULES:")

    conn = __import__('sqlite3').connect('/opt/cryptomaster/local_learning_storage/strategy_learning.db')
    conn.row_factory = __import__('sqlite3').Row
    c = conn.cursor()
    c.execute("SELECT * FROM strategy_rules")

    for row in c.fetchall():
        rule = dict(row)
        print(f"\n  {rule['parameter']}:")
        print(f"    Optimal value: {rule['optimal_value']:.4f}")
        print(f"    Safe range: [{rule['min_value']:.4f}, {rule['max_value']:.4f}]")
        print(f"    Success rate: {rule['success_rate']*100:.1f}% ({rule['sample_count']} trials)")

    conn.close()

    print("\n✅ Learning database ready for Phase 2!")


if __name__ == '__main__':
    init_learning_data()
