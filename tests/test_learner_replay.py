"""Walk-forward learner replay on synthetic trades with known structure."""
from __future__ import annotations

import random

import pytest

from src.services import learner_replay as lr

BASE = 1_800_000_000_000


@pytest.fixture(autouse=True)
def fast_bootstrap(monkeypatch):
    monkeypatch.setattr(lr, "BOOTSTRAP_REPLICATES", 200)


STEP = 600_000  # 10 min between entries -> enough 6 h bootstrap blocks


def make(rows, step=STEP):
    return [lr.Trade(f"t{i}", BASE + i * step, BASE + i * step + 30_000, net, feats)
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
    # second trade enters 10 min after the first, which closed after 30 s -> sees +100
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


LATER = 30 * lr.DAY_MS


def test_preregistered_scores_only_first_final_n_fresh_trades():
    trades = persistent(2000)
    cut = trades[600].entry_ms
    result = lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=cut + LATER)
    assert result["fresh_n"] == 1399
    # persistent structure -> contrarian ranking is clearly harmful
    assert result["verdict"] == "CONTRARIAN_REFUTED"
    assert result["scored_last_entry_ms"] == trades[600 + lr.PREREGISTERED_FINAL_N].entry_ms
    # a later look over more data scores exactly the same fixed set
    later = lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=cut + 2 * LATER)
    assert later["variants"] == result["variants"]


def test_preregistered_is_pending_and_blind_before_fixed_end():
    trades = persistent(2000)
    cut = trades[600].entry_ms
    too_soon = lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=cut + 6 * lr.DAY_MS)
    assert too_soon["verdict"] == "PENDING" and too_soon["variants"] is None
    late_cut = trades[1500].entry_ms
    too_few = lr.evaluate_preregistered(trades, scored_after_ms=late_cut, now_ms=late_cut + LATER)
    assert too_few["verdict"] == "PENDING" and too_few["variants"] is None


def test_validation_fails_closed():
    good = persistent(10)
    dup = good + [good[0]]
    with pytest.raises(ValueError, match="duplicate"):
        lr.evaluate(dup)
    with pytest.raises(ValueError, match="duplicate"):
        lr.evaluate_preregistered(dup, scored_after_ms=0, now_ms=LATER)
    zero = [lr.Trade("z", BASE, BASE, 123.0, feats("a"))]
    with pytest.raises(ValueError, match="invalid"):
        lr.evaluate(zero)
    with pytest.raises(ValueError, match="invalid"):
        lr.evaluate_preregistered(zero, scored_after_ms=0, now_ms=LATER)


def test_same_millisecond_close_is_not_available():
    trades = [lr.Trade("a", BASE, BASE + 1000, 80.0, feats("a")),
              lr.Trade("b", BASE + 1000, BASE + 2000, 0.0, feats("a"))]
    assert lr.replay(trades, lr.Variant("x", ("symbol",), None, prior_weight=0.0))[1] == 0.0


def test_anti_persistent_structure_confirms_contrarian():
    rng = random.Random(4)
    rows, state = [], {f"c{k}": 0.0 for k in range(6)}
    for i in range(1700):
        c = f"c{rng.randrange(6)}"
        net = -state[c] + rng.gauss(0, 3)   # outcome reverses the context's recent level
        state[c] = 0.7 * state[c] + 0.3 * net * 4
        rows.append((net, feats(c)))
    trades = make(rows)
    cut = trades[500].entry_ms
    result = lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=cut + LATER)
    assert result["verdict"] == "CONTRARIAN_CONFIRMED"
    assert result["variants"]["C1_contrarian"]["lift_bps"] > 1


def test_invalid_trade_fails_closed():
    with pytest.raises(ValueError):
        lr.evaluate([lr.Trade("x", BASE, BASE - 1, 0.0, feats("a"))])


def test_pending_until_every_earlier_trade_must_be_closed():
    trades = persistent(2000)
    cut = trades[600].entry_ms
    last_scored = trades[600 + lr.PREREGISTERED_FINAL_N].entry_ms
    days7 = cut + 7 * lr.DAY_MS
    now = max(days7, last_scored + lr.COMPLETE_MARGIN_MS - 1)
    assert lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=now)["verdict"] == "PENDING"
    ok = lr.evaluate_preregistered(trades, scored_after_ms=cut, now_ms=max(days7, last_scored + lr.COMPLETE_MARGIN_MS))
    assert ok["verdict"] != "PENDING"
    assert len(ok["scored_trade_ids"]) == lr.PREREGISTERED_FINAL_N


def test_fast_pace_extends_scored_set_to_cover_min_blocks():
    """1000 trades in ~17 h would give < 16 blocks: stay PENDING, then score more trades."""
    base = persistent(6500)
    dense = make([(t.net_bps, dict(t.features)) for t in base], step=60_000)  # 60 trades/hour
    cut = dense[100].entry_ms
    early = lr.evaluate_preregistered(dense[:1500], scored_after_ms=cut, now_ms=cut + LATER)
    assert early["verdict"] == "PENDING" and early["variants"] is None
    full = lr.evaluate_preregistered(dense, scored_after_ms=cut, now_ms=cut + LATER)
    assert full["verdict"] != "PENDING"
    assert len(full["scored_trade_ids"]) > lr.PREREGISTERED_FINAL_N
    assert full["variants"]["C1_contrarian"]["day_bootstrap"]["blocks"] >= lr.MIN_BLOCKS
