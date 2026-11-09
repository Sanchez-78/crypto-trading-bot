"""Completed 1m views use fetch-time evidence, never aging a cached partial bar.

All candles, clocks and fetch results are injected fixtures. No REST, database,
runtime state, trading thresholds or strategy outcomes are used by this suite.
"""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.services.candle_cache_v1 import CandleCache


BASE_S = 1_800_000_000  # Exact minute boundary, also representative epoch magnitude.
BASE_MS = BASE_S * 1000
SYMBOL = "ETHUSDT"


def bar(offset_minutes, *, volume=100.0, close=100.0):
    return {"open_time": BASE_MS + offset_minutes * 60_000,
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": close, "volume": volume}


def make_cache(rows, *, now=BASE_S + 30, refresh=600, interval="1m", maximum=260):
    clock = [now]
    fetch = Mock(return_value=rows)
    cache = CandleCache(fetch_fn=fetch, now_fn=lambda: clock[0],
                        refresh_seconds=refresh, interval=interval, max_candles=maximum)
    return cache, clock, fetch


def test_completed_view_excludes_partial_and_future_bars_without_mutating_full_bar_features():
    rows = [bar(-2, volume=30, close=98), bar(-1, volume=120, close=101),
            bar(0, volume=2, close=100.01), bar(1, volume=999, close=500)]
    original = deepcopy(rows)
    cache, _, fetch = make_cache(rows)
    result = cache.get_candles(SYMBOL, completed_only=True)
    assert result == original[:2]
    assert rows == original
    fetch.assert_called_once_with(SYMBOL, "1m")
    # A caller's list edits must not alter the cache or the legacy view.
    result.clear()
    assert cache.get_candles(SYMBOL, completed_only=True) == original[:2]
    assert cache.get_candles(SYMBOL) == original
    assert fetch.call_count == 1


@pytest.mark.parametrize("offset,expected", [(59.999, 1), (60.0, 2), (60.001, 2)])
def test_close_boundary_uses_open_time_plus_full_minute(offset, expected):
    rows = [bar(-1), bar(0), bar(1)]
    cache, _, _ = make_cache(rows, now=BASE_S + offset)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:expected]


def test_final_rest_bar_is_retained_when_already_complete_at_fetch_start():
    rows = [bar(-3), bar(-2), bar(-1)]
    cache, _, fetch = make_cache(rows, now=BASE_S + 1)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows
    fetch.assert_called_once()


def test_wall_clock_rollover_does_not_promote_previously_cached_partial():
    old_complete, partial = bar(-1), bar(0, volume=2, close=100.01)
    cache, clock, fetch = make_cache([old_complete, partial])
    assert cache.get_candles(SYMBOL, completed_only=True) == [old_complete]
    clock[0] = BASE_S + 61
    assert cache.get_candles(SYMBOL, completed_only=True) == [old_complete]
    assert cache.get_candles(SYMBOL)[-1] == partial
    assert fetch.call_count == 1

    finalized = bar(0, volume=180, close=100.8)
    fetch.return_value = [old_complete, finalized, bar(1, volume=3)]
    assert cache.get_candles(SYMBOL, completed_only=True, force_refresh=True) == [old_complete, finalized]
    assert fetch.call_count == 2


def test_fetch_crossing_minute_boundary_cannot_make_its_partial_bar_final():
    clock = [BASE_S + 59]
    rows = [bar(-1), bar(0, volume=2)]

    def slow_fetch(symbol, interval):
        assert (symbol, interval) == (SYMBOL, "1m")
        clock[0] = BASE_S + 65  # Response arrives after its sampled last bar closed.
        return rows

    fetch = Mock(side_effect=slow_fetch)
    cache = CandleCache(fetch_fn=fetch, now_fn=lambda: clock[0], refresh_seconds=600)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert cache.last_success_age_s(SYMBOL) == 6
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    fetch.assert_called_once()


@pytest.mark.parametrize("failed_response", ["exception", "empty", "none"])
def test_unsuccessful_refresh_never_advances_completed_cutoff_or_hammers_fetch(failed_response):
    rows = [bar(-1), bar(0, volume=2)]
    cache, clock, fetch = make_cache(rows, refresh=60)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    if failed_response == "exception":
        fetch.side_effect = OSError("fixture REST unavailable")
    else:
        fetch.return_value = [] if failed_response == "empty" else None
    clock[0] = BASE_S + 91
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert cache.last_success_age_s(SYMBOL) == 61
    clock[0] += 1
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert cache.get_candles(SYMBOL, completed_only=False) == rows
    assert fetch.call_count == 2


def test_clock_rollback_limits_view_to_current_time_without_advancing_fetch_cutoff():
    rows = [bar(-1), bar(0), bar(1, volume=2)]
    cache, clock, fetch = make_cache(rows, now=BASE_S + 90)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:2]
    clock[0] = BASE_S + 30
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    clock[0] = BASE_S - 1
    assert cache.get_candles(SYMBOL, completed_only=True) == []
    clock[0] = BASE_S + 150
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:2]
    fetch.assert_called_once()


def test_successful_forced_fetch_after_clock_rollback_uses_new_conservative_cutoff():
    rows = [bar(-1), bar(0), bar(1)]
    cache, clock, fetch = make_cache(rows, now=BASE_S + 90)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:2]
    clock[0] = BASE_S + 30
    assert cache.get_candles(SYMBOL, completed_only=True, force_refresh=True) == rows[:1]
    clock[0] = BASE_S + 100
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert fetch.call_count == 2


def test_each_symbol_keeps_its_own_successful_fetch_cutoff():
    rows = [bar(-1), bar(0)]
    cache, clock, fetch = make_cache(rows)
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    clock[0] = BASE_S + 90
    assert cache.get_candles("ADAUSDT", completed_only=True) == rows
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert fetch.call_count == 2


def test_legacy_first_fetch_cannot_later_promote_its_partial_into_completed_view():
    rows = [bar(-1), bar(0, volume=2)]
    cache, clock, fetch = make_cache(rows)
    assert cache.get_candles(SYMBOL) == rows
    clock[0] = BASE_S + 90
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[:1]
    assert cache.get_candles(SYMBOL, completed_only=False) == rows
    fetch.assert_called_once()


def test_cache_bound_and_original_older_bars_are_preserved_for_both_views():
    rows = [bar(i, volume=i + 10, close=100 + i) for i in range(-5, 1)]
    cache, _, _ = make_cache(rows, maximum=4)
    assert cache.get_candles(SYMBOL) == rows[-4:]
    assert cache.get_candles(SYMBOL, completed_only=True) == rows[-4:-1]


@pytest.mark.parametrize("interval", ["5m", "1h", "1s", "", "1M"])
def test_completed_mode_rejects_unsupported_interval_before_fetch_but_legacy_stays_usable(interval):
    rows = [bar(-1), bar(0)]
    cache, _, fetch = make_cache(rows, interval=interval)
    with pytest.raises(ValueError):
        cache.get_candles(SYMBOL, completed_only=True)
    fetch.assert_not_called()
    assert cache.get_candles(SYMBOL) == rows
    fetch.assert_called_once_with(SYMBOL, interval)


@pytest.mark.parametrize("response", [[], None, OSError("fixture unavailable")])
def test_no_successful_data_yields_empty_completed_view(response):
    cache, clock, fetch = make_cache([])
    if isinstance(response, Exception):
        fetch.side_effect = response
    else:
        fetch.return_value = response
    assert cache.get_candles(SYMBOL, completed_only=True) == []
    assert cache.last_success_age_s(SYMBOL) is None
    clock[0] += 61
    assert cache.get_candles(SYMBOL, completed_only=True) == []
    fetch.assert_called_once()


@pytest.mark.parametrize("invalid", [None, True, False, "1800000000000", float(BASE_MS),
                                      float("nan"), float("inf"), -60_000, BASE_MS + 1])
def test_invalid_open_time_rejects_whole_completed_view_without_mutating_legacy(invalid):
    rows = [bar(-1), {**bar(0), "open_time": invalid}]
    cache, _, fetch = make_cache(rows)
    assert cache.get_candles(SYMBOL) == rows
    with pytest.raises(ValueError):
        cache.get_candles(SYMBOL, completed_only=True)
    assert cache.get_candles(SYMBOL) == rows
    fetch.assert_called_once()


@pytest.mark.parametrize("rows", [[bar(-1), {}], [bar(-1), bar(-1)], [bar(0), bar(-1)],
                                  [bar(-1), bar(2), bar(2)]])
def test_missing_duplicate_or_unordered_timestamps_fail_closed_even_for_future_rows(rows):
    cache, _, _ = make_cache(rows)
    with pytest.raises(ValueError):
        cache.get_candles(SYMBOL, completed_only=True)
