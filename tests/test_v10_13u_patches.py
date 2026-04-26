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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
