"""Tests for binance_client.fetch_candles()'s `limit` parameter, added
2026-08-10 alongside candle_cache_v1.py -- confirms every existing caller's
behavior (limit=config.CANDLE_LIMIT) is unchanged, and the new explicit
`limit` override works.
"""
from src.services import binance_client


def test_default_limit_matches_config_candle_limit(monkeypatch):
    seen = {}

    def _fake_safe_request(url, params, retries=3, delay=2):
        seen["limit"] = params["limit"]
        return []

    monkeypatch.setattr(binance_client, "_safe_request", _fake_safe_request)
    binance_client.fetch_candles("ETHUSDT", "1m")
    assert seen["limit"] == binance_client.CANDLE_LIMIT


def test_explicit_limit_overrides_default(monkeypatch):
    seen = {}

    def _fake_safe_request(url, params, retries=3, delay=2):
        seen["limit"] = params["limit"]
        return []

    monkeypatch.setattr(binance_client, "_safe_request", _fake_safe_request)
    binance_client.fetch_candles("ETHUSDT", "1m", limit=260)
    assert seen["limit"] == 260


def test_fetch_candles_still_returns_parsed_ohlcv_shape(monkeypatch):
    def _fake_safe_request(url, params, retries=3, delay=2):
        return [[1700000000000, "100.0", "101.0", "99.0", "100.5", "10.0", 0, "0", 0, "0", "0", "0"]]

    monkeypatch.setattr(binance_client, "_safe_request", _fake_safe_request)
    result = binance_client.fetch_candles("ETHUSDT", "1m", limit=260)
    assert result == [{
        "open_time": 1700000000000, "open": 100.0, "high": 101.0,
        "low": 99.0, "close": 100.5, "volume": 10.0,
    }]
