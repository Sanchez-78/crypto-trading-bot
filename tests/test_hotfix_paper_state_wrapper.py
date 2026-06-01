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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
