"""Tests for the E1–E4 offline counterfactual analyzer over synthetic shadow data."""
import importlib.util
import sqlite3
from pathlib import Path

from src.services.shadow_excursion_recorder import _SCHEMA

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "e1_e4", REPO / "scripts" / "e1_e4_counterfactual.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)


def _write_db(path, obs_list):
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    with conn:
        for o in obs_list:
            conn.execute(
                "INSERT INTO shadow_excursion_observations (observation_id, source, symbol, side, "
                "regime, signal_ts_ms, entry_ref_price, horizon_ms, feature_schema_version, "
                "features_json, completed, data_quality, sample_count, created_at_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (o["oid"], "t", o["symbol"], o["side"], o["regime"], o["ts"], 100.0,
                 300000, 1, None, 1, o.get("dq", "ok"), 50, o["ts"]))
            conn.execute(
                "INSERT INTO shadow_path_1s (observation_id, second_offset, open_bps, high_bps, "
                "low_bps, close_bps, first_high_ms, first_low_ms, first_extreme, sample_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (o["oid"], 0, 0.0, 0.0, 0.0, o.get("final_close", 0.0), o["ts"], o["ts"], "high", 5))
            for (d, lvl), ms in o.get("crossings", {}).items():
                conn.execute(
                    "INSERT INTO shadow_first_crossing (observation_id, direction, level_bps, first_cross_ms) "
                    "VALUES (?,?,?,?)", (o["oid"], d, lvl, ms))
    conn.close()


def _fav_first(oid, symbol, regime, ts):
    # favorable crosses 15 and 40 before adverse -> +tp for any tp in {15,40}
    return {"oid": oid, "symbol": symbol, "side": "BUY", "regime": regime, "ts": ts,
            "crossings": {("fav", 15): 90, ("fav", 40): 100, ("adv", 15): 200, ("adv", 40): 250}}


def _adv_first(oid, symbol, regime, ts):
    return {"oid": oid, "symbol": symbol, "side": "BUY", "regime": regime, "ts": ts,
            "crossings": {("adv", 15): 90, ("adv", 40): 100, ("fav", 15): 200, ("fav", 40): 250}}


def _dataset(n, fav_every, symbols=("AAA", "BBB", "CCC", "DDD", "EEE")):
    obs = []
    for i in range(n):
        sym = symbols[i % len(symbols)]
        regime = ("BULL", "BEAR", "RANGE")[i % 3]
        ts = 1_000_000_000_000 + i * 3_600_000  # 1h apart -> varied hours
        fav = (i % fav_every != 0)              # deterministic ~ (1-1/fav_every) favorable
        obs.append((_fav_first if fav else _adv_first)(f"o{i}", sym, regime, ts))
    return obs


# ── unit: simulate first-crossing semantics ────────────────────────────────────
def test_simulate_first_crossing_and_timeout():
    fav = E.Observation("a", "S", "BUY", "R", 0, {("fav", 40): 100, ("adv", 15): 200}, 0.0, "ok")
    assert E.simulate(fav, 40, 15, 18.0) == 40 - 18            # favorable first
    adv = E.Observation("b", "S", "BUY", "R", 0, {("fav", 40): 300, ("adv", 15): 100}, 0.0, "ok")
    assert E.simulate(adv, 40, 15, 18.0) == -15 - 18           # adverse first
    only_fav = E.Observation("c", "S", "BUY", "R", 0, {("fav", 40): 100}, 0.0, "ok")
    assert E.simulate(only_fav, 40, 15, 18.0) == 40 - 18
    only_adv = E.Observation("d", "S", "BUY", "R", 0, {("adv", 15): 100}, 0.0, "ok")
    assert E.simulate(only_adv, 40, 15, 18.0) == -15 - 18
    timeout = E.Observation("e", "S", "BUY", "R", 0, {}, 7.0, "ok")   # neither crossed
    assert E.simulate(timeout, 40, 15, 18.0) == 7.0 - 18       # realized final bps


def test_insufficient_observations_is_no_go(tmp_path):
    db = tmp_path / "s.sqlite"
    _write_db(db, _dataset(50, 4))
    r = E.walk_forward(E.load_observations(str(db)))
    assert r["verdict"] == "NO-GO"
    assert any("insufficient observations" in x for x in r["reasons"])


def test_clear_edge_is_go(tmp_path):
    db = tmp_path / "s.sqlite"
    _write_db(db, _dataset(400, 4))   # 75% favorable-first -> strong edge at (40,15)
    r = E.walk_forward(E.load_observations(str(db)))
    assert r["verdict"] == "GO", r["reasons"]
    assert r["selected"] == {"tp_bps": 40, "sl_bps": 15}
    assert r["oos"]["pf"] >= E.PF_GATE
    assert r["oos"]["expectancy_bps"] > 0


def test_no_edge_is_no_go(tmp_path):
    db = tmp_path / "s.sqlite"
    _write_db(db, _dataset(400, 2))   # 50% favorable -> negative expectancy after cost
    r = E.walk_forward(E.load_observations(str(db)))
    assert r["verdict"] == "NO-GO"
    assert any("expectancy" in x or "PF" in x or "CI" in x for x in r["reasons"])


def test_symbol_concentration_blocks_go(tmp_path):
    # one symbol carries ALL profit (always favorable), the rest always adverse
    obs = []
    for i in range(400):
        ts = 1_000_000_000_000 + i * 3_600_000
        regime = ("BULL", "BEAR", "RANGE")[i % 3]
        if i % 5 == 0:
            obs.append(_fav_first(f"o{i}", "DOMINANT", regime, ts))
        else:
            obs.append(_adv_first(f"o{i}", ("BBB", "CCC", "DDD", "EEE")[i % 4], regime, ts))
    db = tmp_path / "s.sqlite"
    _write_db(db, obs)
    r = E.walk_forward(E.load_observations(str(db)))
    assert r["verdict"] == "NO-GO"
    # profit is fully concentrated in one symbol -> concentration reason present
    assert any("concentration" in x for x in r["reasons"])


def test_data_quality_filter_excludes_sparse(tmp_path):
    obs = _dataset(10, 4)
    for o in obs:
        o["dq"] = "sparse"
    db = tmp_path / "s.sqlite"
    _write_db(db, obs)
    assert E.load_observations(str(db), require_quality_ok=True) == []
    assert len(E.load_observations(str(db), require_quality_ok=False)) == 10


def test_end_to_end_via_recorder(tmp_path):
    """Build the shadow db with the real recorder from synthetic ticks, then run the
    analyzer over it — proves the recorder's output schema matches the analyzer's reader."""
    from src.services.shadow_excursion_recorder import ShadowExcursionRecorder
    db = str(tmp_path / "shadow.sqlite")
    rec = ShadowExcursionRecorder(db_path=db, horizon_s=5, ladder_bps="15,40", second_ms=1000)
    t0 = 1_000_000
    # one favorable observation: price rises past +40 bps quickly
    rec.record_signal("e2e", "ETHUSDT", "BUY", "BULL", t0, 100.0)
    rec.on_tick("ETHUSDT", 100.0, t0 + 100)
    rec.on_tick("ETHUSDT", 100.5, t0 + 500)     # +50 bps -> crosses fav 15 & 40
    # feed enough ticks (>=5) so data_quality is "ok" (not filtered out)
    for dt in (1500, 2500, 3500, 4500):
        rec.on_tick("ETHUSDT", 100.5, t0 + dt)
    rec.flush_all(t0 + 6000)
    obs = E.load_observations(db)
    assert len(obs) == 1
    assert obs[0].first_cross.get(("fav", 40)) == t0 + 500
    # simulate a TP=40 hit
    assert E.simulate(obs[0], 40, 15, 18.0) == 40 - 18
