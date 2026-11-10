"""Offline fixtures only: no bot imports, network, credentials or runtime state."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from scripts.research import futures_flow_screen as screen


@pytest.fixture
def market(tmp_path):
    n = 12 * 1440
    times = screen.stamp("2024-01-01") + np.arange(n) * screen.MINUTE
    x = np.arange(n)
    price = 100 + .0001 * x + .2 * np.sin(x / 17) + .1 * np.cos(x / 91)
    volume = 100 + 10 * np.sin(x / 7)
    frame = pd.DataFrame(dict(time=times, open=price, high=price * 1.0005,
                             low=price * .9995, close=price, volume=volume,
                             taker=volume * (.5 + .2 * np.sin(x / 11))))
    metrics = pd.DataFrame({"time": times[::5]})
    for i, key in enumerate(screen.METRICS):
        metrics[key] = 1000 + 100 * np.sin(np.arange(len(metrics)) / (5 + i)) if key.startswith("sum_open") else (
            1 + .2 * np.sin(np.arange(len(metrics)) / (5 + i)))
    funding = pd.DataFrame(dict(time=times[::480], funding_interval_hours=8,
                               funding=.0001 + .00003 * np.sin(np.arange(len(times[::480])))))
    # Evidence fixtures exist only under pytest's tmp_path.
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"start_ms": int(times[0]), "rows": n}), encoding="utf-8")
    return frame, frame.copy(), metrics, funding, frame.copy()


def test_future_observations_cannot_change_earlier_features(market):
    cut = screen.stamp("2024-01-11")
    original = screen.build_features(*market)
    changed = []
    for frame in market:
        copy = frame.copy()
        future = copy.time > cut
        columns = [key for key in copy if key not in ("time", "funding_interval_hours")]
        copy.loc[future, columns] *= 3
        changed.append(copy)
    actual = screen.build_features(*changed)
    boundary = pd.Timestamp(cut, unit="ms", tz="UTC")
    pd.testing.assert_frame_equal(actual.loc[:boundary], original.loc[:boundary])
    assert original.loc[:boundary, list(screen.FEATURES)].notna().sum().min() > 0
    prefix = [frame.loc[frame.time <= cut].copy() for frame in market]
    truncated = screen.build_features(*prefix)
    pd.testing.assert_frame_equal(truncated.loc[:boundary], original.loc[:boundary])


def test_metrics_are_not_available_until_five_minutes_after_stamp(market):
    cut = screen.stamp("2024-01-11")
    base = screen.build_features(*market)
    changed = list(market)
    changed[2] = market[2].copy()
    changed[2].loc[changed[2].time == cut, "sum_taker_long_short_vol_ratio"] = 100
    result = screen.build_features(*changed)
    before = pd.Timestamp(cut + 4 * screen.MINUTE, unit="ms", tz="UTC")
    after = pd.Timestamp(cut + 5 * screen.MINUTE, unit="ms", tz="UTC")
    pd.testing.assert_series_equal(base.loc[:before, "H2_5"], result.loc[:before, "H2_5"])
    assert result.loc[after, "H2_5"] != base.loc[after, "H2_5"]


def test_funding_is_delayed_by_its_published_interval(market):
    cut = screen.stamp("2024-01-11")
    base = screen.build_features(*market)
    changed = list(market)
    changed[3] = market[3].copy()
    changed[3].loc[changed[3].time == cut, "funding"] = .01
    result = screen.build_features(*changed)
    before = pd.Timestamp(cut + 8 * 60 * screen.MINUTE - 1, unit="ms", tz="UTC")
    pd.testing.assert_frame_equal(base.loc[:before, ["H5_5", "H5_15"]], result.loc[:before, ["H5_5", "H5_15"]])
    assert not base[["H5_5", "H5_15"]].equals(result[["H5_5", "H5_15"]])


def test_asof_join_rejects_future_stale_and_does_not_impute_invalid_record():
    dates = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
    series = pd.Series([1., np.nan, 3.], index=dates)
    target = pd.DatetimeIndex([dates[0] - pd.Timedelta(milliseconds=1), dates[0],
                              dates[1], dates[2] + pd.Timedelta(minutes=5)])
    result = screen.available_asof(series, target, max_age_ms=5 * screen.MINUTE)
    np.testing.assert_allclose(result, [np.nan, 1., np.nan, np.nan], equal_nan=True)


def test_z_score_uses_strictly_prior_seven_days():
    dates = pd.date_range("2024-01-01", periods=9 * 1440, freq="min", tz="UTC")
    values = pd.Series(np.sin(np.arange(len(dates)) / 11), index=dates)
    point = 8 * 1440
    values.iloc[point] = 100
    z = screen.trailing_z(values, interval_minutes=1)
    past = values.iloc[point - 7 * 1440:point]
    assert z.iloc[point] == pytest.approx((100 - past.mean()) / past.std(ddof=1))
    assert z.iloc[:7 * 1440].isna().all()


def path_bars(*, high=100.1, low=99.9, close=100., opening=100., count=15):
    return pd.DataFrame(dict(open=np.repeat(opening, count), high=np.repeat(high, count),
                             low=np.repeat(low, count), close=np.repeat(close, count)))


@pytest.mark.parametrize("side", [-1, 1])
def test_same_bar_tp_and_sl_is_stop_loss(side):
    bars = path_bars(high=101, low=99)
    assert screen.simulate_tpsl(100, side, bars) == pytest.approx(-25)
    full = path_bars(high=101, low=99, count=40).assign(
        time=screen.stamp("2024-01-01") + np.arange(40) * screen.MINUTE, volume=10., taker=5.)
    name = "long" if side == 1 else "short"
    assert screen.make_targets(full)[f"tpsl_{name}"].iloc[0] == pytest.approx(-25)


@pytest.mark.parametrize("side,opening,high,low", [(1, 99., 99.1, 98.9), (-1, 101., 101.1, 100.9)])
def test_stop_gap_uses_worse_open(side, opening, high, low):
    assert screen.simulate_tpsl(100, side, path_bars(opening=opening, high=high, low=low, close=opening)) == pytest.approx(-100)


@pytest.mark.parametrize("side", [-1, 1])
def test_take_profit_and_timeout(side):
    bars = path_bars(high=100.4 if side == 1 else 100.1, low=99.9 if side == 1 else 99.6)
    assert screen.simulate_tpsl(100, side, bars) == pytest.approx(35)
    assert screen.simulate_tpsl(100, side, path_bars(close=100.05)) == pytest.approx(side * 5)


def test_targets_use_next_minute_after_decision_and_exact_fifteen_bars():
    start = screen.stamp("2024-01-01")
    prices = 100 + np.arange(40) * .01
    bars = pd.DataFrame(dict(time=start + np.arange(40) * screen.MINUTE, open=prices,
                            high=prices + .001, low=prices - .001, close=prices + .0005,
                            volume=10., taker=5.))
    targets = screen.make_targets(bars)
    assert screen.index_ms(targets.index)[0] == start + screen.MINUTE
    expected = (bars.close.iloc[16] / bars.open.iloc[2] - 1) * 10_000
    assert targets.r15_long.iloc[0] == pytest.approx(expected)
    for index in (0, 3, 20):
        for side, name in ((1, "long"), (-1, "short")):
            actual = screen.simulate_tpsl(bars.open.iloc[index + 2], side, bars.iloc[index + 2:index + 17])
            assert targets[f"tpsl_{name}"].iloc[index] == pytest.approx(actual)
    assert targets.r15_long.iloc[-16:].isna().all()


def test_missing_minute_invalidates_whole_path():
    bars = path_bars(count=40).assign(time=screen.stamp("2024-01-01") + np.arange(40) * screen.MINUTE,
                                     volume=10., taker=5.)
    targets = screen.make_targets(bars.drop(index=8))
    assert targets.iloc[0].isna().all()
    assert targets.iloc[9].notna().all()


def test_nonoverlapping_signals_wait_full_horizon():
    times = np.array([0, 1, 14, 15, 16, 29, 30, 30, 45]) * screen.MINUTE
    assert screen.nonoverlapping(times).tolist() == [0, 3, 6, 8]
    with pytest.raises(ValueError):
        screen.nonoverlapping(np.array([2, 1]))


def test_embargo_and_label_purge_at_split_boundaries():
    cut, start, end = screen.stamp("2025-07-01"), screen.stamp("2025-07-02"), screen.stamp("2026-04-01")
    times = np.array([cut - 17 * screen.MINUTE, cut - 16 * screen.MINUTE, cut, start - 1, start])
    assert screen.embargo_mask(times, screen.stamp("2024-01-01"), cut).tolist() == [True, False, False, False, False]
    assert screen.embargo_mask(times, start, end).tolist() == [False, False, False, False, True]
    end_times = np.array([end - 17 * screen.MINUTE, end - 16 * screen.MINUTE])
    assert screen.embargo_mask(end_times, start, end).tolist() == [True, False]


def test_stage_barrier_prevents_early_holdout_and_second_evaluation(tmp_path):
    train, test, holdout = (tmp_path / (stage + ".json") for stage in ("train", "test", "holdout"))
    calls = []
    compute = lambda: calls.append(True) or {"value": 7}
    with pytest.raises(ValueError, match="previous stage"):
        screen.sealed_stage(holdout, "sig", compute, requires=(train, test))
    assert not calls
    screen.sealed_stage(train, "sig", compute)
    screen.sealed_stage(test, "sig", compute, requires=(train,))
    assert screen.sealed_stage(holdout, "sig", compute, requires=(train, test))["value"] == 7
    assert screen.sealed_stage(holdout, "sig", compute, requires=(train, test))["value"] == 7
    assert len(calls) == 3
    with pytest.raises(ValueError, match="signature mismatch"):
        screen.sealed_stage(holdout, "different", compute)


def test_interrupted_stage_cannot_silently_recompute(tmp_path):
    path = tmp_path / "test.json"
    def crash():
        raise RuntimeError("fixture interrupted evaluation")
    with pytest.raises(RuntimeError):
        screen.sealed_stage(path, "sig", crash)
    with pytest.raises(FileExistsError):
        screen.sealed_stage(path, "sig", lambda: {"result": "second look"})


def test_kline_timestamp_units_and_validation():
    base = screen.stamp("2025-01-01")
    def row(time):
        return [time, 100, 101, 99, 100.5, 10, time + 59_999, 1000, 20, 6, 600, 0]
    for multiplier in (1, 1000):
        result = screen.normalize_frame(pd.DataFrame([row(base * multiplier)]), "spot")
        assert result.time.iloc[0] == base
    invalid = pd.DataFrame([row(base)])
    invalid.iloc[0, 9] = 11
    with pytest.raises(ValueError, match="OHLCV"):
        screen.normalize_frame(invalid, "spot")


def test_metrics_datetime_resolution_is_milliseconds():
    frame = pd.DataFrame({"create_time": ["2024-01-01 00:00:00"], **{key: [1.] for key in screen.METRICS}})
    assert screen.normalize_frame(frame, "metrics").time.iloc[0] == screen.stamp("2024-01-01")


def test_real_funding_millisecond_offset_is_preserved_not_rounded_down():
    timestamp = screen.stamp("2024-01-05") + 1
    frame = pd.DataFrame(dict(calc_time=[timestamp], funding_interval_hours=[8], last_funding_rate=[.0001]))
    normalized = screen.normalize_frame(frame, "funding")
    assert normalized.time.iloc[0] == timestamp
    available = pd.to_datetime([timestamp + 8 * 60 * screen.MINUTE], unit="ms", utc=True)
    series = pd.Series([.0001], index=available)
    before = available - pd.Timedelta(milliseconds=1)
    assert screen.available_asof(series, before, max_age_ms=screen.DAY).isna().all()


def test_archive_integrity_and_no_extraction(tmp_path):
    path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture.csv", "1704067200000,100,101,99,100,10,1704067259999,1000,1,5,500,0\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(screen.read_archive(path, "futures", digest)) == 1
    assert not (tmp_path / "fixture.csv").exists()
    with pytest.raises(ValueError, match="changed"):
        screen.read_archive(path, "futures", "0" * 64)


def test_fetch_checksum_and_offline_missing(tmp_path, monkeypatch):
    payload = b"fixture archive bytes"
    checksum = (hashlib.sha256(payload).hexdigest() + "  fixture.zip").encode()
    monkeypatch.setattr(screen, "download_bytes", lambda url, **kw: checksum if url.endswith("CHECKSUM") else payload)
    saved = screen.fetch_archive(tmp_path, "futures", "BTCUSDT", "2024-01")
    assert saved["status"] == "OK"
    monkeypatch.setattr(screen, "download_bytes", lambda *a, **kw: pytest.fail("unexpected network"))
    assert screen.fetch_archive(tmp_path, "futures", "BTCUSDT", "2024-01", offline=True) == saved
    assert screen.fetch_archive(tmp_path, "futures", "ETHUSDT", "2024-01", offline=True)["status"] == "MISSING_LOCAL"
    (tmp_path / saved["key"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        screen.fetch_archive(tmp_path, "futures", "BTCUSDT", "2024-01", offline=True)


def test_grid_fixed_count_and_both_orientations():
    rules = screen.rule_grid()
    assert len(rules) == 72
    for family in screen.FAMILIES[:-1]:
        rows = [rule for rule in rules if rule.family == family]
        assert len(rows) == 12
        assert {rule.orientation for rule in rows} == {-1, 1}


def test_rule_execution_is_nonoverlapping_per_symbol_and_h6_excludes_btc():
    dates = pd.date_range("2025-07-02", periods=40, freq="min", tz="UTC")
    panel = pd.DataFrame({key: 2. for key in screen.FEATURES}, index=dates)
    for key, value in dict(efficiency=.5, market_return=.01, r15_long=20., r15_short=-20.,
                           tpsl_long=35., tpsl_short=-25.).items():
        panel[key] = value
    panels = {"BTCUSDT": panel, "ETHUSDT": panel.copy()}
    trades = screen.trades_for_rule(panels, screen.Rule("H1", "H1_5", 1.), .4)
    assert len(trades) == 6
    assert trades.groupby("symbol").decision_ms.diff().dropna().min() == 15 * screen.MINUTE
    h6 = screen.trades_for_rule(panels, screen.Rule("H6", "H6_1", 1., -1), .4)
    assert set(h6.symbol) == {"ETHUSDT"} and set(h6.side) == {-1}
    assert len(h6) == 3 and set(h6.tpsl) == {-25.}
    probabilities = {symbol: pd.Series(.7, index=dates) for symbol in panels}
    h7 = screen.trades_for_rule(panels, screen.Rule("H7", "logistic", .6), .4, probabilities=probabilities)
    assert len(h7) == 6 and set(h7.side) == {1}


def test_logistic_json_prediction_is_reproducible_and_no_test_scaling():
    rng = np.random.default_rng(42)
    x = rng.normal(size=(400, len(screen.FEATURES)))
    y = (x[:, 0] + x[:, 1] > 0).astype(int)
    model = screen.fit_logistic(x, y, 1., screen.SEED)
    copy = json.loads(json.dumps(model, allow_nan=False))
    panel = pd.DataFrame(x, columns=screen.FEATURES)
    first = screen.predict_logistic(panel, model)
    augmented = pd.concat([panel, pd.DataFrame([[1e9] * len(screen.FEATURES)], columns=screen.FEATURES)], ignore_index=True)
    np.testing.assert_allclose(screen.predict_logistic(augmented, copy).iloc[:400], first)
    assert copy == model


def fixture_trades(days=20):
    return pd.DataFrame([dict(symbol=symbol, decision_ms=screen.stamp("2025-07-02") + day * screen.DAY,
                              side=1 if day % 2 else -1, regime="TREND" if day % 3 else "CHOP",
                              market="UP" if day % 2 else "DOWN", r15=15. + day % 5, tpsl=13. + day % 3)
                         for day in range(days) for symbol in screen.SYMBOLS])


def test_daily_bootstrap_determinism_costs_and_holm():
    trades = fixture_trades()
    p = replace(screen.Protocol(), bootstrap=200)
    start = screen.stamp("2025-07-02")
    first = screen.block_statistics(trades, start, start + 22 * screen.DAY, p)
    second = screen.block_statistics(trades, start, start + 22 * screen.DAY, p)
    assert first == second
    assert first["calendar_days"] == 22 and first["active_days"] == 20
    assert first["r15"]["net18_bps"] == pytest.approx(first["r15"]["net9_bps"] - 9)
    assert first["r15"]["max_symbol_profit_share"] == pytest.approx(1 / 7)
    assert screen.holm({"a": .01, "b": .04, "c": .03}) == {"a": .03, "c": .06, "b": .06}
    assert "n_below_200" in screen.stage_failures(first, test=True)


def test_lead_guards_reject_beta_and_symbol_concentration():
    trades = fixture_trades(days=60)
    p = replace(screen.Protocol(), bootstrap=200)
    start = screen.stamp("2025-07-02")
    stats = screen.block_statistics(trades, start, start + 60 * screen.DAY, p)
    stats["p_holm"] = .01
    assert screen.stage_failures(stats, test=True) == []
    trades["symbol"] = "BTCUSDT"
    trades["side"] = 1
    trades["market"] = "UP"
    bad = screen.block_statistics(trades, start, start + 60 * screen.DAY, p)
    bad["p_holm"] = .01
    reasons = screen.stage_failures(bad, test=True)
    assert "r15_symbol_concentration" in reasons
    assert "side_-1_not_positive_or_insufficient" in reasons
    assert "market_DOWN_not_positive_or_insufficient" in reasons
