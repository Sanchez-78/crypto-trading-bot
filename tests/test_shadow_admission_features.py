"""M1.3 (audit v6 §3.5): the observation carries the ADMISSION context (P0 decision,
signal strength, exposure state) so offline analysis can reconstruct the
admissible-trade subset. The recorder stores arbitrary features as features_json;
this locks in that the admission fields round-trip to the DB.
"""
import json
import sqlite3

from src.services.shadow_excursion_recorder import ShadowExcursionRecorder


def test_admission_features_roundtrip(tmp_path):
    db = str(tmp_path / "shadow.sqlite")
    r = ShadowExcursionRecorder(db_path=db, horizon_s=3, second_ms=1000)
    feats = {
        "p0_reason": "strict_ev", "strict_ev_allowed": True, "is_blocked": False,
        "edge": "DEV_FADE", "ev": 0.4, "score": 0.9, "obi": 0.1,
        "open_total": 0, "open_symbol": 0, "source": "signal_engine",
    }
    assert r.record_signal("a", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0,
                           features=feats, feature_schema_version=2)
    for sec in range(3):
        r.on_tick("ETHUSDT", 100.0 + sec * 0.001, sec * 1000)
    r.sweep_expired(3_000)

    c = sqlite3.connect(db)
    fj, ver = c.execute(
        "SELECT features_json, feature_schema_version FROM shadow_excursion_observations "
        "WHERE observation_id='a'").fetchone()
    c.close()
    assert ver == 2, ver
    got = json.loads(fj)
    for k in ("p0_reason", "strict_ev_allowed", "is_blocked", "edge",
              "open_total", "open_symbol"):
        assert k in got, (k, got)
    assert got["strict_ev_allowed"] is True and got["is_blocked"] is False
