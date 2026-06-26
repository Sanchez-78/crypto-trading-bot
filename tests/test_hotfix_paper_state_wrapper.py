"""Hotfix Tests: Paper State Wrapper Compatibility

Regression tests for wrapper schema {"positions": {}} support.
"""

import pytest
import json
import tempfile
import os
import time
from pathlib import Path


class TestPaperStateWrapperSchema:
    """Test paper state loader with wrapper schema."""

    def test_wrapper_empty_loads_zero_positions(self):
        """Empty wrapper {"positions": {}} loads zero positions."""
        from src.services import paper_trade_executor

        # Create temp file with wrapper format
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"positions": {}}, f)
            temp_file = f.name

        try:
            # Patch state file path
            original_file = paper_trade_executor._STATE_FILE
            paper_trade_executor._STATE_FILE = temp_file

            # Clear positions
            paper_trade_executor._POSITIONS.clear()

            # Load
            paper_trade_executor._load_paper_state()

            # Verify: should have zero positions
            assert len(paper_trade_executor._POSITIONS) == 0, f"Expected 0 positions, got {len(paper_trade_executor._POSITIONS)}"

        finally:
            paper_trade_executor._STATE_FILE = original_file
            os.unlink(temp_file)

    def test_wrapper_with_valid_position(self):
        """Wrapper with valid position loads exactly one position."""
        from src.services import paper_trade_executor

        now = time.time()
        valid_position = {
            "trade_id": "trade_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_price": 50000.0,
            "entry_ts": now - 10.0,  # 10 seconds ago (well under max_hold_s)
            "size_usd": 100.0,
            "max_hold_s": 300.0,
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"positions": {"trade_001": valid_position}}, f)
            temp_file = f.name

        try:
            original_file = paper_trade_executor._STATE_FILE
            paper_trade_executor._STATE_FILE = temp_file
            paper_trade_executor._POSITIONS.clear()

            paper_trade_executor._load_paper_state()

            assert len(paper_trade_executor._POSITIONS) == 1
            assert "trade_001" in paper_trade_executor._POSITIONS
            assert paper_trade_executor._POSITIONS["trade_001"]["symbol"] == "BTCUSDT"

        finally:
            paper_trade_executor._STATE_FILE = original_file
            os.unlink(temp_file)

    def test_legacy_format_still_works(self):
        """Legacy format {"trade1": position} still loads correctly."""
        from src.services import paper_trade_executor

        now = time.time()
        valid_position = {
            "trade_id": "trade_002",
            "symbol": "ETHUSDT",
            "side": "SELL",
            "entry_price": 2000.0,
            "entry_ts": now - 10.0,
            "size_usd": 200.0,
            "max_hold_s": 300.0,
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            # Legacy format: direct dict with trade_id as key
            json.dump({"trade_002": valid_position}, f)
            temp_file = f.name

        try:
            original_file = paper_trade_executor._STATE_FILE
            paper_trade_executor._STATE_FILE = temp_file
            paper_trade_executor._POSITIONS.clear()

            paper_trade_executor._load_paper_state()

            assert len(paper_trade_executor._POSITIONS) == 1
            assert "trade_002" in paper_trade_executor._POSITIONS
            assert paper_trade_executor._POSITIONS["trade_002"]["symbol"] == "ETHUSDT"

        finally:
            paper_trade_executor._STATE_FILE = original_file
            os.unlink(temp_file)

    def test_invalid_metadata_skipped(self):
        """Invalid metadata records are skipped, not normalized as positions."""
        from src.services import paper_trade_executor

        now = time.time()
        data = {
            "positions": {
                "trade_003": {  # Valid
                    "trade_id": "trade_003",
                    "symbol": "ADAUSDT",
                    "side": "BUY",
                    "entry_price": 0.5,
                    "entry_ts": now - 10.0,
                    "size_usd": 50.0,
                    "max_hold_s": 300.0,
                },
                "positions": {},  # Invalid: "positions" key
                "max_hold_s": 900.0,  # Invalid: non-dict value
                "metadata": {"version": 1},  # Invalid: metadata key
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            temp_file = f.name

        try:
            original_file = paper_trade_executor._STATE_FILE
            paper_trade_executor._STATE_FILE = temp_file
            paper_trade_executor._POSITIONS.clear()

            paper_trade_executor._load_paper_state()

            # Should load only the valid position
            assert len(paper_trade_executor._POSITIONS) == 1
            assert "trade_003" in paper_trade_executor._POSITIONS
            assert paper_trade_executor._POSITIONS["trade_003"]["symbol"] == "ADAUSDT"
            # Invalid keys should not be in _POSITIONS
            assert "positions" not in paper_trade_executor._POSITIONS
            assert "metadata" not in paper_trade_executor._POSITIONS

        finally:
            paper_trade_executor._STATE_FILE = original_file
            os.unlink(temp_file)

    def test_position_without_max_hold_migrated(self):
        """Position without max_hold_s field gets migrated with default."""
        from src.services import paper_trade_executor

        now = time.time()
        data = {
            "positions": {
                "trade_004": {  # Valid with explicit max_hold_s
                    "trade_id": "trade_004",
                    "symbol": "XRPUSDT",
                    "side": "BUY",
                    "entry_price": 2.5,
                    "entry_ts": now - 10.0,
                    "size_usd": 75.0,
                    "max_hold_s": 300.0,
                },
                "trade_005": {  # Missing max_hold_s (will be migrated)
                    "trade_id": "trade_005",
                    "symbol": "LTCUSDT",
                    "side": "SELL",
                    "entry_price": 100.0,
                    "entry_ts": now - 10.0,
                    "size_usd": 100.0,
                    # No max_hold_s - should be added during migration
                },
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            temp_file = f.name

        try:
            original_file = paper_trade_executor._STATE_FILE
            paper_trade_executor._STATE_FILE = temp_file
            paper_trade_executor._POSITIONS.clear()

            paper_trade_executor._load_paper_state()

            # Both positions should be loaded and migrated
            assert len(paper_trade_executor._POSITIONS) == 2
            assert "trade_004" in paper_trade_executor._POSITIONS
            assert "trade_005" in paper_trade_executor._POSITIONS
            # trade_005 should have max_hold_s added
            assert paper_trade_executor._POSITIONS["trade_005"].get("max_hold_s") is not None

        finally:
            paper_trade_executor._STATE_FILE = original_file
            os.unlink(temp_file)

    def test_position_without_tp_sl_gets_defaults(self):
        """P1.1AV: Position without tp/sl gets safe defaults based on entry_price and side."""
        from src.services import paper_trade_executor

        now = time.time()
        # Position WITHOUT tp/sl fields (the blocker condition)
        position_no_tp_sl = {
            "trade_id": "trade_no_tp_sl",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_price": 50000.0,
            "entry_ts": now - 10.0,
            "size_usd": 100.0,
            "max_hold_s": 300.0,
            # MISSING: "tp" and "sl" fields
        }

        # Normalize position
        normalized = paper_trade_executor._normalize_position_for_loading(position_no_tp_sl.copy())

        # Verify tp/sl defaults were added
        assert "tp" in normalized, "TP should be added"
        assert "sl" in normalized, "SL should be added"
        assert normalized["tp"] > 0, f"TP should be positive, got {normalized['tp']}"
        assert normalized["sl"] > 0, f"SL should be positive, got {normalized['sl']}"
        # BUY: tp > entry_price, sl < entry_price
        assert normalized["tp"] > normalized["entry_price"], f"BUY tp={normalized['tp']} should be > entry={normalized['entry_price']}"
        assert normalized["sl"] < normalized["entry_price"], f"BUY sl={normalized['sl']} should be < entry={normalized['entry_price']}"

    def test_position_tp_sl_defaults_allow_evaluation(self):
        """P1.1AV: Loaded position with TP/SL defaults evaluates exits, doesn't skip to timeout."""
        from src.services import paper_trade_executor

        # Verify the blocker gate: if pos.get("tp") and pos["tp"] > 0 and pos.get("sl") and pos["sl"] > 0
        # Gate should PASS after normalization (TP/SL present and valid)
        now = time.time()
        position_no_tp_sl = {
            "trade_id": "trade_eval",
            "symbol": "ETHUSDT",
            "side": "BUY",
            "entry_price": 2000.0,
            "entry_ts": now - 10.0,
            "size_usd": 50.0,
            "max_hold_s": 300.0,
        }

        # Normalize: adds tp/sl defaults
        normalized = paper_trade_executor._normalize_position_for_loading(position_no_tp_sl.copy())

        # Simulate the gate check from line 1987
        gate_passes = (
            normalized.get("tp") and normalized["tp"] > 0 and
            normalized.get("sl") and normalized["sl"] > 0
        )
        assert gate_passes, "TP/SL gate should PASS after normalization (TP/SL evaluation enabled)"

    def test_sell_position_tp_sl_defaults_direction(self):
        """P1.1AV: SELL position tp/sl defaults have correct price direction (tp < entry, sl > entry)."""
        from src.services import paper_trade_executor

        now = time.time()
        # SELL position without tp/sl
        position_sell = {
            "trade_id": "trade_sell",
            "symbol": "ADAUSDT",
            "side": "SELL",
            "entry_price": 0.5,
            "entry_ts": now - 10.0,
            "size_usd": 75.0,
            "max_hold_s": 300.0,
            # MISSING: "tp" and "sl"
        }

        # Normalize: adds tp/sl defaults with SELL-aware calculation
        normalized = paper_trade_executor._normalize_position_for_loading(position_sell.copy())

        # Verify SELL direction: tp < entry_price, sl > entry_price
        assert normalized["tp"] > 0, f"SELL tp should be positive, got {normalized['tp']}"
        assert normalized["sl"] > 0, f"SELL sl should be positive, got {normalized['sl']}"
        assert normalized["tp"] < normalized["entry_price"], f"SELL tp={normalized['tp']} should be < entry={normalized['entry_price']}"
        assert normalized["sl"] > normalized["entry_price"], f"SELL sl={normalized['sl']} should be > entry={normalized['entry_price']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
