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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
