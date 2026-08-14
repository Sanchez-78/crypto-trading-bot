"""Tests for the 2026-08-14 evidence-based fix in
src/services/paper_training_sampler.py's maybe_open_training_sample():
once a segment has been explored enough (segment_n>=20, matching
paper_adaptive_learning._update_segment_policy's own threshold) and its
learned weight has bottomed out at the 0.25 downweight floor, stop opening
more PAPER_STARVATION_DISCOVERY samples in it.

See _workspace/24_starvation_discovery_dominates_wr.md for the live
evidence this closes: PAPER_STARVATION_DISCOVERY was 89% of all trade
volume (rolling100 breakdown) with WR=11.2%, vs 33.3% on the EV-gated
A_STRICT_TAKE path (6% of volume) -- and neither of the two existing
cooldown mechanisms (_bootstrap_discovery_cooldown_from_learner,
_bootstrap_segment_cooldowns_from_learner) actually covers this: the first
requires pf==0.0 exactly (never true with any real wins present), the
second is scoped only to admission_bucket=="C_WEAK_EV_TRAIN".
"""
import time
from unittest.mock import patch, MagicMock

import pytest

import src.services.paper_training_sampler as pts
from src.services.paper_training_sampler import maybe_open_training_sample


@pytest.fixture
def clean_sampler_state():
    """Minimal isolation for the sampler module-level state this test
    touches (mirrors tests/test_p11ap_o2_starvation_discovery.py's fixture,
    scoped down to what these tests need)."""
    for attr in ["_entry_times_minute", "_entry_times_hour"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()
    for attr in ["_recent_dedupe", "_recent_dup_candidate"]:
        obj = getattr(pts, attr, None)
        if hasattr(obj, "clear"):
            obj.clear()
    pts._starvation_discovery_state["open_global"] = 0
    pts._starvation_discovery_state["open_by_symbol"] = {}
    pts._starvation_discovery_state["entry_times_15m"].clear()
    pts._starvation_discovery_state["last_eligible_entry_ts"] = 0.0
    pts._starvation_discovery_state["idle_s"] = 0.0
    pts._STARVATION_DISCOVERY_BUCKET_COOLDOWN = {
        "active": False, "activated_at": 0.0, "cooldown_s": 3600,
        "cooldown_until": 0.0, "closed_n_trigger": 3, "pf_trigger": 0.0,
        "avg_pnl_trigger": -0.10, "timeout_rate_trigger": 0.66,
    }
    pts._SEGMENT_COOLDOWNS = {}
    yield


def _fake_learner(rolling100_entries, segment_weights):
    learner = MagicMock()
    learner.rolling100 = rolling100_entries
    learner.segment_weights = segment_weights
    return learner


_BASE_SIGNAL = {
    "symbol": "BTCUSDT",
    "action": "BUY",
    "regime": "BEAR_TREND",
    "ev": -0.015,
    "score": 0.30,
    "p": 0.60,
    "coherence": 0.75,
    "auditor_factor": 0.85,
}
_SEG_KEY = "BTCUSDT:BEAR_TREND:BUY"


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
def test_skips_admission_for_confirmed_bad_segment(mock_idle, mock_training, mock_cold, clean_sampler_state):
    """segment_n>=20 and weight at the 0.25 floor -> refused, not opened."""
    entries = [(-0.5, "LOSS", _SEG_KEY, time.time())] * 25
    learner = _fake_learner(entries, {_SEG_KEY: 0.25})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is False
    assert result.get("reason") == "segment_confirmed_bad_skip_discovery"
    assert result.get("size_mult") == 0.0


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_allows_admission_when_segment_not_yet_confirmed(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """segment_n<20 (still exploring) -> the skip does NOT trigger, normal
    aggressive-mode admission proceeds -- the discovery/learning function
    itself must be preserved for segments without a confident verdict yet."""
    entries = [(-0.5, "LOSS", _SEG_KEY, time.time())] * 5  # below the 20 threshold
    learner = _fake_learner(entries, {_SEG_KEY: 0.25})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is True
    assert result.get("reason") != "segment_confirmed_bad_skip_discovery"


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_allows_admission_when_weight_above_floor(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """segment_n>=20 but weight only partially downweighted (e.g. 0.5, not
    yet at the 0.25 floor) -> not confirmed-bad enough, still admitted."""
    entries = [(-0.5, "LOSS", _SEG_KEY, time.time())] * 25
    learner = _fake_learner(entries, {_SEG_KEY: 0.5})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is True
    assert result.get("reason") != "segment_confirmed_bad_skip_discovery"


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_different_segment_unaffected(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """A confirmed-bad weight for one segment must not affect a different
    symbol:regime:side combination."""
    other_key = "ETHUSDT:BULL_TREND:SELL"
    entries = [(-0.5, "LOSS", other_key, time.time())] * 25
    learner = _fake_learner(entries, {other_key: 0.25})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is True
    assert result.get("reason") != "segment_confirmed_bad_skip_discovery"


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_learner_lookup_error_fails_open_not_closed(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """If the segment-weight lookup itself raises (e.g. learner state
    corrupted), the check must fail OPEN (log a warning, fall through to
    normal aggressive-mode admission) rather than blocking all discovery
    admission on an unrelated internal error."""
    with patch("src.services.paper_adaptive_learning.get_learner", side_effect=RuntimeError("boom")):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is True
    assert result.get("reason") != "segment_confirmed_bad_skip_discovery"


# ---------------------------------------------------------------------------
# 2026-08-14 SAFETY VALVE regression tests
# (_workspace/27_starvation_skip_caused_total_admission_stall.md): the skip
# above, deployed alone, drove the bot to zero opened positions for a full
# hour once most of the (small, ~8-segment) universe crossed the
# confirmed-bad threshold simultaneously. Bypass the skip once
# starvation-discovery idle time reaches the same 900s "critical idle"
# threshold bot2/main.py's pre-existing watchdog already escalates on.
# ---------------------------------------------------------------------------

@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_safety_valve_bypasses_skip_at_critical_idle(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """A confirmed-bad segment (would normally be skipped) is admitted
    anyway once idle_s crosses the 900s critical-idle threshold -- total
    admission stall is a worse outcome than the WR drag the skip fixes."""
    # maybe_open_training_sample() resets idle_s to 0 on its own if
    # last_eligible_entry_ts reads as the "never set" sentinel (0.0) -- set
    # both fields consistently so that fresh-startup reset doesn't fire.
    pts._starvation_discovery_state["last_eligible_entry_ts"] = time.time() - 950.0
    pts._starvation_discovery_state["idle_s"] = 950.0  # past the 900s threshold
    entries = [(-0.5, "LOSS", _SEG_KEY, time.time())] * 25
    learner = _fake_learner(entries, {_SEG_KEY: 0.25})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is True
    assert result.get("reason") != "segment_confirmed_bad_skip_discovery"


@patch("src.services.paper_training_sampler._is_cold_start_starvation", return_value=False)
@patch("src.services.paper_training_sampler._is_training_enabled", return_value=True)
@patch("src.services.paper_training_sampler._is_starvation_discovery_idle", return_value=True)
@patch("src.services.paper_training_sampler._training_quality_gate", return_value={"allowed": True, "reason": "ok"})
def test_safety_valve_does_not_bypass_below_the_idle_threshold(mock_gate, mock_idle, mock_training, mock_cold, clean_sampler_state):
    """Just below the 900s threshold, the skip still applies normally --
    the safety valve is a last resort, not a general loophole."""
    pts._starvation_discovery_state["idle_s"] = 899.0
    entries = [(-0.5, "LOSS", _SEG_KEY, time.time())] * 25
    learner = _fake_learner(entries, {_SEG_KEY: 0.25})
    with patch("src.services.paper_adaptive_learning.get_learner", return_value=learner):
        result = maybe_open_training_sample(
            signal=dict(_BASE_SIGNAL), ctx={}, reason="REJECT_NEGATIVE_EV",
            current_price=45000.0,
        )
    assert result.get("allowed") is False
    assert result.get("reason") == "segment_confirmed_bad_skip_discovery"
