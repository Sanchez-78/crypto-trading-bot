import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
SPEC = importlib.util.spec_from_file_location("event_shock_screen", ROOT / "scripts" / "research" / "event_shock_screen.py")
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

MIN = m.MINUTE
T0 = m.ff.stamp("2024-03-01")


def bars_from(closes, start=T0, missing=()):
    times = start + MIN * np.arange(len(closes))
    frame = pd.DataFrame({"time": times, "open": closes, "high": closes, "low": closes, "close": closes,
                          "volume": np.ones(len(closes)), "taker": np.zeros(len(closes))})
    frame = frame.drop(index=list(missing)).reset_index(drop=True)
    return m.minute_frame(frame)


def test_grid_is_fixed_and_unique():
    ids = [c.id for c in m.grid()]
    assert len(ids) == 20 == len(set(ids))
    assert sum(i.startswith("E1_") for i in ids) == 12 and sum(i.startswith("E2_") for i in ids) == 8
    assert (m.SEED, m.BOOT, m.COST, m.MIN_TRAIN_N, m.LEAD_N) == (20261126, 2000, 9.0, 200, {"TEST": 200, "HOLDOUT": 100})
    assert (m.START, m.TRAIN_END, m.TEST_START, m.TEST_END, m.HOLDOUT_START) == (
        "2024-01-01", "2025-07-01", "2025-07-02", "2026-04-01", "2026-04-02")


def test_realized_return_timing_missing_bar_and_block_end():
    closes = 100 * np.exp(np.arange(30) * 1e-3)
    bars = bars_from(closes)
    entry = T0 + 5 * MIN
    expected = 1e4 * math.log(closes[5 + 10 - 1] / closes[5])     # open == close in this fixture
    assert m.realized_bps(bars, entry, 10, 1, T0 + 100 * MIN) == pytest.approx(expected)
    assert m.realized_bps(bars, entry, 10, -1, T0 + 100 * MIN) == pytest.approx(-expected)
    assert m.realized_bps(bars, entry, 10, 1, entry + 10 * MIN - 1) is None   # crosses the block end
    gap = bars_from(closes, missing=(9,))
    assert m.realized_bps(gap, entry, 10, 1, T0 + 100 * MIN) is None


def _shock_series(days=9, shock_at=None, size=0.03):
    n = days * 1440
    rng = np.random.default_rng(3)
    logp = np.cumsum(rng.normal(0, 2e-4, n))
    vol = np.ones(n)
    if shock_at is not None:
        logp[shock_at:] += size
        vol[shock_at - 2:shock_at + 3] = 50.0
    closes = 100 * np.exp(logp)
    frame = pd.DataFrame({"time": T0 + MIN * np.arange(n), "open": closes, "high": closes, "low": closes,
                          "close": closes, "volume": vol, "taker": np.zeros(n)})
    return m.minute_frame(frame), closes


def test_e1_signal_uses_completed_bars_and_enters_two_minutes_later():
    shock = 8 * 1440 + 100
    bars, closes = _shock_series(shock_at=shock)
    feats = m.e1_features(bars)
    assert feats.z_r5.iloc[: 7 * 1440].isna().all()                  # 7-day warm-up only
    cfg_fade = m.Config("E1", 3, "fade", 60)
    out = m.e1_samples("BTCUSDT", bars, feats, cfg_fade, T0 + 7 * 1440 * MIN, T0 + 10 * 1440 * MIN)
    assert out, "shock must trigger"
    first = out[0]
    assert first["decision_ms"] >= T0 + shock * MIN                  # not before the shock bar is complete
    assert first["side"] == -1                                       # fade an up-shock
    entry = first["decision_ms"] + 2 * MIN
    i = (entry - T0) // MIN
    assert first["r"] == pytest.approx(-1e4 * math.log(closes[i + 59] / closes[i]))
    follow = m.e1_samples("BTCUSDT", bars, feats, m.Config("E1", 3, "follow", 60), T0 + 7 * 1440 * MIN, T0 + 10 * 1440 * MIN)
    assert follow[0]["side"] == 1 and follow[0]["r"] == pytest.approx(-first["r"])
    # one open sample per symbol: the next signal starts only after the exit
    times = [s["decision_ms"] for s in out]
    assert all(b + 2 * MIN >= a + 2 * MIN + 60 * MIN for a, b in zip(times, times[1:]))


def _funding(times, rates, interval=8):
    return pd.DataFrame({"time": np.asarray(times, dtype="int64"), "funding_interval_hours": interval,
                         "funding": np.asarray(rates, dtype=float)})


def test_e2_uses_only_available_funding_and_fixed_windows():
    hours8 = 8 * 3_600_000
    times = [T0 + i * hours8 for i in range(40)]
    rates = [1e-4] * 39 + [5e-3]                                   # last settlement extreme
    rates[-2] = 4e-3                                                # previous one extreme as well
    fund = _funding(times, rates)
    bars, _ = _shock_series(days=15)
    cfg = m.Config("E2", 2, "fade", 60, "pre")
    out = m.e2_samples("ETHUSDT", bars, fund, cfg, T0, T0 + 15 * 1440 * MIN)
    # settlement 39 (T = times[39]): decision T-62m; newest AVAILABLE rate is #37 (available at times[38]),
    # rate #38 becomes available only at times[39] > decision -> 4e-3 at index 38 is NOT yet usable.
    last = times[39]
    assert all(s["decision_ms"] != last - 62 * MIN for s in out)    # #37 = 1e-4, not extreme -> no signal
    post = m.e2_samples("ETHUSDT", bars, fund, m.Config("E2", 2, "fade", 120, "post"), T0, T0 + 15 * 1440 * MIN)
    for s in post:
        assert s["decision_ms"] % MIN == 0
    avail = m.funding_available(fund)
    assert avail.available_ms.iloc[0] == times[0] + hours8


def test_e2_signal_side_and_lookback():
    hours8 = 8 * 3_600_000
    times = [T0 + i * hours8 for i in range(45)]
    rates = list(1e-4 + 1e-6 * np.sin(np.arange(45)))
    rates[40] = 5e-3                                                # available from times[41]
    fund = _funding(times, rates)
    bars, _ = _shock_series(days=17)
    pre = m.e2_samples("ETHUSDT", bars, fund, m.Config("E2", 2, "fade", 60, "pre"), T0, T0 + 17 * 1440 * MIN)
    hit = [s for s in pre if s["decision_ms"] == times[42] - 62 * MIN]
    assert hit and hit[0]["side"] == -1                              # fade positive (crowded long) funding
    follow = m.e2_samples("ETHUSDT", bars, fund, m.Config("E2", 2, "follow", 60, "pre"), T0, T0 + 17 * 1440 * MIN)
    assert [s for s in follow if s["decision_ms"] == times[42] - 62 * MIN][0]["side"] == 1


def _samples(values, start=T0, per_day=5, symbols=("BTCUSDT", "ETHUSDT")):
    rows = []
    for i, v in enumerate(values):
        rows.append({"symbol": symbols[i % len(symbols)], "decision_ms": start + (i // per_day) * m.DAY + i % per_day * MIN,
                     "side": 1 if i % 2 else -1, "r": v, "market": "UP" if i % 2 else "DOWN"})
    return pd.DataFrame(rows)


def test_stats_ci_and_lead_rules():
    good = _samples([25.0 + (i % 5) for i in range(400)])
    end = T0 + 90 * m.DAY
    st = m.stats(good, T0, end)
    assert st["n"] == 400 and st["net9_bps"] == pytest.approx(27 - 9) and st["ci95_net9"][0] > 0
    st["p_holm"] = 0.01
    assert m.lead_failures(st, "TEST") == []
    flat = m.stats(_samples([9.0 + ((-1) ** i) * 20 for i in range(400)]), T0, end)
    flat["p_holm"] = 0.5
    reasons = m.lead_failures(flat, "TEST")
    assert "net9_not_above_3" in reasons and "ci_not_positive" in reasons and "holm_not_significant" in reasons
    one_symbol = m.stats(_samples([30.0] * 300, symbols=("SOLUSDT",)), T0, end)
    one_symbol["p_holm"] = 0.01
    assert "symbol_concentration" in m.lead_failures(one_symbol, "HOLDOUT")
    empty = m.stats(_samples([]).reindex(columns=["symbol", "decision_ms", "side", "r", "market"]), T0, end)
    assert empty["n"] == 0 and empty["ci95_net9"] is None


def test_selection_requires_200_and_breaks_ties_by_id():
    st = {"E1_a": {"n": 250, "net9_bps": -2.0}, "E1_b": {"n": 250, "net9_bps": -2.0},
          "E1_c": {"n": 150, "net9_bps": 50.0}, "E2_x": {"n": 199, "net9_bps": 10.0}}
    assert m.select(st) == {"E1": "E1_a", "E2": None}


def _zip_csv(path, frame, header=True):
    import io, zipfile, hashlib
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(path.stem + ".csv", frame.to_csv(index=False, header=header))
    path.write_bytes(buf.getvalue())
    return hashlib.sha256(buf.getvalue()).hexdigest()


def test_block_samples_plumbing_on_a_fake_archive_cache(tmp_path):
    rng = np.random.default_rng(5)
    manifest = []
    for month in ("2024-01", "2024-02"):
        start = m.ff.stamp(month + "-01")
        stop = m.ff.stamp("2024-02-01" if month == "2024-01" else "2024-03-01")
        t = np.arange(start, stop, MIN)
        p = 100 * np.exp(np.cumsum(rng.normal(0, 3e-4, len(t))))
        p[len(p) // 2:] *= 1.02                                   # one shock
        vol = np.ones(len(t)); vol[len(p) // 2 - 2: len(p) // 2 + 3] = 80
        kl = pd.DataFrame({"open_time": t, "open": p, "high": p, "low": p, "close": p, "volume": vol,
                           "close_time": t + MIN - 1, "quote_volume": vol, "count": 1, "taker_buy_volume": vol / 2,
                           "taker_buy_quote_volume": vol / 2, "ignore": 0})
        key = m.ff.archive_key("futures", "BTCUSDT", month)
        manifest.append({"kind": "futures", "symbol": "BTCUSDT", "period": month, "key": key, "status": "OK",
                         "sha256": _zip_csv(tmp_path / key, kl)})
        ft = np.arange(start, stop, 8 * 3_600_000)
        fr = pd.DataFrame({"calc_time": ft, "funding_interval_hours": 8,
                           "last_funding_rate": np.r_[np.full(len(ft) - 1, 1e-4), 3e-3]})
        fkey = m.ff.archive_key("funding", "BTCUSDT", month)
        manifest.append({"kind": "funding", "symbol": "BTCUSDT", "period": month, "key": fkey, "status": "OK",
                         "sha256": _zip_csv(tmp_path / fkey, fr)})
    out = m.block_samples(tmp_path, manifest, m.grid(), "2024-01-20", "2024-03-01")
    assert set(out) == {c.id for c in m.grid()}
    for frame in out.values():
        assert list(frame.columns) == ["symbol", "decision_ms", "side", "r", "market"]
        if len(frame):
            assert frame.decision_ms.min() >= m.ff.stamp("2024-01-20")
            assert set(frame.symbol) == {"BTCUSDT"}
    assert sum(len(f) for k, f in out.items() if k.startswith("E1_")) > 0
    st = {cid: m.stats(f, m.ff.stamp("2024-01-20"), m.ff.stamp("2024-03-01")) for cid, f in out.items()}
    assert set(m.select(st)) == {"E1", "E2"}


def test_null_bootstrap_p_value_behaves_as_a_test_of_mean_net9_above_zero():
    end = T0 + 120 * m.DAY
    rng = np.random.default_rng(11)
    strong = m.stats(_samples(list(9 + 15 + rng.normal(0, 20, 600))), T0, end)
    zero = m.stats(_samples(list(9 + rng.normal(0, 20, 600))), T0, end)
    negative = m.stats(_samples(list(9 - 15 + rng.normal(0, 20, 600))), T0, end)
    assert strong["p_one_sided"] < 0.01
    assert 0.05 < zero["p_one_sided"] < 0.95
    assert negative["p_one_sided"] > 0.99
    # explicit null: centred day sums give means exactly (bootstrap mean - observed mean)
    assert strong["bootstrap_valid"] == m.BOOT


def test_null_bootstrap_matches_an_independent_recentred_computation():
    end = T0 + 60 * m.DAY
    rng = np.random.default_rng(12)
    frame = _samples(list(12 + rng.normal(0, 15, 300)))
    st = m.stats(frame, T0, end)
    # independent re-implementation: subtract the observed mean from every sample, resample whole days
    net = frame["r"].to_numpy() - m.COST
    centred = net - net.mean()
    days = (frame.decision_ms.to_numpy() // m.DAY - T0 // m.DAY).astype(int)
    n_days = int(math.ceil(end / m.DAY) - T0 // m.DAY)
    counts = np.bincount(days, minlength=n_days).astype(float)
    sums = np.bincount(days, weights=centred, minlength=n_days)
    g = np.random.default_rng(m.SEED)
    nulls = []
    for begin in range(0, m.BOOT, 100):
        draw = g.integers(0, n_days, size=(min(100, m.BOOT - begin), n_days))
        den = counts[draw].sum(axis=1)
        nulls.append(sums[draw].sum(axis=1)[den > 0] / den[den > 0])
    nulls = np.concatenate(nulls)
    expected = (1 + np.count_nonzero(nulls >= net.mean())) / (len(nulls) + 1)
    assert st["p_one_sided"] == pytest.approx(expected)


def test_run_refuses_an_incomplete_archive_set_before_any_stage(tmp_path):
    manifest = [{"kind": k, "symbol": s, "period": p, "key": m.ff.archive_key(k, s, p), "status": "OK", "sha256": "x"}
                for k, s, p in m.expected_jobs("2024-02")]
    m.check_complete(manifest, "2024-02")                        # complete -> no exception
    assert len(manifest) == 7 * 2 * 2
    broken = [dict(r) for r in manifest]
    broken[3]["status"] = "NOT_FOUND"
    with pytest.raises(SystemExit, match="NOT_EVALUABLE"):
        m.check_complete(broken, "2024-02")
    with pytest.raises(SystemExit, match="NOT_EVALUABLE"):
        m.check_complete(manifest[:-1], "2024-02")
    # offline run on an empty cache stops before writing any stage file
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="NOT_EVALUABLE"):
        m.run(tmp_path / "empty_cache", out, "2024-02", offline=True)
    assert not (out / "train.json").exists() and not (out / "train.started.json").exists()
