"""Audit PR2 (P2, 2026-07-16) — startup guard for double-flip env combinations.

Verifies the truth table in trading_env_guard: a one-sided PAPER_FADE_SIDES
combined with any active signal-inversion flag is rejected fail-closed, while
each flag alone (the existing documented contracts) is preserved.
"""
import pytest

from src.services.trading_env_guard import (
    INVALID_COMBINATION_MARKER,
    InvalidTradingEnvError,
    check_trading_env,
    validate_trading_env,
)

# ── Valid: default, symmetric flips, one-sided fade alone, inversion alone ─────
VALID = [
    {},
    {"PAPER_FADE_SIDES": "both"},
    {"PAPER_FADE_SIDES": "both", "SIGNAL_INVERT_TEST": "1"},
    {"PAPER_FADE_SIDES": "both", "PAPER_INVERT_SIGNAL": "true"},
    {"PAPER_FADE_SIDES": "buy_only"},
    {"PAPER_FADE_SIDES": "sell_only"},
    {"SIGNAL_INVERT_TEST": "1"},                 # invert test without buy_only — kept
    {"PAPER_INVERT_SIGNAL": "true"},
    {"PAPER_FADE_SIDES": "buy_only", "SIGNAL_INVERT_TEST": "0"},
    {"PAPER_FADE_SIDES": "buy_only", "PAPER_INVERT_SIGNAL": "false"},
]

# ── Invalid: one-sided fade + active inversion = double-flip footgun ───────────
INVALID = [
    {"PAPER_FADE_SIDES": "buy_only", "SIGNAL_INVERT_TEST": "1"},
    {"PAPER_FADE_SIDES": "sell_only", "SIGNAL_INVERT_TEST": "1"},
    {"PAPER_FADE_SIDES": "buy_only", "PAPER_INVERT_SIGNAL": "true"},
    {"PAPER_FADE_SIDES": "sell_only", "PAPER_INVERT_SIGNAL": "true"},
    {"PAPER_FADE_SIDES": "BUY_ONLY", "SIGNAL_INVERT_TEST": "1"},   # case-insensitive
    {"PAPER_FADE_SIDES": "buy_only", "SIGNAL_INVERT_TEST": "yes"}, # truthy variants
    {"PAPER_FADE_SIDES": "buy_only", "PAPER_INVERT_SIGNAL": "ON"},
]


@pytest.mark.parametrize("env", VALID)
def test_valid_combinations_pass(env):
    assert check_trading_env(env) == []
    validate_trading_env(env)  # must not raise


@pytest.mark.parametrize("env", INVALID)
def test_invalid_combinations_rejected(env):
    assert check_trading_env(env), "expected a violation for double-flip combo"
    with pytest.raises(InvalidTradingEnvError):
        validate_trading_env(env)


def test_error_message_carries_marker():
    env = {"PAPER_FADE_SIDES": "buy_only", "SIGNAL_INVERT_TEST": "1"}
    with pytest.raises(InvalidTradingEnvError) as exc:
        validate_trading_env(env)
    assert INVALID_COMBINATION_MARKER in str(exc.value)


def test_guard_never_mutates_env_or_auto_flips():
    """Fail-closed only — never silently pick/flip a side, never enable real flags."""
    env = {
        "PAPER_FADE_SIDES": "buy_only",
        "SIGNAL_INVERT_TEST": "1",
        "TRADING_MODE": "paper_live",
        "ENABLE_REAL_ORDERS": "0",
        "LIVE_TRADING_CONFIRMED": "0",
    }
    snapshot = dict(env)
    with pytest.raises(InvalidTradingEnvError):
        validate_trading_env(env)
    assert env == snapshot, "guard must not mutate the environment"


def test_real_safety_flags_stay_false_on_valid_path():
    env = {"PAPER_FADE_SIDES": "buy_only",
           "TRADING_MODE": "paper_live",
           "ENABLE_REAL_ORDERS": "0",
           "LIVE_TRADING_CONFIRMED": "0"}
    validate_trading_env(env)  # valid — no raise
    assert env["ENABLE_REAL_ORDERS"] == "0"
    assert env["LIVE_TRADING_CONFIRMED"] == "0"
    assert env["TRADING_MODE"] == "paper_live"
