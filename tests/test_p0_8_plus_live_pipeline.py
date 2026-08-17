"""Tests for p0_8_plus_live_pipeline.py -- the first module in the
Evidence-First Strategy Expansion v2 program that CAN open a real paper
position for the new P0.8+ strategies. All tests mock evaluate_symbol()
and open_paper_position() -- none touch real Binance, Firestore, the live
position store, or the real candle cache.
"""
import threading
from unittest.mock import patch

import pytest

from src.services import p0_8_plus_live_pipeline as live
from src.services import strategy_contracts as sc
from src.services.live_quote_cache_v1 import LastQuote
from src.services.p0_8_plus_shadow_evaluator import CandidateEvaluation
from src.services.paper_trade_executor import (
    get_paper_open_positions,
    open_paper_position,
    reset_paper_positions,
)


def _quote(symbol="ETHUSDT", bid=1999.0, ask=2001.0) -> LastQuote:
    return LastQuote(symbol=symbol, bid=bid, ask=ask, price=(bid + ask) / 2, received_at_s=0.0)


def _signal(**overrides) -> sc.StrategySignal:
    fields = dict(
        signal_id="sig-1",
        strategy_id="trend_cost_aware",
        strategy_version="v1",
        symbol="ETHUSDT",
        side="BUY",
        regime="BULL_TREND",
        learning_source="trend_cost_aware_v1",
        generated_event_time_ms=1_700_000_000_000,
        generated_processing_time_ms=1_700_000_000_100,
        market_data_event_time_ms=1_700_000_000_000,
        feature_snapshot_time_ms=1_700_000_000_000,
        expected_horizon_seconds=300,
        reference_price=2000.0,
        gross_expected_move_bps=30.0,
        expected_cost_bps=8.0,
        uncertainty_buffer_bps=5.0,
        net_expected_edge_bps=17.0,
        confidence=0.6,
        invalidation_price=1980.0,
        initial_stop_price=1980.0,
        target_reference_price=2030.0,
        exit_profile="dynamic_trend_exit_v1",  # matches strategy_trend_cost_aware_v1.EXIT_PROFILE (reviewer-agent finding C4-adjacent fixture drift)
        feature_schema_version="v1",
    )
    fields.update(overrides)
    return sc.StrategySignal(**fields)


def _evaluation(*, admitted=True, code="P0_ADMIT_EVIDENCE_COLLECTION", **overrides) -> sc.SignalEvaluation:
    fields = dict(
        signal_id="sig-1",
        admitted=admitted,
        decision_code=code,
        decision_reasons=("ok",),
        gross_expected_move_bps=30.0,
        expected_cost_bps=8.0,
        uncertainty_buffer_bps=5.0,
        net_expected_edge_bps=17.0,
        p0_segment_key="ETHUSDT:BUY:BULL_TREND:trend_cost_aware_v1:trend_default",
        p0_strict_ev=False,
        p0_readiness_eligible=False,
        risk_allowed=True,
        risk_reason="risk guard: OK",
        evaluated_at_ms=1_700_000_000_500,
    )
    fields.update(overrides)
    return sc.SignalEvaluation(**fields)


def _candidate(*, admitted=True, quote_source="live", side="BUY", symbol="ETHUSDT",
                strategy_id="trend_cost_aware") -> CandidateEvaluation:
    sig = _signal(symbol=symbol, side=side, strategy_id=strategy_id)
    ev = _evaluation(admitted=admitted)
    return CandidateEvaluation(
        symbol=symbol, strategy_id=strategy_id, side=side,
        regime="BULL_TREND", regime_confidence=0.8,
        signal=sig, evaluation=ev, quote_source=quote_source,
    )


# ---------------------------------------------------------------------------
# _map_to_legacy_signal
# ---------------------------------------------------------------------------

def test_map_to_legacy_signal_sets_required_p0_metadata_fields():
    candidate = _candidate()
    signal_dict, extra = live._map_to_legacy_signal(candidate, 2000.0)
    # paper_trade_executor's P0.3F fail-closed guard requires these three
    # to be present and non-None, or the entry is BLOCKED.
    assert signal_dict["learning_source"] == "trend_cost_aware_v1"
    assert signal_dict["strict_ev"] is False
    assert signal_dict["readiness_eligible"] is False


def test_map_to_legacy_signal_sets_p0_gate_reason_on_signal_not_extra():
    """2026-08-17 (reviewer-agent finding C5): open_paper_position() reads
    p0_gate_reason from `signal`, not `extra` -- an earlier version put it
    in extra, where it was silently never read."""
    candidate = _candidate()
    signal_dict, _ = live._map_to_legacy_signal(candidate, 2000.0)
    assert signal_dict["p0_gate_reason"] == "P0_ADMIT_EVIDENCE_COLLECTION"


def test_map_to_legacy_signal_normalizes_long_short_to_buy_sell():
    candidate = _candidate(side="LONG")
    signal_dict, _ = live._map_to_legacy_signal(candidate, 2000.0)
    assert signal_dict["side"] == "BUY"
    assert signal_dict["action"] == "BUY"

    candidate2 = _candidate(side="SHORT")
    signal_dict2, _ = live._map_to_legacy_signal(candidate2, 2000.0)
    assert signal_dict2["side"] == "SELL"
    assert signal_dict2["action"] == "SELL"


def test_map_to_legacy_signal_ev_is_bps_to_fraction_conversion():
    candidate = _candidate()  # net_expected_edge_bps=17.0
    signal_dict, _ = live._map_to_legacy_signal(candidate, 2000.0)
    assert signal_dict["ev"] == pytest.approx(17.0 / 10000.0)


def test_map_to_legacy_signal_sets_distinct_bucket_not_starvation_discovery():
    """NOTE (reviewer-agent finding C6): this asserts the MAPPING
    function's own output, i.e. what is handed to open_paper_position() --
    not necessarily what ends up on the stored position. See
    _map_to_legacy_signal's docstring: the executor's own internal P0.3C
    reroute logic unconditionally overwrites extra["paper_source"] for a
    brand-new evidence-only strategy. explore_bucket/training_bucket are
    NOT touched by that reroute and remain the reliable attribution field
    on the stored position -- see test_p0_8_plus_live_pipeline_open_
    paper_position_integration.py for what the executor actually stores.
    """
    candidate = _candidate()
    _, extra = live._map_to_legacy_signal(candidate, 2000.0)
    assert extra["explore_bucket"] == "P0_8_PLUS_EVIDENCE_COLLECTION"
    assert extra["training_bucket"] == "P0_8_PLUS_EVIDENCE_COLLECTION"
    assert extra["paper_source"] == "p0_8_plus_evidence_collection"
    assert extra["explore_bucket"] != "PAPER_STARVATION_DISCOVERY"


def test_map_to_legacy_signal_reanchors_tp_sl_to_booked_price():
    """2026-08-17 (reviewer-agent finding C3): the strategy's target/stop
    are absolute prices computed against ITS OWN candle-close
    reference_price (2000.0 in the fixture). If the actual booked price
    differs (here 2010.0, e.g. a live ask), the offset -- not the raw
    absolute price -- must be preserved: target=2030 is +30 from
    reference, so at booked_price=2010 it must re-anchor to 2040, not stay
    2030."""
    candidate = _candidate()  # reference_price=2000, target=2030, stop=1980
    _, extra = live._map_to_legacy_signal(candidate, 2010.0)
    assert extra["tp_from_executor"] == pytest.approx(2040.0)  # 2010 + (2030-2000)
    assert extra["sl_from_executor"] == pytest.approx(1990.0)  # 2010 + (1980-2000)


def test_map_to_legacy_signal_tp_sl_unchanged_when_booked_price_equals_reference():
    candidate = _candidate()
    _, extra = live._map_to_legacy_signal(candidate, 2000.0)
    assert extra["tp_from_executor"] == pytest.approx(2030.0)
    assert extra["sl_from_executor"] == pytest.approx(1980.0)


def test_map_to_legacy_signal_omits_tp_sl_pair_when_no_target():
    sig = _signal(target_reference_price=None)
    ev = _evaluation()
    candidate = CandidateEvaluation(
        symbol="ETHUSDT", strategy_id="trend_cost_aware", side="BUY",
        regime="BULL_TREND", regime_confidence=0.8,
        signal=sig, evaluation=ev, quote_source="live",
    )
    _, extra = live._map_to_legacy_signal(candidate, 2000.0)
    assert "tp_from_executor" not in extra
    assert "sl_from_executor" not in extra


# ---------------------------------------------------------------------------
# run_live_tick
# ---------------------------------------------------------------------------

def test_run_live_tick_opens_position_for_admitted_live_quote_candidate():
    candidate = _candidate(admitted=True, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]) as mock_eval, \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=_quote()), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        mock_open.return_value = {"status": "opened", "trade_id": "t1"}
        opened = live.run_live_tick(symbols=["ETHUSDT"])
    mock_eval.assert_called_once()
    mock_open.assert_called_once()
    assert len(opened) == 1


def test_run_live_tick_skips_non_admitted_candidate():
    candidate = _candidate(admitted=False, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        opened = live.run_live_tick(symbols=["ETHUSDT"])
    mock_open.assert_not_called()
    assert opened == []


def test_run_live_tick_skips_synthetic_quote_even_if_admitted():
    candidate = _candidate(admitted=True, quote_source="synthetic")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        opened = live.run_live_tick(symbols=["ETHUSDT"])
    mock_open.assert_not_called()
    assert opened == []


def test_run_live_tick_survives_evaluate_symbol_exception():
    with patch.object(live, "evaluate_symbol", side_effect=RuntimeError("boom")), \
         patch.object(live, "ensure_registered"), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        opened = live.run_live_tick(symbols=["ETHUSDT"])  # must not raise
    mock_open.assert_not_called()
    assert opened == []


def test_run_live_tick_survives_open_paper_position_exception():
    candidate = _candidate(admitted=True, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=_quote()), \
         patch("src.services.paper_trade_executor.open_paper_position",
               side_effect=RuntimeError("boom")):
        opened = live.run_live_tick(symbols=["ETHUSDT"])  # must not raise
    assert opened == []


def test_run_live_tick_does_not_count_blocked_result_as_opened():
    candidate = _candidate(admitted=True, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=_quote()), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        mock_open.return_value = {"status": "blocked", "reason": "max_open_per_symbol"}
        opened = live.run_live_tick(symbols=["ETHUSDT"])
    assert opened == []


def test_run_live_tick_books_buy_at_ask_not_candle_close():
    """2026-08-17 (trading-safety-agent review): the fill price must be the
    live ask for a BUY, not signal.reference_price (candle close) -- the
    earlier version of this function silently used the candle close even
    when quote_source=="live", biasing evidence quality."""
    candidate = _candidate(admitted=True, quote_source="live", side="BUY")
    quote = _quote(bid=1990.0, ask=2010.0)
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=quote), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        mock_open.return_value = {"status": "opened", "trade_id": "t1"}
        live.run_live_tick(symbols=["ETHUSDT"])
    booked_price = mock_open.call_args.args[1]
    assert booked_price == 2010.0  # ask, not candidate.signal.reference_price (2000.0)


def test_run_live_tick_books_sell_at_bid_not_candle_close():
    candidate = _candidate(admitted=True, quote_source="live", side="SELL")
    quote = _quote(bid=1990.0, ask=2010.0)
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=quote), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        mock_open.return_value = {"status": "opened", "trade_id": "t1"}
        live.run_live_tick(symbols=["ETHUSDT"])
    booked_price = mock_open.call_args.args[1]
    assert booked_price == 1990.0  # bid, not candidate.signal.reference_price


def test_run_live_tick_skips_when_live_quote_aged_out_between_eval_and_open():
    """Race guard: quote_source=="live" at evaluation time does not
    guarantee the quote is still fresh a moment later -- fail closed
    (skip) rather than silently falling back to the candle close."""
    candidate = _candidate(admitted=True, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=None), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open:
        opened = live.run_live_tick(symbols=["ETHUSDT"])
    mock_open.assert_not_called()
    assert opened == []


def test_run_live_tick_multiple_symbols_each_evaluated():
    candidate = _candidate(admitted=False, quote_source="live")
    with patch.object(live, "evaluate_symbol", return_value=[candidate]) as mock_eval, \
         patch.object(live, "ensure_registered"), \
         patch("src.services.paper_trade_executor.open_paper_position"):
        live.run_live_tick(symbols=["ETHUSDT", "ADAUSDT", "SOLUSDT"])
    assert mock_eval.call_count == 3


# ---------------------------------------------------------------------------
# start_live_pipeline_thread -- default-disabled gating
# ---------------------------------------------------------------------------

def test_pipeline_thread_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PAPER_P0_8_PLUS_LIVE_ENABLED", raising=False)
    thread = live.start_live_pipeline_thread()
    assert thread is None


def test_pipeline_thread_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_LIVE_ENABLED", "false")
    thread = live.start_live_pipeline_thread()
    assert thread is None


def test_pipeline_thread_starts_when_enabled(monkeypatch):
    """2026-08-17 (reviewer-agent finding C9): thread.start() returns
    before the daemon thread necessarily reaches its first run_live_tick()
    call -- without synchronization, the `with patch.object(...)` block
    could exit (un-patching run_live_tick) before that first call happens,
    letting the REAL run_live_tick execute unmocked in a background
    thread (real registry mutation, outbound Binance REST). Block on an
    Event set from inside the mock so the patch is guaranteed to still be
    active when the call actually happens."""
    monkeypatch.setenv("PAPER_P0_8_PLUS_LIVE_ENABLED", "true")
    called = threading.Event()

    def _fake_tick(*args, **kwargs):
        called.set()
        return []

    with patch.object(live, "run_live_tick", side_effect=_fake_tick):
        thread = live.start_live_pipeline_thread(interval_s=9999)
        assert thread is not None
        assert thread.daemon is True
        assert called.wait(timeout=5.0), "run_live_tick was not called while still mocked"


# ---------------------------------------------------------------------------
# Integration: _map_to_legacy_signal output through a REAL open_paper_position()
#
# 2026-08-17 (reviewer-agent finding C8): every other test mocks
# open_paper_position(), which cannot see field-mapping bugs the executor
# itself would reject/mishandle (e.g. finding C5's p0_gate_reason placed in
# the wrong dict). This test runs the real executor and empirically pins
# what actually ends up on the stored position, including the disclosed
# P0.3C attribution-overwrite behavior (finding C6) and 0.3x sizing
# consequence (finding C7) -- documenting real, observed behavior rather
# than asserting on the mapping function's intermediate output alone.
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_positions():
    reset_paper_positions()
    yield
    reset_paper_positions()


def test_live_pipeline_signal_opens_a_real_paper_position(clean_positions, monkeypatch):
    """IMPORTANT DISCOVERY while writing this test (goes beyond reviewer-
    agent's C3): PAPER_TP_ZONE_BPS is set in this deployment's .env (35/25
    bps) -- and paper_trade_executor.py's env-override block
    unconditionally supersedes extra["tp_from_executor"]/["sl_from_executor"]
    whenever that var is set (paper_trade_executor.py, "V10.27 CYCLE 7"
    block), regardless of source. This is PRE-EXISTING behavior shared by
    every other caller of the tp_from_executor path, not something this
    patch introduced (the code's own 2026-08-14 comment on that block
    already says "this path is currently superseded in production by the
    env-override block"). Net effect: in the current deployment, this
    pipeline's strategy-specific TP/SL geometry (and therefore this test's
    C3 re-anchoring fix) has NO effect on the actually-stored TP/SL --
    every P0.8+ position gets the same global 35/25bps band as every other
    paper position. Unset the env var for the duration of this test so it
    actually exercises the tp_from_executor path meaningfully; the second
    test below pins the env-set (current production) behavior explicitly.
    """
    monkeypatch.delenv("PAPER_TP_ZONE_BPS", raising=False)
    monkeypatch.delenv("PAPER_SL_ZONE_BPS", raising=False)

    candidate = _candidate(admitted=True, quote_source="live", side="BUY", symbol="ETHUSDT")
    signal_dict, extra = live._map_to_legacy_signal(candidate, 2010.0)

    result = open_paper_position(
        signal_dict, 2010.0, 1_700_000_000.0,
        reason="P0_8_PLUS_EVIDENCE_COLLECTION",
        extra=extra,
    )

    assert result["status"] == "opened", result

    positions = get_paper_open_positions()
    stored = next(p for p in positions if p.get("trade_id") == result["trade_id"])

    # Reliable attribution (survives the executor's internal P0.3C reroute,
    # per _map_to_legacy_signal's docstring):
    assert stored.get("explore_bucket") == "P0_8_PLUS_EVIDENCE_COLLECTION"
    assert stored.get("training_bucket") == "P0_8_PLUS_EVIDENCE_COLLECTION"

    # TP/SL re-anchored to the booked price (2010.0), not the strategy's
    # raw reference-price-relative absolute prices (2030.0/1980.0) --
    # confirms the executor actually applied what extra["tp_from_executor"]
    # / ["sl_from_executor"] carried, on the real position-opening path,
    # when no env override is set to supersede it.
    assert stored["tp"] == pytest.approx(2040.0, rel=0.05)
    assert stored["sl"] == pytest.approx(1990.0, rel=0.05)

    # Entry price is the live-quote-crossed price this test passed in, not
    # the strategy's own candle-close reference_price (2000.0).
    assert stored["entry_price"] == pytest.approx(2010.0)


def test_live_pipeline_tp_sl_currently_superseded_by_env_override_in_production(clean_positions, monkeypatch):
    """Pins the CURRENT production reality (see docstring above): with
    PAPER_TP_ZONE_BPS/PAPER_SL_ZONE_BPS set (as this repo's .env does),
    the strategy-specific tp_from_executor/sl_from_executor mapping this
    module computes is entirely superseded -- every position opened here
    gets the same global band as every other paper position. Documenting
    this explicitly so a future .env change (removing the override) is the
    moment this pipeline's own TP/SL geometry silently becomes load-bearing
    for the first time -- exactly the scenario paper_trade_executor.py's
    own 2026-08-14 comment on this block warns about."""
    monkeypatch.setenv("PAPER_TP_ZONE_BPS", "35")
    monkeypatch.setenv("PAPER_SL_ZONE_BPS", "25")

    candidate = _candidate(admitted=True, quote_source="live", side="BUY", symbol="ETHUSDT")
    signal_dict, extra = live._map_to_legacy_signal(candidate, 2010.0)
    result = open_paper_position(
        signal_dict, 2010.0, 1_700_000_000.0,
        reason="P0_8_PLUS_EVIDENCE_COLLECTION",
        extra=extra,
    )
    assert result["status"] == "opened", result
    positions = get_paper_open_positions()
    stored = next(p for p in positions if p.get("trade_id") == result["trade_id"])
    # NOT the strategy's re-anchored 2040/1990 -- the global env band instead
    # (observed: ~2017, i.e. ~35bps above entry, not the ~149bps the
    # strategy's own target implied).
    assert abs(stored["tp"] - 2040.0) > 15.0, (
        f"expected the env override to dominate, got tp={stored['tp']} "
        f"(too close to the strategy's own re-anchored 2040.0)"
    )
