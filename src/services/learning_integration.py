#!/usr/bin/env python3
"""
Integration layer for Strategy Learning System with Extended Mission Daemon.
Automatically records metrics at each cycle and validates changes against history.
"""

from typing import Dict, Optional, Tuple
from src.services.strategy_learning import StrategyLearningDB, HistoryValidator


class LearningIntegration:
    """Integrates learning system with autonomous mission daemon."""

    def __init__(self):
        self.db = StrategyLearningDB()
        self.validator = HistoryValidator(self.db)

    def record_cycle_end(self, cycle_number: int, metrics: Dict, current_gate: float) -> bool:
        """Record metrics at cycle end for trend analysis."""
        try:
            metrics['gate_pct'] = current_gate
            self.db.record_cycle_snapshot(cycle_number, metrics)
            return True
        except Exception as e:
            print(f"[LEARNING] Error recording cycle {cycle_number}: {e}")
            return False

    def validate_proposed_change(self, parameter: str, old_value: float, new_value: float) -> Tuple[bool, str, float]:
        """MANDATORY: Validate before executing ANY parameter change."""
        return self.validator.validate_change(parameter, old_value, new_value)

    def record_experiment_result(self, cycle_number: int, parameter: str, old_value: float, new_value: float,
                                 metrics_before: Dict, metrics_after: Dict, change_reason: str = "") -> bool:
        """Record experiment results and update learned rules."""
        try:
            wr_delta = metrics_after.get('wr_pct', 0) - metrics_before.get('wr_pct', 0)
            success = wr_delta > -1.0

            if success:
                outcome = 'SUCCESS_MAJOR' if wr_delta > 2.0 else 'SUCCESS_MINOR'
            else:
                outcome = 'CRITICAL_FAILURE' if wr_delta < -5.0 else 'FAILURE'

            experiment = {
                'cycle_number': cycle_number,
                'parameter': parameter,
                'old_value': old_value,
                'new_value': new_value,
                'change_reason': change_reason,
                'wr_before': metrics_before.get('wr_pct'),
                'pnl_before': metrics_before.get('pnl_usd'),
                'timeout_exits_before': metrics_before.get('timeout_exits'),
                'trades_count_before': metrics_before.get('trades_count'),
                'wr_after': metrics_after.get('wr_pct'),
                'pnl_after': metrics_after.get('pnl_usd'),
                'timeout_exits_after': metrics_after.get('timeout_exits'),
                'trades_count_after': metrics_after.get('trades_count'),
                'success': success,
                'outcome': outcome
            }

            self.db.record_experiment(experiment)
            self.db.update_rule_from_experiment(experiment)

            if outcome == 'CRITICAL_FAILURE':
                self.db.add_to_blacklist(parameter, new_value, f"critical_failure_wr_delta_{wr_delta:.1f}", days_until_retry=7)

            return True
        except Exception as e:
            print(f"[LEARNING] Error recording experiment: {e}")
            return False

    def get_statistics(self) -> Dict:
        """Get current learning system statistics."""
        return self.db.get_statistics()


learning = LearningIntegration()
