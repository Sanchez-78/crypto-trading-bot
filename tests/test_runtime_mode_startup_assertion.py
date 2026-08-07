"""P0.7 (Evidence-First Strategy Expansion v2, §2.1) — fail-closed startup
assertion for the real-order prohibition.

The five existing real-order guards (runtime_mode.live_trading_allowed(),
execution_engine.check_live_order_guard(), EXECUTION_ENGINE_ENABLED being
unset, absent Binance API keys, paper_trade_executor's import-time
_enforce_paper_safe_mode()) are all guards-at-use. This test file covers the
new guard-at-boot: assert_real_orders_prohibited() must raise before the
event loop starts if any live-trading flag is misconfigured, and must be a
true no-op under every paper-safe configuration.
"""
import pytest

from src.core import runtime_mode as rm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("TRADING_MODE", "ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED",
              "PAPER_EXPLORATION_ENABLED", "REAL_ORDERS_ALLOWED",
              "REAL_TRADING_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_default_env_never_raises():
    """No env vars set (the documented safe default) must not raise."""
    rm.assert_real_orders_prohibited()  # must not raise


def test_current_production_env_never_raises(monkeypatch):
    """The exact live-production env combination confirmed on Hetzner
    2026-08-07 must not raise — this assertion must never fire under the
    program's actual running configuration."""
    monkeypatch.setenv("TRADING_MODE", "paper_train")
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "false")
    monkeypatch.setenv("REAL_ORDERS_ALLOWED", "false")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "false")
    rm.assert_real_orders_prohibited()  # must not raise


def test_enable_real_orders_true_raises(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "true")
    with pytest.raises(RuntimeError, match="REAL trading is prohibited"):
        rm.assert_real_orders_prohibited()


@pytest.mark.parametrize("truthy", ["true", "1", "yes", "TRUE", "Yes"])
def test_enable_real_orders_truthy_variants_raise(monkeypatch, truthy):
    """real_orders_enabled()'s own parser (unchanged by this patch) recognizes
    exactly {"true", "1", "yes"} case-insensitively — notably NOT "on", unlike
    the broader _TRUTHY set used elsewhere in this codebase (e.g.
    shadow_excursion_recorder.py). That is pre-existing, narrower-is-safer
    behavior; this test asserts the actual documented set, not an assumed one."""
    monkeypatch.setenv("ENABLE_REAL_ORDERS", truthy)
    with pytest.raises(RuntimeError):
        rm.assert_real_orders_prohibited()


def test_enable_real_orders_on_is_not_recognized_as_truthy(monkeypatch):
    """Documents a real cross-module inconsistency found while writing this
    test: real_orders_enabled() does NOT treat "on" as truthy (only
    true/1/yes), while shadow_excursion_recorder.py's _TRUTHY set does. Both
    are individually safe (a missed "on" here fails toward paper-mode, not
    toward live orders), so this is recorded as a documented inconsistency,
    not fixed in this phase — expanding real_orders_enabled()'s parser is out
    of P0.7's scope and touches a security-relevant function beyond what this
    phase's diff should risk."""
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "on")
    rm.assert_real_orders_prohibited()  # does not raise -- "on" alone is not enough


def test_trading_mode_live_real_raises(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live_real")
    with pytest.raises(RuntimeError, match="REAL trading is prohibited"):
        rm.assert_real_orders_prohibited()


def test_live_trading_confirmed_true_raises(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "true")
    with pytest.raises(RuntimeError, match="REAL trading is prohibited"):
        rm.assert_real_orders_prohibited()


def test_paper_exploration_alone_does_not_raise(monkeypatch):
    """paper_exploration_enabled() is one of live_trading_allowed()'s four
    flags, but it is a *safety* flag (its presence blocks live trading, per
    the docstring on live_trading_allowed()) — it must never by itself be a
    reason to halt boot. Only the three trading-enablement flags do."""
    monkeypatch.setenv("PAPER_EXPLORATION_ENABLED", "true")
    rm.assert_real_orders_prohibited()  # must not raise


def test_invalid_trading_mode_falls_back_safe(monkeypatch):
    """A typo/invalid TRADING_MODE value must fall back to the safe mode
    (documented behavior of get_trading_mode()) and therefore must not raise."""
    monkeypatch.setenv("TRADING_MODE", "not_a_real_mode_typo")
    rm.assert_real_orders_prohibited()  # must not raise


def test_called_from_bot2_main_outside_the_swallowing_try_except():
    """Static check: the call site in bot2/main.py must not be inside the
    try/except that only logs a warning for log_runtime_config() — otherwise
    a real-order misconfiguration would be silently downgraded to a warning
    instead of halting boot."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "bot2" / "main.py").read_text(encoding="utf-8")
    assert "assert_real_orders_prohibited" in src

    # The call must appear after the try/except block's `except` line, at
    # the same or lesser indentation than the `try:` — i.e. not nested
    # inside it. Locate the specific try/except this was added next to.
    anchor = "V10.13u+20: Log runtime mode configuration"
    idx = src.index(anchor)
    window = src[idx: idx + 1200]
    try_idx = window.index("try:")
    except_idx = window.index("except")
    call_idx = window.index("assert_real_orders_prohibited()")
    # The call must come after the except block's body, not between try/except.
    assert call_idx > except_idx > try_idx
    # And it must be at column 4 (module-function top level for this block),
    # not indented under the try (which is at column 8 in this file).
    call_line = window[:call_idx].rsplit("\n", 1)[-1]
    assert call_line == "    ", (
        f"assert_real_orders_prohibited() call is indented as if inside the "
        f"try/except (indent={call_line!r}); it must be a sibling statement "
        f"so an exception there is never swallowed"
    )
