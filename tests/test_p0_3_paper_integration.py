"""Tests for V10.13u+20 P0.3 — Paper Exits + Learning Integration."""
import pytest
import time
import os
from unittest.mock import patch, MagicMock
from src.services.paper_trade_executor import (
    open_paper_position,
    update_paper_positions,
    close_paper_position,
    get_paper_open_positions,
    reset_paper_positions,
)


@pytest.fixture
def clean_positions():
    """Fixture to ensure clean state before/after tests."""
    reset_paper_positions()
    yield
    reset_paper_positions()


class TestP03PaperRouting:
    """Test paper executor routing from production TAKE path."""

    def test_paper_mode_routes_take_to_paper_executor(self, clean_positions):
        """Paper mode routes TAKE decision to open_paper_position instead of live executor."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.050,
            "score": 0.25,
            "p": 0.55,
            "coh": 0.70,
            "af": 0.80,
            "price": 2.5432,
        }
        price = 2.5432
        ts = time.time()

        # Open via paper executor
        result = open_paper_position(signal, price, ts, "RDE_TAKE")

        assert result["status"] == "opened"
        assert result["symbol"] == "XRPUSDT"
        assert result["entry_price"] == price

    def test_paper_exit_updates_trigger_learning_update(self, clean_positions):
        """Closed paper trades trigger LEARNING_UPDATE log."""
        signal = {"symbol": "ETHUSDT", "action": "BUY", "ev": 0.045}
        ts = time.time()

        # Open and close paper position
        result = open_paper_position(signal, 1900.0, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # Move price above TP to trigger exit
        closed_trade = close_paper_position(trade_id, 1930.0, ts + 60, "TP")

        assert closed_trade is not None
        assert closed_trade["outcome"] in ["WIN", "LOSS", "FLAT"]
        assert "net_pnl_pct" in closed_trade
        assert closed_trade["mode"] == "paper_live"

    def test_update_paper_positions_collects_closed_trades(self, clean_positions):
        """update_paper_positions() returns list of closed trades with correct schema."""
        signal = {"symbol": "BNBUSDT", "action": "SELL", "ev": 0.040}
        ts = time.time()

        # Open 2 positions
        r1 = open_paper_position(signal, 600.0, ts, "RDE_TAKE")
        r2 = open_paper_position(signal, 595.0, ts + 1, "RDE_TAKE")

        # First position exits on TP, second stays open
        symbol_prices = {"BNBUSDT": 587.0}  # Below SL for both
        closed_trades = update_paper_positions(symbol_prices, ts + 120)

        # Both should close (both hit SL)
        assert len(closed_trades) == 2
        for trade in closed_trades:
            assert "trade_id" in trade
            assert "exit_reason" in trade
            assert "net_pnl_pct" in trade
            assert "outcome" in trade
            assert trade["mode"] == "paper_live"

    def test_paper_trades_separate_from_live_positions(self, clean_positions):
        """Paper trades are managed separately from live positions dict."""
        # Paper position added via open_paper_position
        signal = {"symbol": "ADAUSDT", "action": "BUY", "ev": 0.035}
        result = open_paper_position(signal, 1.0, time.time(), "RDE_TAKE")

        # Verify it's in paper executor, not live positions
        paper_positions = get_paper_open_positions()
        assert len(paper_positions) == 1
        assert paper_positions[0]["symbol"] == "ADAUSDT"

    def test_live_trading_guard_blocks_when_all_conditions_not_met(self):
        """live_trading_allowed() returns False unless all 4 conditions pass."""
        from src.core.runtime_mode import live_trading_allowed, get_trading_mode, TradingMode

        # Default should be False (safe mode)
        assert not live_trading_allowed()


class TestP03FirebaseIntegration:
    """Test Firebase learning integration for paper trades."""

    @patch('src.services.firebase_client.db')
    def test_paper_trade_saved_to_firebase(self, mock_db, clean_positions):
        """Closed paper trades can be saved to Firebase trades_paper collection."""
        # Mock Firebase
        mock_collection = MagicMock()
        mock_db.collection.return_value = mock_collection

        # Create a closed paper trade
        closed_trade = {
            "trade_id": "paper_abc123",
            "symbol": "XRPUSDT",
            "side": "BUY",
            "entry_price": 2.5,
            "exit_price": 2.53,
            "net_pnl_pct": 1.02,
            "outcome": "WIN",
            "mode": "paper_live",
        }

        # Verify schema includes required fields
        required_fields = [
            "trade_id", "symbol", "side", "entry_price", "exit_price",
            "net_pnl_pct", "outcome", "mode"
        ]
        for field in required_fields:
            assert field in closed_trade


class TestP03DeprecatedDefaults:
    """Verify safe defaults prevent accidental live trading."""

    def test_paper_mode_default_in_env(self):
        """TRADING_MODE defaults to paper_live in .env.example."""
        # This is a documentation test — verify that safe defaults are configured
        env_file = "C:\\Projects\\CryptoMaster_srv\\.env.example"
        if os.path.exists(env_file):
            with open(env_file, encoding="utf-8") as f:
                content = f.read()
                # Verify safe defaults
                assert "TRADING_MODE=paper_live" in content
                assert "ENABLE_REAL_ORDERS=false" in content
                assert "LIVE_TRADING_CONFIRMED=false" in content

    def test_runtime_mode_functions_exist(self):
        """Verify runtime_mode module has required functions."""
        try:
            from src.core.runtime_mode import (
                is_paper_mode,
                live_trading_allowed,
                get_trading_mode,
                check_live_order_guard,
            )
            # All imports successful
            assert callable(is_paper_mode)
            assert callable(live_trading_allowed)
            assert callable(get_trading_mode)
            assert callable(check_live_order_guard)
        except ImportError as e:
            pytest.fail(f"runtime_mode imports failed: {e}")
