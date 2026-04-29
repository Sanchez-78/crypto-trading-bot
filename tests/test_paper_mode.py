"""Tests for V10.13u+20 paper trading mode."""
import pytest
import time
from src.services.paper_trade_executor import (
    open_paper_position,
    update_paper_positions,
    close_paper_position,
    get_paper_open_positions,
    reset_paper_positions,
    _calculate_pnl,
)


@pytest.fixture
def clean_positions():
    """Fixture to ensure clean state before/after tests."""
    reset_paper_positions()
    yield
    reset_paper_positions()


class TestPaperExecutorBasics:
    """Test paper executor core functionality."""

    def test_open_paper_position_with_real_price(self, clean_positions):
        """Paper executor opens position with real price."""
        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.050,
            "score": 0.25,
            "p": 0.55,
            "coh": 0.70,
            "af": 0.80,
        }
        price = 2.5432  # Real price
        ts = time.time()

        result = open_paper_position(signal, price, ts, "RDE_TAKE")

        assert result["status"] == "opened"
        assert result["symbol"] == "XRPUSDT"
        assert result["entry_price"] == price
        assert "trade_id" in result

    def test_open_paper_position_refuses_invalid_price(self, clean_positions):
        """Paper executor refuses missing or invalid price."""
        signal = {"symbol": "ETHUSDT", "action": "BUY", "ev": 0.040}

        # Test with zero price
        result = open_paper_position(signal, 0.0, time.time(), "RDE_TAKE")
        assert result["status"] == "blocked"
        assert result["reason"] == "invalid_price"

        # Test with None price
        result = open_paper_position(signal, None, time.time(), "RDE_TAKE")
        assert result["status"] == "blocked"

    def test_open_paper_position_respects_max_open(self, clean_positions):
        """Paper executor refuses entry when max open positions exceeded."""
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.050}
        ts = time.time()

        # Open 3 positions (default max)
        for i in range(3):
            result = open_paper_position(signal, 2.5 + i * 0.1, ts, "RDE_TAKE")
            assert result["status"] == "opened"

        # Fourth should be blocked
        result = open_paper_position(signal, 2.8, ts, "RDE_TAKE")
        assert result["status"] == "blocked"
        assert result["reason"] == "max_open_exceeded"

    def test_paper_buy_pnl_correct_after_fees(self, clean_positions):
        """Paper BUY PnL correct after fees and slippage."""
        signal = {"symbol": "BTCUSDT", "action": "BUY", "ev": 0.050}
        entry_price = 100.0
        ts = time.time()

        # Open at 100
        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # Exit at 101 (1% gain)
        exit_price = 101.0
        closed = close_paper_position(trade_id, exit_price, ts + 60, "TP")

        assert closed is not None
        # gross = (101-100)/100 = 1%
        # fee = 0.15%, slippage = 0.03%
        # net = 1 - 0.15 - 0.03 = 0.82%
        assert abs(closed["gross_pnl_pct"] - 1.0) < 0.01
        assert abs(closed["fee_pct"] - 0.15) < 0.01
        assert abs(closed["slippage_pct"] - 0.03) < 0.01
        assert abs(closed["net_pnl_pct"] - 0.82) < 0.01
        assert closed["outcome"] == "WIN"

    def test_paper_sell_pnl_correct(self, clean_positions):
        """Paper SELL PnL correct after fees and slippage."""
        signal = {"symbol": "ETHUSDT", "action": "SELL", "ev": 0.045}
        entry_price = 100.0
        ts = time.time()

        # Open SELL at 100
        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # Exit at 99 (1% gain for short)
        exit_price = 99.0
        closed = close_paper_position(trade_id, exit_price, ts + 60, "TP")

        assert closed is not None
        # For SELL: (100-99)/100 = 1%
        # net = 1 - 0.15 - 0.03 = 0.82%
        assert abs(closed["net_pnl_pct"] - 0.82) < 0.01
        assert closed["outcome"] == "WIN"

    def test_timeout_outcome_based_on_net_pnl_not_reason(self, clean_positions):
        """TIMEOUT outcome based on net PnL, not exit reason."""
        signal = {"symbol": "ADAUSDT", "action": "BUY", "ev": 0.040}
        entry_price = 1.0
        ts = time.time()

        # Open at 1.0
        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # Exit with TIMEOUT but at 1.01 (0.82% net = WIN despite TIMEOUT)
        exit_price = 1.01
        closed = close_paper_position(trade_id, exit_price, ts + 1000, "TIMEOUT")

        assert closed is not None
        assert closed["exit_reason"] == "TIMEOUT"
        # outcome based on net_pnl_pct, not on TIMEOUT reason
        assert closed["outcome"] == "WIN"

    def test_timeout_loss_if_negative_pnl(self, clean_positions):
        """TIMEOUT classified as LOSS if net PnL negative."""
        signal = {"symbol": "SOLUSDT", "action": "BUY", "ev": 0.035}
        entry_price = 100.0
        ts = time.time()

        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # Exit at 99 (1% loss, more than fees)
        exit_price = 99.0
        closed = close_paper_position(trade_id, exit_price, ts + 2000, "TIMEOUT")

        assert closed is not None
        assert closed["exit_reason"] == "TIMEOUT"
        assert closed["outcome"] == "LOSS"

    def test_paper_close_produces_canonical_schema(self, clean_positions):
        """Closed paper trade has all required canonical fields."""
        signal = {
            "symbol": "BNBUSDT",
            "action": "BUY",
            "ev": 0.055,
            "score": 0.30,
            "p": 0.58,
            "coh": 0.75,
            "af": 0.85,
            "regime": "BULL_TREND",
        }
        entry_price = 500.0
        ts = time.time()

        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        exit_price = 505.0
        closed = close_paper_position(trade_id, exit_price, ts + 120, "TP")

        # Verify all canonical fields present
        required_fields = [
            "trade_id",
            "mode",
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "entry_ts",
            "exit_ts",
            "exit_reason",
            "duration_s",
            "size_usd",
            "gross_pnl_pct",
            "fee_pct",
            "slippage_pct",
            "net_pnl_pct",
            "outcome",
            "ev_at_entry",
            "score_at_entry",
            "p_at_entry",
            "coh_at_entry",
            "af_at_entry",
            "rde_decision",
            "regime",
            "created_at",
        ]

        for field in required_fields:
            assert field in closed, f"Missing field: {field}"

        # Verify values
        assert closed["mode"] == "paper_live"
        assert closed["symbol"] == "BNBUSDT"
        assert closed["side"] == "BUY"
        assert closed["entry_price"] == entry_price
        assert closed["exit_price"] == exit_price
        assert abs(closed["duration_s"] - 120) < 1

    def test_update_paper_positions_triggers_exits(self, clean_positions):
        """update_paper_positions checks for TP/SL/TIMEOUT and closes."""
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.050}
        entry_price = 2.5
        ts = time.time()

        result = open_paper_position(signal, entry_price, ts, "RDE_TAKE")
        trade_id = result["trade_id"]

        # TP should be around 2.5 * 1.012 = 2.530
        # Update with price above TP
        symbol_prices = {"XRPUSDT": 2.535}
        closed_trades = update_paper_positions(symbol_prices, ts + 60)

        assert len(closed_trades) == 1
        assert closed_trades[0]["trade_id"] == trade_id
        assert closed_trades[0]["exit_reason"] == "TP"

    def test_get_paper_open_positions_returns_current_list(self, clean_positions):
        """get_paper_open_positions returns list of open positions."""
        signal = {"symbol": "XRPUSDT", "action": "BUY", "ev": 0.050}
        ts = time.time()

        # Open 2 positions
        open_paper_position(signal, 2.5, ts, "RDE_TAKE")
        open_paper_position(signal, 2.6, ts, "RDE_TAKE")

        open_positions = get_paper_open_positions()
        assert len(open_positions) == 2
        assert all(p["symbol"] == "XRPUSDT" for p in open_positions)


class TestPnLCalculation:
    """Test PnL calculation helper."""

    def test_calculate_pnl_buy_win(self):
        """BUY with profit produces WIN outcome."""
        pnl = _calculate_pnl(
            side="BUY",
            entry_price=100.0,
            exit_price=102.0,
            size_usd=1000.0,
        )

        assert abs(pnl["gross_pnl_pct"] - 2.0) < 0.01
        assert pnl["outcome"] == "WIN"

    def test_calculate_pnl_sell_loss(self):
        """SELL with loss produces LOSS outcome."""
        pnl = _calculate_pnl(
            side="SELL",
            entry_price=100.0,
            exit_price=101.5,
            size_usd=1000.0,
        )

        # (100-101.5)/100 = -1.5%, minus fees and slippage
        assert pnl["gross_pnl_pct"] < 0
        assert pnl["outcome"] == "LOSS"

    def test_calculate_pnl_flat_small_change(self):
        """Small change between profit and loss produces FLAT."""
        # Need move > 0.05% gross but < 0.05% net (after fees+slippage)
        # Fees: 0.15%, Slippage: 0.03%, Threshold: 0.05%
        # Net = Gross - 0.18% must be in (-0.05%, 0.05%)
        # Gross must be > 0.13% (0.13 - 0.18 = -0.05) and < 0.23% (0.23 - 0.18 = 0.05)
        # Use 0.20%: net = 0.20 - 0.18 = 0.02% (FLAT because 0.02% < 0.05%)
        pnl = _calculate_pnl(
            side="BUY",
            entry_price=100.0,
            exit_price=100.20,
            size_usd=1000.0,
        )

        assert pnl["outcome"] == "FLAT"


class TestRuntimeMode:
    """Test runtime_mode integration."""

    def test_paper_mode_is_paper_mode(self):
        """Verify is_paper_mode() works."""
        from src.core.runtime_mode import is_paper_mode, get_trading_mode, TradingMode
        import os

        # Set to paper_live
        os.environ["TRADING_MODE"] = "paper_live"
        # Force re-eval
        import importlib
        import src.core.runtime_mode as rm
        importlib.reload(rm)

        # Verify
        assert rm.is_paper_mode()

    def test_live_trading_blocked_by_default(self):
        """live_trading_allowed() returns False by default."""
        from src.core.runtime_mode import live_trading_allowed
        import os

        # Reset to defaults
        os.environ.pop("TRADING_MODE", None)
        os.environ.pop("ENABLE_REAL_ORDERS", None)
        os.environ.pop("LIVE_TRADING_CONFIRMED", None)
        os.environ.pop("PAPER_EXPLORATION_ENABLED", None)

        # Should be False
        assert not live_trading_allowed()


class TestP1M1RoutingToPaperTraining:
    """P1.1M: Route accepted and blocked signals into paper training."""

    def test_paper_train_strict_take_opens_position(self, clean_positions):
        """Strict TAKE opens A_STRICT_TAKE paper position in paper_train mode."""
        import os
        os.environ["TRADING_MODE"] = "paper_train"

        signal = {
            "symbol": "XRPUSDT",
            "action": "BUY",
            "ev": 0.050,
            "score": 0.25,
            "price": 2.5,
            "features": {"ema_diff": 0.001, "macd": 0.0001},
            "regime": "BULL_TREND",
        }

        result = open_paper_position(
            signal,
            price=2.5,
            ts=time.time(),
            reason="RDE_TAKE",
            extra={
                "paper_source": "strict_take",
                "training_bucket": "A_STRICT_TAKE",
                "original_decision": "TAKE",
                "score_at_entry": signal.get("score", 0.0),
            },
        )

        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["training_bucket"] == "A_STRICT_TAKE"
        assert pos["original_decision"] == "TAKE"

    def test_paper_train_side_inference_creates_entry(self, clean_positions):
        """Training sampler with side inference opens C_WEAK_EV_TRAIN."""
        import os
        os.environ["TRADING_MODE"] = "paper_train"

        signal = {
            "symbol": "ETHUSDT",
            "action": "",  # No side specified, will be inferred
            "ev": 0.015,
            "score": 0.12,
            "p": 0.52,
            "coherence": 0.65,
            "auditor_factor": 0.75,
            "price": 1800.0,
            "features": {"ema_diff": 0.002, "macd": 0.0005, "rsi": 30},
            "regime": "BULL_TREND",
        }

        # Simulate paper training sampler result
        result = open_paper_position(
            signal,
            price=1800.0,
            ts=time.time(),
            reason="TRAINING_SAMPLER:REJECT_ECON_BAD_ENTRY",
            extra={
                "paper_source": "training_sampler",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "side_inferred": True,
                "original_decision": "REJECT_ECON_BAD_ENTRY",
                "cost_edge_ok": False,
                "expected_move_pct": 1.5,
                "size_mult": 0.05,
                "max_hold_s": 300,
            },
        )

        assert result["status"] == "opened"
        positions = get_paper_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["training_bucket"] == "C_WEAK_EV_TRAIN"
        assert pos["side_inferred"] is True

    def test_paper_train_closed_trade_has_training_metadata(self, clean_positions):
        """Closed training trade preserves all P1.1M metadata."""
        import os
        os.environ["TRADING_MODE"] = "paper_train"

        signal = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": -0.010,  # Negative EV for D_NEG_EV_CONTROL
            "score": 0.05,
            "price": 50000.0,
        }

        # Open D_NEG_EV_CONTROL training position
        result = open_paper_position(
            signal,
            price=50000.0,
            ts=time.time(),
            reason="TRAINING_SAMPLER:REJECT_NEGATIVE_EV",
            extra={
                "paper_source": "training_sampler",
                "training_bucket": "D_NEG_EV_CONTROL",
                "original_decision": "REJECT_NEGATIVE_EV",
                "side_inferred": False,
                "cost_edge_ok": False,
                "expected_move_pct": -1.0,
                "required_move_pct": 0.23,
                "size_mult": 0.02,
                "max_hold_s": 240,
                "regime": "RANGING",
            },
        )

        trade_id = result["trade_id"]

        # Close at a loss
        closed = close_paper_position(
            position_id=trade_id,
            price=49500.0,
            ts=time.time() + 120,
            reason="SL",
        )

        assert closed is not None
        assert closed["training_bucket"] == "D_NEG_EV_CONTROL"
        assert closed["outcome"] == "LOSS"
        # Control bucket exit is allowed even with loss
        assert closed["net_pnl_pct"] < 0
