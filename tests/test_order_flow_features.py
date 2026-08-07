"""P0.9 (Evidence-First Strategy Expansion v2, §11, §22.1 'Features') tests."""
import pytest

from src.services import order_flow_features as ofi


# ---------------------------------------------------------------------------
# top_of_book_imbalance (§11.1, §22.1 "Imbalance at balanced book / positive
# / negative")
# ---------------------------------------------------------------------------

def test_imbalance_balanced_book_is_zero():
    assert ofi.top_of_book_imbalance(100.0, 100.0) == 0.0


def test_imbalance_bid_dominant_is_positive():
    v = ofi.top_of_book_imbalance(150.0, 50.0)
    assert v == pytest.approx(0.5)


def test_imbalance_ask_dominant_is_negative():
    v = ofi.top_of_book_imbalance(50.0, 150.0)
    assert v == pytest.approx(-0.5)


def test_imbalance_zero_liquidity_returns_none_not_zero():
    """§11.1: 'If denominator is too small, mark invalid' -- must be
    distinguishable from a genuine balanced-book zero."""
    assert ofi.top_of_book_imbalance(0.0, 0.0) is None


def test_imbalance_rejects_negative_quantities():
    with pytest.raises(ValueError):
        ofi.top_of_book_imbalance(-1.0, 10.0)


# ---------------------------------------------------------------------------
# microprice / microprice_offset_bps (§11.2, §22.1 "Microprice at equal
# quantities / bid dominance / ask dominance")
# ---------------------------------------------------------------------------

def test_microprice_equal_quantities_equals_midprice():
    mp = ofi.microprice(bid_price=100.0, ask_price=100.10, bid_qty=50.0, ask_qty=50.0)
    assert mp == pytest.approx(100.05)


def test_microprice_bid_dominant_shifts_toward_ask():
    """More bid quantity -> price pressure toward the ask (more buyers
    waiting) -- formula: microprice = (ask*bid_qty + bid*ask_qty) / total."""
    mp = ofi.microprice(bid_price=100.0, ask_price=100.10, bid_qty=90.0, ask_qty=10.0)
    mid = 100.05
    assert mp > mid


def test_microprice_ask_dominant_shifts_toward_bid():
    mp = ofi.microprice(bid_price=100.0, ask_price=100.10, bid_qty=10.0, ask_qty=90.0)
    mid = 100.05
    assert mp < mid


def test_microprice_offset_bps_zero_at_equal_quantities():
    off = ofi.microprice_offset_bps(bid_price=100.0, ask_price=100.10, bid_qty=50.0, ask_qty=50.0)
    assert off == pytest.approx(0.0, abs=1e-9)


def test_microprice_offset_bps_positive_for_bid_dominance():
    off = ofi.microprice_offset_bps(bid_price=100.0, ask_price=100.10, bid_qty=90.0, ask_qty=10.0)
    assert off > 0


def test_microprice_rejects_crossed_book():
    with pytest.raises(ValueError):
        ofi.microprice(bid_price=100.10, ask_price=100.0, bid_qty=1.0, ask_qty=1.0)


def test_microprice_falls_back_to_mid_at_zero_liquidity():
    mp = ofi.microprice(bid_price=100.0, ask_price=100.10, bid_qty=0.0, ask_qty=0.0)
    assert mp == pytest.approx(100.05)


# ---------------------------------------------------------------------------
# TradeEvent sign convention (§8.2, reused)
# ---------------------------------------------------------------------------

def test_trade_event_buyer_is_maker_false_is_positive_signed_qty():
    e = ofi.TradeEvent(event_time_ms=1, price=100.0, quantity=2.0, buyer_is_maker=False)
    assert e.signed_quantity == 2.0
    assert e.signed_notional == 200.0


def test_trade_event_buyer_is_maker_true_is_negative_signed_qty():
    e = ofi.TradeEvent(event_time_ms=1, price=100.0, quantity=2.0, buyer_is_maker=True)
    assert e.signed_quantity == -2.0
    assert e.signed_notional == -200.0


# ---------------------------------------------------------------------------
# RollingTradeWindow -- §22.1 "Signed delta windows / Window expiration",
# §8.4 bounded structures
# ---------------------------------------------------------------------------

def test_rolling_window_empty_stats():
    w = ofi.RollingTradeWindow(window_seconds=10)
    s = w.stats(now_ms=1_000_000)
    assert s.trade_count == 0
    assert s.signed_notional_delta == 0.0
    assert s.aggressor_buy_ratio is None


def test_rolling_window_aggregates_signed_delta():
    w = ofi.RollingTradeWindow(window_seconds=10)
    w.add(ofi.TradeEvent(event_time_ms=1_000_000, price=100.0, quantity=1.0, buyer_is_maker=False))
    w.add(ofi.TradeEvent(event_time_ms=1_000_100, price=100.0, quantity=2.0, buyer_is_maker=True))
    s = w.stats(now_ms=1_000_200)
    assert s.trade_count == 2
    assert s.signed_notional_delta == pytest.approx(100.0 - 200.0)
    assert s.buy_aggressor_notional == pytest.approx(100.0)
    assert s.sell_aggressor_notional == pytest.approx(200.0)


def test_rolling_window_expires_old_events():
    """§22.1 'Window expiration' -- events older than window_seconds must
    not be counted."""
    w = ofi.RollingTradeWindow(window_seconds=1)  # 1 second
    w.add(ofi.TradeEvent(event_time_ms=1_000_000, price=100.0, quantity=1.0, buyer_is_maker=False))
    s_fresh = w.stats(now_ms=1_000_500)  # 0.5s later, still in window
    assert s_fresh.trade_count == 1
    s_expired = w.stats(now_ms=1_002_000)  # 2s later, expired
    assert s_expired.trade_count == 0


def test_rolling_window_rejects_non_positive_window():
    with pytest.raises(ValueError):
        ofi.RollingTradeWindow(window_seconds=0)


def test_rolling_window_large_trade_signed_delta():
    w = ofi.RollingTradeWindow(window_seconds=10)
    for _ in range(5):
        w.add(ofi.TradeEvent(event_time_ms=1_000_000, price=100.0, quantity=1.0, buyer_is_maker=False))
    w.add(ofi.TradeEvent(event_time_ms=1_000_000, price=100.0, quantity=100.0, buyer_is_maker=True))  # large sell
    s = w.stats(now_ms=1_000_001)
    assert s.large_trade_signed_delta < 0  # the large sell dominates


# ---------------------------------------------------------------------------
# persistence_fraction (§11.4)
# ---------------------------------------------------------------------------

def _flow_stats(signed_delta, trade_count=5):
    return ofi.FlowWindowStats(
        window_seconds=1, signed_notional_delta=signed_delta, absolute_notional=abs(signed_delta),
        buy_aggressor_notional=max(0, signed_delta), sell_aggressor_notional=max(0, -signed_delta),
        aggressor_buy_ratio=None, trade_count=trade_count, average_trade_size=1.0,
        large_trade_signed_delta=0.0,
    )


def test_persistence_all_bullish_subwindows():
    windows = [_flow_stats(10), _flow_stats(20), _flow_stats(5)]
    assert ofi.persistence_fraction(windows, bullish=True) == 1.0


def test_persistence_mixed_subwindows():
    windows = [_flow_stats(10), _flow_stats(-20), _flow_stats(5)]
    assert ofi.persistence_fraction(windows, bullish=True) == pytest.approx(2 / 3)


def test_persistence_empty_windows_is_zero():
    assert ofi.persistence_fraction([], bullish=True) == 0.0


def test_persistence_ignores_empty_trade_count_subwindows():
    windows = [_flow_stats(10, trade_count=0), _flow_stats(10, trade_count=5)]
    assert ofi.persistence_fraction(windows, bullish=True) == 1.0  # only the non-empty one counted


# ---------------------------------------------------------------------------
# evaluate_flow_for_side -- §11.5 conflict/confirmation, §11.8 reason codes
# ---------------------------------------------------------------------------

def _bullish_short_window():
    """large_trade_signed_delta=0.0 deliberately -- this fixture exercises
    the general confirm/conflict path in isolation from the dedicated
    large-trade-conflict path (see test_flow_large_trade_conflict_overrides_confirmation,
    which has its own fixture with a nonzero large-trade delta)."""
    return ofi.FlowWindowStats(1, 500.0, 500.0, 500.0, 0.0, 1.0, 10, 50.0, 0.0)


def _bearish_short_window():
    return ofi.FlowWindowStats(1, -500.0, 500.0, 0.0, 500.0, 0.0, 10, 50.0, 0.0)


def _neutral_short_window(n=10):
    return ofi.FlowWindowStats(1, 0.0, 0.0, 0.0, 0.0, None, n, 0.0, 0.0)


def test_flow_confirm_bullish_for_long():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_CONFIRM_BULLISH


def test_flow_confirm_bearish_for_short():
    ev = ofi.evaluate_flow_for_side(
        side="SELL", best_bid=100.0, best_ask=100.05, bid_qty=10.0, ask_qty=90.0,
        book_age_ms=100, short_window_stats=_bearish_short_window(),
        medium_window_stats=_bearish_short_window(),
        persistence_windows=[_bearish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_CONFIRM_BEARISH


def test_flow_conflict_long_when_flow_is_bearish():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=10.0, ask_qty=90.0,
        book_age_ms=100, short_window_stats=_bearish_short_window(),
        medium_window_stats=_bearish_short_window(),
        persistence_windows=[_bearish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_CONFLICT_LONG


def test_flow_conflict_short_when_flow_is_bullish():
    ev = ofi.evaluate_flow_for_side(
        side="SELL", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_CONFLICT_SHORT


def test_flow_neutral_when_ambiguous():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=50.0, ask_qty=50.0,
        book_age_ms=100, short_window_stats=_neutral_short_window(),
        medium_window_stats=_neutral_short_window(),
        persistence_windows=[_neutral_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_NEUTRAL


def test_flow_stale_book_rejected():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=99_999, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()], spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_STALE


def test_flow_spread_expansion_rejected():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()], spread_bps=999.0,
    )
    assert ev.reason_code == ofi.FLOW_SPREAD_EXPANSION


def test_flow_insufficient_trades():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_neutral_short_window(n=1),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()], spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_INSUFFICIENT_TRADES


def test_flow_book_invalid_crossed():
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.10, best_ask=100.0, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()], spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_BOOK_INVALID


def test_flow_large_trade_conflict_overrides_confirmation():
    """A single large sell dominating the short window must flag conflict
    even if other components look bullish."""
    conflicting_window = ofi.FlowWindowStats(
        1, 500.0, 1000.0, 500.0, 0.0, 1.0, 10, 50.0, large_trade_signed_delta=-800.0,
    )
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=conflicting_window,
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.reason_code == ofi.FLOW_LARGE_TRADE_CONFLICT


def test_evaluate_flow_rejects_unknown_side():
    with pytest.raises(ValueError):
        ofi.evaluate_flow_for_side(
            side="SIDEWAYS", best_bid=100.0, best_ask=100.05, bid_qty=1.0, ask_qty=1.0,
            book_age_ms=100, short_window_stats=_neutral_short_window(),
            medium_window_stats=_neutral_short_window(), persistence_windows=[], spread_bps=1.0,
        )


def test_evaluate_flow_always_returns_raw_values_not_only_verdict():
    """§11.6: 'Do not make the evidence schema store only pass/fail.'"""
    ev = ofi.evaluate_flow_for_side(
        side="BUY", best_bid=100.0, best_ask=100.05, bid_qty=90.0, ask_qty=10.0,
        book_age_ms=100, short_window_stats=_bullish_short_window(),
        medium_window_stats=_bullish_short_window(),
        persistence_windows=[_bullish_short_window()] * 3, spread_bps=5.0,
    )
    assert ev.microprice_offset_bps is not None
    assert ev.top_of_book_imbalance is not None
    assert ev.signed_notional_delta_short is not None


# ---------------------------------------------------------------------------
# shadow_counterfactual (§11.7 Pattern A)
# ---------------------------------------------------------------------------

def test_shadow_counterfactual_true_when_confirmed():
    ev = ofi.FlowEvaluation(ofi.FLOW_CONFIRM_BULLISH, 1.0, 0.5, 100.0, 100.0, 1.0, 1.0, False)
    assert ofi.shadow_counterfactual(ev, side="BUY") is True


def test_shadow_counterfactual_false_when_neutral():
    ev = ofi.FlowEvaluation(ofi.FLOW_NEUTRAL, 0.0, 0.0, 0.0, 0.0, 0.0, None, False)
    assert ofi.shadow_counterfactual(ev, side="BUY") is False


def test_shadow_counterfactual_false_when_conflicting():
    ev = ofi.FlowEvaluation(ofi.FLOW_CONFLICT_LONG, -1.0, -0.5, -100.0, -100.0, 0.0, 0.0, False)
    assert ofi.shadow_counterfactual(ev, side="BUY") is False


def test_shadow_counterfactual_side_specific():
    """A bullish confirmation must not count as a shadow-confirm for a short
    side, and vice versa."""
    bullish_ev = ofi.FlowEvaluation(ofi.FLOW_CONFIRM_BULLISH, 1.0, 0.5, 100.0, 100.0, 1.0, 1.0, False)
    assert ofi.shadow_counterfactual(bullish_ev, side="SELL") is False
