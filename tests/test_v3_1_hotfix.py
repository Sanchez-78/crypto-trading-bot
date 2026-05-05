"""
Tests for V3.1 senior hotfix issues.

Issue 1 (P0): Timeout close must use last known price, not entry price fallback.
Issue 2 (P0): Outcome classifier must not flatten all tiny non-neutral trades.
Issue 3 (P1): open_positions count must reflect total, not truncated items.
Issue 4 (P1): Snapshot must use injected `now` throughout.
Issue 5 (P1): Semantic hash excludes all volatile age/time fields.
Issue 6 (P1): PnL unit semantics — unit_pnl excluded from profit extraction.
"""

import math
import time
import pytest


# ── Issue 1: Timeout close uses last known price ──────────────────────────────

def _make_position(trade_id="paper_test_001", symbol="BTCUSDT", entry_price=50000.0,
                   entry_ts=None, max_hold_s=60.0, last_price=None, last_price_ts=None):
    now = entry_ts or (time.time() - 120)
    pos = {
        "trade_id": trade_id,
        "symbol": symbol,
        "entry_price": entry_price,
        "entry_ts": now,
        "tp": entry_price * 1.01,
        "sl": entry_price * 0.99,
        "max_hold_s": max_hold_s,
        "training_bucket": "C_WEAK_EV_TRAIN",
        "paper_source": "training_sampler",
    }
    if last_price is not None:
        pos["last_price"] = last_price
        pos["last_price_ts"] = last_price_ts or time.time()
    return pos


def test_timeout_close_uses_last_known_price_not_entry_price(monkeypatch):
    """Timed-out position with a recent last_price must close at that price."""
    import src.services.paper_trade_executor as pte

    now_ts = time.time()
    entry_ts = now_ts - 200  # 200s ago, well past any max_hold_s
    last_px = 51000.0

    pos = _make_position(
        trade_id="t_price_test",
        entry_price=50000.0,
        entry_ts=entry_ts,
        max_hold_s=60.0,
        last_price=last_px,
        last_price_ts=now_ts - 10,  # fresh price (10s ago)
    )

    # Inject position directly into module state
    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()
        pte._POSITIONS["t_price_test"] = pos

    closed_trades = []

    def mock_close(position_id, price, ts, reason):
        closed_trades.append({"trade_id": position_id, "close_price": price, "reason": reason})
        with pte._POSITION_LOCK:
            pte._POSITIONS.pop(position_id, None)
        return {"trade_id": position_id, "close_price": price, "reason": reason}

    monkeypatch.setattr(pte, "close_paper_position", mock_close)

    result = pte.check_and_close_timeout_positions(now_ts)

    assert len(result) == 1
    assert result[0]["close_price"] == last_px, (
        f"Expected close at last_price {last_px}, got {result[0]['close_price']}"
    )
    assert result[0]["reason"] == "TIMEOUT"


def test_timeout_close_no_price_does_not_learning_update(monkeypatch):
    """Timed-out position without a recent price must be quarantined with learning_skipped=True."""
    import src.services.paper_trade_executor as pte

    now_ts = time.time()
    entry_ts = now_ts - 200

    pos = _make_position(
        trade_id="t_no_price",
        entry_price=50000.0,
        entry_ts=entry_ts,
        max_hold_s=60.0,
        # no last_price set
    )

    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()
        pte._POSITIONS["t_no_price"] = pos

    close_called = []
    monkeypatch.setattr(pte, "close_paper_position",
                        lambda *a, **kw: close_called.append(a) or None)
    monkeypatch.setattr(pte, "_save_paper_state", lambda: None)

    result = pte.check_and_close_timeout_positions(now_ts)

    # close_paper_position must NOT be called
    assert len(close_called) == 0, "close_paper_position should not be called when no price"
    assert len(result) == 1
    assert result[0]["learning_skipped"] is True
    assert result[0]["exit_reason"] == "TIMEOUT_NO_PRICE"


def test_timeout_close_no_price_frees_or_quarantines_cap_safely(monkeypatch):
    """After TIMEOUT_NO_PRICE the position must be removed from _POSITIONS (cap freed)."""
    import src.services.paper_trade_executor as pte

    now_ts = time.time()
    pos = _make_position(
        trade_id="t_cap_free",
        entry_ts=now_ts - 200,
        max_hold_s=60.0,
    )

    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()
        pte._POSITIONS["t_cap_free"] = pos

    monkeypatch.setattr(pte, "close_paper_position", lambda *a, **kw: None)
    monkeypatch.setattr(pte, "_save_paper_state", lambda: None)

    pte.check_and_close_timeout_positions(now_ts)

    with pte._POSITION_LOCK:
        assert "t_cap_free" not in pte._POSITIONS, "Position must be removed after TIMEOUT_NO_PRICE"


def test_timeout_close_logs_no_price(monkeypatch, caplog):
    """TIMEOUT_NO_PRICE must emit a warning log with [PAPER_TIMEOUT_NO_PRICE] tag."""
    import logging
    import src.services.paper_trade_executor as pte

    now_ts = time.time()
    pos = _make_position(
        trade_id="t_log_check",
        entry_ts=now_ts - 200,
        max_hold_s=60.0,
    )

    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()
        pte._POSITIONS["t_log_check"] = pos

    monkeypatch.setattr(pte, "close_paper_position", lambda *a, **kw: None)
    monkeypatch.setattr(pte, "_save_paper_state", lambda: None)

    with caplog.at_level(logging.WARNING, logger="src.services.paper_trade_executor"):
        pte.check_and_close_timeout_positions(now_ts)

    assert any("[PAPER_TIMEOUT_NO_PRICE]" in r.message for r in caplog.records), (
        "[PAPER_TIMEOUT_NO_PRICE] warning not logged"
    )


# ── Issue 2: Outcome classifier must not flatten tiny non-neutral trades ──────

from src.services.app_metrics_contract import _classify_outcome, _EPS


def _trade_classify(profit, close_reason, stored_result=None):
    t = {"close_reason": close_reason}
    if stored_result:
        t["result"] = stored_result
    return _classify_outcome(t, profit)


def test_small_non_neutral_profit_is_win():
    """A small TP profit (non-neutral) must be WIN, not FLAT."""
    result = _trade_classify(profit=0.0005, close_reason="TP")
    assert result == "WIN", f"Expected WIN, got {result}"


def test_small_non_neutral_loss_is_loss():
    """A small SL loss (non-neutral) must be LOSS, not FLAT."""
    result = _trade_classify(profit=-0.0005, close_reason="SL")
    assert result == "LOSS", f"Expected LOSS, got {result}"


def test_tiny_timeout_profit_is_flat():
    """A tiny profit on TIMEOUT (neutral) must be FLAT."""
    result = _trade_classify(profit=0.00005, close_reason="TIMEOUT")
    assert result == "FLAT", f"Expected FLAT, got {result}"


def test_tiny_timeout_loss_is_flat():
    """A tiny loss on TIMEOUT (neutral) must be FLAT."""
    result = _trade_classify(profit=-0.0001, close_reason="TIMEOUT")
    assert result == "FLAT", f"Expected FLAT, got {result}"


def test_stored_result_respected_for_non_neutral_exit():
    """If trade has result=WIN and close_reason is TP, stored result wins."""
    result = _trade_classify(profit=0.0003, close_reason="TP", stored_result="WIN")
    assert result == "WIN"


def test_stored_result_loss_respected_for_non_neutral_exit():
    """If trade has result=LOSS and close_reason is SL, stored result wins."""
    result = _trade_classify(profit=-0.0003, close_reason="SL", stored_result="LOSS")
    assert result == "LOSS"


def test_neutral_scratch_tiny_is_flat():
    """SCRATCH_EXIT with tiny loss → FLAT."""
    result = _trade_classify(profit=-0.0002, close_reason="SCRATCH_EXIT")
    assert result == "FLAT"


def test_neutral_stagnation_tiny_is_flat():
    """STAGNATION_EXIT with tiny profit → FLAT."""
    result = _trade_classify(profit=0.00003, close_reason="STAGNATION_EXIT")
    assert result == "FLAT"


def test_neutral_large_profit_is_win():
    """A large profit on TIMEOUT_PROFIT (neutral but material) → WIN."""
    result = _trade_classify(profit=0.01, close_reason="TIMEOUT_PROFIT")
    assert result == "WIN"


def test_truly_zero_non_neutral_is_flat():
    """Exactly zero profit on non-neutral exit → FLAT (via _EPS guard)."""
    result = _trade_classify(profit=0.0, close_reason="TP")
    assert result == "FLAT"


# ── Issue 3: open_positions count must be total not truncated ─────────────────

from src.services.app_metrics_contract import build_app_metrics_snapshot, APP_METRICS_MAX_OPEN_POSITIONS


def test_open_positions_count_is_total_even_when_items_limited():
    """count must reflect all positions, not just the first 50."""
    total = APP_METRICS_MAX_OPEN_POSITIONS + 15
    ops = [
        {"trade_id": str(i), "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": 1e6}
        for i in range(total)
    ]
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=ops, last_signals={}, now=1e6
    )
    assert s["open_positions"]["count"] == total, (
        f"count should be {total} (total), got {s['open_positions']['count']}"
    )


def test_open_positions_items_limited_to_50():
    """items must be capped at APP_METRICS_MAX_OPEN_POSITIONS."""
    total = APP_METRICS_MAX_OPEN_POSITIONS + 15
    ops = [
        {"trade_id": str(i), "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": 1e6}
        for i in range(total)
    ]
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=ops, last_signals={}, now=1e6
    )
    assert len(s["open_positions"]["items"]) <= APP_METRICS_MAX_OPEN_POSITIONS
    assert s["open_positions"]["items_limit"] == APP_METRICS_MAX_OPEN_POSITIONS
    assert s["open_positions"]["items_count"] == min(total, APP_METRICS_MAX_OPEN_POSITIONS)


# ── Issue 4: Snapshot must use injected now ───────────────────────────────────

def test_snapshot_uses_injected_now_for_since_last_trade():
    """since_last_trade_s must use injected now, not time.time()."""
    last_trade_ts = 1_000_000.0
    injected_now = 1_000_120.0  # 120s after last trade

    trades = [{"profit": 0.01, "close_reason": "TP", "timestamp": last_trade_ts}]
    s = build_app_metrics_snapshot(
        closed_trades=trades, session_metrics={}, open_positions=[],
        last_signals={}, now=injected_now
    )
    since = s["kpis"]["since_last_trade_s"]
    assert since is not None
    assert abs(since - 120.0) < 1.0, f"Expected ~120s, got {since}"


def test_open_position_age_uses_injected_now():
    """age_s for open positions must be computed from injected now."""
    entry_ts = 1_000_000.0
    injected_now = 1_000_300.0  # 300s after entry

    ops = [{"trade_id": "x", "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": entry_ts}]
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=ops,
        last_signals={}, now=injected_now
    )
    items = s["open_positions"]["items"]
    assert len(items) == 1
    assert abs(items[0]["age_s"] - 300.0) < 1.0, f"Expected ~300s, got {items[0]['age_s']}"


def test_signal_age_uses_injected_now():
    """age_s for recommendations must be computed from injected now."""
    sig_ts = 1_000_000.0
    injected_now = 1_000_045.0  # 45s after signal

    last_signals = {"BTCUSDT": {"action": "BUY", "ts": sig_ts, "confidence": 0.8}}
    s = build_app_metrics_snapshot(
        closed_trades=[], session_metrics={}, open_positions=[],
        last_signals=last_signals, now=injected_now
    )
    rec = s["recommendations"]["BTCUSDT"]
    assert abs(rec["age_s"] - 45.0) < 1.0, f"Expected ~45s, got {rec['age_s']}"


# ── Issue 5: Semantic hash excludes volatile fields ───────────────────────────

def _snapshot(now=1e6, **kwargs):
    defaults = dict(
        closed_trades=[], session_metrics={}, open_positions=[],
        last_signals={}, now=now
    )
    defaults.update(kwargs)
    return build_app_metrics_snapshot(**defaults)


def test_semantic_hash_ignores_generated_at():
    """Two snapshots differing only in generated_at must hash identically."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    s1 = _snapshot(now=1e6)
    s2 = _snapshot(now=1e6)
    s1["generated_at"] = 111111.0
    s2["generated_at"] = 999999.0
    assert _app_metrics_semantic_hash(s1) == _app_metrics_semantic_hash(s2)


def test_semantic_hash_ignores_since_last_trade():
    """Snapshots differing only in kpis.since_last_trade_s must hash identically."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    s1 = _snapshot(now=1e6)
    s2 = _snapshot(now=1e6)
    s1["kpis"]["since_last_trade_s"] = 10.0
    s2["kpis"]["since_last_trade_s"] = 9999.0
    assert _app_metrics_semantic_hash(s1) == _app_metrics_semantic_hash(s2)


def test_semantic_hash_ignores_open_position_age():
    """Snapshots differing only in open position age_s must hash identically."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    ops = [{"trade_id": "a", "symbol": "BTCUSDT", "entry_price": 50000.0, "entry_ts": 1e6}]
    s1 = _snapshot(now=1_000_060.0, open_positions=ops)
    s2 = _snapshot(now=1_000_120.0, open_positions=ops)
    # age_s differs but everything else is the same
    assert _app_metrics_semantic_hash(s1) == _app_metrics_semantic_hash(s2)


def test_semantic_hash_ignores_recommendation_age():
    """Snapshots differing only in recommendation age_s must hash identically."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    sig = {"action": "BUY", "ts": 1e6, "confidence": 0.8}
    s1 = _snapshot(now=1_000_010.0, last_signals={"BTCUSDT": sig})
    s2 = _snapshot(now=1_000_020.0, last_signals={"BTCUSDT": sig})
    assert _app_metrics_semantic_hash(s1) == _app_metrics_semantic_hash(s2)


def test_semantic_hash_changes_when_recommendation_action_changes():
    """Different recommendation action must produce different hash."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    s1 = _snapshot(last_signals={"BTCUSDT": {"action": "BUY", "ts": 1e6, "confidence": 0.8}})
    s2 = _snapshot(last_signals={"BTCUSDT": {"action": "SELL", "ts": 1e6, "confidence": 0.8}})
    assert _app_metrics_semantic_hash(s1) != _app_metrics_semantic_hash(s2)


def test_semantic_hash_changes_when_kpi_changes():
    """Different net_pnl must produce different hash."""
    from src.services.firebase_client import _app_metrics_semantic_hash
    import time as _t
    trades_win = [{"profit": 0.05, "close_reason": "TP", "timestamp": 1e6}]
    trades_loss = [{"profit": -0.05, "close_reason": "SL", "timestamp": 1e6}]
    s1 = _snapshot(closed_trades=trades_win)
    s2 = _snapshot(closed_trades=trades_loss)
    assert _app_metrics_semantic_hash(s1) != _app_metrics_semantic_hash(s2)


# ── Issue 6: PnL unit semantics ───────────────────────────────────────────────

from src.services.app_metrics_contract import _extract_profit


def test_app_metrics_prefers_profit_over_net_pnl_pct():
    """profit field takes priority over any percent field."""
    trade = {"profit": 0.05, "net_pnl_pct": 5.0}
    assert _extract_profit(trade) == pytest.approx(0.05)


def test_net_pnl_pct_not_used_as_profit_without_conversion():
    """net_pnl_pct (percent) must NOT be returned as-is (would be 100× wrong)."""
    trade = {"net_pnl_pct": 5.0}
    result = _extract_profit(trade)
    # net_pnl_pct is not in the extraction chain, so result falls through to 0
    assert result == pytest.approx(0.0), (
        f"net_pnl_pct should not be treated as decimal profit, got {result}"
    )


def test_closed_paper_trade_has_canonical_profit_field():
    """A trade with 'profit' field must return that exact value."""
    trade = {"profit": -0.0123, "pnl": 99.0, "net_pnl": 88.0}
    assert _extract_profit(trade) == pytest.approx(-0.0123)


def test_unit_pnl_not_used_by_extract_profit():
    """unit_pnl must NOT be returned by _extract_profit (ambiguous unit)."""
    trade = {"unit_pnl": 0.05}
    result = _extract_profit(trade)
    assert result == pytest.approx(0.0), (
        f"unit_pnl should be excluded from profit extraction, got {result}"
    )


def test_extract_profit_falls_back_to_net_pnl():
    """When only net_pnl is available, it must be used."""
    trade = {"net_pnl": 0.033}
    assert _extract_profit(trade) == pytest.approx(0.033)
