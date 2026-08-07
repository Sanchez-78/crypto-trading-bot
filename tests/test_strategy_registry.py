"""P0.7/central-contract tests -- StrategyRegistry (§16.3)."""
import pytest

from src.services.strategy_registry import StrategyRegistration, StrategyRegistry, get_default_registry


def _reg(**overrides):
    kwargs = dict(
        strategy_id="trend_cost_aware",
        current_version="1",
        enabled=True,
        evidence_only=True,
        allowed_symbols=frozenset({"ETHUSDT"}),
        allowed_regimes=frozenset({"BULL_TREND"}),
        allowed_sides=frozenset({"BUY"}),
        exit_profile="dynamic_trend_exit_v1",
        minimum_warmup_seconds=60,
        required_feature_schema_version="v1",
    )
    kwargs.update(overrides)
    return StrategyRegistration(**kwargs)


def test_register_and_get():
    reg = StrategyRegistry()
    reg.register(_reg())
    got = reg.get("trend_cost_aware")
    assert got is not None
    assert got.current_version == "1"


def test_unknown_strategy_returns_none():
    reg = StrategyRegistry()
    assert reg.get("does_not_exist") is None
    assert reg.is_registered("does_not_exist") is False


def test_reregister_same_version_is_allowed_idempotent():
    reg = StrategyRegistry()
    reg.register(_reg())
    reg.register(_reg())  # same version -- must not raise
    assert reg.get("trend_cost_aware").current_version == "1"


def test_reregister_different_version_without_unregister_raises():
    """§23.7 cohort-version discipline: silently swapping a registered
    strategy to a new version must not be possible by accident."""
    reg = StrategyRegistry()
    reg.register(_reg(current_version="1"))
    with pytest.raises(ValueError):
        reg.register(_reg(current_version="2"))


def test_unregister_then_register_new_version_succeeds():
    reg = StrategyRegistry()
    reg.register(_reg(current_version="1"))
    reg.unregister("trend_cost_aware")
    reg.register(_reg(current_version="2"))
    assert reg.get("trend_cost_aware").current_version == "2"


def test_registration_rejects_empty_strategy_id():
    with pytest.raises(ValueError):
        _reg(strategy_id="")


def test_registration_rejects_unknown_side():
    with pytest.raises(ValueError):
        _reg(allowed_sides=frozenset({"SIDEWAYS"}))


def test_registration_rejects_negative_warmup():
    with pytest.raises(ValueError):
        _reg(minimum_warmup_seconds=-1)


def test_registration_is_frozen():
    r = _reg()
    with pytest.raises(Exception):
        r.enabled = False  # type: ignore[misc]


def test_all_strategy_ids():
    reg = StrategyRegistry()
    reg.register(_reg(strategy_id="a"))
    reg.register(_reg(strategy_id="b"))
    assert reg.all_strategy_ids() == frozenset({"a", "b"})


def test_default_registry_is_a_singleton():
    a = get_default_registry()
    b = get_default_registry()
    assert a is b
