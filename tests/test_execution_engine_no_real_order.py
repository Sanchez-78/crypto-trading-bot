"""Audit F1 (2026-07-17) — the real Binance order primitive must be fail-closed.

`execution_engine.BinanceClient.market_order` is the only real signed
`POST /api/v3/order` in the repo. These tests prove no paper/default config can
reach the HTTP submission — the central four-flag live guard blocks it at the
primitive, so REAL=NO-GO holds even if the engine is re-wired.
"""
import asyncio
import re
from pathlib import Path

import pytest

import src.services.execution_engine as ee

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def paper_env(monkeypatch):
    # Ensure no live flags leak in from the environment.
    for k in ("TRADING_MODE", "ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED",
              "PAPER_EXPLORATION_ENABLED", "EXECUTION_ENGINE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_market_order_fail_closed_in_paper(monkeypatch):
    client = ee.BinanceClient("k", "s", ee.BINANCE_BASE)

    # If the guard ever lets execution reach the HTTP client, fail loudly.
    async def _must_not_be_called():
        raise AssertionError("market_order reached the HTTP client in paper mode!")

    monkeypatch.setattr(client, "_get_client", _must_not_be_called)
    result = asyncio.run(client.market_order("XRPUSDT", "BUY", 1.0))
    assert result == {}  # blocked, no order dict returned


def test_guard_is_consulted(monkeypatch):
    seen = {}

    def _fake_guard(symbol, side):
        seen["symbol"] = symbol
        seen["side"] = side
        return {"allowed": False, "reason": "test_block", "mode": "paper"}

    monkeypatch.setattr("src.core.runtime_mode.check_live_order_guard", _fake_guard)
    client = ee.BinanceClient("k", "s", ee.BINANCE_BASE)
    asyncio.run(client.market_order("ETHUSDT", "SELL", 2.0))
    assert seen == {"symbol": "ETHUSDT", "side": "SELL"}


def test_guard_precedes_http_post_statically():
    src = (REPO / "src/services/execution_engine.py").read_text()
    body = src.split("async def market_order")[1].split("async def close")[0]
    assert "check_live_order_guard" in body
    assert body.index("check_live_order_guard") < body.index('client.post("/api/v3/order"'), \
        "guard must run before the HTTP order submission"


def test_no_other_unguarded_order_submission():
    """Repo-wide: the only real `/api/v3/order` POST lives in execution_engine
    and is guarded. If a new one appears, this test must be revisited."""
    hits = []
    for path in (REPO / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/v3/order" in text:
            hits.append(path.relative_to(REPO).as_posix())
    assert hits == ["src/services/execution_engine.py"], f"unexpected order path(s): {hits}"
