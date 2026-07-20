"""M2 maker-fill model v2 — logic validation on synthetic enriched shadow data.

Not a market claim; asserts the corrected harness behaves as specified: admissible
filter (recorded decision), spread-aware executable scenario, horizon-aware embargo,
a REAL block-bootstrap CI, exit-policy selection, and honest coverage gating.
"""
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "maker_fill_model_v2.py"

_spec = importlib.util.spec_from_file_location("mfm2", SCRIPT)
mfm2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mfm2)


def _build(db, n_adm=260, n_blocked=80, with_spread=True, with_feats=True, revert=True):
    c = sqlite3.connect(db)
    path_cols = ("observation_id TEXT, second_offset INTEGER, open_bps REAL, high_bps REAL, "
                 "low_bps REAL, close_bps REAL, first_high_ms INTEGER, first_low_ms INTEGER, "
                 "first_extreme TEXT, sample_count INTEGER"
                 + (", spread_bps REAL" if with_spread else "")
                 + ", PRIMARY KEY(observation_id, second_offset)")
    c.executescript(
        "CREATE TABLE shadow_excursion_observations(observation_id TEXT PRIMARY KEY, source TEXT, "
        "symbol TEXT, side TEXT, regime TEXT, signal_ts_ms INTEGER, entry_ref_price REAL, "
        "horizon_ms INTEGER, feature_schema_version INTEGER, features_json TEXT, completed INTEGER, "
        "data_quality TEXT, sample_count INTEGER, created_at_ms INTEGER);"
        f"CREATE TABLE shadow_path_1s({path_cols});")
    i = 0
    HOUR = 3_600_000

    def mk(blocked=False, feats=True, regime="BULL_TREND"):
        nonlocal i
        oid = f"o{i}"; ts = 1000 + i * HOUR       # 1h apart >> embargo
        fj = json.dumps({"strict_ev_allowed": not blocked, "is_blocked": blocked}) if feats else None
        c.execute("INSERT INTO shadow_excursion_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, "live", "ETHUSDT", "BUY", regime, ts, 2000.0, 10000, 2, fj, 1, "ok", 10, ts))
        dip, g, spread = -5.0, (4.0 if revert else -6.0), 4.0
        for s in range(10):
            low = 0.0 if s < 2 else (dip if s == 2 else dip + (g - dip) * (s - 2) / 7)
            row = [oid, s, low, max(low, 0.0), low, low, ts, ts, "low", 5]
            if with_spread:
                row.append(spread)
            c.execute("INSERT INTO shadow_path_1s VALUES(" + ",".join("?" * len(row)) + ")", row)
        i += 1

    for k in range(n_adm):
        mk(feats=with_feats, regime="BULL_TREND" if k % 2 else "RANGING")
    for _ in range(n_blocked):
        mk(blocked=True)
    c.commit(); c.close()


def _run(db):
    out = subprocess.run([sys.executable, str(SCRIPT), db], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_admissible_filter_uses_recorded_decision(tmp_path):
    db = str(tmp_path / "s.sqlite"); _build(db, 260, 80)
    d = _run(db)
    assert d["n_obs_ok"] == 340 and d["n_admissible"] == 260, d


def test_conservative_skipped_without_spread(tmp_path):
    db = str(tmp_path / "ns.sqlite"); _build(db, 260, 0, with_spread=False)
    d = _run(db)
    assert d["has_spread_column"] is False
    assert "skipped" in d["walk_forward"]["conservative"], d["walk_forward"]["conservative"]
    assert d["GO"] is False   # coverage gate: no spread -> no GO


def test_legacy_rows_kept_but_flagged(tmp_path):
    db = str(tmp_path / "leg.sqlite"); _build(db, 260, 0, with_feats=False)
    d = _run(db)
    assert d["n_admissible"] == 260               # legacy rows kept
    assert d["admission_feature_fraction"] == 0.0  # but flagged
    assert d["coverage_ok_for_GO"] is False and d["GO"] is False


def test_block_bootstrap_is_a_real_ci():
    # A real CI of the mean SHRINKS with n (a percentile-of-block-means would not).
    import random as _r
    rng = _r.Random(1); small = [2.0 + rng.uniform(-3, 3) for _ in range(40)]
    rng = _r.Random(1); big = [2.0 + rng.uniform(-3, 3) for _ in range(400)]
    lo_s, hi_s = mfm2._block_bootstrap_ci(small)
    lo_b, hi_b = mfm2._block_bootstrap_ci(big)
    assert lo_b > 0, (lo_b, hi_b)                 # decisively-positive mean, big n
    assert (hi_b - lo_b) < (hi_s - lo_s)          # CI narrows with n (real bootstrap)


def test_exit_policy_reported(tmp_path):
    db = str(tmp_path / "s.sqlite"); _build(db, 260, 0)
    wf = _run(db)["walk_forward"]["conservative"]
    assert wf.get("exit_clock") in ("A", "B"), wf


def test_reverting_positive_nonreverting_negative(tmp_path):
    dbp = str(tmp_path / "rev.sqlite"); _build(dbp, 260, 0, revert=True)
    dbn = str(tmp_path / "non.sqlite"); _build(dbn, 260, 0, revert=False)
    rev = _run(dbp)["walk_forward"]["conservative"]["test_exp_bps"]
    non = _run(dbn)["walk_forward"]["conservative"]["test_exp_bps"]
    # reverting is a real positive edge; non-reverting can't beat "don't trade" (0),
    # so the model correctly picks a no-fill config -> <= 0, never a fabricated gain.
    assert rev > 0 >= non, (rev, non)
