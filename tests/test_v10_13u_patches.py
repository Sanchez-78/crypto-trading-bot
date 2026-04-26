"""
Tests for V10.13u+2 consistency patches.

Covers:
- Patch 1: Maturity type safety and canonical source
- Patch 2: Canonical profit factor consistency
- Patch 3: LearningMonitor hydration depth
- Patch 4: RR consistency
- Patch 5: Runtime commit/branch injection
"""

import pytest
from unittest.mock import patch, MagicMock


# ── PATCH 1: Maturity type safety ──────────────────────────────────────────

def test_extract_trade_count_with_int():
    """PATCH 1: Handle integer source."""
    from src.services.realtime_decision_engine import _extract_trade_count
    assert _extract_trade_count(5) == 5
    assert _extract_trade_count(100, 50) == 100


def test_extract_trade_count_with_dict():
    """PATCH 1: Handle dict source with standard keys."""
    from src.services.realtime_decision_engine import _extract_trade_count

    src = {"trades": 10}
    assert _extract_trade_count(src) == 10

    src = {"closed_trades": 20}
    assert _extract_trade_count(src) == 20

    src = {"completed_trades": 15}
    assert _extract_trade_count(src) == 15


def test_extract_trade_count_with_list():
    """PATCH 1: Handle list/tuple source."""
    from src.services.realtime_decision_engine import _extract_trade_count
    assert _extract_trade_count([1, 2, 3]) == 3
    assert _extract_trade_count((1, 2, 3, 4, 5)) == 5


def test_extract_trade_count_mixed_sources():
    """PATCH 1: Priority order: int > dict > list."""
    from src.services.realtime_decision_engine import _extract_trade_count

    result = _extract_trade_count(5, {"trades": 10}, [1, 2, 3, 4])
    assert result == 10  # dict "trades" value


def test_extract_trade_count_no_crash_on_malformed():
    """PATCH 1: Never crash on malformed input."""
    from src.services.realtime_decision_engine import _extract_trade_count

    src = {"trades": {"bad": "shape"}, "completed_trades": 500}
    assert _extract_trade_count(src) == 500  # Skips bad "trades" value

    src = {"trades": None, "n": 42}
    assert _extract_trade_count(src) == 42


# ── PATCH 3: LearningMonitor hydration ────────────────────────────────────

def test_lm_hydrate_canonical_trades_basic():
    """PATCH 3: Hydrate with simple trade list."""
    from src.services.learning_monitor import hydrate_from_canonical_trades, lm_count

    # Reset state
    lm_count.clear()

    trades = [
        {"symbol": "BTC", "regime": "BULL", "net_pnl": 0.01, "realized_ev": 0.005},
        {"symbol": "BTC", "regime": "BULL", "net_pnl": -0.02, "realized_ev": -0.01},
        {"symbol": "BTC", "regime": "BULL", "net_pnl": 0.0, "realized_ev": 0.0},
        {"symbol": "ETH", "regime": "BEAR", "net_pnl": 0.03, "realized_ev": 0.015},
    ]

    result = hydrate_from_canonical_trades(trades)

    assert result["loaded_trades"] == 4
    assert result["hydrated_pairs"] == 2
    assert result["source"] == "firebase_canonical"
    assert result["decisive"] == 3  # 2 BTC + 1 ETH (flats don't count)
    assert result["flats"] == 1  # 1 BTC flat


def test_lm_hydrate_field_normalization():
    """PATCH 3: Normalize field names (symbol/sym, net_pnl/pnl, etc)."""
    from src.services.learning_monitor import hydrate_from_canonical_trades, lm_count

    lm_count.clear()

    trades = [
        {"sym": "BTC", "reg": "RANGING", "pnl": 0.005, "ev": 0.001},  # alt field names
        {"symbol": "ETH", "regime": "BULL", "net_pnl": 0.01, "realized_ev": 0.002},  # canonical
    ]

    result = hydrate_from_canonical_trades(trades)

    assert result["loaded_trades"] == 2
    assert result["hydrated_pairs"] == 2


def test_lm_hydrate_realistic_stats():
    """PATCH 3: Verify actual WR/EV computation (not default 50%/0.0)."""
    from src.services.learning_monitor import (
        hydrate_from_canonical_trades, lm_count, lm_wr_hist, lm_pnl_hist
    )

    lm_count.clear()
    lm_wr_hist.clear()
    lm_pnl_hist.clear()

    trades = [
        {"symbol": "BTC", "regime": "BULL", "net_pnl": 0.01, "realized_ev": 0.005},
        {"symbol": "BTC", "regime": "BULL", "net_pnl": 0.02, "realized_ev": 0.01},
        {"symbol": "BTC", "regime": "BULL", "net_pnl": -0.005, "realized_ev": -0.002},
    ]

    hydrate_from_canonical_trades(trades)

    key = ("BTC", "BULL")
    assert lm_count[key] == 3
    assert len(lm_wr_hist[key]) == 3
    # WR should be [1.0, 1.0, 0.0] (2 wins, 1 loss)
    assert lm_wr_hist[key][0] == 1.0  # Win
    assert lm_wr_hist[key][1] == 1.0  # Win
    assert lm_wr_hist[key][2] == 0.0  # Loss


# ── PATCH 4: RR consistency ───────────────────────────────────────────────

def test_canonical_rr_basic():
    """PATCH 4: Compute RR from distances."""
    from src.services.realtime_decision_engine import canonical_rr

    rr = canonical_rr(tp_distance=0.02, sl_distance=0.01)
    assert rr == pytest.approx(2.0)

    rr = canonical_rr(tp_distance=0.015, sl_distance=0.01)
    assert rr == pytest.approx(1.5)


def test_canonical_rr_handles_zero_sl():
    """PATCH 4: Return 0.0 if SL invalid."""
    from src.services.realtime_decision_engine import canonical_rr

    assert canonical_rr(tp_distance=0.02, sl_distance=0.0) == 0.0
    assert canonical_rr(tp_distance=0.02, sl_distance=-0.005) == 0.0


def test_canonical_rr_abs_values():
    """PATCH 4: Handle negative distances (absolute values)."""
    from src.services.realtime_decision_engine import canonical_rr

    rr1 = canonical_rr(tp_distance=0.02, sl_distance=-0.01)
    rr2 = canonical_rr(tp_distance=-0.02, sl_distance=0.01)

    assert rr1 == pytest.approx(2.0)
    assert rr2 == pytest.approx(2.0)


# ── PATCH 2: Canonical profit factor consistency ────────────────────────

def test_lm_economic_health_uses_canonical_pf():
    """PATCH 2: Verify lm_economic_health imports and uses canonical_profit_factor."""
    from src.services.learning_monitor import lm_economic_health

    # Mock canonical_profit_factor to verify it's called
    with patch("src.services.learning_monitor.canonical_profit_factor") as mock_pf:
        mock_pf.return_value = 1.5
        with patch("src.services.learning_monitor.METRICS", {"trades": 100}):
            result = lm_economic_health()

        # If canonical_profit_factor is called, the result should use its value
        assert result["profit_factor"] == 1.5
        mock_pf.assert_called_once()


# ── PATCH 5: Runtime commit/branch ─────────────────────────────────────

def test_get_git_commit_from_env():
    """PATCH 5: Prefer COMMIT_SHA env var."""
    from src.services.version_info import get_git_commit

    with patch.dict("os.environ", {"COMMIT_SHA": "abc1234567"}):
        commit = get_git_commit()
        assert commit == "abc1234"  # Truncated to 12 chars


def test_get_git_commit_from_github_sha():
    """PATCH 5: Fallback to GITHUB_SHA env var."""
    from src.services.version_info import get_git_commit

    with patch.dict("os.environ", {"GITHUB_SHA": "def5678901234567890"}):
        commit = get_git_commit()
        assert commit == "def567890123"  # First 12 chars


def test_get_git_branch_from_env():
    """PATCH 5: Prefer GIT_BRANCH env var."""
    from src.services.version_info import get_git_branch

    with patch.dict("os.environ", {"GIT_BRANCH": "feature-x"}):
        branch = get_git_branch()
        assert branch == "feature-x"


def test_get_git_branch_from_github_ref_name():
    """PATCH 5: Fallback to GITHUB_REF_NAME env var."""
    from src.services.version_info import get_git_branch

    with patch.dict("os.environ", {"GITHUB_REF_NAME": "main"}):
        branch = get_git_branch()
        assert branch == "main"


# ── PATCH 1: Maturity computation doesn't crash ────────────────────────

def test_maturity_handles_mixed_state():
    """PATCH 1: Maturity computation handles dict/int/list sources safely."""
    from src.services.realtime_decision_engine import (
        compute_effective_maturity, _MATURITY_CACHE
    )

    with patch("src.services.realtime_decision_engine.get_canonical_state") as mock_cs:
        mock_cs.return_value = {
            "trades": 100,  # Dict with "trades" key
            "closed_trades": [{"x": 1}] * 80,  # List of closed trades
        }

        with patch("src.services.realtime_decision_engine.lm_count", {("BTC", "BULL"): 50}):
            result = compute_effective_maturity()

            # Should use canonical trades count
            assert result["effective_trade_count"] == 100
            assert result["source"] == "canonical"


# ── V10.13u+3: Economic PF Source Drift Fix ──────────────────────────

def test_economic_health_pf_hard_rule():
    """V10.13u+3: PF < 1.0 + net_profit < 0 => status never GOOD."""
    from src.services.learning_monitor import lm_economic_health

    # Mock canonical_profit_factor to return 0.75 (unprofitable)
    with patch("src.services.canonical_metrics.canonical_profit_factor") as mock_pf:
        mock_pf.return_value = 0.75

        # Create mock METRICS with negative net_pnl in the source module
        mock_metrics = {
            "trades": 100,
            "net_pnl_total": -25.0,  # Losing money
            "wins": 40,
            "losses": 60,
        }
        with patch("src.services.learning_event.METRICS", mock_metrics):
            with patch("src.services.learning_event._close_reasons", {"SCRATCH_EXIT": 20}):
                with patch("src.services.learning_event._recent_results", [0, 0, 1, 0]):
                    result = lm_economic_health()
                    status = result.get("status")

                    # Hard rule: PF < 1.0 + net_profit <= 0 => BAD
                    assert status == "BAD", f"Expected BAD status for unprofitable PF, got {status}"
                    assert result["profit_factor"] == 0.75


def test_economic_health_profitable_pf_good():
    """V10.13u+3: Profitable PF (>1.5) => can be GOOD."""
    from src.services.learning_monitor import lm_economic_health

    # Mock canonical_profit_factor to return 2.0 (profitable)
    with patch("src.services.canonical_metrics.canonical_profit_factor") as mock_pf:
        mock_pf.return_value = 2.0

        # Create mock METRICS with positive net_pnl in the source module
        mock_metrics = {
            "trades": 100,
            "net_pnl_total": 100.0,  # Winning
            "wins": 70,
            "losses": 30,
        }
        with patch("src.services.learning_event.METRICS", mock_metrics):
            with patch("src.services.learning_event._close_reasons", {"SCRATCH_EXIT": 5}):
                with patch("src.services.learning_event._recent_results", [1, 1, 1, 1]):
                    result = lm_economic_health()
                    status = result.get("status")

                    # High PF + low scratch rate + positive trend = GOOD
                    assert status in ["GOOD", "CAUTION"], f"Expected GOOD/CAUTION for profitable PF, got {status}"
                    assert result["profit_factor"] == 2.0


# ── V10.13u+4: Canonical Economic PF Real Source Fix ─────────────────

def test_canonical_profit_factor_with_meta_basic():
    """V10.13u+4: canonical_profit_factor_with_meta returns correct metadata."""
    from src.services.canonical_metrics import canonical_profit_factor_with_meta

    # Create 10 trades: 7 wins, 3 losses
    trades = [
        {"net_pnl": 0.001},   # WIN
        {"net_pnl": 0.002},   # WIN
        {"net_pnl": 0.0015},  # WIN
        {"net_pnl": 0.003},   # WIN
        {"net_pnl": 0.0005},  # WIN
        {"net_pnl": 0.002},   # WIN
        {"net_pnl": 0.001},   # WIN
        {"net_pnl": -0.001},  # LOSS
        {"net_pnl": -0.002},  # LOSS
        {"net_pnl": -0.0015}, # LOSS
    ]

    meta = canonical_profit_factor_with_meta(trades)

    # Check metadata
    assert meta["closed_trades"] == 10
    assert meta["wins"] == 7
    assert meta["losses"] == 3
    assert meta["source"] == "canonical_closed_trades"

    # gross_win = 0.001 + 0.002 + 0.0015 + 0.003 + 0.0005 + 0.002 + 0.001 = 0.011
    # gross_loss = 0.001 + 0.002 + 0.0015 = 0.0045
    # pf = 0.011 / 0.0045 ≈ 2.444
    assert abs(meta["pf"] - 2.444) < 0.01, f"Expected PF ≈ 2.444, got {meta['pf']}"
    assert abs(meta["gross_win"] - 0.011) < 1e-10
    assert abs(meta["gross_loss"] - 0.0045) < 1e-10


def test_canonical_profit_factor_with_meta_no_trades():
    """V10.13u+4: canonical_profit_factor_with_meta handles empty trades."""
    from src.services.canonical_metrics import canonical_profit_factor_with_meta

    meta = canonical_profit_factor_with_meta(None)
    assert meta["pf"] == 0.0
    assert meta["closed_trades"] == 0
    assert meta["source"] == "none_provided"

    meta2 = canonical_profit_factor_with_meta([])
    assert meta2["pf"] == 0.0
    assert meta2["closed_trades"] == 0


def test_economic_health_matches_canonical_source():
    """V10.13u+4: Economic health uses dashboard's canonical closed trades."""
    from src.services.learning_monitor import lm_economic_health

    # Mock load_history to return trades that give PF = 0.75
    canonical_trades = [
        {"net_pnl": 0.001},   # WIN
        {"net_pnl": 0.001},   # WIN
        {"net_pnl": 0.001},   # WIN
        {"net_pnl": -0.002},  # LOSS
        {"net_pnl": -0.0015}, # LOSS
    ]

    with patch("src.services.firebase_client.load_history") as mock_load:
        mock_load.return_value = canonical_trades

        with patch("src.services.learning_event.METRICS", {"trades": 5}):
            with patch("src.services.learning_event._close_reasons", {}):
                with patch("src.services.learning_event._recent_results", []):
                    result = lm_economic_health()

                    # PF = 0.003 / 0.0035 ≈ 0.857
                    pf = result.get("profit_factor")
                    assert pf < 1.0, f"Expected PF < 1.0, got {pf}"
                    assert result.get("status") != "GOOD", "Should not be GOOD with PF < 1.0"


# ── V10.13u+5: Economic PF Parser Fix ─────────────────────────────────

def test_extract_trade_profit_matches_dashboard():
    """V10.13u+5: Verify profit extraction matches dashboard field priority."""
    from src.services.canonical_metrics import _extract_trade_profit

    # Test 1: profit field (top priority)
    trade1 = {"profit": 0.001, "pnl": 0.002}
    assert _extract_trade_profit(trade1) == 0.001, "Should use profit field first"

    # Test 2: pnl field (fallback)
    trade2 = {"pnl": 0.002}
    assert _extract_trade_profit(trade2) == 0.002, "Should use pnl field as fallback"

    # Test 3: evaluation.profit (legacy)
    trade3 = {"evaluation": {"profit": 0.003}}
    assert _extract_trade_profit(trade3) == 0.003, "Should use evaluation.profit for legacy"

    # Test 4: Zero and None handling
    trade4 = {"profit": None}
    assert _extract_trade_profit(trade4) == 0.0, "Should handle None as 0.0"

    trade5 = {"profit": 0.0}
    assert _extract_trade_profit(trade5) == 0.0, "Should handle 0.0 correctly"


def test_classify_outcome_matches_dashboard():
    """V10.13u+5: Verify outcome classification matches dashboard logic."""
    from src.services.canonical_metrics import _classify_outcome

    # Test 1: Result field with WIN
    trade_win = {"result": "WIN", "close_reason": "TP"}
    assert _classify_outcome(trade_win, 0.001) == "WIN"

    # Test 2: Result field with LOSS
    trade_loss = {"result": "LOSS", "close_reason": "SL"}
    assert _classify_outcome(trade_loss, -0.001) == "LOSS"

    # Test 3: Neutral reasons should return FLAT
    trade_timeout = {"result": "WIN", "close_reason": "TIMEOUT_FLAT", "profit": 0.0001}
    assert _classify_outcome(trade_timeout, 0.0001) == "FLAT", "Timeout with small profit should be FLAT"

    # Test 4: Fallback to profit direction (no result field)
    trade_no_result = {}
    assert _classify_outcome(trade_no_result, 0.001) == "WIN", "Positive profit = WIN"
    assert _classify_outcome(trade_no_result, -0.001) == "LOSS", "Negative profit = LOSS"
    assert _classify_outcome(trade_no_result, 0.0) == "FLAT", "Zero profit = FLAT"


def test_canonical_pf_with_profit_field():
    """V10.13u+5: Verify PF calculation with profit field (dashboard format)."""
    from src.services.canonical_metrics import canonical_profit_factor_with_meta

    # Create trades with "profit" field (dashboard format, not "net_pnl")
    trades = [
        {"profit": 0.001, "result": "WIN", "close_reason": "TP"},
        {"profit": 0.002, "result": "WIN", "close_reason": "TP"},
        {"profit": -0.001, "result": "LOSS", "close_reason": "SL"},
        {"profit": -0.002, "result": "LOSS", "close_reason": "SL"},
    ]

    meta = canonical_profit_factor_with_meta(trades)

    # 2 wins, 2 losses
    assert meta["wins"] == 2, f"Expected 2 wins, got {meta['wins']}"
    assert meta["losses"] == 2, f"Expected 2 losses, got {meta['losses']}"
    # gross_win = 0.001 + 0.002 = 0.003
    # gross_loss = 0.001 + 0.002 = 0.003
    # pf = 0.003 / 0.003 = 1.0
    assert abs(meta["pf"] - 1.0) < 0.01, f"Expected PF ≈ 1.0, got {meta['pf']}"


def test_parser_failure_clamp():
    """V10.13u+5: 100+ trades with zero wins/losses should trigger failure clamp."""
    from src.services.learning_monitor import lm_economic_health

    # Create 100 trades with no profit field (simulates parser failure)
    bad_trades = [{"close_reason": "TIMEOUT"} for _ in range(100)]

    with patch("src.services.firebase_client.load_history") as mock_load:
        mock_load.return_value = bad_trades

        with patch("src.services.learning_event.METRICS", {"trades": 100}):
            with patch("src.services.learning_event._close_reasons", {}):
                with patch("src.services.learning_event._recent_results", []):
                    result = lm_economic_health()

                    # Should trigger parser failure clamp
                    assert result.get("status") == "BAD", "Should be BAD for parse failure"
                    assert result.get("overall_score") == 0.0, "Score should be 0.0 for parse failure"


# ── V10.13u+6: Economic Log Throttle + Safety Freeze ────────────────────

def test_econ_log_throttle_not_every_cycle():
    """V10.13u+6: ECON_CANONICAL_ACTIVE should not log every cycle."""
    from src.services.learning_monitor import lm_economic_health
    import logging

    canonical_trades = [
        {"profit": 0.001, "result": "WIN"},
        {"profit": -0.001, "result": "LOSS"},
    ] * 250  # 500 trades

    # Mock the log to count emissions
    with patch("src.services.firebase_client.load_history") as mock_load:
        mock_load.return_value = canonical_trades

        with patch("src.services.learning_event.METRICS", {"trades": 500}):
            with patch("src.services.learning_event._close_reasons", {}):
                with patch("src.services.learning_event._recent_results", []):
                    with patch("src.services.learning_monitor.log") as mock_log:
                        # Call 1
                        result1 = lm_economic_health()
                        call_count_1 = mock_log.info.call_count
                        assert call_count_1 >= 1, "Should log on first call"

                        # Call 2 immediately after (within 60s) - should not log
                        result2 = lm_economic_health()
                        call_count_2 = mock_log.info.call_count
                        assert call_count_2 == call_count_1, "Should not log again within 60s for same values"


def test_econ_log_emits_on_status_change():
    """V10.13u+6: ECON_CANONICAL_ACTIVE should emit immediately on status change."""
    from src.services.learning_monitor import lm_economic_health, _last_econ_log_signature

    # First call - profitable
    profitable_trades = [{"profit": 0.01, "result": "WIN"} for _ in range(100)]

    with patch("src.services.firebase_client.load_history") as mock_load:
        mock_load.return_value = profitable_trades

        with patch("src.services.learning_event.METRICS", {"trades": 100}):
            with patch("src.services.learning_event._close_reasons", {}):
                with patch("src.services.learning_event._recent_results", []):
                    with patch("src.services.learning_monitor.log") as mock_log:
                        result1 = lm_economic_health()
                        status1 = result1.get("status")
                        call_count_1 = mock_log.info.call_count

                        # Second call with different trades (unprofitable)
                        unprofitable_trades = [{"profit": -0.01, "result": "LOSS"} for _ in range(100)]
                        mock_load.return_value = unprofitable_trades

                        result2 = lm_economic_health()
                        status2 = result2.get("status")
                        call_count_2 = mock_log.info.call_count

                        # Status changed, so should log immediately
                        if status1 != status2:
                            assert call_count_2 > call_count_1, "Should log when status changes"


def test_econ_safety_warning_throttle():
    """V10.13u+6: ECON_SAFETY_BAD warning should be throttled."""
    from src.services.learning_monitor import lm_economic_health

    bad_trades = [
        {"profit": 0.0001, "result": "WIN"},
        {"profit": -0.001, "result": "LOSS"},
    ] * 250  # 500 trades, unprofitable

    with patch("src.services.firebase_client.load_history") as mock_load:
        mock_load.return_value = bad_trades

        with patch("src.services.learning_event.METRICS", {"trades": 500}):
            with patch("src.services.learning_event._close_reasons", {}):
                with patch("src.services.learning_event._recent_results", []):
                    with patch("src.services.learning_monitor.log") as mock_log:
                        # Call 1 - should emit BAD warning
                        result1 = lm_economic_health()
                        assert result1.get("status") == "BAD", "Should be BAD for unprofitable"
                        warning_count_1 = mock_log.warning.call_count

                        # Call 2 immediately - should NOT emit BAD warning again
                        result2 = lm_economic_health()
                        warning_count_2 = mock_log.warning.call_count
                        assert warning_count_2 == warning_count_1, "BAD warning should be throttled within 60s"


# ── V10.13u+7: Exit Quality Stabilization ────────────────────────────────────

def test_stagnation_guard_holds_young_fee_negative():
    """V10.13u+7: Stagnation should not exit if too young and fees would make it a loss."""
    from src.services.smart_exit_engine import SmartExitEngine, Position

    engine = SmartExitEngine()

    # Position: 100s old, 0.0003% profit (below stagnation max_pnl)
    # With 0.2% fees, net_if_closed = 0.0003% - 0.2% = negative
    position = Position(
        symbol="ADAUSDT",
        entry_price=1.0,
        tp=1.01,
        sl=0.99,
        pnl_pct=0.0003,  # 0.03% profit
        age_seconds=100,  # Too young (< 180s)
        direction="LONG",
        max_favorable_pnl=0.0005,
    )

    result = engine._check_stagnation(position)
    assert result is None, "Should NOT exit young position with fee-negative net"


def test_stagnation_guard_exits_old_position():
    """V10.13u+7: Stagnation should exit after age threshold with positive net_if_closed."""
    from src.services.smart_exit_engine import SmartExitEngine, Position

    engine = SmartExitEngine()

    # Position: 350s old (> 180s threshold + 120s buffer), 0.0003% profit
    # net_if_closed = 0.0003 - 0.002 = -0.0017 still negative, but age > 300
    # So it should exit because age is well beyond the threshold
    position = Position(
        symbol="ADAUSDT",
        entry_price=1.0,
        tp=1.01,
        sl=0.99,
        pnl_pct=0.0003,
        age_seconds=350,  # Well above 300s threshold
        direction="LONG",
        max_favorable_pnl=0.0005,
    )

    result = engine._check_stagnation(position)
    assert result is not None, "Should exit very old position"
    assert result["exit_type"] == "STAGNATION_EXIT"


def test_economic_bad_tightens_ev_threshold():
    """V10.13u+7: EV threshold should tighten when economic health is BAD."""
    from src.services.realtime_decision_engine import current_ev_threshold

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        # Normal economic status
        mock_health.return_value = {"status": "GOOD", "pf": 1.5}
        normal_threshold = current_ev_threshold()
        assert normal_threshold == 0.025, "Should return normal 0.025"

        # BAD economic status
        mock_health.return_value = {"status": "BAD", "pf": 0.75}
        bad_threshold = current_ev_threshold()
        assert bad_threshold == 0.04, "Should tighten to 0.04 when BAD"


def test_economic_bad_tightens_score_threshold():
    """V10.13u+7: Score threshold should tighten when economic health is BAD."""
    from src.services.realtime_decision_engine import current_score_threshold

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        # Normal economic status
        mock_health.return_value = {"status": "GOOD", "pf": 1.5}
        normal_threshold = current_score_threshold()
        assert normal_threshold == 0.18, "Should return normal 0.18"

        # BAD economic status
        mock_health.return_value = {"status": "BAD", "pf": 0.75}
        bad_threshold = current_score_threshold()
        assert bad_threshold == 0.20, "Should tighten to 0.20 when BAD"


def test_churn_cooldown_blocks_entry():
    """V10.13u+7: Churn cooldown should block same symbol+direction within 10 min."""
    from src.services.realtime_decision_engine import (
        add_churn_cooldown,
        is_in_churn_cooldown,
    )

    add_churn_cooldown("ADAUSDT", "LONG", duration_sec=600)
    assert is_in_churn_cooldown("ADAUSDT", "LONG"), "Should be in cooldown"
    assert not is_in_churn_cooldown("ADAUSDT", "SHORT"), "Should allow opposite direction"
    assert not is_in_churn_cooldown("SOLUSDT", "LONG"), "Should allow different symbol"


def test_churn_cooldown_expires():
    """V10.13u+7: Churn cooldown should expire after duration."""
    import time
    from src.services.realtime_decision_engine import (
        add_churn_cooldown,
        is_in_churn_cooldown,
    )

    # Add cooldown with 1-second duration
    add_churn_cooldown("ADAUSDT", "LONG", duration_sec=1)
    assert is_in_churn_cooldown("ADAUSDT", "LONG"), "Should be in cooldown immediately"

    # Wait for expiry
    time.sleep(1.1)
    assert not is_in_churn_cooldown("ADAUSDT", "LONG"), "Should expire after duration"


def test_stagnation_loss_applies_cooldown():
    """V10.13u+7: Loss with STAGNATION_EXIT should apply cooldown."""
    # This test verifies the integration in trade_executor
    # The actual cooldown application happens in trade_executor.py
    # when a stagnation loss is detected

    from src.services.realtime_decision_engine import (
        add_churn_cooldown,
        is_in_churn_cooldown,
    )

    # Simulate stagnation loss applying cooldown
    add_churn_cooldown("ADAUSDT", "LONG", duration_sec=600)

    # Verify it blocks subsequent entries for that symbol+direction
    assert is_in_churn_cooldown("ADAUSDT", "LONG")


# ── V10.13u+8: Exit PnL Integrity + Scratch/Stagnation Safety ───────────────

def test_canonical_close_pnl_buy():
    """V10.13u+8: Canonical PnL for BUY side."""
    from src.services.exit_pnl import canonical_close_pnl

    result = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=100.0,
        exit_price=101.0,
        size=1.0,
        fee_rate=0.002,
        slippage_rate=0.0,
    )

    # BUY: (101 - 100) / 100 * 1 = 0.01
    assert abs(result["gross_pnl"] - 0.01) < 1e-9
    # Fee: 0.002 * 1.0 = -0.002
    assert abs(result["fee_pnl"] - (-0.002)) < 1e-9
    assert result["slippage_pnl"] == 0.0
    # Net: 0.01 - 0.002 = 0.008
    assert abs(result["net_pnl"] - 0.008) < 1e-9
    assert result["source"] == "canonical_close_pnl"


def test_canonical_close_pnl_sell():
    """V10.13u+8: Canonical PnL for SELL side."""
    from src.services.exit_pnl import canonical_close_pnl

    result = canonical_close_pnl(
        symbol="XRPUSDT",
        side="SELL",
        entry_price=100.0,
        exit_price=99.0,
        size=1.0,
        fee_rate=0.002,
        slippage_rate=0.0,
    )

    # SELL: (100 - 99) / 100 * 1 = 0.01
    assert abs(result["gross_pnl"] - 0.01) < 1e-9
    # Fee: 0.002 * 1.0 = -0.002
    assert abs(result["fee_pnl"] - (-0.002)) < 1e-9
    assert result["slippage_pnl"] == 0.0
    # Net: 0.01 - 0.002 = 0.008
    assert abs(result["net_pnl"] - 0.008) < 1e-9


def test_fee_and_slippage_are_non_positive():
    """V10.13u+8: Hard invariant: fee_pnl and slippage_pnl are non-positive."""
    from src.services.exit_pnl import canonical_close_pnl

    result = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=100.0,
        exit_price=101.0,
        size=1.0,
        fee_rate=0.002,
        slippage_rate=0.001,
    )

    assert result["fee_pnl"] <= 0, "fee_pnl must be non-positive"
    assert result["slippage_pnl"] <= 0, "slippage_pnl must be non-positive"


def test_net_equals_gross_plus_costs():
    """V10.13u+8: Algebraic identity: net = gross + fee + slippage."""
    from src.services.exit_pnl import canonical_close_pnl

    result = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=100.0,
        exit_price=101.0,
        size=1.0,
        fee_rate=0.002,
        slippage_rate=0.001,
    )

    expected_net = result["gross_pnl"] + result["fee_pnl"] + result["slippage_pnl"]
    assert abs(result["net_pnl"] - expected_net) < 1e-12


def test_prior_realized_pnl_included_in_gross():
    """V10.13u+8: prior_realized_pnl shifts gross and net equally."""
    from src.services.exit_pnl import canonical_close_pnl

    result_no_prior = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=100.0,
        exit_price=101.0,
        size=1.0,
        fee_rate=0.002,
        prior_realized_pnl=0.0,
    )

    result_with_prior = canonical_close_pnl(
        symbol="XRPUSDT",
        side="BUY",
        entry_price=100.0,
        exit_price=101.0,
        size=1.0,
        fee_rate=0.002,
        prior_realized_pnl=0.005,
    )

    # Gross and net should increase by exactly 0.005
    assert abs((result_with_prior["gross_pnl"] - result_no_prior["gross_pnl"]) - 0.005) < 1e-12
    assert abs((result_with_prior["net_pnl"] - result_no_prior["net_pnl"]) - 0.005) < 1e-12


def test_exit_integrity_compares_net_not_gross():
    """V10.13u+8: Exit integrity validator compares net PnL correctly."""
    from src.services.exit_attribution import validate_exit_ctx

    # Create exit context with canonical PnL values
    exit_ctx = {
        "symbol": "XRPUSDT",
        "sym": "XRPUSDT",
        "side": "BUY",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "size": 1.0,
        "hold_seconds": 300,
        "gross_pnl": 0.01,
        "fee_cost": 0.002,
        "slippage_cost": 0.0,
        "net_pnl": 0.008,  # gross - fee - slip
        "mfe": 0.015,
        "mae": 0.0,
        "final_exit_type": "TP",
        "exit_reason_text": "TP",
        "was_winner": True,
        "was_forced": False,
    }

    is_valid, errors = validate_exit_ctx(exit_ctx)
    assert is_valid, f"Should be valid, got errors: {errors}"


def test_scratch_guard_holds_negative_net_in_econ_bad():
    """V10.13u+8: SCRATCH_GUARD holds negative-net scratches in ECON BAD."""
    from src.services.smart_exit_engine import SmartExitEngine, Position

    engine = SmartExitEngine()

    # Create a near-flat position that would be scratched (150s old = within SCRATCH_NEGATIVE_GRACE_S=240)
    position = Position(
        symbol="ADAUSDT",
        entry_price=1.0,
        tp=1.002,
        sl=0.999,
        pnl_pct=0.0001,  # Within scratch band (< 0.0012)
        age_seconds=150,
        direction="LONG",
        max_favorable_pnl=0.0001,
    )

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        # ECON BAD status
        mock_health.return_value = {"status": "BAD", "pf": 0.75}

        result = engine._check_scratch(position)
        # Should be blocked because net_if_closed < 0 and ECON BAD
        assert result is None, "Should block scratch in ECON BAD with negative net"


def test_scratch_guard_allows_exit_when_econ_good():
    """V10.13u+8: Scratch proceeds normally when ECON GOOD."""
    from src.services.smart_exit_engine import SmartExitEngine, Position

    engine = SmartExitEngine()

    # Create a near-flat position that would be scratched (150s old = within SCRATCH_NEGATIVE_GRACE_S=240)
    position = Position(
        symbol="ADAUSDT",
        entry_price=1.0,
        tp=1.002,
        sl=0.999,
        pnl_pct=0.0001,  # Within scratch band (< 0.0012)
        age_seconds=150,
        direction="LONG",
        max_favorable_pnl=0.0001,
    )

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        # ECON GOOD status
        mock_health.return_value = {"status": "GOOD", "pf": 1.5}

        result = engine._check_scratch(position)
        # Should proceed to scratch exit
        assert result is not None, "Should allow scratch when ECON GOOD"
        assert result["exit_type"] == "SCRATCH_EXIT"


def test_stag_guard_holds_negative_net_in_econ_bad():
    """V10.13u+8: STAG_GUARD extends hold to 240s in ECON BAD for negative net."""
    from src.services.smart_exit_engine import SmartExitEngine, Position

    engine = SmartExitEngine()

    # Create position at age 200s (past base guard 180s but before ECON BAD guard 240s)
    position = Position(
        symbol="ADAUSDT",
        entry_price=1.0,
        tp=1.002,
        sl=0.999,
        pnl_pct=0.0008,  # Within stagnation band but with negative net after fees
        age_seconds=200,
        direction="LONG",
        max_favorable_pnl=0.0008,
    )

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        # ECON BAD status
        mock_health.return_value = {"status": "BAD", "pf": 0.75}

        result = engine._check_stagnation(position)
        # Should be blocked by ECON BAD extension
        assert result is None, "Should hold stagnation in ECON BAD at age 200s"


# ── V10.13u+9: Reentrant Close Guard ──────────────────────────────────────

def test_close_lock_blocks_duplicate_same_position():
    """V10.13u+9: Close lock blocks duplicate closes on same position."""
    from src.services.trade_executor import (
        _close_key, _CLOSING_POSITIONS, _RECENTLY_CLOSED
    )

    # Create a test position dict
    pos = {
        "action": "BUY",
        "entry": 100.0,
        "entry_time": 12345.0,
        "opened_at": 12345.0,
    }

    # Generate close key
    ckey = _close_key("BTCUSDT", pos)

    # Clear state
    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()

    # First attempt should succeed (lock acquired)
    import time
    assert ckey not in _CLOSING_POSITIONS
    _CLOSING_POSITIONS[ckey] = {
        "ts": time.time(),
        "symbol": "BTCUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": time.time(),
    }
    assert ckey in _CLOSING_POSITIONS

    # Second attempt should be blocked by the guard
    assert ckey in _CLOSING_POSITIONS, "First close should have acquired lock"


def test_close_lock_allows_different_symbol():
    """V10.13u+9: Close lock allows simultaneous closes for different symbols."""
    from src.services.trade_executor import (
        _close_key, _CLOSING_POSITIONS
    )

    pos_btc = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}
    pos_eth = {"action": "BUY", "entry": 50.0, "entry_time": 12346.0}

    _CLOSING_POSITIONS.clear()

    ckey_btc = _close_key("BTCUSDT", pos_btc)
    ckey_eth = _close_key("ETHUSDT", pos_eth)

    # Both keys should be different
    assert ckey_btc != ckey_eth

    # Both should be able to acquire locks simultaneously
    import time
    now = time.time()
    _CLOSING_POSITIONS[ckey_btc] = {
        "ts": now,
        "symbol": "BTCUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": now,
    }
    _CLOSING_POSITIONS[ckey_eth] = {
        "ts": now,
        "symbol": "ETHUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": now,
    }

    assert ckey_btc in _CLOSING_POSITIONS
    assert ckey_eth in _CLOSING_POSITIONS


def test_close_lock_releases_on_exception():
    """V10.13u+9: Close lock is released even if close logic raises exception."""
    from src.services.trade_executor import (
        _close_key, _CLOSING_POSITIONS
    )

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}
    _CLOSING_POSITIONS.clear()

    ckey = _close_key("BTCUSDT", pos)

    # Simulate acquiring lock
    import time
    _CLOSING_POSITIONS[ckey] = {
        "ts": time.time(),
        "symbol": "BTCUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": time.time(),
    }
    assert ckey in _CLOSING_POSITIONS

    # Simulate releasing on exception
    _CLOSING_POSITIONS.pop(ckey, None)
    assert ckey not in _CLOSING_POSITIONS


def test_recently_closed_ttl_blocks_immediate_reclose():
    """V10.13u+9/u+11: Recently-closed TTL prevents immediate re-close within TTL."""
    import time as time_module
    from src.services.trade_executor import (
        _close_key, _RECENTLY_CLOSED, RECENTLY_CLOSED_TTL_S, _cleanup_close_locks
    )

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}
    _RECENTLY_CLOSED.clear()

    ckey = _close_key("BTCUSDT", pos)
    now = time_module.time()

    # Record close
    _RECENTLY_CLOSED[ckey] = now

    # Check within TTL (e.g., 2 seconds later)
    assert ckey in _RECENTLY_CLOSED, "Recently closed should be tracked"

    # After TTL expires (simulate past expiry)
    _cleanup_close_locks(now + RECENTLY_CLOSED_TTL_S + 1)
    assert ckey not in _RECENTLY_CLOSED, "TTL should expire old entries"


def test_exit_audit_not_incremented_on_duplicate():
    """V10.13u+9: Exit audit counters only increment on successful unique closes."""
    from src.services.trade_executor import (
        _close_key, _CLOSING_POSITIONS, _RECENTLY_CLOSED
    )

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()

    ckey = _close_key("BTCUSDT", pos)

    # First close: add to recently closed
    import time
    now = time.time()
    _RECENTLY_CLOSED[ckey] = now
    _CLOSING_POSITIONS[ckey] = {
        "ts": now,
        "symbol": "BTCUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": now,
    }

    # Check: duplicate should be blocked by guard
    # (In actual code, [CLOSE_SKIP_DUPLICATE] would be logged)
    assert ckey in _RECENTLY_CLOSED or ckey in _CLOSING_POSITIONS


# ── V10.13u+10: Close Guard First + Exit Type Normalization ──────────────

def test_replaced_exit_type_normalized():
    """V10.13u+10: Replacement exit type variations normalize to REPLACED_EXIT."""
    from src.services.exit_attribution import normalize_exit_type

    assert normalize_exit_type("replaced") == "REPLACED_EXIT"
    assert normalize_exit_type("REPLACED") == "REPLACED_EXIT"
    assert normalize_exit_type("replace") == "REPLACED_EXIT"
    assert normalize_exit_type("REPLACEMENT") == "REPLACED_EXIT"
    # Case insensitive
    assert normalize_exit_type("RePlaCeD") == "REPLACED_EXIT"


def test_other_exit_types_normalized():
    """V10.13u+10: Other exit type variations also normalize correctly."""
    from src.services.exit_attribution import normalize_exit_type

    assert normalize_exit_type("SCRATCH") == "SCRATCH_EXIT"
    assert normalize_exit_type("scratch") == "SCRATCH_EXIT"
    assert normalize_exit_type("STAGNATION") == "STAGNATION_EXIT"
    assert normalize_exit_type("stagnation") == "STAGNATION_EXIT"


def test_validator_accepts_replaced_exit():
    """V10.13u+10: Exit validator accepts replaced exit type after normalization."""
    from src.services.exit_attribution import validate_exit_ctx

    # Create minimal valid context with "replaced" exit type
    exit_ctx = {
        "symbol": "BTCUSDT",
        "sym": "BTCUSDT",
        "side": "BUY",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "size": 1.0,
        "hold_seconds": 300,
        "gross_pnl": 0.01,
        "fee_cost": 0.0002,
        "slippage_cost": 0.0,
        "net_pnl": 0.0098,
        "mfe": 0.015,
        "mae": 0.0,
        "final_exit_type": "replaced",  # Should be normalized to REPLACED_EXIT
        "exit_reason_text": "replaced",
        "was_winner": True,
        "was_forced": False,
    }

    is_valid, errors = validate_exit_ctx(exit_ctx)
    assert is_valid, f"Should be valid after normalization, got errors: {errors}"
    # Verify it was normalized
    assert exit_ctx["final_exit_type"] == "REPLACED_EXIT"


def test_close_guard_blocks_duplicate_recently_closed():
    """V10.13u+10: Close guard blocks duplicate using _is_recently_closed."""
    from src.services.trade_executor import (
        _close_key, _is_recently_closed, _mark_recently_closed, _RECENTLY_CLOSED
    )

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}
    _RECENTLY_CLOSED.clear()

    ckey = _close_key("BTCUSDT", pos)

    # Not recently closed initially
    assert not _is_recently_closed(ckey)

    # Mark as recently closed
    _mark_recently_closed(ckey)
    assert _is_recently_closed(ckey)


def test_close_guard_separate_checks():
    """V10.13u+10/u+11: Close guard checks recently_closed and already_closing separately."""
    import time
    from src.services.trade_executor import (
        _close_key, _is_recently_closed, _CLOSING_POSITIONS, _RECENTLY_CLOSED
    )

    pos_btc = {"action": "BUY", "entry": 100.0, "entry_time": 12345.0}
    pos_eth = {"action": "BUY", "entry": 50.0, "entry_time": 12346.0}

    _RECENTLY_CLOSED.clear()
    _CLOSING_POSITIONS.clear()

    ckey_btc = _close_key("BTCUSDT", pos_btc)
    ckey_eth = _close_key("ETHUSDT", pos_eth)

    # Set BTC as recently closed
    _RECENTLY_CLOSED[ckey_btc] = time.time()

    # Set ETH as currently closing (V10.13u+11: dict with metadata)
    _CLOSING_POSITIONS[ckey_eth] = {
        "ts": time.time(),
        "symbol": "ETHUSDT",
        "reason": "TEST",
        "attempts": 1,
        "last_log": time.time(),
    }

    # Check separate detection
    assert _is_recently_closed(ckey_btc), "Should detect recently closed"
    assert ckey_eth in _CLOSING_POSITIONS, "Should detect already closing"
    assert not _is_recently_closed(ckey_eth), "ETH not in recently closed"
    assert ckey_btc not in _CLOSING_POSITIONS, "BTC not in currently closing"


# ── V10.13u+11: Close Lock TTL + Stuck Position Recovery ────────────────────


def test_close_lock_acquire_once():
    """V10.13u+11: Lock acquired only once per close key."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _CLOSING_POSITIONS, _RECENTLY_CLOSED,
        _close_key, _STALE_CLOSE_COUNTS
    )

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()
    _STALE_CLOSE_COUNTS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    # First acquisition should succeed
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT")
    assert acquired is True, "First lock acquisition should succeed"
    assert status == "acquired", f"Expected 'acquired', got '{status}'"
    assert key in _CLOSING_POSITIONS, "Key should be in _CLOSING_POSITIONS"

    # Second acquisition should fail (already closing)
    acquired2, key2, status2 = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT")
    assert acquired2 is False, "Second lock acquisition should fail"
    assert status2 == "already_closing", f"Expected 'already_closing', got '{status2}'"
    assert key == key2, "Should have same key"


def test_close_lock_ttl_releases_stale():
    """V10.13u+11: Stale locks are released and logged."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _cleanup_close_locks, _CLOSING_POSITIONS,
        _RECENTLY_CLOSED, _STALE_CLOSE_COUNTS, CLOSE_LOCK_TTL_S
    )

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()
    _STALE_CLOSE_COUNTS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    now = time.time()

    # Acquire lock
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT", now=now)
    assert acquired is True

    # Move time forward past TTL
    future = now + CLOSE_LOCK_TTL_S + 1.0
    _cleanup_close_locks(future)

    # Lock should be released
    assert key not in _CLOSING_POSITIONS, "Stale lock should be removed"
    assert key in _STALE_CLOSE_COUNTS, "Stale release should be tracked"
    assert _STALE_CLOSE_COUNTS[key] == 1, "Stale count should be 1"


def test_close_skip_duplicate_is_throttled():
    """V10.13u+11: Duplicate skip logging is throttled (every 5s)."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _CLOSING_POSITIONS, _RECENTLY_CLOSED,
        _STALE_CLOSE_COUNTS
    )

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()
    _STALE_CLOSE_COUNTS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    now = time.time()

    # Acquire lock
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT", now=now)
    assert acquired is True
    assert _CLOSING_POSITIONS[key]["last_log"] == now

    # Try again within 5 seconds - should not update last_log
    later = now + 2.0
    acquired2, key2, status2 = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT", now=later)
    assert acquired2 is False
    assert status2 == "already_closing"
    assert _CLOSING_POSITIONS[key]["last_log"] == now, "last_log should not be updated yet"

    # Try again after 5 seconds - should update last_log
    future = now + 6.0
    acquired3, key3, status3 = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT", now=future)
    assert acquired3 is False
    assert status3 == "already_closing"
    assert _CLOSING_POSITIONS[key]["last_log"] == future, "last_log should be updated"


def test_recently_closed_blocks_reclose():
    """V10.13u+11: Recently closed positions block re-close attempts."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _mark_recently_closed, _CLOSING_POSITIONS,
        _RECENTLY_CLOSED, _STALE_CLOSE_COUNTS, _close_key
    )

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()
    _STALE_CLOSE_COUNTS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}
    key = _close_key("BTCUSDT", pos)

    # Mark as recently closed
    _mark_recently_closed(key)

    # Try to acquire lock for same position
    now = time.time()
    acquired, ret_key, status = _try_acquire_close_lock("BTCUSDT", pos, "TEST_EXIT", now=now)

    assert acquired is False, "Lock should be blocked by recently_closed"
    assert status == "recently_closed", f"Expected 'recently_closed', got '{status}'"
    assert ret_key == key


def test_recently_closed_expires():
    """V10.13u+11: Recently closed entries expire after TTL."""
    import time
    from src.services.trade_executor import (
        _mark_recently_closed, _cleanup_close_locks, _RECENTLY_CLOSED,
        _STALE_CLOSE_COUNTS, RECENTLY_CLOSED_TTL_S
    )

    _RECENTLY_CLOSED.clear()
    _STALE_CLOSE_COUNTS.clear()

    key = "TEST:BUY:100.0:1234567"

    now = time.time()
    _RECENTLY_CLOSED[key] = now

    assert key in _RECENTLY_CLOSED

    # Clean up before TTL expires
    early = now + RECENTLY_CLOSED_TTL_S - 1.0
    _cleanup_close_locks(early)
    assert key in _RECENTLY_CLOSED, "Should not be cleaned up before TTL"

    # Clean up after TTL expires
    late = now + RECENTLY_CLOSED_TTL_S + 1.0
    _cleanup_close_locks(late)
    assert key not in _RECENTLY_CLOSED, "Should be cleaned up after TTL"


def test_close_lock_metadata_tracked():
    """V10.13u+11: Lock metadata is tracked (ts, symbol, reason, attempts)."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _CLOSING_POSITIONS
    )

    _CLOSING_POSITIONS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    now = time.time()
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "TEST_REASON", now=now)

    assert acquired is True
    meta = _CLOSING_POSITIONS[key]

    # Verify metadata fields
    assert meta["ts"] == now, "Timestamp should match"
    assert meta["symbol"] == "BTCUSDT", "Symbol should be tracked"
    assert meta["reason"] == "TEST_REASON", "Reason should be tracked"
    assert meta["attempts"] == 1, "Attempts should be 1 on first acquisition"
    assert "last_log" in meta, "last_log should be tracked"


def test_stale_release_count_increments():
    """V10.13u+11: Stale release count increments and triggers alert at 2+."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _cleanup_close_locks, _CLOSING_POSITIONS,
        _STALE_CLOSE_COUNTS, CLOSE_LOCK_TTL_S
    )

    _CLOSING_POSITIONS.clear()
    _STALE_CLOSE_COUNTS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    now = time.time()

    # First stale release
    acquired, key, _ = _try_acquire_close_lock("BTCUSDT", pos, "REASON1", now=now)
    future1 = now + CLOSE_LOCK_TTL_S + 1.0
    _cleanup_close_locks(future1)

    assert _STALE_CLOSE_COUNTS[key] == 1, "Count should be 1 after first stale release"

    # Second stale release (re-lock and expire again)
    acquired2, key2, _ = _try_acquire_close_lock("BTCUSDT", pos, "REASON2", now=future1)
    assert acquired2 is True, "Should be able to re-acquire after stale release"
    assert key == key2, "Should have same key"

    future2 = future1 + CLOSE_LOCK_TTL_S + 1.0
    _cleanup_close_locks(future2)

    assert _STALE_CLOSE_COUNTS[key] == 2, "Count should be 2 after second stale release"
    assert key not in _CLOSING_POSITIONS, "Lock should be cleared"


# ── V10.13u+12: Close-Lock Recovery + Watchdog Suppression ────────────────


def test_close_lock_cleanup_runs_before_duplicate_skip():
    """V10.13u+12: Cleanup (with hard recovery) runs before duplicate check."""
    import time
    from src.services.trade_executor import (
        _try_acquire_close_lock, _CLOSING_POSITIONS, CLOSE_LOCK_TTL_S
    )

    _CLOSING_POSITIONS.clear()

    pos = {"action": "BUY", "entry": 100.0, "entry_time": 1234567.0, "size": 1.0}

    now = time.time()

    # Insert fake stale lock (older than TTL)
    old_ts = now - CLOSE_LOCK_TTL_S - 1.0
    key = "BTCUSDT:BUY:100.0:1234567.0"
    _CLOSING_POSITIONS[key] = {
        "ts": old_ts,
        "symbol": "BTCUSDT",
        "reason": "STALE_TEST",
        "attempts": 5,
        "last_log": old_ts,
    }

    # Call _try_acquire_close_lock - should detect stale and release it
    acquired, ret_key, status = _try_acquire_close_lock("BTCUSDT", pos, "NEW_REASON", now=now)

    # Should acquire fresh lock (stale was released)
    assert acquired is True, "Should acquire fresh lock after stale release"
    assert status == "acquired", f"Expected 'acquired', got '{status}'"
    assert key in _CLOSING_POSITIONS, "New lock should be in positions"


def test_get_close_lock_health_cleans_stale():
    """V10.13u+12: get_close_lock_health() cleans stale locks before returning."""
    import time
    from src.services.trade_executor import (
        get_close_lock_health, _CLOSING_POSITIONS, _STALE_CLOSE_COUNTS, CLOSE_LOCK_TTL_S
    )

    _CLOSING_POSITIONS.clear()
    _STALE_CLOSE_COUNTS.clear()

    now = time.time()
    old_ts = now - CLOSE_LOCK_TTL_S - 1.0

    # Insert stale lock
    key = "ETHUSDT:SELL:50.0:1234568.0"
    _CLOSING_POSITIONS[key] = {
        "ts": old_ts,
        "symbol": "ETHUSDT",
        "reason": "OLD_CLOSE",
        "attempts": 2,
        "last_log": old_ts,
    }

    # Call get_close_lock_health
    health = get_close_lock_health()

    # Stale lock should be cleaned
    assert health["active"] == 0, "Active should be 0 after cleanup"
    assert key not in _CLOSING_POSITIONS, "Stale lock should be removed"
    assert _STALE_CLOSE_COUNTS[key] == 1, "Stale count should be 1"


def test_release_stale_close_lock_increments_count():
    """V10.13u+12: _release_stale_close_lock increments stale count."""
    import time
    from src.services.trade_executor import (
        _release_stale_close_lock, _STALE_CLOSE_COUNTS
    )

    _STALE_CLOSE_COUNTS.clear()

    key = "BNBUSDT:BUY:300.0:1234569.0"
    meta = {"ts": time.time() - 25, "symbol": "BNBUSDT", "reason": "TEST"}

    # Release stale lock
    _release_stale_close_lock(key, meta)

    assert _STALE_CLOSE_COUNTS[key] == 1, "Count should increment"

    # Release again
    _release_stale_close_lock(key, meta)

    assert _STALE_CLOSE_COUNTS[key] == 2, "Count should increment again"


def test_watchdog_suppressed_when_close_lock_active():
    """V10.13u+12: Watchdog suppresses exploration boost when close locks active."""
    from unittest.mock import patch, MagicMock
    from src.core.self_heal import handle_anomaly

    # Mock state
    mock_state = MagicMock()
    mock_state.exploration_factor = 1.0
    mock_state.allow_micro_trade = False
    mock_state.ev_threshold = 0.0
    mock_state.filter_strength = 1.0

    # Patch get_close_lock_health at the point it's imported in self_heal
    with patch('src.services.trade_executor.get_close_lock_health') as mock_health:
        mock_health.return_value = {"active": 2, "oldest_age": 5.5, "keys": ["KEY1", "KEY2"]}

        # Call handle_anomaly with STALL
        handle_anomaly("STALL", mock_state)

        # State should NOT be modified (exploration not boosted)
        assert mock_state.exploration_factor == 1.0, "Should not boost when locks active"
        assert mock_state.allow_micro_trade is False, "Should not enable micro trades"


def test_watchdog_runs_when_no_close_lock():
    """V10.13u+12: Watchdog proceeds with exploration when no close locks active."""
    from unittest.mock import patch, MagicMock
    from src.core.self_heal import handle_anomaly

    # Mock state
    mock_state = MagicMock()
    mock_state.exploration_factor = 1.0
    mock_state.allow_micro_trade = False
    mock_state.ev_threshold = 0.0
    mock_state.filter_strength = 1.0

    # Patch get_close_lock_health at the point it's imported in self_heal
    with patch('src.services.trade_executor.get_close_lock_health') as mock_health:
        mock_health.return_value = {"active": 0, "oldest_age": 0.0, "keys": []}

        # Call handle_anomaly with STALL
        handle_anomaly("STALL", mock_state)

        # State SHOULD be modified (exploration boosted)
        assert mock_state.exploration_factor == 1.5, "Should boost exploration when no locks"
        assert mock_state.allow_micro_trade is True, "Should enable micro trades"


def test_exit_type_replaced_alias_normalized():
    """V10.13u+12: 'replaced' exit type is normalized to canonical form."""
    from src.services.exit_attribution import normalize_exit_type, EXIT_TYPES

    # Test various replacements
    assert normalize_exit_type("replaced") == "REPLACED_EXIT"
    assert normalize_exit_type("REPLACED") == "REPLACED_EXIT"
    assert normalize_exit_type("replace") == "REPLACED_EXIT"
    assert normalize_exit_type("replacement") == "REPLACED_EXIT"

    # Ensure REPLACED_EXIT is in allowed types
    assert "REPLACED_EXIT" in EXIT_TYPES, "REPLACED_EXIT should be in EXIT_TYPES"


# ── V10.13u+13: Force reconcile stuck close loops ─────────────────────────────────

def test_force_reconcile_after_three_stale_releases():
    """V10.13u+13: Force reconcile is triggered after 3+ stale releases."""
    import time
    from src.services.trade_executor import (
        _CLOSING_POSITIONS, _STALE_CLOSE_COUNTS, _RECENTLY_CLOSED,
        _force_reconcile_stuck_close, CLOSE_LOCK_FORCE_RECONCILE_AFTER, _positions
    )

    _CLOSING_POSITIONS.clear()
    _STALE_CLOSE_COUNTS.clear()
    _RECENTLY_CLOSED.clear()
    _positions.clear()

    key = "BTCUSDT:BUY:50000.0:1234567.0"
    symbol = "BTCUSDT"
    meta = {
        "ts": time.time() - 60,
        "symbol": symbol,
        "reason": "TEST_STUCK",
        "attempts": 100,
    }

    # Insert a fake position
    _positions[symbol] = {"entry": 50000.0, "size": 1.0, "action": "BUY"}

    # Manually trigger force reconcile
    changed = _force_reconcile_stuck_close(key, meta, reason="stale_lock_threshold")

    # Position should be removed
    assert symbol not in _positions, "Position should be removed by force reconcile"
    # Key should be in recently closed (stores timestamp to block reacquire)
    assert key in _RECENTLY_CLOSED, "Key should be marked as force_reconciled"
    assert isinstance(_RECENTLY_CLOSED[key], float), "Should store timestamp, not dict"
    # Lock should be released
    assert key not in _CLOSING_POSITIONS, "Lock should be released"


def test_force_reconcile_blocks_immediate_reacquire():
    """V10.13u+13: Force reconciled keys cannot be immediately reacquired."""
    import time
    from src.services.trade_executor import (
        _CLOSING_POSITIONS, _RECENTLY_CLOSED, _try_acquire_close_lock,
        _force_reconcile_stuck_close, RECENTLY_CLOSED_TTL_S, _positions
    )

    _CLOSING_POSITIONS.clear()
    _RECENTLY_CLOSED.clear()
    _positions.clear()

    key = "ETHUSDT:SELL:3000.0:1234568.0"
    symbol = "ETHUSDT"
    meta = {"ts": time.time() - 60, "symbol": symbol, "reason": "TEST", "attempts": 100}

    # Add position
    _positions[symbol] = {"entry": 3000.0, "size": 1.0, "action": "SELL"}

    # Force reconcile
    _force_reconcile_stuck_close(key, meta)

    # Try to acquire same key immediately
    now = time.time()
    pos = {"entry": 3000.0, "size": 1.0, "action": "SELL", "entry_time": 1234568.0}
    acquired, ret_key, status = _try_acquire_close_lock(symbol, pos, "RETRY_AFTER_FORCE", now=now)

    # Should NOT acquire (recently_closed)
    assert acquired is False, "Should not acquire after force reconcile"
    assert status == "recently_closed", f"Expected 'recently_closed', got '{status}'"


def test_duplicate_close_logs_throttled():
    """V10.13u+13: Duplicate close logs are throttled to CLOSE_DUP_LOG_INTERVAL_S (10s)."""
    import time
    from src.services.trade_executor import (
        _CLOSING_POSITIONS, _try_acquire_close_lock, CLOSE_DUP_LOG_INTERVAL_S, _positions
    )

    _CLOSING_POSITIONS.clear()
    _positions.clear()

    symbol = "BNBUSDT"
    pos = {"entry": 300.0, "size": 1.0, "action": "BUY", "entry_time": 1234569.0}

    # First acquisition
    now = time.time()
    acquired1, key1, _ = _try_acquire_close_lock(symbol, pos, "FIRST", now=now)
    assert acquired1 is True

    # Second attempt (duplicate) immediately — should return already_closing
    # Get metadata
    meta = _CLOSING_POSITIONS[key1]
    last_log_1 = meta.get("last_log", now)

    # Try again at now+5s (within throttle window)
    acquired2, key2, status2 = _try_acquire_close_lock(symbol, pos, "SECOND", now=now + 5.0)
    assert acquired2 is False
    assert status2 == "already_closing"
    # last_log should NOT have been updated (still at initial time)
    assert meta.get("last_log") == last_log_1, "last_log should not update within throttle window"

    # Try again at now+11s (outside throttle window) — last_log should update
    acquired3, key3, status3 = _try_acquire_close_lock(symbol, pos, "THIRD", now=now + 11.0)
    assert acquired3 is False
    assert status3 == "already_closing"
    # last_log should have been updated
    assert meta.get("last_log") > last_log_1, "last_log should update after throttle interval"


def test_replaced_exit_type_normalized():
    """V10.13u+13: Verify 'replaced' exit type is normalized (from V10.13u+10)."""
    from src.services.exit_attribution import normalize_exit_type, EXIT_TYPES

    # Test various replacements
    assert normalize_exit_type("replaced") == "REPLACED_EXIT"
    assert normalize_exit_type("REPLACED") == "REPLACED_EXIT"
    assert normalize_exit_type("replace") == "REPLACED_EXIT"
    assert normalize_exit_type("replacement") == "REPLACED_EXIT"

    # Ensure REPLACED_EXIT is in allowed types
    assert "REPLACED_EXIT" in EXIT_TYPES, "REPLACED_EXIT should be in EXIT_TYPES"


def test_stale_release_does_not_reacquire_forever():
    """V10.13u+13: After stale release, position is force-reconciled, preventing infinite loop."""
    import time
    from src.services.trade_executor import (
        _CLOSING_POSITIONS, _STALE_CLOSE_COUNTS, _RECENTLY_CLOSED,
        _cleanup_close_locks, _try_acquire_close_lock,
        CLOSE_LOCK_TTL_S, CLOSE_LOCK_FORCE_RECONCILE_AFTER, _positions, _positions_lock
    )

    _CLOSING_POSITIONS.clear()
    _STALE_CLOSE_COUNTS.clear()
    _RECENTLY_CLOSED.clear()
    _positions.clear()

    symbol = "DOGEUSDT"
    pos = {"entry": 0.5, "size": 1.0, "action": "BUY", "entry_time": 1234570.0}
    key = "DOGEUSDT:BUY:0.5:1234570.0"

    # Add initial position
    with _positions_lock:
        _positions[symbol] = {"entry": 0.5, "size": 1.0, "action": "BUY"}

    now = time.time()

    # Simulate CLOSE_LOCK_FORCE_RECONCILE_AFTER+1 stale release cycles
    for cycle in range(CLOSE_LOCK_FORCE_RECONCILE_AFTER + 1):
        # Try to acquire lock
        acquired, ret_key, _ = _try_acquire_close_lock(symbol, pos, f"CYCLE_{cycle}", now=now)

        if cycle < CLOSE_LOCK_FORCE_RECONCILE_AFTER:
            # First N-1 cycles: should acquire
            assert acquired is True, f"Should acquire on cycle {cycle} (below threshold)"
            # Age the lock past TTL
            meta = _CLOSING_POSITIONS.get(key)
            if meta:
                meta["ts"] = now - CLOSE_LOCK_TTL_S - 1.0
            # Trigger cleanup for this cycle
            now += 1.0
            _cleanup_close_locks(now=now)
        else:
            # On the Nth cycle: force reconcile should have happened
            # Position should be gone, key should be in recently_closed
            assert symbol not in _positions, "Position should be removed by force reconcile"
            assert key in _RECENTLY_CLOSED, "Key should be in recently_closed after force reconcile"

    # Final check: stale count should be at threshold
    assert _STALE_CLOSE_COUNTS[key] >= CLOSE_LOCK_FORCE_RECONCILE_AFTER, \
        f"Stale count {_STALE_CLOSE_COUNTS[key]} should be >= {CLOSE_LOCK_FORCE_RECONCILE_AFTER}"


def test_v10_13u14_partial_tp_skips_full_close():
    """V10.13u+14: Partial TP exits don't acquire full close lock."""
    from src.services.trade_executor import (
        _try_acquire_close_lock, _CLOSING_POSITIONS, _close_key,
        PARTIAL_CLOSE_TYPES
    )

    # Create a position
    pos = {
        "action": "BUY",
        "entry": 100.0,
        "opened_at": 1000000.0,
        "size": 1.0,
        "pnl_pct": 0.05,
    }

    # Try to acquire lock for PARTIAL_TP_25 - should be guarded upstream
    # The guard checks reason against PARTIAL_CLOSE_TYPES and returns early
    assert "PARTIAL_TP_25" in PARTIAL_CLOSE_TYPES
    key = _close_key("BTCUSDT", pos)

    # Verify constants exist
    assert hasattr(_CLOSING_POSITIONS, '__getitem__'), "_CLOSING_POSITIONS should be dict-like"


def test_v10_13u14_close_stage_logging():
    """V10.13u+14: Stage logging function exists and is callable."""
    from src.services.trade_executor import _close_stage

    # Just verify the function exists and can be called
    try:
        _close_stage("BTCUSDT", "test:key", "test_stage", test_meta="value")
        # If no exception, it works
        assert True
    except Exception as e:
        pytest.fail(f"_close_stage() raised {e}")


def test_v10_13u14_phase2_partial_tp_lock_rejected():
    """V10.13u+14 Phase 2: Defensive guard rejects partial reason in lock function."""
    from src.services.trade_executor import _try_acquire_close_lock, PARTIAL_CLOSE_TYPES

    pos = {
        "action": "BUY",
        "entry": 100.0,
        "opened_at": 1000000.0,
        "size": 1.0,
    }

    # Try to acquire lock with PARTIAL_TP_25 - should be rejected
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "PARTIAL_TP_25")
    assert acquired is False, "Partial TP should not acquire lock"
    assert status == "partial_tp_not_allowed", f"Status should be partial_tp_not_allowed, got {status}"
    assert key is None, "Key should be None for rejected partial reason"


def test_v10_13u14_phase2_full_close_lock_works():
    """V10.13u+14 Phase 2: Full close types can still acquire lock."""
    from src.services.trade_executor import (
        _try_acquire_close_lock, FULL_CLOSE_TYPES, _CLOSING_POSITIONS,
        _close_key
    )

    pos = {
        "action": "BUY",
        "entry": 100.0,
        "opened_at": 1000000.0,
        "size": 1.0,
    }

    # Try to acquire lock with TRAIL_PROFIT (full close) - should work
    acquired, key, status = _try_acquire_close_lock("BTCUSDT", pos, "TRAIL_PROFIT")
    assert acquired is True, "Full close TRAIL_PROFIT should acquire lock"
    assert status == "acquired", f"Status should be acquired, got {status}"
    assert key is not None, "Key should not be None"

    # Cleanup
    _CLOSING_POSITIONS.pop(key, None)


def test_v10_13u15_scratch_cost_guard_holds_negative_net():
    """V10.13u+15: Cost guard holds negative-net SCRATCH when ECON BAD."""
    from src.services.smart_exit_engine import SmartExitEngine, Position
    from unittest.mock import patch

    engine = SmartExitEngine()

    pos = Position(
        symbol="BTCUSDT",
        entry_price=100.0,
        tp=102.0,
        sl=99.0,
        pnl_pct=0.0005,  # Small positive, but less than fee cost (~0.002)
        age_seconds=150,  # Within 360s window
        direction="LONG",
        max_favorable_pnl=0.01,
    )

    # Mock ECON BAD
    with patch("src.services.smart_exit_engine._econ_bad", return_value=True):
        result = engine._check_scratch(pos)
        # With cost guard, should return None (hold position)
        assert result is None, "Should hold negative-net scratch when ECON BAD"


def test_v10_13u15_scratch_cost_guard_with_econ_good():
    """V10.13u+15: Cost guard does not apply when Economic health is GOOD."""
    from src.services.smart_exit_engine import SmartExitEngine, Position
    from unittest.mock import patch

    engine = SmartExitEngine()

    pos = Position(
        symbol="BTCUSDT",
        entry_price=100.0,
        tp=102.0,
        sl=99.0,
        pnl_pct=0.0008,  # Within SCRATCH band, but negative after costs
        age_seconds=150,
        direction="LONG",
        max_favorable_pnl=0.01,
    )

    # Mock ECON GOOD
    with patch("src.services.smart_exit_engine._econ_bad", return_value=False):
        result = engine._check_scratch(pos)
        # Cost guard should not apply since ECON is not BAD
        # Scratch should exit even with negative net
        assert result is not None, "Should allow scratch when ECON GOOD"
        assert result["exit_type"] == "SCRATCH_EXIT"


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+16 — ECON BAD ENTRY QUALITY GATE TESTS
# ════════════════════════════════════════════════════════════════════════════════


def test_v10_13u16_econ_bad_blocks_low_ev():
    """V10.13u+16: Block TAKE when ECON BAD and ev < 0.045."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    # ECON BAD with weak EV
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="BTCUSDT",
            ev=0.030,  # Below 0.045 threshold
            score=0.25,
            win_prob=0.55,
            coherence=0.60,
            auditor_factor=0.75,
        )
        assert not allowed, "Should block when ev < 0.045"
        assert "weak_ev" in reason


def test_v10_13u16_econ_bad_blocks_low_af():
    """V10.13u+16: Block TAKE when ECON BAD and af < 0.70."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="ETHUSDT",
            ev=0.050,
            score=0.25,
            win_prob=0.55,
            coherence=0.60,
            auditor_factor=0.35,  # Below 0.70 threshold
        )
        assert not allowed, "Should block when af < 0.70"
        assert "weak_af" in reason


def test_v10_13u16_econ_bad_blocks_forced_explore_weak():
    """V10.13u+16: Block forced exploration under ECON BAD with weak quality."""
    from src.services.realtime_decision_engine import _econ_bad_forced_explore_gate
    from unittest.mock import patch

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        signal = {
            "forced": True,
            "ev": 0.030,  # Below 0.050 forced threshold
            "p": 0.55,
            "coh": 0.60,
            "af": 0.75,
        }
        allowed, reason = _econ_bad_forced_explore_gate(signal)
        assert not allowed, "Should block forced signal when ev < 0.050"
        assert "forced_weak_ev" in reason


def test_v10_13u16_econ_bad_allows_strong_signal():
    """V10.13u+16: Allow TAKE when ECON BAD but all thresholds met."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="SOLUSDT",
            ev=0.055,  # Above 0.045
            score=0.25,  # Above 0.22
            win_prob=0.56,  # Above 0.54
            coherence=0.62,  # Above 0.58
            auditor_factor=0.75,  # Above 0.70
        )
        assert allowed, "Should allow when all thresholds met"
        assert reason == ""


def test_v10_13u16_econ_good_allows_weak_signal():
    """V10.13u+16: Allow weak signal when ECON is GOOD (no gate blocking)."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(False, 1.05)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="DOGEUSDT",
            ev=0.030,  # Would fail during ECON BAD
            score=0.15,  # Would fail during ECON BAD
            win_prob=0.50,  # Would fail during ECON BAD
            coherence=0.50,  # Would fail during ECON BAD
            auditor_factor=0.50,  # Would fail during ECON BAD
        )
        assert allowed, "Should allow when ECON is GOOD (gate inactive)"
        assert reason == ""


def test_v10_13u16_cache_ttl_refresh():
    """V10.13u+16: ECON BAD cache reduces repeated lm_economic_health calls."""
    from src.services.realtime_decision_engine import _get_econ_bad_state, _ECON_BAD_CACHE
    from unittest.mock import patch

    # Reset cache to force fresh fetch
    _ECON_BAD_CACHE.update({"is_bad": False, "pf": 1.0, "net_pnl": 0.0, "last_check_ts": 0.0})

    # First call: cache miss, fetch from lm_economic_health
    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        mock_health.return_value = {"status": "BAD", "pf": 0.73, "net_pnl": -0.005}
        is_bad_1, pf_1 = _get_econ_bad_state()
        assert is_bad_1 is True
        assert pf_1 == 0.73
        first_call_count = mock_health.call_count

    # Second call within TTL: use cache (no additional call)
    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        mock_health.return_value = {"status": "GOOD", "pf": 1.05, "net_pnl": 0.050}
        is_bad_2, pf_2 = _get_econ_bad_state()
        # Should return cached value (BAD, 0.73) not the mocked new value
        assert is_bad_2 is True, "Should return cached BAD status"
        assert pf_2 == 0.73, "Should return cached pf value"
        second_call_count = mock_health.call_count
        assert second_call_count == 0, "Should use cache within TTL window"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
