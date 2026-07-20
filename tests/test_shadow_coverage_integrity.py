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


def test_high_density_but_truncated_at_shutdown(tmp_path):
    # The audit 3.4 case: MANY ticks in a short window (density passes) but the
    # path never reached the horizon end -> must NOT be 'ok'; flagged truncated.
    r = _make(tmp_path)
    r.record_signal("dense_trunc", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(4):                         # seconds 0..3 only
        for k in range(4):                       # 16 samples >= want(10): density OK
            r.on_tick("ETHUSDT", 100.0 + k * 0.0001, sec * 1000 + k * 100)
    r.flush_all(4_000)
    dq = _dq(str(tmp_path / "shadow.sqlite"), "dense_trunc")
    assert dq == "partial_shutdown", dq


def test_density_sparse_at_shutdown_stays_sparse(tmp_path):
    # Reconciliation: a genuinely low-density observer flushed at shutdown keeps
    # 'sparse' (density defect), NOT 'partial_shutdown' — don't conflate the two.
    r = _make(tmp_path)
    r.record_signal("sparse", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    r.on_tick("ETHUSDT", 100.0, 0)               # single sample << want(10)
    r.flush_all(1_000)
    dq = _dq(str(tmp_path / "shadow.sqlite"), "sparse")
    assert dq == "sparse", dq
