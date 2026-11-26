"""Tests for the preregistered window evaluation; only temporary SQLite files are used."""
import hashlib
import random
import sqlite3

import pytest

from scripts.research import threshold_window_eval as ev
from src.core.trade_metrics_contract import WIN_THRESHOLD_PCT


def make_db(path, trades):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE closed_trades (trade_id TEXT, symbol TEXT, side TEXT, entry_ts REAL, "
                 "exit_ts REAL, pnl_usd REAL, pnl_pct REAL, predicted_net_edge_bps REAL)")
    conn.executemany("INSERT INTO closed_trades VALUES (?,?,?,?,?,?,?,?)", trades)
    conn.commit()
    conn.close()
    return str(path)


def synth(n, means, seed=1, start=ev.T0):
    """means: {predicted_value: mean_net_bps}; trades spread over the 7-day window."""
    rng = random.Random(seed)
    keys = list(means)
    span = ev.END - start
    out = []
    for i in range(n):
        pred = keys[i % len(keys)]
        entry = start + (i * span) / n
        net = rng.gauss(means[pred], 30)
        out.append((f"t{i}", "BTCUSDT", "BUY", entry, entry + 600, net / 100 * 0.5, net / 100, pred))
    return out


def run(db):
    return ev.evaluate(ev.load(db))


def test_win_threshold_matches_contract():
    assert ev.WIN_THRESHOLD_PCT == WIN_THRESHOLD_PCT


def test_refuses_before_window_settles(tmp_path, capsys, monkeypatch):
    db = make_db(tmp_path / "c.sqlite", synth(10, {0: 0}))
    monkeypatch.setattr(ev.time, "time", lambda: ev.END + ev.SETTLE_S - 1)
    assert ev.main(["--db", db]) == 2
    assert '"NOT_YET"' in capsys.readouterr().out


def test_runs_after_window_settles(tmp_path, capsys, monkeypatch):
    db = make_db(tmp_path / "c.sqlite", synth(10, {0: 0}))
    monkeypatch.setattr(ev.time, "time", lambda: ev.END + ev.SETTLE_S)
    assert ev.main(["--db", db]) == 0
    assert '"INSUFFICIENT_DATA"' in capsys.readouterr().out


def test_cli_has_no_time_override(tmp_path):
    db = make_db(tmp_path / "c.sqlite", synth(10, {0: 0}))
    with pytest.raises(SystemExit):
        ev.main(["--db", db, "--now", str(ev.END + 10 ** 6)])


def test_insufficient_data_below_1000(tmp_path):
    db = make_db(tmp_path / "c.sqlite", synth(999, {5: 20, -20: -20}))
    report = run(db)
    assert report["verdict"] == "INSUFFICIENT_DATA"
    assert report["recommended_cut"] == -25 and report["label"] == "NO_CHANGE"


def test_window_is_half_open_on_entry_time(tmp_path):
    base = synth(3, {0: 0})
    edges = [("a", "X", "BUY", ev.T0, ev.T0 + 60, 0, 0.1, 0),
             ("b", "X", "BUY", ev.T0 - 1, ev.T0 + 60, 0, 0.1, 0),
             ("c", "X", "BUY", ev.END, ev.END + 60, 0, 0.1, 0),
             ("d", "X", "BUY", ev.END - 1, ev.END + 600, 0, 0.1, 0)]
    db = make_db(tmp_path / "c.sqlite", base + edges)
    ids = {r["trade_id"] for r in ev.load(db)}
    assert {"a", "d"} <= ids and not {"b", "c"} & ids


def test_keep_current_when_predictor_is_uninformative(tmp_path):
    db = make_db(tmp_path / "c.sqlite", synth(1400, {-20: -8, -5: -8, 5: -8}))
    report = run(db)
    assert report["verdict"] == "KEEP_CURRENT" and report["recommended_cut"] == -25


def test_tighten_loss_reduction_when_dropped_trades_are_worse(tmp_path):
    db = make_db(tmp_path / "c.sqlite", synth(1400, {-20: -15, -5: -4, 5: -3}))
    report = run(db)
    assert report["verdict"] == "TIGHTEN"
    assert report["recommended_cut"] in (-10, 0)
    assert report["label"] == "LOSS_REDUCTION"
    assert report["cuts"]["-25"]["eligible"] is False


def test_positive_hypothesis_label(tmp_path):
    db = make_db(tmp_path / "c.sqlite", synth(2100, {-20: -15, -5: -10, 5: 12}))
    report = run(db)
    assert report["verdict"] == "TIGHTEN" and report["recommended_cut"] == 0
    assert report["label"] == "POSITIVE_HYPOTHESIS"


def test_cut_needs_at_least_100_trades(tmp_path):
    trades = synth(1300, {-20: -15})
    trades += [(f"g{i}", "X", "BUY", ev.T0 + 1000 + i * 3000, ev.T0 + 1600 + i * 3000, 0.1, 0.2, 5)
               for i in range(99)]
    report = run(make_db(tmp_path / "c.sqlite", trades))
    assert report["cuts"]["0"]["n"] == 99 and report["cuts"]["0"]["eligible"] is False
    assert report["verdict"] == "KEEP_CURRENT"


def test_missing_prediction_is_never_selected(tmp_path):
    trades = synth(1100, {-20: -15, 5: -2})
    trades += [(f"m{i}", "X", "BUY", ev.T0 + i * 100, ev.T0 + i * 100 + 60, 1, 0.5, None) for i in range(50)]
    report = run(make_db(tmp_path / "c.sqlite", trades))
    assert report["missing_prediction"] == 50
    assert report["cuts"]["-25"]["n"] == 1100 and report["gate_population"]["n"] == 1100
    assert report["all_descriptive"]["n"] == 1150
    assert report["cuts"]["0"]["newly_dropped"]["n"] == 550


def test_wr_counts_flats_in_denominator():
    rows = ev.prepare([
        dict(trade_id="w", entry_ts=ev.T0, exit_ts=ev.T0 + 1, pnl_pct=0.2, pnl_usd=1, predicted_net_edge_bps=0),
        dict(trade_id="f", entry_ts=ev.T0, exit_ts=ev.T0 + 1, pnl_pct=0.05, pnl_usd=0, predicted_net_edge_bps=0),
        dict(trade_id="l", entry_ts=ev.T0, exit_ts=ev.T0 + 1, pnl_pct=-0.3, pnl_usd=-2, predicted_net_edge_bps=0)])
    s = ev.summary(rows)
    assert (s["wins"], s["losses"], s["flats"]) == (1, 1, 1)
    assert s["wr_pct"] == pytest.approx(100 / 3) and s["pf"] == pytest.approx(0.5)


def test_duplicate_trade_id_fails_closed():
    row = dict(trade_id="x", entry_ts=ev.T0, exit_ts=ev.T0 + 1, pnl_pct=0.1, pnl_usd=0, predicted_net_edge_bps=0)
    with pytest.raises(ValueError):
        ev.prepare([row, dict(row)])


def test_open_is_read_only_and_leaves_bytes_unchanged(tmp_path, monkeypatch):
    db = make_db(tmp_path / "c.sqlite", synth(20, {0: 0}))
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    real_connect = sqlite3.connect
    seen = []

    def spy(target, *a, **k):
        conn = real_connect(target, *a, **k)
        seen.append(target)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE probe (x)")
        return conn

    monkeypatch.setattr(ev.sqlite3, "connect", spy)
    ev.load(db)
    assert seen and "mode=ro" in seen[0]
    assert hashlib.sha256(open(db, "rb").read()).hexdigest() == before


def test_minimum_counts_only_the_gate_population(tmp_path):
    trades = synth(900, {-20: -15, 5: 5})
    trades += [(f"m{i}", "X", "BUY", ev.T0 + i * 100, ev.T0 + i * 100 + 60, 0, 0.1, None) for i in range(200)]
    trades += [(f"b{i}", "X", "BUY", ev.T0 + i * 100 + 7, ev.T0 + i * 100 + 67, 0, 0.1, -40) for i in range(200)]
    report = run(make_db(tmp_path / "c.sqlite", trades))
    assert report["gate_population"]["n"] == 900 and report["below_current_cut"] == 200
    assert report["verdict"] == "INSUFFICIENT_DATA"


def test_trades_below_current_cut_never_make_a_cut_eligible(tmp_path):
    trades = synth(1400, {-20: -8, -5: -8, 5: -8})
    trades += synth(700, {-40: -80}, seed=7)
    trades = [(f"x{i}",) + t[1:] for i, t in enumerate(trades)]
    report = run(make_db(tmp_path / "c.sqlite", trades))
    assert report["below_current_cut"] == 700
    assert report["cuts"]["0"]["newly_dropped"]["n"] == 934
    assert report["verdict"] == "KEEP_CURRENT"
    assert not report["cuts"]["-10"]["eligible"] and not report["cuts"]["0"]["eligible"]


@pytest.mark.parametrize("pvalues,expected", [
    ({"-10": 0.01, "0": 0.02}, {"-10": True, "0": True}),
    ({"-10": 0.013, "0": 0.001}, {"-10": True, "0": True}),
    ({"-10": 0.02, "0": 0.02}, {"-10": False, "0": False}),
    ({"-10": 0.0125, "0": 0.03}, {"-10": True, "0": False}),
    ({"-10": None, "0": 0.001}, {"-10": False, "0": True}),
])
def test_holm_two_hypotheses(pvalues, expected):
    assert ev.holm(pvalues) == expected
