"""M2 maker-fill model v2 — logic validation on synthetic enriched shadow data.

Not a market claim; asserts the harness behaves: admissible filter, spread-aware
scenarios, walk-forward, and CI wiring all work as specified.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[1] / "scripts" / "maker_fill_model_v2.py")


def _build(db, n_admissible=300, n_blocked=80, n_overcap=40, revert=True):
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE shadow_excursion_observations(observation_id TEXT PRIMARY KEY, "
        "source TEXT, symbol TEXT, side TEXT, regime TEXT, signal_ts_ms INTEGER, "
        "entry_ref_price REAL, horizon_ms INTEGER, feature_schema_version INTEGER, "
        "features_json TEXT, completed INTEGER, data_quality TEXT, sample_count INTEGER, "
        "created_at_ms INTEGER);"
        "CREATE TABLE shadow_path_1s(observation_id TEXT, second_offset INTEGER, "
        "open_bps REAL, high_bps REAL, low_bps REAL, close_bps REAL, first_high_ms INTEGER, "
        "first_low_ms INTEGER, first_extreme TEXT, sample_count INTEGER, spread_bps REAL, "
        "PRIMARY KEY(observation_id, second_offset));")
    i = 0

    def mk(blocked=False, overcap=False):
        nonlocal i
        oid = f"o{i}"; ts = 1000 + i * 1000
        feats = {"strict_ev_allowed": not blocked, "is_blocked": blocked,
                 "open_symbol": 3 if overcap else 0, "open_total": 0}
        c.execute("INSERT INTO shadow_excursion_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, "live", "ETHUSDT", "BUY", "BULL_TREND", ts, 2000.0, 10000, 2,
                   json.dumps(feats), 1, "ok", 10, ts))
        dip, g, spread = -5.0, (4.0 if revert else -5.0), 4.0
        for s in range(10):
            low = 0.0 if s < 2 else (dip if s == 2 else dip + (g - dip) * (s - 2) / 7)
            close = low
            c.execute("INSERT INTO shadow_path_1s VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, s, close, max(close, 0.0), low, close, ts, ts, "low", 5, spread))
        i += 1

    for _ in range(n_admissible): mk()
    for _ in range(n_blocked): mk(blocked=True)
    for _ in range(n_overcap): mk(overcap=True)
    c.commit(); c.close()


def _run(db):
    out = subprocess.run([sys.executable, SCRIPT, db], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_admissible_filter_excludes_blocked_and_overcap(tmp_path):
    db = str(tmp_path / "s.sqlite"); _build(db, 300, 80, 40)
    d = _run(db)
    assert d["n_obs_ok"] == 420 and d["n_admissible"] == 300, d
    assert d["has_spread_column"] is True


def test_optimistic_fills_at_least_as_often_as_conservative(tmp_path):
    db = str(tmp_path / "s.sqlite"); _build(db, 300, 0, 0)
    d = _run(db)
    o = d["walk_forward"]["optimistic"]; c = d["walk_forward"]["conservative"]
    assert o["test_fill_rate"] >= c["test_fill_rate"], (o, c)


def test_reverting_positive_nonreverting_negative(tmp_path):
    dbp = str(tmp_path / "rev.sqlite"); _build(dbp, 300, 0, 0, revert=True)
    dbn = str(tmp_path / "non.sqlite"); _build(dbn, 300, 0, 0, revert=False)
    rev = _run(dbp)["walk_forward"]["optimistic"]["test_exp_bps"]
    non = _run(dbn)["walk_forward"]["optimistic"]["test_exp_bps"]
    assert rev > non, (rev, non)
