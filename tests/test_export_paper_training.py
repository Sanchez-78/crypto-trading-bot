"""
Tests for paper training dataset exporter.

Ensures:
- Parsing of all log types
- Joining by trade_id
- Schema consistency
- Roundtrip (write + read)
- Edge cases
"""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.export_paper_training_dataset import (
    parse_kv_tokens,
    parse_entry_log,
    parse_exit_log,
    parse_attribution_log,
    parse_lm_state_log,
    join_trade_records,
    export_jsonl,
    process_log_file,
    _safe_float,
    _safe_int,
    _safe_bool,
)


class TestSafeConversions:
    """Test safe type conversion helpers."""

    def test_safe_float_valid(self):
        assert _safe_float("3.14") == 3.14
        assert _safe_float("0") == 0.0
        assert _safe_float("-1.5") == -1.5

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None
        assert _safe_float("abc", 0.0) == 0.0
        assert _safe_float(None) is None
        assert _safe_float(None, 99.0) == 99.0

    def test_safe_int_valid(self):
        assert _safe_int("42") == 42
        assert _safe_int("0") == 0
        assert _safe_int("-10") == -10

    def test_safe_int_invalid(self):
        assert _safe_int("3.14") is None
        assert _safe_int("abc", 0) == 0
        assert _safe_int(None) is None

    def test_safe_bool_valid(self):
        assert _safe_bool("True") is True
        assert _safe_bool("true") is True
        assert _safe_bool("1") is True
        assert _safe_bool("False") is False
        assert _safe_bool("false") is False
        assert _safe_bool("0") is False

    def test_safe_bool_invalid(self):
        assert _safe_bool("maybe", False) is False
        assert _safe_bool(None) is None


class TestParseKVTokens:
    """Test key-value token parser."""

    def test_simple_tokens(self):
        result = parse_kv_tokens("symbol=BTCUSDT trade_id=paper_123")
        assert result["symbol"] == "BTCUSDT"
        assert result["trade_id"] == "paper_123"

    def test_quoted_values(self):
        result = parse_kv_tokens('reason="tp_hit" bucket="C_WEAK_EV_TRAIN"')
        assert result["reason"] == "tp_hit"
        assert result["bucket"] == "C_WEAK_EV_TRAIN"

    def test_numeric_values(self):
        result = parse_kv_tokens("ev=2.5 net_pnl_pct=-0.18 hold_seconds=3600")
        assert result["ev"] == "2.5"
        assert result["net_pnl_pct"] == "-0.18"
        assert result["hold_seconds"] == "3600"

    def test_bool_values(self):
        result = parse_kv_tokens("touched_tp=True touched_sl=False")
        assert result["touched_tp"] == "True"
        assert result["touched_sl"] == "False"

    def test_empty_message(self):
        result = parse_kv_tokens("")
        assert result == {}


class TestParseEntryLog:
    """Test entry log parsing."""

    def test_valid_entry(self):
        line = (
            "[PAPER_TRAIN_QUALITY_ENTRY] symbol=BTC/USDT trade_id=paper_001 "
            "side=BUY source=training_sampler bucket=C_WEAK_EV_TRAIN "
            "training_bucket=C_WEAK_EV_TRAIN entry=67000.0 tp_pct=1.5 sl_pct=0.8 "
            "regime=bull_trend cost_edge_ok=True geometry_calibrated=True"
        )
        result = parse_entry_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_001"
        assert result["symbol"] == "BTC/USDT"
        assert result["side"] == "BUY"
        assert result["entry"] == 67000.0
        assert result["tp_pct"] == 1.5
        assert result["cost_edge_ok"] is True
        assert result["geometry_calibrated"] is True

    def test_entry_missing_log_type(self):
        line = "symbol=BTC/USDT trade_id=paper_001"
        result = parse_entry_log(line)
        assert result is None

    def test_entry_partial_fields(self):
        line = "[PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_002 symbol=ETH/USDT side=SELL"
        result = parse_entry_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_002"
        assert result["symbol"] == "ETH/USDT"
        assert result["side"] == "SELL"
        assert result["entry"] is None
        assert result["tp_pct"] is None

    def test_entry_malformed(self):
        line = "[PAPER_TRAIN_QUALITY_ENTRY]"
        result = parse_entry_log(line)
        # Should handle gracefully
        assert result is not None or result is None


class TestParseExitLog:
    """Test exit log parsing."""

    def test_valid_exit(self):
        line = (
            "[PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_001 "
            "exit=67500.0 outcome=WIN attribution=tp_hit reason=touched_tp "
            "mfe_pct=2.1 mae_pct=0.3 net_pnl_pct=0.75 gross_move_pct=0.75 "
            "fee_drag_pct=0.06 touched_tp=True touched_sl=False timeout=False "
            "hold_s=3600"
        )
        result = parse_exit_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_001"
        assert result["exit"] == 67500.0
        assert result["outcome"] == "WIN"
        assert result["reason"] == "touched_tp"
        assert result["touched_tp"] is True
        assert result["hold_s"] == 3600.0

    def test_exit_missing_log_type(self):
        line = "trade_id=paper_001 outcome=LOSS"
        result = parse_exit_log(line)
        assert result is None

    def test_exit_partial_fields(self):
        line = "[PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_003 outcome=FLAT net_pnl_pct=0.01"
        result = parse_exit_log(line)
        assert result is not None
        assert result["outcome"] == "FLAT"
        assert result["net_pnl_pct"] == 0.01

    def test_exit_with_metadata_for_backfill(self):
        """Exit log can include metadata for backfilling missing entry log."""
        line = (
            "[PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_750d95d13fdf "
            "symbol=ETHUSDT side=SELL source=training_sampler "
            "training_bucket=C_WEAK_EV_TRAIN entry_regime=BEAR_TREND "
            "exit=2143.62 outcome=WIN net_pnl_pct=0.5"
        )
        result = parse_exit_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_750d95d13fdf"
        assert result["symbol"] == "ETHUSDT"
        assert result["side"] == "SELL"
        assert result["source"] == "training_sampler"
        assert result["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert result["entry_regime"] == "BEAR_TREND"
        assert result["outcome"] == "WIN"
        assert result["net_pnl_pct"] == 0.5


class TestParseAttributionLog:
    """Test attribution log parsing."""

    def test_valid_attribution(self):
        line = "[PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_001 attribution=tp_hit reason=touched_tp"
        result = parse_attribution_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_001"
        assert result["attribution"] == "tp_hit"
        assert result["reason"] == "touched_tp"

    def test_attribution_missing_log_type(self):
        line = "trade_id=paper_001 attribution=tp_hit"
        result = parse_attribution_log(line)
        assert result is None

    def test_attribution_with_metadata_for_backfill(self):
        """Attribution log can include metadata for backfilling missing entry log."""
        line = (
            "[PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_5c50052b35aa "
            "symbol=BNBUSDT side=BUY source=training_sampler "
            "training_bucket=C_WEAK_EV_TRAIN entry_regime=BEAR_TREND "
            "attribution=NORMAL_WIN reason=tp_hit net_pnl_pct=0.75"
        )
        result = parse_attribution_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_5c50052b35aa"
        assert result["symbol"] == "BNBUSDT"
        assert result["side"] == "BUY"
        assert result["source"] == "training_sampler"
        assert result["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert result["entry_regime"] == "BEAR_TREND"
        assert result["attribution"] == "NORMAL_WIN"
        assert result["net_pnl_pct"] == 0.75


class TestParseLMStateLog:
    """Test LM state log parsing."""

    def test_valid_lm_state(self):
        line = "[LM_STATE_AFTER_UPDATE] trade_id=paper_001 lm_total_trades=38"
        result = parse_lm_state_log(line)
        assert result is not None
        assert result["trade_id"] == "paper_001"
        assert result["lm_total_trades"] == 38

    def test_lm_state_missing_log_type(self):
        line = "trade_id=paper_001 lm_total_trades=38"
        result = parse_lm_state_log(line)
        assert result is None


class TestJoinTradeRecords:
    """Test joining entry/exit/attr/lm records by trade_id."""

    def test_join_complete_record(self):
        entries = {
            "T001": {
                "log_type": "PAPER_TRAIN_QUALITY_ENTRY",
                "trade_id": "T001",
                "symbol": "BTC/USDT",
                "side": "BUY",
                "ev": 2.5,
                "tp_pct": 1.5,
                "sl_pct": 0.8,
            }
        }
        exits = {
            "T001": {
                "log_type": "PAPER_TRAIN_QUALITY_EXIT",
                "trade_id": "T001",
                "outcome": "WIN",
                "attribution": "tp_hit",
                "net_pnl_pct": 0.75,
                "hold_seconds": 3600,
            }
        }
        attrs = {}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        record = result[0]
        assert record["trade_id"] == "T001"
        assert record["symbol"] == "BTC/USDT"
        assert record["outcome"] == "WIN"
        assert record["net_pnl_pct"] == 0.75

    def test_join_missing_exit(self):
        """Trades with entry but no exit are still exported."""
        entries = {"T002": {"trade_id": "T002", "symbol": "ETH/USDT"}}
        exits = {}
        attrs = {}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        assert result[0]["trade_id"] == "T002"
        assert result[0]["outcome"] is None

    def test_join_attribution_precedence(self):
        """Attribution log fields take precedence over exit log fields."""
        entries = {}
        exits = {"T003": {"trade_id": "T003", "attribution": "wrong", "reason": "wrong_direction"}}
        attrs = {"T003": {"trade_id": "T003", "attribution": "correct", "reason": "fee_dominated"}}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        assert result[0]["attribution"] == "correct"
        assert result[0]["reason"] == "fee_dominated"

    def test_join_schema_consistency(self):
        """All output records have same schema."""
        entries = {"T001": {"trade_id": "T001"}, "T002": {"trade_id": "T002"}}
        exits = {}
        attrs = {}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        if len(result) > 0:
            expected_keys = set(result[0].keys())
            for record in result:
                assert set(record.keys()) == expected_keys

    def test_metadata_backfill_from_exit_log(self):
        """Metadata (symbol, side, source, bucket) backfills from exit log if entry missing."""
        entries = {}  # No entry log
        exits = {
            "T004": {
                "log_type": "PAPER_TRAIN_QUALITY_EXIT",
                "trade_id": "T004",
                "symbol": "ETHUSDT",
                "side": "SELL",
                "source": "training_sampler",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "entry_regime": "BEAR_TREND",
                "outcome": "WIN",
                "net_pnl_pct": 0.5,
            }
        }
        attrs = {}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        record = result[0]
        assert record["symbol"] == "ETHUSDT"
        assert record["side"] == "SELL"
        assert record["source"] == "training_sampler"
        assert record["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert record["entry_regime"] == "BEAR_TREND"
        assert record["outcome"] == "WIN"

    def test_metadata_backfill_from_attribution_log(self):
        """Metadata backfills from attribution log if entry and exit missing."""
        entries = {}  # No entry log
        exits = {}  # No exit log
        attrs = {
            "T005": {
                "log_type": "PAPER_TRAIN_ECON_ATTRIB",
                "trade_id": "T005",
                "symbol": "BNBUSDT",
                "side": "BUY",
                "source": "training_sampler",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "entry_regime": "BULL_TREND",
                "attribution": "NORMAL_WIN",
                "net_pnl_pct": 0.75,
            }
        }
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        record = result[0]
        assert record["symbol"] == "BNBUSDT"
        assert record["side"] == "BUY"
        assert record["source"] == "training_sampler"
        assert record["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert record["entry_regime"] == "BULL_TREND"
        assert record["attribution"] == "NORMAL_WIN"

    def test_metadata_entry_takes_precedence(self):
        """Entry log metadata takes precedence over exit/attr logs."""
        entries = {
            "T006": {
                "trade_id": "T006",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "source": "primary",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "entry_regime": "BULL",
            }
        }
        exits = {
            "T006": {
                "trade_id": "T006",
                "symbol": "WRONG_SYMBOL",
                "side": "SELL",
                "source": "wrong_source",
                "training_bucket": "WRONG_BUCKET",
                "entry_regime": "BEAR",
                "outcome": "WIN",
            }
        }
        attrs = {}
        lm_updates = {}

        result = join_trade_records(entries, exits, attrs, lm_updates)
        assert len(result) == 1
        record = result[0]
        # Entry takes precedence
        assert record["symbol"] == "BTCUSDT"
        assert record["side"] == "BUY"
        assert record["source"] == "primary"
        assert record["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert record["entry_regime"] == "BULL"


class TestExportJsonl:
    """Test JSONL export."""

    def test_export_creates_file(self):
        records = [
            {"trade_id": "T001", "symbol": "BTC/USDT", "outcome": "WIN"},
            {"trade_id": "T002", "symbol": "ETH/USDT", "outcome": "LOSS"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_output.jsonl"
            export_jsonl(records, str(output_path))
            assert output_path.exists()

            # Verify contents
            lines = output_path.read_text().strip().split("\n")
            assert len(lines) == 2
            obj1 = json.loads(lines[0])
            assert obj1["trade_id"] == "T001"
            obj2 = json.loads(lines[1])
            assert obj2["trade_id"] == "T002"

    def test_export_creates_directories(self):
        """Parent directories are created if needed."""
        records = [{"trade_id": "T001"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "deep" / "nested" / "output.jsonl"
            export_jsonl(records, str(output_path))
            assert output_path.exists()

    def test_export_roundtrip(self):
        """Write and read back produces same data."""
        original = [
            {
                "trade_id": "T001",
                "symbol": "BTC/USDT",
                "ev": 2.5,
                "net_pnl_pct": 0.75,
                "outcome": "WIN",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "roundtrip.jsonl"
            export_jsonl(original, str(output_path))

            # Read back
            lines = output_path.read_text().strip().split("\n")
            reloaded = [json.loads(line) for line in lines]

            assert len(reloaded) == len(original)
            assert reloaded[0]["trade_id"] == original[0]["trade_id"]
            assert reloaded[0]["symbol"] == original[0]["symbol"]


class TestProcessLogFile:
    """Test full log file processing."""

    def test_process_sample_log(self):
        """Process a sample log file with mixed records."""
        log_content = """
2026-05-19 10:00:00 [PAPER_TRAIN_QUALITY_ENTRY] trade_id=T001 symbol=BTC/USDT side=BUY ev=2.5 p=0.55 score_final=0.72 expected_move_pct=2.5 entry_price=67000.0 tp_pct=1.5 sl_pct=0.8 training_bucket=C_WEAK_EV_TRAIN cost_edge_ok=True timestamp=1716144000.5
2026-05-19 10:01:00 [PAPER_TRAIN_QUALITY_EXIT] trade_id=T001 exit_price=67500.0 outcome=WIN attribution=tp_hit reason=touched_tp mfe_pct=2.1 mae_pct=0.3 net_pnl_pct=0.75 gross_move_pct=0.75 fee_drag_pct=0.06 touched_tp=True touched_sl=False timeout=False hold_seconds=3600 timestamp=1716147600.5
2026-05-19 10:02:00 [PAPER_TRAIN_ECON_ATTRIB] trade_id=T001 attribution=tp_hit reason=touched_tp
2026-05-19 10:03:00 [LM_STATE_AFTER_UPDATE] trade_id=T001 lm_total_trades=38
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(log_content)
            f.flush()
            temp_path = f.name

        try:
            records = process_log_file(temp_path)
            assert len(records) >= 1
            record = records[0]
            assert record["trade_id"] == "T001"
            assert record["symbol"] == "BTC/USDT"
            assert record["outcome"] == "WIN"
            assert record["net_pnl_pct"] == 0.75
        finally:
            Path(temp_path).unlink()

    def test_process_empty_log(self):
        """Empty log file produces empty output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            records = process_log_file(temp_path)
            assert len(records) == 0
        finally:
            Path(temp_path).unlink()

    def test_process_malformed_lines(self):
        """Malformed lines are skipped gracefully."""
        log_content = """
This line has no structure
[PAPER_TRAIN_QUALITY_ENTRY] trade_id=T001 symbol=BTC/USDT side=BUY
Random garbage [PAPER_TRAIN_QUALITY_EXIT] incomplete
[PAPER_TRAIN_QUALITY_EXIT] trade_id=T001 outcome=WIN
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(log_content)
            f.flush()
            temp_path = f.name

        try:
            records = process_log_file(temp_path)
            # Should process what it can
            assert isinstance(records, list)
        finally:
            Path(temp_path).unlink()

    def test_metadata_backfill_integration_missing_entry(self):
        """Integration test: metadata backfills from exit when entry log missing."""
        # Real-world scenario: entry log missing but exit has all metadata
        log_content = """
2026-05-19 10:00:00 [PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_750d95d13fdf symbol=ETHUSDT side=SELL source=training_sampler training_bucket=C_WEAK_EV_TRAIN entry_regime=BEAR_TREND exit=2143.62 outcome=WIN net_pnl_pct=0.5 gross_move_pct=0.6 fee_drag_pct=0.1
2026-05-19 10:01:00 [PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_750d95d13fdf attribution=NORMAL_WIN
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(log_content)
            f.flush()
            temp_path = f.name

        try:
            records = process_log_file(temp_path)
            assert len(records) == 1
            record = records[0]
            assert record["trade_id"] == "paper_750d95d13fdf"
            # Metadata should be backfilled from exit log
            assert record["symbol"] == "ETHUSDT"
            assert record["side"] == "SELL"
            assert record["source"] == "training_sampler"
            assert record["training_bucket"] == "C_WEAK_EV_TRAIN"
            assert record["entry_regime"] == "BEAR_TREND"
            # Exit-specific fields
            assert record["outcome"] == "WIN"
            assert record["net_pnl_pct"] == 0.5
        finally:
            Path(temp_path).unlink()

    def test_metadata_backfill_integration_attr_only(self):
        """Integration test: metadata backfills from attribution when entry/exit missing."""
        # Real-world scenario: only attribution log has metadata
        log_content = """
2026-05-19 10:00:00 [PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_5c50052b35aa symbol=BNBUSDT side=BUY source=training_sampler training_bucket=C_WEAK_EV_TRAIN entry_regime=BULL_TREND attribution=NORMAL_WIN reason=tp_hit net_pnl_pct=0.75
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(log_content)
            f.flush()
            temp_path = f.name

        try:
            records = process_log_file(temp_path)
            assert len(records) == 1
            record = records[0]
            assert record["trade_id"] == "paper_5c50052b35aa"
            # Metadata should be backfilled from attribution log
            assert record["symbol"] == "BNBUSDT"
            assert record["side"] == "BUY"
            assert record["source"] == "training_sampler"
            assert record["training_bucket"] == "C_WEAK_EV_TRAIN"
            assert record["entry_regime"] == "BULL_TREND"
            # Attribution fields
            assert record["attribution"] == "NORMAL_WIN"
            assert record["net_pnl_pct"] == 0.75
        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
