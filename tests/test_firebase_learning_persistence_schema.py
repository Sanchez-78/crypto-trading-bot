"""Regression test for the P0-FIX (2026-08-05) schema-drop bug in
FirebaseLearningPersistence.save_learning_state()/load_learning_state().

Before the fix: save_learning_state() reconstructed a 3-field-only dict
(lifetime_metrics, regime_tp_strategy, rolling_windows), silently dropping
everything else the caller passed in — in particular segment_weights,
qualification_window, qualification_n, qualification_started_at,
operator_unlock, and paper_admission_controls. Since
paper_adaptive_learning.py._load_state() tries this Firebase-backed path
FIRST on every process restart, those fields silently reset to defaults on
every restart even though they had real accumulated values.

See _workspace/03_forensics_learning_persistence.md for the full evidence
trail (confirmed via deterministic static code trace, plus a live read-only
check against production state).
"""

import os
import tempfile
import shutil
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.firebase_learning_persistence import FirebaseLearningPersistence


class TestFirebaseLearningPersistenceSchemaRoundTrip(unittest.TestCase):
    """A save/load round trip through FirebaseLearningPersistence must not
    drop any field the caller provided — regardless of whether this module
    knows the field's name."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_learning_state_phase1.json")
        self.persistence = FirebaseLearningPersistence(state_file=self.state_file)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _full_learning_obj(self):
        """Mirrors the dict shape paper_adaptive_learning.py._save_state() builds."""
        return {
            "lifetime_metrics": {
                "trades_closed": 466,
                "profit_factor": 1.10,
                "expectancy": 0.01,
                "net_pnl": 4.5,
            },
            "learning_controls": {
                "lifecycle": "PAPER_COLLECTING",
                "learning_enabled": True,
                "learning_blend": 1.0,
            },
            "regime_tp_strategy": {"BULL_TREND": {"low_vol": {"tp_pct": 0.20, "wr": 0.55, "n": 40}}},
            "rolling_windows": {"rolling20": [], "rolling50": [], "rolling100": []},
            "segment_weights": {"BTCUSDT:BULL_TREND:BUY": 0.35},
            "qualification_schema_version": 1,
            "qualification_started_at": 1754000000.0,
            "qualification_n": 100,
            "qualification_window": [(0.01, "WIN", "BTCUSDT:BULL_TREND:BUY", 1754000100.0, "trade-123")],
            "operator_unlock": False,
            "paper_admission_controls": {
                "starvation_discovery_cooldown": {"active": True, "cooldown_until": 1754003600.0},
                "c_weak_segment_cooldowns": {},
            },
            "recorded_trade_ids": ["trade-123", "trade-124"],
        }

    def test_save_then_load_round_trips_every_field(self):
        obj = self._full_learning_obj()
        assert self.persistence.save_learning_state(obj) is True

        loaded = self.persistence.load_learning_state()
        assert loaded is not None, "load should succeed (>=20 trades, fresh timestamp)"

        # The fields that were silently dropped before the fix:
        assert loaded["segment_weights"] == obj["segment_weights"], \
            "segment_weights must survive the save/load round trip"
        assert loaded["qualification_n"] == 100, \
            "qualification_n must survive the save/load round trip"
        # JSON round-trips tuples as lists — compare element-wise, not by type.
        assert [list(e) for e in loaded["qualification_window"]] == \
               [list(e) for e in obj["qualification_window"]], \
            "qualification_window must survive the save/load round trip"
        assert loaded["qualification_started_at"] == obj["qualification_started_at"]
        assert loaded["operator_unlock"] == obj["operator_unlock"]
        assert loaded["paper_admission_controls"] == obj["paper_admission_controls"], \
            "paper_admission_controls (cooldowns/quarantines) must survive the round trip"
        assert loaded["recorded_trade_ids"] == obj["recorded_trade_ids"]

        # Fields that already round-tripped correctly before the fix must still work.
        assert loaded["lifetime_metrics"] == obj["lifetime_metrics"]
        assert loaded["regime_tp_strategy"] == obj["regime_tp_strategy"]
        assert loaded["rolling_windows"] == obj["rolling_windows"]

    def test_full_paper_adaptive_learning_restart_cycle_preserves_qualification(self):
        """End-to-end: a PaperAdaptiveLearning instance saving via this module,
        then a FRESH instance loading (simulating a process restart going
        through the Firebase-first load path), must see the same
        qualification_n it had before the restart."""
        from src.services import paper_adaptive_learning as pal

        # Point both the Firebase-path singleton functions and _firebase_available
        # at our isolated persistence instance for this test.
        orig_save, orig_load, orig_avail = pal.save_learning, pal.load_learning, pal._firebase_available
        try:
            pal.save_learning = self.persistence.save_learning_state
            pal.load_learning = self.persistence.load_learning_state
            pal._firebase_available = True

            local_state_file = os.path.join(self.temp_dir, "local_adaptive_state.json")
            learner = pal.PaperAdaptiveLearning(state_file=local_state_file)
            learner.qualification_started_at = 0.0  # accept any entry_ts as post-epoch
            for i in range(20):
                learner.record_close({
                    "trade_id": f"t{i}",
                    "symbol": "BTCUSDT",
                    "regime": "BULL_TREND",
                    "side": "BUY",
                    "outcome": "WIN",
                    "net_pnl_pct": 0.2,
                    "entry_ts": 1.0,
                    "training_bucket": "A_STRICT_TAKE",
                })
            assert learner.qualification_n == 20

            # Simulate a restart: fresh instance, same (now-populated) persistence backend.
            restarted = pal.PaperAdaptiveLearning(state_file=local_state_file)
            assert restarted.qualification_n == 20, (
                "qualification_n must survive a simulated process restart via the "
                "Firebase-first load path, not silently reset to 0"
            )
        finally:
            pal.save_learning, pal.load_learning, pal._firebase_available = orig_save, orig_load, orig_avail


if __name__ == "__main__":
    unittest.main()
