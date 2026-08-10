"""Tests for live_quote_cache_v1.py. None of these tests touch the real
event_bus subscriber list persistently in a way that leaks across tests --
_on_price_tick is called directly, and ensure_subscribed()'s idempotency
is tested against a fresh module-level _subscribed flag reset via
monkeypatch rather than the real global event_bus subscription list.
"""
import time

import pytest

from src.services import live_quote_cache_v1 as qc


@pytest.fixture(autouse=True)
def _reset_cache_state(monkeypatch):
    """Isolate each test's view of the module-level cache/subscribed flag."""
    monkeypatch.setattr(qc, "_last_quotes", {})
    monkeypatch.setattr(qc, "_subscribed", False)
    yield


def _tick(symbol="ETHUSDT", bid=1900.0, ask=1900.2, price=1900.1):
    return {"symbol": symbol, "bid": bid, "ask": ask, "price": price, "obi": 0.0}


# ---------------------------------------------------------------------------
# _on_price_tick / get_last_quote
# ---------------------------------------------------------------------------

def test_get_last_quote_returns_none_before_any_tick():
    assert qc.get_last_quote("ETHUSDT") is None


def test_on_price_tick_then_get_last_quote_returns_it():
    qc._on_price_tick(_tick())
    q = qc.get_last_quote("ETHUSDT")
    assert q is not None
    assert q.bid == 1900.0
    assert q.ask == 1900.2
    assert q.price == 1900.1
    assert q.symbol == "ETHUSDT"


def test_later_tick_overwrites_earlier_one():
    qc._on_price_tick(_tick(bid=1900.0, ask=1900.2))
    qc._on_price_tick(_tick(bid=1901.0, ask=1901.2))
    q = qc.get_last_quote("ETHUSDT")
    assert q.bid == 1901.0


def test_symbols_tracked_independently():
    qc._on_price_tick(_tick(symbol="ETHUSDT"))
    qc._on_price_tick(_tick(symbol="ADAUSDT", bid=0.19, ask=0.191, price=0.1905))
    assert qc.get_last_quote("ETHUSDT").symbol == "ETHUSDT"
    assert qc.get_last_quote("ADAUSDT").symbol == "ADAUSDT"


@pytest.mark.parametrize("bad_data", [
    None, "not a dict", {}, {"symbol": "ETHUSDT"},
    {"symbol": "ETHUSDT", "bid": None, "ask": 1900.2, "price": 1900.1},
    {"symbol": "ETHUSDT", "bid": "abc", "ask": 1900.2, "price": 1900.1},
    {"symbol": "ETHUSDT", "bid": 0.0, "ask": 1900.2, "price": 1900.1},
    {"symbol": "ETHUSDT", "bid": -1.0, "ask": 1900.2, "price": 1900.1},
    {"symbol": "ETHUSDT", "bid": 1900.5, "ask": 1900.2, "price": 1900.1},  # crossed
    {"symbol": "", "bid": 1900.0, "ask": 1900.2, "price": 1900.1},
])
def test_on_price_tick_silently_ignores_malformed_payloads(bad_data):
    qc._on_price_tick(bad_data)  # must not raise
    assert qc.get_last_quote("ETHUSDT") is None


def test_get_last_quote_respects_max_age_s(monkeypatch):
    """Monkeypatches this module's own `time` name binding (pytest's
    monkeypatch auto-undoes this), never the real stdlib time.time --
    mutating that globally would affect unrelated code (locks, pytest
    internals) for the duration of the test."""
    t = [1000.0]

    class _FakeTime:
        @staticmethod
        def time():
            return t[0]

    monkeypatch.setattr(qc, "time", _FakeTime)
    qc._on_price_tick(_tick())
    t[0] += 10.0
    assert qc.get_last_quote("ETHUSDT", max_age_s=5.0) is None
    assert qc.get_last_quote("ETHUSDT", max_age_s=20.0) is not None


def test_get_last_quote_no_max_age_returns_regardless_of_staleness():
    qc._on_price_tick(_tick())
    assert qc.get_last_quote("ETHUSDT") is not None
    assert qc.get_last_quote("ETHUSDT", max_age_s=None) is not None


# ---------------------------------------------------------------------------
# known_symbols
# ---------------------------------------------------------------------------

def test_known_symbols_reflects_ticks_received():
    assert qc.known_symbols() == frozenset()
    qc._on_price_tick(_tick(symbol="ETHUSDT"))
    qc._on_price_tick(_tick(symbol="SOLUSDT", bid=77.0, ask=77.1, price=77.05))
    assert qc.known_symbols() == frozenset({"ETHUSDT", "SOLUSDT"})


# ---------------------------------------------------------------------------
# ensure_subscribed
# ---------------------------------------------------------------------------

def test_ensure_subscribed_registers_with_event_bus(monkeypatch):
    calls = []

    def _fake_subscribe_once(event, handler):
        calls.append((event, handler))

    monkeypatch.setattr("src.core.event_bus.subscribe_once", _fake_subscribe_once)
    qc.ensure_subscribed()
    assert calls == [("price_tick", qc._on_price_tick)]


def test_ensure_subscribed_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr("src.core.event_bus.subscribe_once", lambda event, handler: calls.append(1))
    qc.ensure_subscribed()
    qc.ensure_subscribed()
    qc.ensure_subscribed()
    assert len(calls) == 1


def test_published_tick_reaches_the_cache_through_the_real_event_bus(monkeypatch):
    """Integration-style: prove this module actually receives ticks
    through the real event_bus.publish()/subscribe() path, not just via
    direct calls to _on_price_tick in the other tests above."""
    monkeypatch.setattr(qc, "_subscribed", False)
    from src.core import event_bus
    # Use a fresh event name so this test doesn't collide with the real
    # "price_tick" subscribers already registered by other modules in
    # this same test process.
    monkeypatch.setattr(qc, "_on_price_tick", qc._on_price_tick)  # keep same ref
    event_bus.subscribe_once("price_tick", qc._on_price_tick)
    event_bus.publish("price_tick", _tick(symbol="ETHUSDT", bid=1950.0, ask=1950.3, price=1950.15))
    q = qc.get_last_quote("ETHUSDT")
    assert q is not None
    assert q.bid == 1950.0
