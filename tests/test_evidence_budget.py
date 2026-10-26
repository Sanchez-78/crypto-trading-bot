"""Stop-rule boundaries and immutable historical evidence, without runtime I/O."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from src.services.evidence_budget import decide_evidence_budget


@pytest.mark.parametrize("values,code", [
    ([], "CONTINUE"), ([-100], "CONTINUE"), ([-1] * 39, "CONTINUE"),
    ([-1] * 40, "STOP_NO_EDGE"), ([-1] * 150, "STOP_NO_EDGE"),
    ([0] * 149, "CONTINUE"), ([0] * 150, "STOP_BUDGET_EXHAUSTED"),
    ([1] * 150, "CONTINUE"), ([-1, 1] * 75, "STOP_BUDGET_EXHAUSTED"),
])
def test_ordered_boundaries(values, code):
    result = decide_evidence_budget(values)
    assert result.code == code and result.allowed == (code == "CONTINUE")
    assert result.n == len(values)


def test_exact_zero_bounds_use_strict_upper_and_inclusive_lower():
    upper_zero = decide_evidence_budget([-2, 0], min_n=2, max_n=3, z=1)
    assert upper_zero.upper_bound_bps == 0 and upper_zero.code == "CONTINUE"
    lower_zero = decide_evidence_budget([0, 2], min_n=2, max_n=2, z=1)
    assert lower_zero.lower_bound_bps == 0 and lower_zero.code == "STOP_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("value", [None, "1", True, 1j, float("nan"), float("inf"), -float("inf"), 10**1000])
def test_invalid_history_even_before_warmup(value):
    result = decide_evidence_budget([value])
    assert not result.allowed and result.code == "INVALID_HISTORY"
    assert result.mean_net_bps is None and result.upper_bound_bps is None


@pytest.mark.parametrize("kwargs", [dict(min_n=1), dict(min_n=True), dict(min_n=50, max_n=40),
                                   dict(max_n=150.0), dict(z=0), dict(z=True), dict(z=float("inf")),
                                   dict(z=10**1000)])
def test_invalid_policy_fails_closed(kwargs):
    assert decide_evidence_budget([1] * 40, **kwargs).code == "INVALID_HISTORY"


def test_nonfinite_computed_bounds_fail_closed():
    assert decide_evidence_budget([-1.7e308, 1.7e308], min_n=2).code == "INVALID_HISTORY"


def test_zero_deviation_and_no_sample_information():
    flat = decide_evidence_budget([3] * 40)
    assert flat.mean_net_bps == flat.upper_bound_bps == flat.lower_bound_bps == 3
    assert decide_evidence_budget([]).mean_net_bps is None
    assert decide_evidence_budget([3]).upper_bound_bps is None


def test_deterministic_immutable_decision_and_unchanged_input():
    values = [-10, 5] * 30
    before = list(values)
    decision = decide_evidence_budget(values)
    assert decide_evidence_budget(values) == decision and values == before
    with pytest.raises(FrozenInstanceError):
        decision.allowed = True


def test_supplied_epoch_evidence_stops_mean_reversion_but_not_cold_breakout():
    path = Path(__file__).resolve().parents[1] / "docs/codex_prompts/evidence/epoch_20260925_closed_trades.json"
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    results = {source: decide_evidence_budget([row["pnl_pct"] * 100 for row in rows if row["learning_source"] == source])
               for source in ("sideways_mean_reversion_v1", "volatility_breakout_v1")}
    stopped = results["sideways_mean_reversion_v1"]
    assert stopped.n == 57 and stopped.code == "STOP_NO_EDGE" and not stopped.allowed
    assert stopped.upper_bound_bps == pytest.approx(-5.6367682215)
    continuing = results["volatility_breakout_v1"]
    assert continuing.n == 25 and continuing.code == "CONTINUE" and continuing.allowed
