"""Tests for candle_cache_v1.CandleCache."""
import pytest

from src.services.candle_cache_v1 import CandleCache


def _make_candles(n, start_time_ms=1_700_000_000_000):
    return [
        {"open_time": start_time_ms + i * 60_000, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0 + i, "volume": 10.0}
        for i in range(n)
    ]


def test_rejects_non_positive_refresh_seconds():
    with pytest.raises(ValueError):
        CandleCache(refresh_seconds=0)


def test_rejects_non_positive_max_candles():
    with pytest.raises(ValueError):
        CandleCache(max_candles=0)


def test_fetches_on_first_call():
    calls = []

    def fetch(symbol, interval):
        calls.append((symbol, interval))
        return _make_candles(5)

    cache = CandleCache(fetch_fn=fetch)
    result = cache.get_candles("ETHUSDT")
    assert len(result) == 5
    assert calls == [("ETHUSDT", "1m")]


def test_does_not_refetch_within_refresh_window():
    calls = []
    t = [1000.0]

    def fetch(symbol, interval):
        calls.append(1)
        return _make_candles(5)

    cache = CandleCache(fetch_fn=fetch, refresh_seconds=60.0, now_fn=lambda: t[0])
    cache.get_candles("ETHUSDT")
    t[0] += 10.0  # within the 60s window
    cache.get_candles("ETHUSDT")
    assert len(calls) == 1


def test_refetches_after_refresh_window_elapses():
    calls = []
    t = [1000.0]

    def fetch(symbol, interval):
        calls.append(1)
        return _make_candles(5)

    cache = CandleCache(fetch_fn=fetch, refresh_seconds=60.0, now_fn=lambda: t[0])
    cache.get_candles("ETHUSDT")
    t[0] += 61.0
    cache.get_candles("ETHUSDT")
    assert len(calls) == 2


def test_force_refresh_bypasses_the_window():
    calls = []

    def fetch(symbol, interval):
        calls.append(1)
        return _make_candles(5)

    cache = CandleCache(fetch_fn=fetch, refresh_seconds=60.0)
    cache.get_candles("ETHUSDT")
    cache.get_candles("ETHUSDT", force_refresh=True)
    assert len(calls) == 2


def test_bounds_cache_to_max_candles():
    def fetch(symbol, interval):
        return _make_candles(500)

    cache = CandleCache(fetch_fn=fetch, max_candles=100)
    result = cache.get_candles("ETHUSDT")
    assert len(result) == 100
    # Bounded to the MOST RECENT candles, not the oldest.
    assert result[-1]["close"] == _make_candles(500)[-1]["close"]


def test_serves_stale_data_on_fetch_failure_rather_than_raising():
    state = {"fail": False}

    def fetch(symbol, interval):
        if state["fail"]:
            raise RuntimeError("network blip")
        return _make_candles(5)

    cache = CandleCache(fetch_fn=fetch, refresh_seconds=1.0)
    first = cache.get_candles("ETHUSDT")
    assert len(first) == 5
    state["fail"] = True
    second = cache.get_candles("ETHUSDT", force_refresh=True)
    assert second == first  # stale but served, not empty/raised


def test_returns_empty_list_when_never_successfully_fetched():
    def fetch(symbol, interval):
        raise RuntimeError("always fails")

    cache = CandleCache(fetch_fn=fetch)
    result = cache.get_candles("ETHUSDT")
    assert result == []


def test_get_candles_never_raises_even_on_persistent_failure():
    def fetch(symbol, interval):
        raise RuntimeError("boom")

    cache = CandleCache(fetch_fn=fetch)
    cache.get_candles("ETHUSDT")  # must not raise
    cache.get_candles("ETHUSDT", force_refresh=True)  # must not raise


def test_symbols_are_cached_independently():
    calls = []

    def fetch(symbol, interval):
        calls.append(symbol)
        return _make_candles(3)

    cache = CandleCache(fetch_fn=fetch)
    cache.get_candles("ETHUSDT")
    cache.get_candles("ADAUSDT")
    assert calls == ["ETHUSDT", "ADAUSDT"]


def test_last_success_age_s_none_before_first_fetch():
    cache = CandleCache(fetch_fn=lambda s, i: _make_candles(3))
    assert cache.last_success_age_s("ETHUSDT") is None


def test_last_success_age_s_after_fetch():
    t = [1000.0]
    cache = CandleCache(fetch_fn=lambda s, i: _make_candles(3), now_fn=lambda: t[0])
    cache.get_candles("ETHUSDT")
    t[0] += 42.0
    assert cache.last_success_age_s("ETHUSDT") == pytest.approx(42.0)


def test_last_success_age_s_not_updated_by_a_failed_refresh():
    state = {"fail": False}
    t = [1000.0]

    def fetch(symbol, interval):
        if state["fail"]:
            raise RuntimeError("blip")
        return _make_candles(3)

    cache = CandleCache(fetch_fn=fetch, refresh_seconds=1.0, now_fn=lambda: t[0])
    cache.get_candles("ETHUSDT")
    t[0] += 10.0
    state["fail"] = True
    cache.get_candles("ETHUSDT", force_refresh=True)
    assert cache.last_success_age_s("ETHUSDT") == pytest.approx(10.0)


def test_default_cache_singleton_returns_same_instance():
    from src.services.candle_cache_v1 import get_default_cache
    a = get_default_cache()
    b = get_default_cache()
    assert a is b


def test_default_fetch_requests_max_candles_as_limit(monkeypatch):
    """Regression guard for the CANDLE_LIMIT=100 vs strategy MIN_CANDLES=200
    mismatch discovered in this session's live smoke test -- the default
    (no fetch_fn injected) fetch path must request `max_candles`, not the
    shared config.CANDLE_LIMIT default."""
    from src.services import binance_client

    seen = {}

    def _fake_fetch_candles(symbol, interval, limit=binance_client.CANDLE_LIMIT):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(binance_client, "fetch_candles", _fake_fetch_candles)
    cache = CandleCache(max_candles=260)  # no fetch_fn injected -> uses the real default path
    cache.get_candles("ETHUSDT")
    assert seen["limit"] == 260
