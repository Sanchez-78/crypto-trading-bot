"""Regression (audit v6 §3.4): data_quality must NOT label a truncated path 'ok'.

sample_count alone can pass even when the path never reached the horizon end (a
symbol went silent, or a shutdown flush_all persisted an observer mid-horizon).
A full-coverage path stays 'ok'; a shutdown-truncated one becomes
'partial_shutdown' so the maker-fill (M1) dataset stays clean.
"""
import sqlite3

from src.services.shadow_excursion_recorder import ShadowExcursionRecorder


def _dq(db_path, oid):
    c = sqlite3.connect(db_path)
    row = c.execute(
        "SELECT data_quality FROM shadow_excursion_observations WHERE observation_id=?",
        (oid,)).fetchone()
    c.close()
    return row[0] if row else None


def _make(tmp_path):
    return ShadowExcursionRecorder(
        db_path=str(tmp_path / "shadow.sqlite"), horizon_s=10, second_ms=1000)


def test_full_coverage_is_ok(tmp_path):
    r = _make(tmp_path)
    r.record_signal("full", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(10):                       # ticks covering seconds 0..9
        r.on_tick("ETHUSDT", 100.0 + sec * 0.001, sec * 1000)
    r.sweep_expired(10_000)                      # horizon elapsed -> normal persist
    assert _dq(str(tmp_path / "shadow.sqlite"), "full") == "ok"


def test_shutdown_truncated_is_flagged(tmp_path):
    r = _make(tmp_path)
    r.record_signal("trunc", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(4):                         # only seconds 0..3 of a 10s horizon
        r.on_tick("ETHUSDT", 100.0 + sec * 0.001, sec * 1000)
    r.flush_all(4_000)                           # shutdown flush mid-horizon
    dq = _dq(str(tmp_path / "shadow.sqlite"), "trunc")
    assert dq == "partial_shutdown", dq
    assert dq != "ok"
