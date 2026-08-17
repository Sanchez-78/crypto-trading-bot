"""Tests for the 2026-08-17 fix in realtime_decision_engine.py:

1. `_try_discovery_admission()` -- extracted, shared helper for routing a
   rejected candidate through the P0-gated "starvation discovery"
   mechanism. Previously this logic was inlined ONLY in the
   REJECT_NEGATIVE_EV branch of evaluate_signal(); the SKIP_SCORE_HARD
   branch had its own unconditional `return None` and never reached it.
2. The new critical-idle escape hatch in the SKIP_SCORE_HARD branch: once
   idle time reaches 1800s, it calls the same shared helper instead of
   silently stalling forever.

See _workspace/28_hard_score_reject_bypasses_discovery_entirely.md for the
live evidence this closes: 66+ hours, zero trades, service reporting
healthy the whole time, because a persistently negative EV/score meant
nothing downstream of SKIP_SCORE_HARD ever got a chance to run.
"""
from unittest.mock import patch, MagicMock

import pytest

import src.services.realtime_decision_engine as rde


_BASE_SIGNAL = {"symbol": "ETHUSDT", "regime": "BEAR_TREND", "action": "SELL", "price": 1900.0}


def test_try_discovery_admission_opens_a_position_when_sampler_allows():
    """Happy path: P0 routes it through, sampler allows it, a paper
    position gets opened with the expected metadata."""
    routed_signal = dict(_BASE_SIGNAL, learning_source="paper_evidence_collection",
                          paper_source="paper_evidence_collection", segment_key="seg1",
                          p0_gate_reason="ok")
    with patch("src.services.realtime_decision_engine._route_training_sample_through_p0_rde",
               return_value=routed_signal) as mock_route, \
         patch("src.services.paper_training_sampler.maybe_open_training_sample",
               return_value={"allowed": True, "bucket": "PAPER_STARVATION_DISCOVERY",
                             "side_inferred": False, "cost_edge_ok": True}) as mock_sampler, \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open, \
         patch("src.services.paper_exploration.maybe_open_paper_exploration_from_reject") as mock_explore:
        rde._try_discovery_admission(
            dict(_BASE_SIGNAL), "SKIP_SCORE_HARD", "score_hard_floor", 0.01, -0.05,
        )

    mock_explore.assert_called_once()
    mock_route.assert_called_once()
    assert mock_route.call_args.kwargs["route_reason"] == "SKIP_SCORE_HARD"
    mock_sampler.assert_called_once()
    assert mock_sampler.call_args.kwargs["reason"] == "SKIP_SCORE_HARD"
    mock_open.assert_called_once()
    extra = mock_open.call_args.kwargs["extra"]
    assert extra["original_decision"] == "SKIP_SCORE_HARD"
    assert extra["reject_reason"] == "score_hard_floor"


def test_try_discovery_admission_does_not_open_when_p0_rejects():
    """If _route_training_sample_through_p0_rde returns None (P0 refused),
    no sampler call and no position ever gets attempted."""
    with patch("src.services.realtime_decision_engine._route_training_sample_through_p0_rde",
               return_value=None), \
         patch("src.services.paper_training_sampler.maybe_open_training_sample") as mock_sampler, \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open, \
         patch("src.services.paper_exploration.maybe_open_paper_exploration_from_reject"):
        rde._try_discovery_admission(
            dict(_BASE_SIGNAL), "REJECT_NEGATIVE_EV", "negative_ev", 0.01, -0.05,
        )

    mock_sampler.assert_not_called()
    mock_open.assert_not_called()


def test_try_discovery_admission_does_not_open_when_sampler_refuses():
    routed_signal = dict(_BASE_SIGNAL)
    with patch("src.services.realtime_decision_engine._route_training_sample_through_p0_rde",
               return_value=routed_signal), \
         patch("src.services.paper_training_sampler.maybe_open_training_sample",
               return_value={"allowed": False, "reason": "segment_confirmed_bad_skip_discovery"}), \
         patch("src.services.paper_trade_executor.open_paper_position") as mock_open, \
         patch("src.services.paper_exploration.maybe_open_paper_exploration_from_reject"):
        rde._try_discovery_admission(
            dict(_BASE_SIGNAL), "SKIP_SCORE_HARD", "score_hard_floor", 0.01, -0.05,
        )

    mock_open.assert_not_called()


def test_try_discovery_admission_never_raises_when_exploration_probe_fails():
    with patch("src.services.paper_exploration.maybe_open_paper_exploration_from_reject",
               side_effect=RuntimeError("boom")), \
         patch("src.services.realtime_decision_engine._route_training_sample_through_p0_rde",
               return_value=None):
        rde._try_discovery_admission(
            dict(_BASE_SIGNAL), "REJECT_NEGATIVE_EV", "negative_ev", 0.01, -0.05,
        )  # must not raise


def test_try_discovery_admission_never_raises_when_sampler_import_fails():
    routed_signal = dict(_BASE_SIGNAL)
    with patch("src.services.realtime_decision_engine._route_training_sample_through_p0_rde",
               return_value=routed_signal), \
         patch("src.services.paper_training_sampler.maybe_open_training_sample",
               side_effect=RuntimeError("boom")), \
         patch("src.services.paper_exploration.maybe_open_paper_exploration_from_reject"):
        rde._try_discovery_admission(
            dict(_BASE_SIGNAL), "SKIP_SCORE_HARD", "score_hard_floor", 0.01, -0.05,
        )  # must not raise
