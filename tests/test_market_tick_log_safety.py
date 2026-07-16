"""Audit PR2 (P2, 2026-07-16) — per-tick log safety in market_stream.

The old code logged one DEBUG line per symbol per tick (~75+ lines/s) with no
guard. These tests pin the new contract: silent by default, and when explicitly
enabled it is both sampled and throttled with a bounded numeric format.
"""
import logging

import pytest

import src.services.market_stream as ms

LOGGER = "src.services.market_stream"


def _tick_lines(records):
    return [r for r in records if r.getMessage().startswith("tick ")]


def test_per_tick_debug_disabled_by_default():
    assert ms._TICK_DEBUG is False


def test_no_debug_when_disabled(monkeypatch, caplog):
    monkeypatch.setattr(ms, "_TICK_DEBUG", False)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(5000):
            ms._maybe_tick_debug("BTCUSDT", 1.0, 1.1, 1.05, 0.0)
    assert _tick_lines(caplog.records) == []


def test_sampling_limits_volume(monkeypatch, caplog):
    # Isolate sampling from throttling: throttle disabled (interval 0).
    monkeypatch.setattr(ms, "_TICK_DEBUG", True)
    monkeypatch.setattr(ms, "_TICK_DEBUG_SAMPLE_EVERY", 100)
    monkeypatch.setattr(ms, "_TICK_DEBUG_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(ms, "_tick_debug_count", 0)
    monkeypatch.setattr(ms, "_tick_debug_last_emit", 0.0)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(1000):
            ms._maybe_tick_debug("BTCUSDT", 1.0, 1.1, 1.05, 0.0)
    # 1000 ticks, 1-in-100 sampled, no throttle -> exactly 10 lines
    assert len(_tick_lines(caplog.records)) == 10


def test_throttle_limits_rate(monkeypatch, caplog):
    # Every tick is a sampling candidate, but a long min-interval blocks all but
    # the first within the window.
    monkeypatch.setattr(ms, "_TICK_DEBUG", True)
    monkeypatch.setattr(ms, "_TICK_DEBUG_SAMPLE_EVERY", 1)
    monkeypatch.setattr(ms, "_TICK_DEBUG_MIN_INTERVAL_S", 999.0)
    monkeypatch.setattr(ms, "_tick_debug_count", 0)
    monkeypatch.setattr(ms, "_tick_debug_last_emit", 0.0)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(500):
            ms._maybe_tick_debug("BTCUSDT", 1.0, 1.1, 1.05, 0.0)
    assert len(_tick_lines(caplog.records)) == 1


def test_debug_format_is_bounded_numeric(monkeypatch, caplog):
    monkeypatch.setattr(ms, "_TICK_DEBUG", True)
    monkeypatch.setattr(ms, "_TICK_DEBUG_SAMPLE_EVERY", 1)
    monkeypatch.setattr(ms, "_TICK_DEBUG_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(ms, "_tick_debug_count", 0)
    monkeypatch.setattr(ms, "_tick_debug_last_emit", 0.0)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        ms._maybe_tick_debug("BTCUSDT", 1.2345, 1.2350, 1.23475, 0.5)
    line = _tick_lines(caplog.records)[0].getMessage()
    # Only the whitelisted numeric fields — no raw payload / dict / secrets.
    assert line.startswith("tick BTCUSDT ")
    for field in ("bid=", "ask=", "mid=", "obi="):
        assert field in line
    assert "{" not in line and "}" not in line
