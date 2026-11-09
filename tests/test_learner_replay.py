"""Walk-forward learner replay on synthetic trades with known structure."""
from __future__ import annotations

import random

import pytest

from src.services import learner_replay as lr

BASE = 1_800_000_000_000


def make(rows):
    return [lr.Trade(f"t{i}", BASE + i * 60_000, BASE + i * 60_000 + 30_000, net, feats)
            for i, (net, feats) in enumerate(rows)]


def feats(ctx):
    return {"source": "s", "symbol": ctx, "regime": "R", "side": "BUY", "hour6": "0", "pred_bucket": "NA"}


def persistent(n=1200, seed=1):
    rng = random.Random(seed)
    means = {f"c{k}": -12 + 3 * k for k in range(8)}
    return make([(means[c] + rng.gauss(0, 6), feats(c)) for c in (rng.choice(list(means)) for _ in range(n))])


def noise(n=1200, seed=2):
    rng = random.Random(seed)
    return make([(rng.gauss(-9, 18), feats(f"c{rng.randrange(8)}")) for _ in range(n)])


def test_no_lookahead_uses_only_closed_trades():
    trades = make([(100.0, feats("a")), (-100.0, feats("a"))])
    # second trade enters 60 s after the first, which closed after 30 s -> sees +100
    est = lr.replay(trades, lr.Variant("x", ("symbol",), None, prior_weight=0.0))
    assert est[0] == 0.0 and est[1] == pytest.approx(100.0)
    overlapping = [lr.Trade("a", BASE, BASE + 10_000, 50.0, feats("a")),
                   lr.Trade("b", BASE + 5_000, BASE + 6_000, 0.0, feats("a"))]
    assert lr.replay(overlapping, lr.Variant("x", ("symbol",), None, prior_weight=0.0))[1] == 0.0


def test_persistent_structure_gives_confirmed_holdout_lift():
    result = lr.evaluate(persistent())
    assert result["verdict"] == "HOLDOUT_LIFT_CONFIRMED"
    assert result["variants"]["V4_symbol_side"]["holdout"]["lift_bps"] > 5


def test_noise_is_not_confirmed():
    result = lr.evaluate(noise())
    assert result["verdict"] == "HOLDOUT_LIFT_NOT_CONFIRMED"


def test_contrarian_is_exact_negation_ranking():
    trades = persistent(400)
    v2 = lr.replay(trades, lr.Variant("a", lr.BASE_KEYS, None))
    c1 = lr.replay(trades, lr.Variant("b", lr.BASE_KEYS, None, sign=-1.0))
    assert c1 == [-x for x in v2]


def test_preregistered_scores_only_fresh_trades():
    trades = persistent(1000)
    cut = trades[600].entry_ms
    result = lr.evaluate_preregistered(trades, scored_after_ms=cut)
    assert result["fresh_n"] == 399
    # persistent structure -> contrarian ranking is clearly harmful
    assert result["verdict"] == "CONTRARIAN_REFUTED"
    assert lr.evaluate_preregistered(trades, scored_after_ms=trades[900].entry_ms)["verdict"] == "INSUFFICIENT_DATA"


def test_anti_persistent_structure_confirms_contrarian():
    rng = random.Random(4)
    rows, state = [], {f"c{k}": 0.0 for k in range(6)}
    for i in range(1500):
        c = f"c{rng.randrange(6)}"
        net = -state[c] + rng.gauss(0, 3)   # outcome reverses the context's recent level
        state[c] = 0.7 * state[c] + 0.3 * net * 4
        rows.append((net, feats(c)))
    trades = make(rows)
    result = lr.evaluate_preregistered(trades, scored_after_ms=trades[500].entry_ms)
    assert result["verdict"] == "CONTRARIAN_CONFIRMED"
    assert result["variants"]["C1_contrarian"]["lift_bps"] > 1


def test_invalid_trade_fails_closed():
    with pytest.raises(ValueError):
        lr.evaluate([lr.Trade("x", BASE, BASE - 1, 0.0, feats("a"))])
