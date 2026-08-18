"""§22.7 Property Invariants (Evidence-First Strategy Expansion v2) --
one consolidated, explicitly-named suite for the document's required
invariant list, scoped to the P0.8+ pipeline.

Most of these invariants are ALREADY covered elsewhere in the suite
(cross-referenced below in each test's docstring) -- this file's job is
to make the document's own invariant list explicit and named in ONE
place (§22.7: "Add invariant tests" as a named category, not scattered
incidentally), and to close the two gaps found while auditing existing
coverage against the document's exact list: funding-observer-opens-zero
and signal-cannot-open-twice, neither of which had a dedicated test
anywhere in the repository as of 2026-08-18.
"""
import time
from unittest.mock import patch

import pytest

from src.services import p0_8_plus_live_pipeline as live
from src.services import strategy_contracts as sc
from src.services import strategy_funding_observer_v1 as funding_observer
from src.services.live_quote_cache_v1 import LastQuote
from src.services.p0_8_plus_shadow_evaluator import CandidateEvaluation
from src.services.paper_trade_executor import (
    get_paper_open_positions,
    open_paper_position,
    reset_paper_positions,
)


@pytest.fixture
def clean_positions():
    reset_paper_positions()
    yield
    reset_paper_positions()


# ---------------------------------------------------------------------------
# "funding observer opens zero positions"
# ---------------------------------------------------------------------------

def test_funding_observer_has_no_candidate_generation_function():
    """§15.1: 'It must not open a position.' Structural, not just
    behavioral -- this module has no generate_candidates() at all, so
    there is no candidate for signal_router.py to ever admit. Confirmed
    directly against the module's own public surface, not inferred."""
    assert not hasattr(funding_observer, "generate_candidates")


def test_funding_observer_module_does_not_import_strategy_signal_or_router():
    """Static confirmation (mirrors the module's own bypass-test
    discipline used by every other P0.8+ strategy) that this module
    cannot construct a StrategySignal or reach the router/executor.
    AST-based (not a raw substring search) -- the module's own docstring
    explains this invariant in prose, which would otherwise self-defeat a
    naive `"signal_router" not in source` check."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(funding_observer))
    forbidden = {"strategy_contracts", "signal_router", "open_paper_position", "paper_trade_executor"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    assert not (found & forbidden), f"forbidden import found: {found & forbidden}"


def test_funding_observer_is_not_registered_as_a_strategy():
    """§15.1: registering it would misrepresent it as a signal-producing
    strategy awaiting admission, which it structurally cannot be."""
    from src.services.strategy_registry import get_default_registry

    reg = get_default_registry()
    assert not reg.is_registered(funding_observer.STRATEGY_ID)


# ---------------------------------------------------------------------------
# "one signal cannot open twice"
# ---------------------------------------------------------------------------

def _signal(signal_id="sig-dup-1", **overrides):
    fields = dict(
        signal_id=signal_id,
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
        exit_profile="dynamic_trend_exit_v1",
        feature_schema_version="v1",
    )
    fields.update(overrides)
    return sc.StrategySignal(**fields)


def _evaluation(signal_id="sig-dup-1") -> sc.SignalEvaluation:
    return sc.SignalEvaluation(
        signal_id=signal_id, admitted=True, decision_code="P0_ADMIT_EVIDENCE_COLLECTION",
        decision_reasons=("ok",), gross_expected_move_bps=30.0, expected_cost_bps=8.0,
        uncertainty_buffer_bps=5.0, net_expected_edge_bps=17.0,
        p0_segment_key="ETHUSDT:BUY:BULL_TREND:trend_cost_aware_v1:dynamic_trend_exit_v1",
        p0_strict_ev=False, p0_readiness_eligible=False, risk_allowed=True, risk_reason="ok",
        evaluated_at_ms=1_700_000_000_500,
    )


def test_same_signal_id_processed_twice_is_capped_at_one_open_position(clean_positions):
    """The pipeline doesn't do signal_id-level dedup by itself (each real
    tick's signal_id is freshly timestamped, so exact collisions don't
    occur naturally) -- what actually prevents a runaway duplicate is the
    pre-existing exploration exposure cap (max 1 open position per
    symbol+bucket, paper_trade_executor._check_exploration_exposure_caps).
    This test proves that guarantee holds even in the adversarial case of
    the identical signal_id being evaluated twice in a row (e.g. a retry,
    a duplicate tick, a caller bug)."""
    candidate = CandidateEvaluation(
        symbol="ETHUSDT", strategy_id="trend_cost_aware", side="BUY",
        regime="BULL_TREND", regime_confidence=0.8,
        signal=_signal(), evaluation=_evaluation(), quote_source="live",
    )
    quote = LastQuote(symbol="ETHUSDT", bid=1999.0, ask=2001.0, price=2000.0, received_at_s=0.0)

    with patch.object(live, "evaluate_symbol", return_value=[candidate]), \
         patch.object(live, "ensure_registered"), \
         patch.object(live.live_quote_cache_v1, "get_last_quote", return_value=quote):
        opened_first = live.run_live_tick(symbols=["ETHUSDT"])
        opened_second = live.run_live_tick(symbols=["ETHUSDT"])  # same signal_id again

    total_opened = len(opened_first) + len(opened_second)
    open_positions = get_paper_open_positions()
    assert total_opened <= 1, f"expected at most 1 open from duplicate signal_id, got {total_opened}"
    assert len(open_positions) <= 1


def test_closed_position_cannot_be_closed_twice(clean_positions):
    """Cross-referenced with tests/test_paper_close_pipeline.py's existing
    coverage of this invariant for the legacy path -- pinned here
    explicitly for the P0.8+-sourced position shape too."""
    from src.services.paper_trade_executor import close_paper_position

    signal = {"symbol": "ETHUSDT", "action": "BUY", "ev": 0.02, "regime": "BULL_TREND",
              "learning_source": "trend_cost_aware_v1", "strict_ev": False, "readiness_eligible": False}
    result = open_paper_position(
        signal, 2000.0, time.time(), "P0_8_PLUS_EVIDENCE_COLLECTION",
        extra={"explore_bucket": "P0_8_PLUS_EVIDENCE_COLLECTION"},
    )
    assert result["status"] == "opened", result
    trade_id = result["trade_id"]

    first_close = close_paper_position(position_id=trade_id, price=2010.0, ts=time.time(), reason="TP")
    assert first_close is not None

    second_close = close_paper_position(position_id=trade_id, price=2010.0, ts=time.time(), reason="TP")
    assert second_close is None, "closing an already-closed position must be a no-op, not a second close record"


# ---------------------------------------------------------------------------
# "real-order function call count equals zero" -- cross-referenced with
# tests/test_audit_p0_correctness.py and the runtime_mode assertion
# (docs/P0_7_ACCEPTANCE.md); pinned here for the P0.8+ call path
# specifically.
# ---------------------------------------------------------------------------

def test_p0_8_plus_live_pipeline_module_has_no_real_order_reference():
    import inspect

    source = inspect.getsource(live)
    for forbidden in ("place_order", "create_order", "binance_client.order", "ENABLE_REAL_ORDERS=true"):
        assert forbidden not in source, f"found forbidden real-order reference: {forbidden!r}"
