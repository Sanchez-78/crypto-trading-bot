"""§20 (Evidence-First Strategy Expansion v2) — fail-closed startup
configuration validation for the P0.8+ pipeline.

Mirrors test_runtime_mode_startup_assertion.py's discipline exactly: the
assertion must be a true no-op under every currently-valid configuration,
and must raise before the event loop starts for each documented invalid
combination.
"""
import pytest

from src.services import p0_8_plus_config_validation as cv


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (
        "PAPER_FEE_PCT", "PAPER_SLIPPAGE_PCT",
        "PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS",
        "PAPER_P0_8_PLUS_MAX_DATA_AGE_MS",
        "PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_default_env_never_raises():
    cv.assert_p0_8_plus_config_valid()  # must not raise


def test_current_production_values_never_raise(monkeypatch):
    """The exact live-production values (PAPER_FEE_PCT=0.0004,
    PAPER_SLIPPAGE_PCT=0.0, confirmed via SSH on the server,
    _workspace/33) must not raise."""
    monkeypatch.setenv("PAPER_FEE_PCT", "0.0004")
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "0.0")
    cv.assert_p0_8_plus_config_valid()  # must not raise


def test_negative_fee_pct_raises(monkeypatch):
    monkeypatch.setenv("PAPER_FEE_PCT", "-0.001")
    with pytest.raises(cv.P0_8_PlusConfigError, match="PAPER_FEE_PCT"):
        cv.assert_p0_8_plus_config_valid()


def test_negative_slippage_pct_raises(monkeypatch):
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "-0.0001")
    with pytest.raises(cv.P0_8_PlusConfigError, match="PAPER_SLIPPAGE_PCT"):
        cv.assert_p0_8_plus_config_valid()


def test_zero_fee_and_slippage_do_not_raise(monkeypatch):
    """Zero is a valid (if unrealistic) value -- only strictly negative
    values are rejected."""
    monkeypatch.setenv("PAPER_FEE_PCT", "0.0")
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "0.0")
    cv.assert_p0_8_plus_config_valid()  # must not raise


def test_negative_synthetic_spread_raises(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS", "-1.0")
    with pytest.raises(cv.P0_8_PlusConfigError, match="SYNTHETIC_SPREAD_BPS"):
        cv.assert_p0_8_plus_config_valid()


def test_zero_max_data_age_ms_raises(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_MAX_DATA_AGE_MS", "0")
    with pytest.raises(cv.P0_8_PlusConfigError, match="MAX_DATA_AGE_MS"):
        cv.assert_p0_8_plus_config_valid()


def test_negative_max_data_age_ms_raises(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_MAX_DATA_AGE_MS", "-100")
    with pytest.raises(cv.P0_8_PlusConfigError, match="MAX_DATA_AGE_MS"):
        cv.assert_p0_8_plus_config_valid()


def test_zero_quote_max_age_s_raises(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S", "0")
    with pytest.raises(cv.P0_8_PlusConfigError, match="QUOTE_MAX_AGE_S"):
        cv.assert_p0_8_plus_config_valid()


def test_non_numeric_value_raises_with_clear_message(monkeypatch):
    monkeypatch.setenv("PAPER_FEE_PCT", "not_a_number")
    with pytest.raises(cv.P0_8_PlusConfigError, match="not a valid number"):
        cv.assert_p0_8_plus_config_valid()


def test_error_type_is_a_runtime_error_subclass():
    """P0_8_PlusConfigError must be catchable as a plain RuntimeError too
    (matches the pattern of assert_real_orders_prohibited(), which raises
    a bare RuntimeError) so generic startup-failure handling still works."""
    assert issubclass(cv.P0_8_PlusConfigError, RuntimeError)


def test_called_from_bot2_main_outside_the_swallowing_try_except():
    """Static check, same discipline as
    test_runtime_mode_startup_assertion.py's equivalent test: the call
    site must not be inside the try/except that only logs a warning for
    log_runtime_config() -- otherwise an invalid P0.8+ config would be
    silently downgraded to a warning instead of halting boot."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "bot2" / "main.py").read_text(encoding="utf-8")
    assert "assert_p0_8_plus_config_valid" in src

    anchor = "V10.13u+20: Log runtime mode configuration"
    idx = src.index(anchor)
    window = src[idx: idx + 1600]
    try_idx = window.index("try:")
    except_idx = window.index("except")
    call_idx = window.index("assert_p0_8_plus_config_valid()")
    assert call_idx > except_idx > try_idx
    call_line = window[:call_idx].rsplit("\n", 1)[-1]
    assert call_line == "    ", (
        f"assert_p0_8_plus_config_valid() call is indented as if inside the "
        f"try/except (indent={call_line!r}); it must be a sibling statement "
        f"so an exception there is never swallowed"
    )


def test_called_after_real_orders_assertion_not_before():
    """The real-order prohibition (P0.7) must be checked first -- a
    P0.8+-specific config error should never mask a real-order
    misconfiguration by raising before that more critical check runs."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "bot2" / "main.py").read_text(encoding="utf-8")
    real_orders_idx = src.index("assert_real_orders_prohibited()")
    p0_8_plus_idx = src.index("assert_p0_8_plus_config_valid()")
    assert real_orders_idx < p0_8_plus_idx
