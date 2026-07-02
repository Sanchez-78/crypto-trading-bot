#!/usr/bin/env python3
"""
Autonomous Learning System - Phase 1: Setup & Data Recording

Records every strategy change and result, builds knowledge base for autonomous decisions.
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Tuple

DB_PATH = "/opt/cryptomaster/local_learning_storage/strategy_learning.db"


class StrategyLearningDB:
    """
    Database for recording experiments, learning optimal values, managing blacklists.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def init_schema(self):
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Strategy experiments: every change we make and its result
        c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_number INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

                -- What changed
                parameter TEXT NOT NULL,
                old_value REAL,
                new_value REAL NOT NULL,
                change_reason TEXT,

                -- Before metrics
                wr_before REAL,
                pnl_before REAL,
                timeout_exits_before INTEGER,
                trades_count_before INTEGER,

                -- After metrics (recorded next cycle)
                wr_after REAL,
                pnl_after REAL,
                timeout_exits_after INTEGER,
                trades_count_after INTEGER,

                -- Analysis
                impact_wr REAL,
                impact_timeouts REAL,
                impact_volume REAL,
                success BOOLEAN,
                outcome TEXT,

                -- Learning
                repeat_count INTEGER DEFAULT 1,
                confidence REAL DEFAULT 0.5
            )
        """)

        # Strategy rules: learned safe ranges and optimal values
        c.execute("""
            CREATE TABLE IF NOT EXISTS strategy_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parameter TEXT UNIQUE NOT NULL,

                min_value REAL,
                max_value REAL,
                optimal_value REAL,

                market_condition TEXT DEFAULT 'unknown',
                wr_range_min REAL,
                wr_range_max REAL,

                success_rate REAL DEFAULT 0.5,
                sample_count INTEGER DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Failed strategies blacklist
        c.execute("""
            CREATE TABLE IF NOT EXISTS failed_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parameter TEXT NOT NULL,
                value REAL NOT NULL,
                reason TEXT,
                failure_count INTEGER DEFAULT 1,
                last_attempted DATETIME DEFAULT CURRENT_TIMESTAMP,
                blacklist_until DATETIME,
                confidence REAL DEFAULT 0.8
            )
        """)

        # Cycle snapshots: metrics at each cycle for reference
        c.execute("""
            CREATE TABLE IF NOT EXISTS cycle_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_number INTEGER UNIQUE NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

                wr_pct REAL,
                pnl_usd REAL,
                trades_count INTEGER,
                open_positions INTEGER,
                timeout_exits_count INTEGER,
                tp_exits_count INTEGER,
                sl_exits_count INTEGER,

                gate_pct REAL,
                notes TEXT
            )
        """)

        conn.commit()
        conn.close()

    def record_cycle_snapshot(self, cycle_number: int, metrics: Dict):
        """Record metrics at each cycle for trend analysis."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            INSERT OR REPLACE INTO cycle_snapshots
            (cycle_number, wr_pct, pnl_usd, trades_count, open_positions,
             timeout_exits_count, tp_exits_count, sl_exits_count, gate_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cycle_number,
            metrics.get('wr_pct'),
            metrics.get('pnl_usd'),
            metrics.get('trades_count'),
            metrics.get('open_positions'),
            metrics.get('timeout_exits'),
            metrics.get('tp_exits'),
            metrics.get('sl_exits'),
            metrics.get('gate_pct')
        ))

        conn.commit()
        conn.close()

    def record_experiment(self, experiment: Dict) -> int:
        """Record a strategy experiment (parameter change and results)."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            INSERT INTO strategy_experiments
            (cycle_number, parameter, old_value, new_value, change_reason,
             wr_before, pnl_before, timeout_exits_before, trades_count_before,
             wr_after, pnl_after, timeout_exits_after, trades_count_after,
             impact_wr, impact_timeouts, impact_volume, success, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            experiment['cycle_number'],
            experiment['parameter'],
            experiment.get('old_value'),
            experiment['new_value'],
            experiment.get('change_reason'),
            experiment.get('wr_before'),
            experiment.get('pnl_before'),
            experiment.get('timeout_exits_before'),
            experiment.get('trades_count_before'),
            experiment.get('wr_after'),
            experiment.get('pnl_after'),
            experiment.get('timeout_exits_after'),
            experiment.get('trades_count_after'),
            experiment.get('wr_after', 0) - experiment.get('wr_before', 0),
            experiment.get('timeout_exits_after', 0) - experiment.get('timeout_exits_before', 0),
            experiment.get('trades_count_after', 0) - experiment.get('trades_count_before', 0),
            experiment.get('success', False),
            experiment.get('outcome', 'UNKNOWN')
        ))

        conn.commit()
        last_id = c.lastrowid
        conn.close()
        return last_id

    def add_to_blacklist(self, parameter: str, value: float, reason: str, days_until_retry: int = 7):
        """Add a failed strategy to blacklist (don't retry for N days)."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        blacklist_until = datetime.now(timezone.utc) + timedelta(days=days_until_retry)

        # Check if already blacklisted
        c.execute("""
            SELECT id, failure_count FROM failed_strategies
            WHERE parameter = ? AND value = ?
        """, (parameter, value))
        existing = c.fetchone()

        if existing:
            # Update existing entry
            new_count = existing[1] + 1
            c.execute("""
                UPDATE failed_strategies
                SET failure_count = ?, last_attempted = ?, blacklist_until = ?, reason = ?
                WHERE id = ?
            """, (new_count, datetime.now(timezone.utc), blacklist_until, reason, existing[0]))
        else:
            # Create new entry
            c.execute("""
                INSERT INTO failed_strategies
                (parameter, value, reason, blacklist_until, confidence)
                VALUES (?, ?, ?, ?, ?)
            """, (parameter, value, reason, blacklist_until, 0.8))

        conn.commit()
        conn.close()

    def is_blacklisted(self, parameter: str, value: float) -> Tuple[bool, Optional[str]]:
        """Check if a strategy is blacklisted. Returns (is_blacklisted, reason)."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            SELECT reason, blacklist_until FROM failed_strategies
            WHERE parameter = ? AND value = ?
            AND blacklist_until > datetime('now')
        """, (parameter, value))

        result = c.fetchone()
        conn.close()

        if result:
            return True, f"{result[0]} (blacklisted until {result[1]})"
        return False, None

    def get_learned_bounds(self, parameter: str) -> Optional[Dict]:
        """Get learned safe bounds for a parameter."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            SELECT min_value, max_value, optimal_value, success_rate, sample_count
            FROM strategy_rules
            WHERE parameter = ?
        """, (parameter,))

        result = c.fetchone()
        conn.close()

        if result:
            return {
                'min': result[0],
                'max': result[1],
                'optimal': result[2],
                'success_rate': result[3],
                'sample_count': result[4]
            }
        return None

    def get_experiment_history(self, parameter: str, limit: int = 10) -> List[Dict]:
        """Get experiment history for a parameter."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT * FROM strategy_experiments
            WHERE parameter = ?
            ORDER BY cycle_number DESC
            LIMIT ?
        """, (parameter, limit))

        results = [dict(row) for row in c.fetchall()]
        conn.close()
        return results

    def was_recently_tried(self, parameter: str, old_value: float, new_value: float, cycles: int = 5) -> bool:
        """Check if this exact change was tried in last N cycles."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            SELECT COUNT(*) FROM strategy_experiments
            WHERE parameter = ? AND old_value = ? AND new_value = ?
            AND cycle_number > (SELECT MAX(cycle_number) FROM cycle_snapshots) - ?
        """, (parameter, old_value, new_value, cycles))

        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def update_rule_from_experiment(self, experiment: Dict):
        """Update strategy rule based on experiment result."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        parameter = experiment['parameter']
        new_value = experiment['new_value']
        impact_wr = experiment.get('impact_wr', 0)
        success = experiment.get('success', False)

        # Get or create rule
        c.execute("SELECT * FROM strategy_rules WHERE parameter = ?", (parameter,))
        rule = c.fetchone()

        if not rule:
            # Create new rule with learned value
            c.execute("""
                INSERT INTO strategy_rules
                (parameter, optimal_value, min_value, max_value, success_rate, sample_count)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (parameter, new_value, new_value * 0.8, new_value * 1.2, 1.0 if success else 0.0))
        else:
            # Update existing rule
            old_success_rate = rule[7] or 0.5  # success_rate (default to 0.5 if NULL)
            old_sample_count = rule[8] or 1  # sample_count (default to 1 if NULL)
            new_sample_count = old_sample_count + 1
            new_success_rate = (
                (old_success_rate * old_sample_count + (1.0 if success else 0.0)) / new_sample_count
            )

            # Update optimal value if major improvement
            optimal_value = rule[3] if impact_wr < 0.5 else new_value

            c.execute("""
                UPDATE strategy_rules
                SET success_rate = ?, sample_count = ?, optimal_value = ?, last_updated = ?
                WHERE parameter = ?
            """, (new_success_rate, new_sample_count, optimal_value, datetime.now(timezone.utc), parameter))

        conn.commit()
        conn.close()

    def get_statistics(self) -> Dict:
        """Get overall learning statistics."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM strategy_experiments")
        total_experiments = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM strategy_experiments WHERE success = 1")
        successful = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM failed_strategies")
        blacklisted = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM strategy_rules")
        learned_rules = c.fetchone()[0]

        conn.close()

        success_rate = (successful / total_experiments * 100) if total_experiments > 0 else 0

        return {
            'total_experiments': total_experiments,
            'successful': successful,
            'success_rate_pct': round(success_rate, 1),
            'blacklisted_strategies': blacklisted,
            'learned_rules': learned_rules
        }


class HistoryValidator:
    """
    Validates proposed changes against learned history.
    CORE safety mechanism - prevents repeating mistakes.
    """

    def __init__(self, db: StrategyLearningDB):
        self.db = db

    def validate_change(self, parameter: str, old_value: float, new_value: float) -> Tuple[bool, str, float]:
        """
        Validate a proposed change.
        Returns: (allowed: bool, reason: str, confidence_score: float)
        """

        # Check 1: Is this blacklisted?
        is_blacklisted, reason = self.db.is_blacklisted(parameter, new_value)
        if is_blacklisted:
            return False, f"Blacklisted: {reason}", 0.0

        # Check 2: Was this tried recently?
        if self.db.was_recently_tried(parameter, old_value, new_value, cycles=5):
            history = self.db.get_experiment_history(parameter, limit=1)
            if history:
                last = history[0]
                if not last['success']:
                    return False, f"Already tried in cycle {last['cycle_number']}, resulted in failure", 0.0

        # Check 3: Is it within learned safe bounds?
        bounds = self.db.get_learned_bounds(parameter)
        if bounds:
            if new_value < bounds['min'] or new_value > bounds['max']:
                return False, (
                    f"Outside learned bounds for {parameter}: "
                    f"learned range [{bounds['min']:.4f}, {bounds['max']:.4f}], "
                    f"proposed {new_value:.4f}"
                ), 0.0

            confidence = bounds['success_rate'] if bounds['sample_count'] >= 3 else 0.5
        else:
            confidence = 0.5

        return True, "APPROVED", confidence

    def get_recommendation(self, parameter: str) -> Optional[Dict]:
        """
        Recommend a value for a parameter based on learned history.
        """
        bounds = self.db.get_learned_bounds(parameter)
        if not bounds or bounds['sample_count'] < 2:
            return None

        return {
            'parameter': parameter,
            'recommended_value': bounds['optimal'],
            'safe_range': [bounds['min'], bounds['max']],
            'confidence': bounds['success_rate'],
            'tried_times': bounds['sample_count']
        }
