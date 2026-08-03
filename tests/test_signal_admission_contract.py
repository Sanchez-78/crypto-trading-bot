from src.services.signal_admission_contract import (
    has_authoritative_rde_take,
    is_explicit_rde_reject,
    is_regime_aligned,
    select_regime_aligned_candidate,
    stamp_rde_outcome,
)


def test_stamp_rde_take_is_authoritative():
    signal = {"symbol": "ETHUSDT"}

    assert stamp_rde_outcome(signal, signal) is signal
    assert signal["rde_accepted"] is True
    assert signal["rde_decision"] == "TAKE"
    assert has_authoritative_rde_take(signal) is True
    assert is_explicit_rde_reject(signal) is False


def test_stamp_rde_reject_is_authoritative():
    signal = {"symbol": "ADAUSDT", "ev": 0.05, "bucket": "A_STRICT_TAKE"}

    stamp_rde_outcome(signal, None)

    assert signal["rde_accepted"] is False
    assert signal["rde_decision"] == "REJECT"
    assert has_authoritative_rde_take(signal) is False
    assert is_explicit_rde_reject(signal) is True


def test_legacy_signal_is_not_misclassified_as_explicit_reject_or_take():
    signal = {"symbol": "SOLUSDT"}

    assert is_explicit_rde_reject(signal) is False
    assert has_authoritative_rde_take(signal) is False


def test_directional_regimes_require_matching_side():
    assert is_regime_aligned("BUY", "BULL_TREND") is True
    assert is_regime_aligned("SELL", "BULL_TREND") is False
    assert is_regime_aligned("SELL", "BEAR_TREND") is True
    assert is_regime_aligned("BUY", "BEAR_TREND") is False


def test_neutral_regimes_allow_both_sides():
    for regime in ("RANGING", "QUIET_RANGE", "HIGH_VOL", "UNKNOWN"):
        assert is_regime_aligned("BUY", regime) is True
        assert is_regime_aligned("SELL", regime) is True


def test_bear_regime_never_falls_back_to_high_scoring_buy():
    selected = select_regime_aligned_candidate(
        regime="BEAR_TREND",
        buy_score=5.0,
        buy_features={"buy": True},
        sell_score=2.0,
        sell_features={"sell": True},
        minimum_score=3.0,
    )

    assert selected == (None, 0.0, {})


def test_directional_regime_uses_aligned_candidate_when_qualified():
    selected = select_regime_aligned_candidate(
        regime="BEAR_TREND",
        buy_score=6.0,
        buy_features={"buy": True},
        sell_score=3.0,
        sell_features={"sell": True},
        minimum_score=3.0,
    )

    assert selected == ("SELL", 3.0, {"sell": True})


def test_neutral_regime_selects_best_qualified_side():
    selected = select_regime_aligned_candidate(
        regime="RANGING",
        buy_score=3.0,
        buy_features={"buy": True},
        sell_score=4.0,
        sell_features={"sell": True},
        minimum_score=3.0,
    )

    assert selected == ("SELL", 4.0, {"sell": True})
