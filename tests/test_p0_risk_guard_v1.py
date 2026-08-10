"""§17 tests -- p0_risk_guard_v1.evaluate_risk_guard().

All dependencies are injected (live_trading_allowed_fn, is_daily_dd_safe_fn,
firebase_health_fn, open_positions) -- these tests never touch real
runtime_mode/risk_engine/firebase_client/paper_trade_executor global state.
"""
import pytest

from src.services.p0_risk_guard_v1 import RiskGuardResult, evaluate_risk_guard


def _kwargs(**overrides):
    kwargs = dict(
        symbol="ETHUSDT",
        side="BUY",
        open_positions=[],
        live_trading_allowed_fn=lambda: False,
        is_daily_dd_safe_fn=lambda: True,
        firebase_health_fn=lambda: {"available": True},
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_all_checks_pass_allows_entry():
    result = evaluate_risk_guard(**_kwargs())
    assert result.allowed is True
    assert result.reason == ""
    assert result.checks == {
        "paper_only_state": True, "daily_risk": True,
        "quota_reserve": True, "position_conflict": True,
    }


# ---------------------------------------------------------------------------
# §17.1 paper-only state
# ---------------------------------------------------------------------------

def test_denies_when_live_trading_allowed_is_true():
    """Must be at least as conservative as the existing 5-layer real-order
    guard -- if live trading is somehow allowed, the new pipeline refuses
    everything rather than assuming it's fine."""
    result = evaluate_risk_guard(**_kwargs(live_trading_allowed_fn=lambda: True))
    assert result.allowed is False
    assert "real trading is allowed" in result.reason
    assert result.checks["paper_only_state"] is False


def test_paper_only_check_exception_fails_closed():
    def _raise():
        raise RuntimeError("env read failed")
    result = evaluate_risk_guard(**_kwargs(live_trading_allowed_fn=_raise))
    assert result.allowed is False
    assert "raised" in result.reason


def test_paper_only_state_checked_before_other_checks():
    """Short-circuit ordering: a paper-only failure must not proceed to
    evaluate daily risk/quota/position checks (cheap-path + clearest
    single-reason diagnostic)."""
    def _boom():
        raise AssertionError("must not be called")
    result = evaluate_risk_guard(**_kwargs(
        live_trading_allowed_fn=lambda: True,
        is_daily_dd_safe_fn=_boom,
        firebase_health_fn=_boom,
    ))
    assert result.allowed is False
    assert result.checks.get("daily_risk") is None


# ---------------------------------------------------------------------------
# §17.2 daily risk
# ---------------------------------------------------------------------------

def test_denies_when_daily_dd_unsafe():
    result = evaluate_risk_guard(**_kwargs(is_daily_dd_safe_fn=lambda: False))
    assert result.allowed is False
    assert "daily drawdown" in result.reason
    assert result.checks["daily_risk"] is False


def test_daily_dd_check_exception_fails_closed():
    def _raise():
        raise RuntimeError("risk_engine unavailable")
    result = evaluate_risk_guard(**_kwargs(is_daily_dd_safe_fn=_raise))
    assert result.allowed is False


# ---------------------------------------------------------------------------
# §17.1 quota reserve
# ---------------------------------------------------------------------------

def test_denies_when_firebase_degraded():
    result = evaluate_risk_guard(**_kwargs(
        firebase_health_fn=lambda: {"available": False, "reason": "quota_429"},
    ))
    assert result.allowed is False
    assert "quota_429" in result.reason
    assert result.checks["quota_reserve"] is False


def test_firebase_health_exception_fails_closed():
    def _raise():
        raise RuntimeError("firebase client not initialized")
    result = evaluate_risk_guard(**_kwargs(firebase_health_fn=_raise))
    assert result.allowed is False


# ---------------------------------------------------------------------------
# §17.1 duplicate / opposite position conflict
# ---------------------------------------------------------------------------

def test_denies_duplicate_same_side_position():
    result = evaluate_risk_guard(**_kwargs(
        open_positions=[{"symbol": "ETHUSDT", "side": "BUY"}],
    ))
    assert result.allowed is False
    assert "duplicate position" in result.reason


def test_denies_opposite_side_position():
    result = evaluate_risk_guard(**_kwargs(
        side="BUY", open_positions=[{"symbol": "ETHUSDT", "side": "SELL"}],
    ))
    assert result.allowed is False
    assert "opposite position" in result.reason


def test_allows_when_open_position_is_a_different_symbol():
    result = evaluate_risk_guard(**_kwargs(
        symbol="ETHUSDT", open_positions=[{"symbol": "BTCUSDT", "side": "BUY"}],
    ))
    assert result.allowed is True


def test_handles_legacy_action_field_and_long_short_aliases():
    """Some position dicts in this codebase use 'action' instead of 'side',
    and LONG/SHORT instead of BUY/SELL (see paper_trade_executor.py's own
    normalization helpers) -- the guard must not silently ignore a real
    conflict just because of field-name/value variance."""
    result = evaluate_risk_guard(**_kwargs(
        symbol="ETHUSDT", side="BUY",
        open_positions=[{"symbol": "ETHUSDT", "action": "LONG"}],
    ))
    assert result.allowed is False
    assert "duplicate position" in result.reason


# ---------------------------------------------------------------------------
# open_positions sourcing (dict vs list) and lazy accessor
# ---------------------------------------------------------------------------

def test_open_positions_none_uses_injected_accessor_dict_shape():
    """paper_trade_executor.get_open_positions() returns a dict keyed by
    position_id -- the guard must accept that shape when open_positions is
    not explicitly passed."""
    def _accessor():
        return {"pos-1": {"symbol": "ETHUSDT", "side": "BUY"}}

    result = evaluate_risk_guard(
        symbol="ETHUSDT", side="BUY", open_positions=None,
        live_trading_allowed_fn=lambda: False,
        is_daily_dd_safe_fn=lambda: True,
        firebase_health_fn=lambda: {"available": True},
        get_open_positions_fn=_accessor,
    )
    assert result.allowed is False
    assert "duplicate position" in result.reason


def test_open_positions_accessor_exception_fails_closed():
    def _raise():
        raise RuntimeError("position store unavailable")

    result = evaluate_risk_guard(
        symbol="ETHUSDT", side="BUY", open_positions=None,
        live_trading_allowed_fn=lambda: False,
        is_daily_dd_safe_fn=lambda: True,
        firebase_health_fn=lambda: {"available": True},
        get_open_positions_fn=_raise,
    )
    assert result.allowed is False
    assert "could not read open positions" in result.reason
