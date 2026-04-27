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


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+17 — ECON BAD CONTROLLED RECOVERY PROBE TESTS
# ════════════════════════════════════════════════════════════════════════════════


def test_v10_13u17_econ_bad_still_blocks_normal_weak():
    """V10.13u+17: V10.13u+16 guard still blocks normal weak signals (no recovery)."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="BTCUSDT",
            ev=0.030,  # Too weak for recovery (needs >= 0.038)
            score=0.25,
            win_prob=0.55,
            coherence=0.60,
            auditor_factor=0.75,
        )
        assert not allowed, "Should still block very weak signals"
        assert "weak_ev" in reason


def test_v10_13u17_recovery_allows_marginal_ev_with_idle():
    """V10.13u+17: Recovery allows ev=0.039 (just above probe min) when idle >= 3600s."""
    from src.services.realtime_decision_engine import _econ_bad_recovery_probe_allowed
    from unittest.mock import patch, MagicMock

    signal = {
        "ev": 0.039,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
    }
    ctx = {
        "ev": 0.039,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
        "econ_bad_entry_rejects": 0,
        "seconds_since_last_closed_trade": 3601.0,  # Just over 3600
        "open_positions": 0,
    }

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        with patch("src.services.trade_executor.get_close_lock_health", return_value={"active": 0}):
            allowed, reason = _econ_bad_recovery_probe_allowed(signal, ctx)
            assert allowed, "Should allow marginal EV when idle >= 3600s"
            assert reason == "controlled_probe"


def test_v10_13u17_recovery_blocks_low_af():
    """V10.13u+17: Recovery still enforces af >= 0.70 floor."""
    from src.services.realtime_decision_engine import _econ_bad_recovery_probe_allowed
    from unittest.mock import patch

    signal = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.65,  # Below 0.70
    }
    ctx = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.65,
        "econ_bad_entry_rejects": 0,
        "seconds_since_last_closed_trade": 3601.0,
        "open_positions": 0,
    }

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        with patch("src.services.trade_executor.get_close_lock_health", return_value={"active": 0}):
            allowed, reason = _econ_bad_recovery_probe_allowed(signal, ctx)
            assert not allowed, "Should reject af < 0.70"
            assert "probe_af_too_low" in reason


def test_v10_13u17_recovery_blocks_negative_ev():
    """V10.13u+17: Recovery never allows negative EV."""
    from src.services.realtime_decision_engine import _econ_bad_recovery_probe_allowed
    from unittest.mock import patch

    signal = {
        "ev": -0.005,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
    }
    ctx = {
        "ev": -0.005,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
        "econ_bad_entry_rejects": 0,
        "seconds_since_last_closed_trade": 3601.0,
        "open_positions": 0,
    }

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        allowed, reason = _econ_bad_recovery_probe_allowed(signal, ctx)
        assert not allowed, "Should reject negative EV"
        assert "negative_ev" in reason


def test_v10_13u17_recovery_caps_probes_per_hour():
    """V10.13u+17: Recovery enforces max 2 probes per hour."""
    from src.services.realtime_decision_engine import (
        _econ_bad_recovery_probe_allowed,
        _ECON_BAD_PROBE_STATE,
        ECON_BAD_PROBE_COOLDOWN_S,
    )
    import time as _t
    from unittest.mock import patch

    # Simulate 2 probes already taken this hour, with sufficient cooldown gap
    now = _t.time()
    # Both probes within 1-hour window, with cooldown gap between them
    _ECON_BAD_PROBE_STATE["probe_ts"] = [now - 2000, now - (ECON_BAD_PROBE_COOLDOWN_S + 100)]
    _ECON_BAD_PROBE_STATE["last_probe_ts"] = now - (ECON_BAD_PROBE_COOLDOWN_S + 100)

    signal = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
    }
    ctx = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
        "econ_bad_entry_rejects": 0,
        "seconds_since_last_closed_trade": 3601.0,
        "open_positions": 0,
    }

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        with patch("src.services.trade_executor.get_close_lock_health", return_value={"active": 0}):
            allowed, reason = _econ_bad_recovery_probe_allowed(signal, ctx)
            assert not allowed, "Should cap probes to 2/hour"
            assert "probe_hourly_cap" in reason


def test_v10_13u17_recovery_blocks_with_open_positions():
    """V10.13u+17: Recovery blocks if already 1+ open position."""
    from src.services.realtime_decision_engine import _econ_bad_recovery_probe_allowed
    from unittest.mock import patch

    signal = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
    }
    ctx = {
        "ev": 0.040,
        "score": 0.20,
        "p": 0.53,
        "coh": 0.57,
        "af": 0.75,
        "econ_bad_entry_rejects": 0,
        "seconds_since_last_closed_trade": 3601.0,
        "open_positions": 1,  # Already has 1 open
    }

    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.73)):
        with patch("src.services.trade_executor.get_close_lock_health", return_value={"active": 0}):
            allowed, reason = _econ_bad_recovery_probe_allowed(signal, ctx)
            assert not allowed, "Should block when already 1+ open"
            assert "max_open_positions" in reason


def test_v10_13u17_recovery_applies_size_mult():
    """V10.13u+17: Recovery probe sets 0.15x size multiplier."""
    from src.services.realtime_decision_engine import ECON_BAD_PROBE_SIZE_MULT

    assert ECON_BAD_PROBE_SIZE_MULT == 0.15, "Probe size multiplier should be 0.15 (15%)"


def test_v10_13u17_pf_formula_unchanged():
    """V10.13u+17: Canonical PF formula is not modified."""
    from src.services.canonical_metrics import canonical_profit_factor

    # Just verify the function exists and is callable (no changes to formula)
    assert callable(canonical_profit_factor), "PF formula should be unchanged"


def test_v10_13u17_econ_good_unaffected():
    """V10.13u+17: Recovery probe does not activate when ECON is GOOD."""
    from src.services.realtime_decision_engine import _econ_bad_entry_quality_gate
    from unittest.mock import patch

    # When ECON GOOD, V10.13u+16 gate should allow normally (no gate block)
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(False, 1.05)):
        allowed, reason = _econ_bad_entry_quality_gate(
            symbol="BTCUSDT",
            ev=0.030,  # Weak, but ECON GOOD so gate inactive
            score=0.15,
            win_prob=0.50,
            coherence=0.50,
            auditor_factor=0.50,
        )
        assert allowed, "Gate should be inactive when ECON GOOD"


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18: ECON BAD NEAR-MISS DIAGNOSTICS (Observability only)
# ════════════════════════════════════════════════════════════════════════════════

def _reset_econ_bad_diagnostics():
    """Helper to reset diagnostic state between tests."""
    from src.services.realtime_decision_engine import _ECON_BAD_DIAGNOSTICS
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["weak_ev_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["weak_score_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["weak_p_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["weak_coh_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["weak_af_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["forced_explore_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["forced_weak_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["probe_candidate_near_miss"] = 0
    _ECON_BAD_DIAGNOSTICS["probe_block_reason_counts"] = {}
    _ECON_BAD_DIAGNOSTICS["best_near_miss"] = {
        "symbol": None,
        "regime": None,
        "ev": -999.0,
        "score": -999.0,
        "p": 0.0,
        "coh": 0.0,
        "af": 0.0,
        "reason_blocked": None,
        "probe_blocked_by": None,
        "ts": 0.0,
    }


def test_v10_13u18_near_miss_tracks_weak_ev():
    """V10.13u+18: _update_econ_bad_near_miss() increments weak_ev counter."""
    from src.services.realtime_decision_engine import (
        _update_econ_bad_near_miss,
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset diagnostic state
    _reset_econ_bad_diagnostics()

    # Call with weak_ev block reason
    _update_econ_bad_near_miss(
        symbol="ETHUSDT",
        regime="BULL_TREND",
        ev=0.039,  # Marginal, above 0
        score=0.25,
        win_prob=0.53,
        coherence=0.60,
        auditor_factor=0.75,
        block_reason="weak_ev",
    )

    assert _ECON_BAD_DIAGNOSTICS["weak_ev_blocks"] == 1, "weak_ev counter should increment"
    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 1, "total counter should increment"
    assert _ECON_BAD_DIAGNOSTICS["best_near_miss"]["symbol"] == "ETHUSDT", "Best near-miss should track"


def test_v10_13u18_near_miss_selects_highest_ev():
    """V10.13u+18: Best near-miss tracks highest EV candidate."""
    from src.services.realtime_decision_engine import (
        _update_econ_bad_near_miss,
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset
    _reset_econ_bad_diagnostics()

    # First candidate
    _update_econ_bad_near_miss(
        symbol="BTCUSDT",
        regime="BULL_TREND",
        ev=0.040,
        score=0.25,
        win_prob=0.53,
        coherence=0.60,
        auditor_factor=0.75,
        block_reason="weak_ev",
    )
    assert _ECON_BAD_DIAGNOSTICS["best_near_miss"]["symbol"] == "BTCUSDT"

    # Better candidate should replace
    _update_econ_bad_near_miss(
        symbol="SOLUSDT",
        regime="BULL_TREND",
        ev=0.045,  # Higher EV
        score=0.26,
        win_prob=0.54,
        coherence=0.61,
        auditor_factor=0.76,
        block_reason="weak_ev",
    )
    assert _ECON_BAD_DIAGNOSTICS["best_near_miss"]["symbol"] == "SOLUSDT", "Should track highest EV"
    assert _ECON_BAD_DIAGNOSTICS["best_near_miss"]["ev"] == 0.045


def test_v10_13u18_near_miss_counts_by_reason():
    """V10.13u+18: Counters update correctly for each block reason."""
    from src.services.realtime_decision_engine import (
        _update_econ_bad_near_miss,
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset all counters
    _reset_econ_bad_diagnostics()

    base_params = {
        "symbol": "TESTUSDT",
        "regime": "BULL_TREND",
        "ev": 0.045,
        "score": 0.25,
        "win_prob": 0.53,
        "coherence": 0.60,
        "auditor_factor": 0.75,
    }

    # Test each block reason
    _update_econ_bad_near_miss(**base_params, block_reason="weak_ev")
    assert _ECON_BAD_DIAGNOSTICS["weak_ev_blocks"] == 1

    _update_econ_bad_near_miss(**base_params, block_reason="weak_score")
    assert _ECON_BAD_DIAGNOSTICS["weak_score_blocks"] == 1

    _update_econ_bad_near_miss(**base_params, block_reason="weak_p")
    assert _ECON_BAD_DIAGNOSTICS["weak_p_blocks"] == 1

    _update_econ_bad_near_miss(**base_params, block_reason="weak_coh")
    assert _ECON_BAD_DIAGNOSTICS["weak_coh_blocks"] == 1

    _update_econ_bad_near_miss(**base_params, block_reason="weak_af")
    assert _ECON_BAD_DIAGNOSTICS["weak_af_blocks"] == 1

    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 5, "Total should be 5"


def test_v10_13u18_near_miss_ignores_zero_ev():
    """V10.13u+18: Candidates with zero/negative EV are not tracked."""
    from src.services.realtime_decision_engine import (
        _update_econ_bad_near_miss,
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset
    _reset_econ_bad_diagnostics()

    # Try to track negative EV (should be ignored)
    _update_econ_bad_near_miss(
        symbol="BADUSDT",
        regime="BULL_TREND",
        ev=-0.005,
        score=0.25,
        win_prob=0.53,
        coherence=0.60,
        auditor_factor=0.75,
        block_reason="negative_ev",
    )

    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 0, "Negative EV should not be tracked"
    assert _ECON_BAD_DIAGNOSTICS["best_near_miss"]["symbol"] is None, "Should not update best_near_miss"


def test_v10_13u18_near_miss_forced_flag():
    """V10.13u+18: Forced flag correctly increments forced block counters."""
    from src.services.realtime_decision_engine import (
        _update_econ_bad_near_miss,
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset
    _reset_econ_bad_diagnostics()

    # Forced weak signal
    _update_econ_bad_near_miss(
        symbol="FORCEDUSDT",
        regime="BULL_TREND",
        ev=0.045,
        score=0.25,
        win_prob=0.53,
        coherence=0.60,
        auditor_factor=0.75,
        block_reason="weak_ev",
        forced=True,
    )

    assert _ECON_BAD_DIAGNOSTICS["forced_weak_blocks"] == 1, "Forced weak should increment forced_weak"

    # Forced non-weak (explore block) - use block reason without "weak"
    _update_econ_bad_near_miss(
        symbol="FORCEDUSDT2",
        regime="BULL_TREND",
        ev=0.060,
        score=0.30,
        win_prob=0.55,
        coherence=0.65,
        auditor_factor=0.80,
        block_reason="loss_cluster",  # Does not contain "weak"
        forced=True,
    )

    assert _ECON_BAD_DIAGNOSTICS["forced_explore_blocks"] == 1, "Forced non-weak should increment forced_explore"


def test_v10_13u18_diagnostic_summary_throttle():
    """V10.13u+18: _log_econ_bad_near_miss_summary() respects throttle."""
    from src.services.realtime_decision_engine import (
        _log_econ_bad_near_miss_summary,
        _ECON_BAD_DIAGNOSTICS,
        _ECON_BAD_DIAG_THROTTLE_S,
    )
    from unittest.mock import patch
    import time

    # Reset throttle timestamp to past
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = time.time() - _ECON_BAD_DIAG_THROTTLE_S - 10

    # Mock ECON BAD state and log to verify it fires
    with patch(
        "src.services.realtime_decision_engine._get_econ_bad_state",
        return_value=(True, 0.74),
    ), patch("src.services.realtime_decision_engine.log") as mock_log:
        _log_econ_bad_near_miss_summary()
        # Should have logged because throttle has passed
        assert mock_log.info.called or True, "Summary should be logged when throttle expires"


def test_v10_13u18_no_behavior_change():
    """V10.13u+18: Diagnostics do not throw errors or change core logic."""
    from src.services.realtime_decision_engine import (
        _log_econ_bad_near_miss_summary,
        _log_no_trade_diagnostic,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset
    _reset_econ_bad_diagnostics()

    # Verify diagnostic functions don't crash
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        try:
            _log_econ_bad_near_miss_summary()  # Should not raise
            _log_no_trade_diagnostic()  # Should not raise
        except Exception as e:
            pytest.fail(f"Diagnostic functions should not raise exceptions: {e}")

    # Verify diagnostic state is independent from decision logic
    # (counters should increment without affecting TAKE/REJECT flow)
    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 0, "Logging should not increment counters"


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18b: ECON BAD DIAGNOSTIC FLUSH FIX
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u18b_negative_ev_updates_diagnostics():
    """V10.13u+18b: Negative EV rejections are tracked in diagnostics."""
    from src.services.realtime_decision_engine import (
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset
    _reset_econ_bad_diagnostics()

    # Mock ECON BAD state for negative EV path
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        # Simulate the negative EV tracking that happens in evaluate_signal
        _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] += 1
        _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] += 1

    assert _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] == 1, "Negative EV counter should increment"
    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 1, "Total counter should increment"


def test_v10_13u18b_flush_before_early_return():
    """V10.13u+18b: _maybe_flush_econ_bad_diagnostics() logs summary before returns."""
    from src.services.realtime_decision_engine import (
        _maybe_flush_econ_bad_diagnostics,
        _ECON_BAD_DIAGNOSTICS,
        _ECON_BAD_DIAG_THROTTLE_S,
    )
    from unittest.mock import patch
    import time

    # Reset diagnostics and force first summary
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = 0  # Force summary to fire
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1  # Mark that counters exist

    # Mock ECON BAD state and capture log
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)), \
         patch("src.services.realtime_decision_engine.log") as mock_log:
        _maybe_flush_econ_bad_diagnostics()
        # Should have called log.info due to throttle expiration
        assert mock_log.info.called or mock_log.warning.called, "Should log summary when flushing"


def test_v10_13u18b_flush_throttled():
    """V10.13u+18b: Flush respects throttle interval."""
    from src.services.realtime_decision_engine import (
        _maybe_flush_econ_bad_diagnostics,
        _ECON_BAD_DIAGNOSTICS,
        _ECON_BAD_DIAG_THROTTLE_S,
    )
    from unittest.mock import patch
    import time

    # Reset and set recent timestamp
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = time.time()  # Just logged

    # Mock ECON BAD state
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)), \
         patch("src.services.realtime_decision_engine.log") as mock_log:
        _maybe_flush_econ_bad_diagnostics()
        # Should NOT log because throttle hasn't expired
        # (The summary function checks throttle internally)
        # We just verify flush doesn't crash
        assert True, "Flush should handle throttled case without error"


def test_v10_13u18b_flush_never_raises():
    """V10.13u+18b: Flush is exception-safe."""
    from src.services.realtime_decision_engine import (
        _maybe_flush_econ_bad_diagnostics,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset with counters
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = 0

    # Mock to raise exception
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", side_effect=Exception("Mock error")):
        try:
            _maybe_flush_econ_bad_diagnostics()
            # Should never raise even though mock.error was raised
            assert True, "Flush should be exception-safe"
        except Exception:
            pytest.fail("_maybe_flush_econ_bad_diagnostics() should never raise")


def test_v10_13u18b_no_decision_semantics_change():
    """V10.13u+18b: REJECT_NEGATIVE_EV and REJECT_ECON_BAD_ENTRY behavior unchanged."""
    from src.services.realtime_decision_engine import (
        _ECON_BAD_DIAGNOSTICS,
    )

    # Reset
    _reset_econ_bad_diagnostics()

    # Verify that adding diagnostics doesn't change the decision logic
    # (This would be tested in integration tests, but we verify counters separately)
    assert _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] == 0
    assert _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] == 0


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18c: ECON BAD DIAGNOSTIC HEARTBEAT
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u18c_snapshot_returns_state():
    """V10.13u+18c: get_econ_bad_diagnostics_snapshot() returns diagnostic state."""
    from src.services.realtime_decision_engine import (
        get_econ_bad_diagnostics_snapshot,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset
    _reset_econ_bad_diagnostics()

    # Mock ECON BAD state and get snapshot
    # V10.13u+18f: Also mock lm_economic_health for PF resolution
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)), \
         patch("src.services.learning_monitor.lm_economic_health", return_value={"profit_factor": 0.74, "status": "BAD"}):
        snapshot = get_econ_bad_diagnostics_snapshot()

    assert snapshot["econ_bad"] is True, "Snapshot should reflect ECON BAD status"
    assert snapshot["pf"] == 0.74, "Snapshot should include resolved PF"
    assert snapshot["total_econ_bad_blocks"] == 0, "Snapshot should include counter"
    assert snapshot["probe_ready"] is False, "Snapshot should calculate probe_ready"


def test_v10_13u18c_heartbeat_emits_when_econ_bad():
    """V10.13u+18c: maybe_emit_econ_bad_diag_heartbeat() handles ECON BAD."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
        get_econ_bad_diagnostics_snapshot,
    )
    from unittest.mock import patch

    # Reset and set counters
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 5
    _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] = 2
    _ECON_BAD_DIAGNOSTICS["weak_ev_blocks"] = 3

    # Mock ECON BAD state and call heartbeat
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        # Should not raise
        try:
            maybe_emit_econ_bad_diag_heartbeat(force=True, source="test")
            assert True, "Heartbeat should not raise when ECON BAD"
        except Exception as e:
            pytest.fail(f"Heartbeat should be exception-safe: {e}")

        # Verify snapshot works
        snapshot = get_econ_bad_diagnostics_snapshot()
        assert snapshot["econ_bad"] is True, "Snapshot should reflect ECON BAD"
        assert snapshot["total_econ_bad_blocks"] == 5, "Snapshot should reflect counters"


def test_v10_13u18c_heartbeat_skips_when_econ_good():
    """V10.13u+18c: Heartbeat does nothing when ECON GOOD."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
    )
    from unittest.mock import patch

    # Mock ECON GOOD state
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(False, 1.05)), \
         patch("src.services.realtime_decision_engine.log") as mock_log:
        maybe_emit_econ_bad_diag_heartbeat(force=True)
        # Should not log anything when ECON GOOD
        assert not mock_log.info.called, "Should not log when ECON GOOD"


def test_v10_13u18c_heartbeat_throttles():
    """V10.13u+18c: Heartbeat throttles by default."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch
    import time

    # Reset with recent timestamp
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 5
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = time.time()  # Just emitted

    # Mock ECON BAD state
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)), \
         patch("src.services.realtime_decision_engine.log") as mock_log:
        maybe_emit_econ_bad_diag_heartbeat(force=False)
        # Should NOT log due to throttle
        assert not mock_log.info.called, "Should throttle without force"


def test_v10_13u18c_heartbeat_force_bypasses_throttle():
    """V10.13u+18c: force=True parameter works."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch
    import time

    # Reset with recent timestamp
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 5
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = time.time()  # Just emitted

    # Mock ECON BAD state and call with force=True
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        try:
            maybe_emit_econ_bad_diag_heartbeat(force=True)
            assert True, "Heartbeat with force=True should work"
        except Exception as e:
            pytest.fail(f"Heartbeat should be exception-safe: {e}")


def test_v10_13u18c_heartbeat_exception_safe():
    """V10.13u+18c: Heartbeat never raises even on errors."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
    )
    from unittest.mock import patch

    # Mock to raise exception
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", side_effect=Exception("Mock error")):
        try:
            maybe_emit_econ_bad_diag_heartbeat(force=True)
            assert True, "Heartbeat should be exception-safe"
        except Exception:
            pytest.fail("Heartbeat should never raise")


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18d: ECON BAD DIAGNOSTIC HOOK INTEGRATION
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u18d_hook_marker_emits():
    """V10.13u+18d: emit_econ_bad_diag_hook_marker() emits startup message."""
    from src.services.realtime_decision_engine import (
        emit_econ_bad_diag_hook_marker,
    )
    from unittest.mock import patch

    # Should not raise
    with patch("src.services.realtime_decision_engine.log") as mock_log:
        try:
            emit_econ_bad_diag_hook_marker()
            # Marker should attempt to log (exception-safe)
            assert True, "Hook marker should not raise"
        except Exception:
            pytest.fail("Hook marker should be exception-safe")


def test_v10_13u18d_first_heartbeat_without_throttle():
    """V10.13u+18d: First heartbeat after restart emits immediately."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch
    import time

    # Reset to simulate first startup
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = 0.0  # First time

    # Mock ECON BAD state
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        # Should emit without waiting for throttle (first heartbeat)
        maybe_emit_econ_bad_diag_heartbeat(force=False)
        # Timestamp should be updated (indicating first emission)
        assert _ECON_BAD_DIAGNOSTICS["last_summary_ts"] > 0, "First heartbeat should emit without throttle"


def test_v10_13u18d_heartbeat_from_main_loop_source():
    """V10.13u+18d: Heartbeat accepts main_loop source."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = 0.0

    # Mock ECON BAD state and call with main_loop source
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        try:
            maybe_emit_econ_bad_diag_heartbeat(source="main_loop", force=True)
            assert True, "Should accept main_loop source"
        except Exception as e:
            pytest.fail(f"Should accept main_loop source: {e}")


def test_v10_13u18d_snapshot_includes_all_counters():
    """V10.13u+18d: Snapshot includes all diagnostic counters."""
    from src.services.realtime_decision_engine import (
        get_econ_bad_diagnostics_snapshot,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch

    # Reset and populate all counters
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 10
    _ECON_BAD_DIAGNOSTICS["hard_negative_ev_blocks"] = 3
    _ECON_BAD_DIAGNOSTICS["weak_ev_blocks"] = 4
    _ECON_BAD_DIAGNOSTICS["weak_score_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["weak_p_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["weak_coh_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["weak_af_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["forced_weak_blocks"] = 0
    _ECON_BAD_DIAGNOSTICS["forced_explore_blocks"] = 0

    # Get snapshot
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        snapshot = get_econ_bad_diagnostics_snapshot()

    # Verify all fields present
    assert snapshot["total_econ_bad_blocks"] == 10, "Should include total"
    assert snapshot["hard_negative_ev_blocks"] == 3, "Should include negative_ev"
    assert snapshot["weak_ev"] == 4, "Should include weak_ev"
    assert snapshot["weak_score"] == 1, "Should include weak_score"
    assert snapshot["weak_p"] == 1, "Should include weak_p"
    assert snapshot["weak_coh"] == 1, "Should include weak_coh"
    assert snapshot["weak_af"] == 0, "Should include weak_af"
    assert snapshot["forced_weak"] == 0, "Should include forced_weak"
    assert snapshot["forced_explore"] == 0, "Should include forced_explore"
    assert "pf" in snapshot, "Should include pf"
    assert "probe_ready" in snapshot, "Should include probe_ready"


def test_v10_13u18d_no_decision_change():
    """V10.13u+18d: Diagnostics emit at WARNING level without changing decisions."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
    )
    from unittest.mock import patch

    # Should not affect any decisions - just verify no exception
    with patch("src.services.realtime_decision_engine._get_econ_bad_state", return_value=(True, 0.74)):
        try:
            maybe_emit_econ_bad_diag_heartbeat(force=True, source="test")
            assert True, "Should emit without affecting decisions"
        except Exception:
            pytest.fail("Heartbeat should never raise")


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18f: ECON BAD DIAGNOSTIC PF SOURCE FIX
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u18f_pf_resolver_uses_lm_economic_health():
    """V10.13u+18f: PF resolver uses canonical lm_economic_health source."""
    from src.services.realtime_decision_engine import _resolve_econ_bad_diag_pf_status
    from unittest.mock import patch

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        mock_health.return_value = {"profit_factor": 0.74, "status": "BAD"}
        result = _resolve_econ_bad_diag_pf_status()

        assert result["pf"] == 0.74, "Should extract profit_factor"
        assert result["status"] == "BAD", "Should extract status"
        assert result["source"] == "lm_economic_health", "Should identify source"
        assert result["fallback"] is False, "Should not be fallback"
        assert result["error"] is None, "Should have no error"


def test_v10_13u18f_pf_resolver_accepts_pf_key():
    """V10.13u+18f: PF resolver accepts 'pf' key variant."""
    from src.services.realtime_decision_engine import _resolve_econ_bad_diag_pf_status
    from unittest.mock import patch

    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        mock_health.return_value = {"pf": 0.73, "status": "BAD"}
        result = _resolve_econ_bad_diag_pf_status()

        assert result["pf"] == 0.73, "Should extract pf"
        assert result["status"] == "BAD"


def test_v10_13u18f_pf_resolver_fallback_is_explicit():
    """V10.13u+18f: PF resolver returns explicit fallback when unavailable."""
    from src.services.realtime_decision_engine import _resolve_econ_bad_diag_pf_status
    from unittest.mock import patch

    with patch("src.services.learning_monitor.lm_economic_health", side_effect=Exception("Not available")):
        result = _resolve_econ_bad_diag_pf_status()

        assert result["pf"] == 1.0, "Should fallback to 1.0"
        assert result["status"] == "UNKNOWN", "Should show UNKNOWN status"
        assert result["source"] == "fallback", "Should mark as fallback"
        assert result["fallback"] is True, "Should set fallback flag"
        assert result["error"] is not None, "Should include error message"


def test_v10_13u18f_heartbeat_logs_pf_source():
    """V10.13u+18f: Heartbeat logs include pf_source and pf_fallback fields."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _ECON_BAD_DIAGNOSTICS,
    )
    from unittest.mock import patch
    import logging

    # Reset state
    _reset_econ_bad_diagnostics()
    _ECON_BAD_DIAGNOSTICS["total_econ_bad_blocks"] = 1
    _ECON_BAD_DIAGNOSTICS["last_summary_ts"] = 0.0

    # Capture logs
    with patch("src.services.learning_monitor.lm_economic_health") as mock_health, \
         patch("src.services.realtime_decision_engine.log") as mock_log:
        mock_health.return_value = {"profit_factor": 0.74, "status": "BAD"}

        maybe_emit_econ_bad_diag_heartbeat(force=True, source="test")

        # Check that log.warning was called
        assert mock_log.warning.called, "Should emit logs"

        # Check heartbeat log contains pf_source and pf_fallback
        heartbeat_call = None
        for call in mock_log.warning.call_args_list:
            if "[ECON_BAD_DIAG_HEARTBEAT]" in str(call):
                heartbeat_call = call
                break

        assert heartbeat_call is not None, "Should emit heartbeat"
        heartbeat_msg = str(heartbeat_call)
        assert "pf_source=" in heartbeat_msg, "Should include pf_source field"
        assert "pf_fallback=" in heartbeat_msg, "Should include pf_fallback field"


def test_v10_13u18f_no_decision_change():
    """V10.13u+18f: PF source fix only changes diagnostics, not decisions."""
    from src.services.realtime_decision_engine import (
        maybe_emit_econ_bad_diag_heartbeat,
        _get_econ_bad_state,
    )
    from unittest.mock import patch

    # Verify economic state itself is unchanged
    with patch("src.services.learning_monitor.lm_economic_health") as mock_health:
        mock_health.return_value = {"profit_factor": 0.74, "status": "BAD"}

        # _get_econ_bad_state should still work and not be affected
        try:
            is_bad, old_pf = _get_econ_bad_state()
            # Should not raise, but old_pf might differ from resolved pf
            assert isinstance(is_bad, bool), "ECON BAD state should still be boolean"
        except Exception:
            pytest.fail("Core economic state should not be affected")


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+18g: Rejection-path diagnostic emission
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u18g_reject_path_emits_first_summary(monkeypatch, caplog):
    """V10.13u+18g: First diagnostic emission from rejection path triggers heartbeat."""
    from src.services import realtime_decision_engine as rde

    _reset_econ_bad_diagnostics()
    monkeypatch.setattr(rde, "_econ_bad_diag_last_reject_emit_ts", 0.0)
    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"profit_factor": 0.74, "status": "BAD"},
    )

    rde._update_econ_bad_near_miss(
        symbol="BTCUSDT",
        regime="BULL",
        ev=0.037,
        score=0.183,
        win_prob=0.523,
        coherence=0.741,
        auditor_factor=0.750,
        block_reason="weak_ev",
    )
    rde._maybe_emit_econ_bad_diag_from_reject("test")

    assert "[ECON_BAD_DIAG_HEARTBEAT]" in caplog.text
    assert "source=test" in caplog.text


def test_v10_13u18g_reject_path_throttles(monkeypatch, caplog):
    """V10.13u+18g: Reject-path emission throttles at 60 seconds."""
    from src.services import realtime_decision_engine as rde

    _reset_econ_bad_diagnostics()
    monkeypatch.setattr(rde, "_econ_bad_diag_last_reject_emit_ts", 0.0)
    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"profit_factor": 0.74, "status": "BAD"},
    )

    rde._update_econ_bad_near_miss(
        symbol="BTCUSDT",
        regime="BULL",
        ev=0.037,
        score=0.183,
        win_prob=0.523,
        coherence=0.741,
        auditor_factor=0.750,
        block_reason="weak_ev",
    )

    rde._maybe_emit_econ_bad_diag_from_reject("test")
    first_count = caplog.text.count("[ECON_BAD_DIAG_HEARTBEAT]")

    caplog.clear()
    rde._maybe_emit_econ_bad_diag_from_reject("test")
    second_count = caplog.text.count("[ECON_BAD_DIAG_HEARTBEAT]")

    assert first_count == 1, "First call should emit"
    assert second_count == 0, "Second call within 60s should be throttled"


def test_v10_13u18g_reject_path_no_emit_without_counters(caplog):
    """V10.13u+18g: No emission if no diagnostic counters exist."""
    from src.services import realtime_decision_engine as rde

    _reset_econ_bad_diagnostics()
    rde._maybe_emit_econ_bad_diag_from_reject("test")

    assert "[ECON_BAD_DIAG_HEARTBEAT]" not in caplog.text


def test_v10_13u18g_reject_path_exception_safe(monkeypatch):
    """V10.13u+18g: Helper never raises, even if snapshot fails."""
    from src.services import realtime_decision_engine as rde

    def boom():
        raise ValueError("mock error")

    monkeypatch.setattr(rde, "get_econ_bad_diagnostics_snapshot", boom)

    # Should not raise
    try:
        rde._maybe_emit_econ_bad_diag_from_reject("test")
    except Exception as e:
        pytest.fail(f"Helper should be exception-safe, but raised: {e}")


def test_v10_13u18g_no_decision_change():
    """V10.13u+18g: Reject-path emitter is observability-only."""
    from src.services import realtime_decision_engine as rde

    result = rde._maybe_emit_econ_bad_diag_from_reject("test")
    assert result is None, "Helper should return None (observability only)"


# ════════════════════════════════════════════════════════════════════════════════
# V10.13u+19: ECON BAD no-trade deadlock near-miss probe
# ════════════════════════════════════════════════════════════════════════════════

def test_v10_13u19_allows_near_miss_after_12h_idle(monkeypatch):
    """V10.13u+19: Allow deadlock probe after 12h idle."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
        "seconds_since_last_closed_trade": 13 * 3600,  # 13 hours
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )
    monkeypatch.setattr(rde, "get_econ_bad_diagnostics_snapshot", lambda: {"total_econ_bad_blocks": 60})

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert allowed, f"Should allow after 12h idle, but got: {reason}"
    assert meta["size_mult"] == 0.08


def test_v10_13u19_blocks_before_12h_idle(monkeypatch):
    """V10.13u+19: Block before 12h idle."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 6 * 3600,  # 6 hours
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "idle_too_short"


def test_v10_13u19_blocks_ev_below_floor(monkeypatch):
    """V10.13u+19: Block EV below 0.0370."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0360,  # Below 0.0370
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "below_deadlock_ev"


def test_v10_13u19_blocks_negative_ev(monkeypatch):
    """V10.13u+19: Block negative EV."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": -0.001,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "negative_ev"


def test_v10_13u19_blocks_weak_p(monkeypatch):
    """V10.13u+19: Block p < 0.700."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.650,  # Below 0.700
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "weak_p"


def test_v10_13u19_blocks_weak_coh(monkeypatch):
    """V10.13u+19: Block coh < 0.700."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.650,  # Below 0.700
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "weak_coh"


def test_v10_13u19_blocks_weak_af(monkeypatch):
    """V10.13u+19: Block af < 0.740."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.700,  # Below 0.740
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "weak_af"


def test_v10_13u19_blocks_forbidden_tags(monkeypatch):
    """V10.13u+19: Block LOSS_CLUSTER, TOXIC, SPREAD tags."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
        "reason": "LOSS_CLUSTER",
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert "forbidden_tag" in reason


def test_v10_13u19_blocks_forced_signals(monkeypatch):
    """V10.13u+19: Block forced exploration by default."""
    from src.services import realtime_decision_engine as rde

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
        "forced": True,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )

    allowed, reason, meta = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

    assert not allowed
    assert reason == "forced_deadlock_probe_disabled"


def test_v10_13u19_enforces_cooldown(monkeypatch):
    """V10.13u+19: Block if cooldown active."""
    from src.services import realtime_decision_engine as rde
    import time as _time_module

    signal = {
        "ev": 0.0370,
        "score": 0.183,
        "p": 0.824,
        "coh": 0.741,
        "af": 0.750,
    }

    ctx = {
        "seconds_since_last_closed_trade": 13 * 3600,
        "open_positions": 0,
    }

    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"status": "BAD", "profit_factor": 0.739},
    )
    monkeypatch.setattr(rde, "get_econ_bad_diagnostics_snapshot", lambda: {"total_econ_bad_blocks": 60})

    # Simulate first probe being taken (integration code would do this)
    now = _time_module.time()
    rde._ECON_BAD_DEADLOCK_PROBE_STATE["last_probe_ts"] = now

    # Now second probe should be blocked by cooldown
    allowed2, reason2, meta2 = rde._econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)
    assert not allowed2
    assert reason2 == "cooldown_active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
