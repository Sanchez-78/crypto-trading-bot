# -*- coding: utf-8 -*-
"""Tests for the rolling-window headline fix (bug 2026-07-15).

The dashboard headline (win_rate_pct / profit_factor) must reflect RECENT bot
form, sourced from the newest <=100 rows of cache.sqlite:closed_trades — NOT from
lifetime_pf (16k+ trades, pre-fix losing era) and NOT from the durable learning
rolling window. Covers:
  1. _rolling_window_metrics WR/PF/net math on a temp sqlite with known rows.
  2. Empty / missing cache -> helper returns None, metrics fall back (never-500).
  3. Headline win_rate_pct/profit_factor come from the rolling window (not lifetime)
     when the cache has rows; net_pnl_window added; lifetime block untouched.
"""
import json
import sqlite3
import time

import pytest

pytest.importorskip("flask")

from src.services import dashboard_web

# Reuse the helpers from the existing contract test module.
from tests.test_dashboard_contract_fixes import (
    _hide_opt_cryptomaster,
    _make_cache_db,
    _write_learning_state,
)


def _make_ro_db(tmp_path, rows):
    """Create a minimal cache.sqlite with closed_trades and insert `rows`.

    `rows` is a list of (trade_id, pnl_usd, pnl_pct, exit_ts). None values are
    stored as SQL NULL.
    """
    conn = _make_cache_db(tmp_path, with_side_column=True)
    for tid, pu, pp, xts in rows:
        conn.execute(
            "INSERT INTO closed_trades (trade_id, symbol, side, entry_ts, exit_ts,"
            " entry_price, exit_price, pnl_usd, pnl_pct, win, exit_reason, regime)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, "BTCUSDT", "BUY", xts - 10, xts, 100.0, 101.0, pu, pp, 0, "TP", "TREND"),
        )
    conn.commit()
    conn.close()
    return str(tmp_path / "local_learning_storage" / "cache.sqlite")


# ---------------------------------------------------------------------------
# 1. Helper math
# ---------------------------------------------------------------------------

def test_rolling_helper_computes_wr_and_pf_from_usd(tmp_path):
    now = time.time()
    # 3 wins (+2,+3,+5 => gross_win=10), 2 losses (-4,-1 => gross_loss=5).
    rows = [
        ("w1", 2.0, 1.0, now - 50),
        ("w2", 3.0, 1.5, now - 40),
        ("w3", 5.0, 2.0, now - 30),
        ("l1", -4.0, -2.0, now - 20),
        ("l2", -1.0, -0.5, now - 10),
    ]
    cache_path = _make_ro_db(tmp_path, rows)
    m = dashboard_web._rolling_window_metrics(cache_path, 100)
    assert m is not None
    assert m["n"] == 5
    assert m["wins"] == 3
    assert m["win_rate_pct"] == pytest.approx(60.0)
    assert m["profit_factor"] == pytest.approx(2.0)  # 10 / 5
    assert m["net_pnl"] == pytest.approx(5.0)  # 10 - 5


def test_rolling_helper_limit_and_ordering(tmp_path):
    now = time.time()
    # 4 rows; newest 2 (by exit_ts) are both losses -> WR must be 0 with limit=2.
    rows = [
        ("old_win1", 5.0, 1.0, now - 400),
        ("old_win2", 5.0, 1.0, now - 300),
        ("new_loss1", -1.0, -1.0, now - 200),
        ("new_loss2", -1.0, -1.0, now - 100),
    ]
    cache_path = _make_ro_db(tmp_path, rows)
    m = dashboard_web._rolling_window_metrics(cache_path, 2)
    assert m["n"] == 2
    assert m["wins"] == 0
    assert m["win_rate_pct"] == pytest.approx(0.0)
    assert m["profit_factor"] == pytest.approx(0.0)  # no wins in window


def test_rolling_helper_falls_back_to_pct_when_usd_null_or_zero(tmp_path):
    now = time.time()
    # pnl_usd all NULL/0 -> win rule + PF basis fall back to pnl_pct.
    rows = [
        ("w1", None, 1.0, now - 30),
        ("w2", 0.0, 2.0, now - 20),
        ("l1", None, -1.0, now - 10),
    ]
    cache_path = _make_ro_db(tmp_path, rows)
    m = dashboard_web._rolling_window_metrics(cache_path, 100)
    assert m["n"] == 3
    assert m["wins"] == 2  # pct>0 for w1,w2
    assert m["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert m["profit_factor"] == pytest.approx(3.0)  # (1+2) / 1
    assert m["net_pnl"] == pytest.approx(2.0)  # 1+2-1


def test_rolling_helper_all_wins_no_losses_capped_pf(tmp_path):
    now = time.time()
    rows = [("w1", 2.0, 1.0, now - 20), ("w2", 3.0, 1.0, now - 10)]
    cache_path = _make_ro_db(tmp_path, rows)
    m = dashboard_web._rolling_window_metrics(cache_path, 100)
    assert m["wins"] == 2
    assert m["win_rate_pct"] == pytest.approx(100.0)
    assert m["profit_factor"] == pytest.approx(99.0)  # no losing $ -> capped


# ---------------------------------------------------------------------------
# 2. Empty / missing cache -> None (never raise)
# ---------------------------------------------------------------------------

def test_rolling_helper_missing_file_returns_none(tmp_path):
    assert dashboard_web._rolling_window_metrics(str(tmp_path / "nope.sqlite"), 100) is None


def test_rolling_helper_empty_table_returns_none(tmp_path):
    cache_path = _make_ro_db(tmp_path, [])  # table exists, no rows
    assert dashboard_web._rolling_window_metrics(cache_path, 100) is None


def test_rolling_helper_never_raises_on_corrupt_db(tmp_path):
    bad = tmp_path / "corrupt.sqlite"
    bad.write_bytes(b"this is not a sqlite database")
    assert dashboard_web._rolling_window_metrics(str(bad), 100) is None


def test_metrics_fall_back_without_raising_when_cache_empty(tmp_path, monkeypatch):
    # Learning state present (so get_live_metrics_from_cache returns a payload),
    # but no cache.sqlite rows -> headline falls back to learning-state values.
    _write_learning_state(tmp_path, lifetime_n=5, learning_enabled=True)
    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)
    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    # lifetime_pf from _write_learning_state is 1.2; rolling window unavailable.
    assert metrics["profit_factor"] == pytest.approx(1.2)
    assert "win_rate_pct" in metrics
    assert "net_pnl_window" in metrics


# ---------------------------------------------------------------------------
# 3. Headline sourced from rolling window (not lifetime) when cache has rows
# ---------------------------------------------------------------------------

def test_headline_uses_rolling_window_not_lifetime(tmp_path, monkeypatch):
    # Learning state: lifetime_pf=1.2 and a rolling window that is ALL wins (so the
    # old code path would give WR=100). The cache.sqlite recent window is 60% WR /
    # PF 2.0 / net +5 — the headline must reflect the cache, not either legacy source.
    _write_learning_state(tmp_path, lifetime_n=16733, learning_enabled=True)
    now = time.time()
    _make_ro_db(tmp_path, [
        ("w1", 2.0, 1.0, now - 50),
        ("w2", 3.0, 1.5, now - 40),
        ("w3", 5.0, 2.0, now - 30),
        ("l1", -4.0, -2.0, now - 20),
        ("l2", -1.0, -0.5, now - 10),
    ])
    _hide_opt_cryptomaster(monkeypatch)
    monkeypatch.chdir(tmp_path)

    metrics = dashboard_web.get_live_metrics_from_cache()
    assert metrics is not None
    # Headline from rolling window:
    assert metrics["win_rate_pct"] == pytest.approx(60.0)
    assert metrics["profit_factor"] == pytest.approx(2.0)
    assert metrics["win_rate_window"] == 5
    assert metrics["net_pnl_window"] == pytest.approx(5.0)
    # NOT the lifetime PF (1.2) and NOT the all-win learning-window WR (100).
    assert metrics["profit_factor"] != pytest.approx(1.2)
    assert metrics["win_rate_pct"] != pytest.approx(100.0)
    # Lifetime block stays available and separate (untouched).
    assert metrics["lifetime_metrics"]["lifetime_pf"] == pytest.approx(1.2)
    assert metrics["lifetime_metrics"]["lifetime_n"] == 16733
    # Session-based net_pnl still present, distinct field from net_pnl_window.
    assert "net_pnl" in metrics
