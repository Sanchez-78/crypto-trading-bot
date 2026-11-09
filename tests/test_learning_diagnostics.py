"""Learning-precondition diagnostics on synthetic data with known structure."""
from __future__ import annotations

import random

import pytest

from src.services.learning_diagnostics import Observation, diagnose


def obs(context, net, *, action="ADAPTIVE", estimate=0.0, probability=0.3, gross=None, ts=0.0):
    return Observation(context, action, estimate, probability, net, net + 9 if gross is None else gross, ts)


def noise_only(seed=1, contexts=10, per=40):
    rng = random.Random(seed)
    rows, ts = [], 0.0
    for i in range(per):
        for c in range(contexts):
            ts += 1
            net = rng.gauss(-9, 18)
            rows.append(obs(f"c{c}", net, action="ADAPTIVE" if ts % 2 else "CONTROL",
                            estimate=rng.gauss(-9, 3), gross=net + 9, ts=ts))
    return rows


def structured(seed=2, contexts=10, per=40):
    """Contexts with large persistent offsets; learner estimate equals true offset."""
    rng = random.Random(seed)
    rows, ts = [], 0.0
    for i in range(per):
        for c in range(contexts):
            ts += 1
            true = -20 + 4 * c
            net = true + rng.gauss(0, 5)
            rows.append(obs(f"c{c}", net, action="ADAPTIVE" if ts % 2 else "CONTROL",
                            estimate=true, gross=net + 9, ts=ts))
    return rows


def test_pure_noise_fails_every_precondition():
    result = diagnose(noise_only(seed=2))
    assert result["reasons"][0] == "SIGNAL_NO_GROSS_EDGE"
    assert "CONTEXTS_NOISE_ONLY" in result["reasons"]
    assert "CONTEXTS_DO_NOT_PERSIST" in result["reasons"]
    assert "ESTIMATE_UNINFORMATIVE" in result["reasons"]
    assert result["context_dispersion"]["p_value"] > 0.05


def test_false_positive_rates_stay_near_five_percent():
    runs = [diagnose(noise_only(seed=s))["reasons"] for s in range(100, 200)]
    assert sum("CONTEXTS_DIFFER" in r for r in runs) <= 15
    assert sum("CONTEXTS_PERSIST" in r for r in runs) <= 12
    assert sum("ESTIMATE_RANKS_OUTCOMES" in r for r in runs) <= 12


def test_real_structure_is_detected():
    result = diagnose(structured())
    assert "CONTEXTS_DIFFER" in result["reasons"]
    assert "CONTEXTS_PERSIST" in result["reasons"]
    assert "ESTIMATE_RANKS_OUTCOMES" in result["reasons"]
    assert result["context_dispersion"]["ratio"] > 5
    assert result["context_dispersion"]["p_value"] < 1e-6
    assert result["estimate_vs_outcome"]["spearman"] > 0.8


def test_gross_edge_codes():
    positive = [obs("a", 5.0 + (i % 3), gross=20.0 + (i % 5), ts=i) for i in range(50)]
    negative = [obs("a", -5.0, gross=-20.0 - (i % 5), ts=i) for i in range(50)]
    assert diagnose(positive)["reasons"][0] == "SIGNAL_HAS_GROSS_EDGE"
    assert diagnose(negative)["reasons"][0] == "SIGNAL_NEGATIVE_GROSS"
    assert diagnose([obs("a", 1.0)])["reasons"][0] == "SIGNAL_INSUFFICIENT_DATA"


def test_small_contexts_are_insufficient_not_noise():
    rows = [obs(f"c{i % 30}", float(i % 7), ts=i) for i in range(60)]
    result = diagnose(rows)
    assert result["context_dispersion"] is None
    assert "CONTEXTS_INSUFFICIENT_DATA" in result["reasons"]
    assert "PERSISTENCE_INSUFFICIENT_DATA" in result["reasons"]


def test_learning_curve_quarters_and_trend():
    rows = []
    for q in range(4):
        for i in range(20):
            ts = q * 100 + i
            rows.append(obs("c", -10 + 4 * q, action="ADAPTIVE", ts=ts))
            rows.append(obs("c", -10, action="CONTROL", ts=ts + 0.5))
    result = diagnose(rows)
    diffs = [q["diff_bps"] for q in result["learning_curve"]]
    assert len(diffs) == 4 and diffs == pytest.approx([0, 4, 8, 12])
    assert "CURVE_IMPROVING" in result["reasons"]
    flat = [obs("c", -10, action=a, ts=i) for i, a in enumerate(["ADAPTIVE", "CONTROL"] * 40)]
    assert "CURVE_FLAT_OR_WORSE" in diagnose(flat)["reasons"]


def test_probe_and_warmup_handling():
    rows = [obs("c", float(i), action="WARMUP", estimate=float(i), ts=i) for i in range(200)]
    result = diagnose(rows)
    assert result["estimate_vs_outcome"]["n"] == 0
    assert result["adaptive_probability"] is None
    assert result["learning_curve"] == []


def test_invalid_observation_fails_closed():
    with pytest.raises(ValueError):
        diagnose([obs("c", float("nan"))])


def test_order_independent():
    rows = noise_only(seed=5)
    shuffled = rows[:]
    random.Random(9).shuffle(shuffled)
    assert diagnose(rows) == diagnose(shuffled)
