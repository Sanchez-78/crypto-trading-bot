"""M1.2: shadow recorder captures the executable quote spread (bid/ask) per 1s
bucket, backward-compatibly (NULL when the feed carries no quotes), and migrates
a pre-existing shadow_path_1s that lacks the column.
"""
import sqlite3

from src.services.shadow_excursion_recorder import ShadowExcursionRecorder


def _rows(db, oid):
    c = sqlite3.connect(db)
    r = c.execute(
        "SELECT second_offset, spread_bps FROM shadow_path_1s "
        "WHERE observation_id=? ORDER BY second_offset", (oid,)).fetchall()
    c.close()
    return r


def _make(tmp_path):
    return ShadowExcursionRecorder(
        db_path=str(tmp_path / "shadow.sqlite"), horizon_s=5, second_ms=1000)


def test_spread_captured_from_bid_ask(tmp_path):
    r = _make(tmp_path)
    r.record_signal("q", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    # bid=99.95, ask=100.05 -> mid=100, spread=0.10 -> 10 bps, each second 0..4
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0, sec * 1000, bid=99.95, ask=100.05)
    r.sweep_expired(5_000)
    rows = _rows(str(tmp_path / "shadow.sqlite"), "q")
    assert rows, "no path rows"
    for _, spread in rows:
        assert spread is not None and abs(spread - 10.0) < 1e-6, rows


def test_spread_null_without_quotes(tmp_path):
    r = _make(tmp_path)
    r.record_signal("noq", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0 + sec * 0.001, sec * 1000)   # no bid/ask
    r.sweep_expired(5_000)
    rows = _rows(str(tmp_path / "shadow.sqlite"), "noq")
    assert rows
    assert all(spread is None for _, spread in rows), rows


def test_migration_adds_spread_column(tmp_path):
    # Pre-existing DB with the OLD path_1s schema (no spread_bps).
    db = str(tmp_path / "old.sqlite")
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE shadow_path_1s (observation_id TEXT NOT NULL, "
        "second_offset INTEGER NOT NULL, open_bps REAL, high_bps REAL, low_bps REAL, "
        "close_bps REAL, first_high_ms INTEGER, first_low_ms INTEGER, first_extreme TEXT, "
        "sample_count INTEGER NOT NULL, PRIMARY KEY (observation_id, second_offset));")
    c.commit(); c.close()
    # Opening the recorder on it must ALTER in the new column (via _db()).
    r = ShadowExcursionRecorder(db_path=db, horizon_s=5, second_ms=1000)
    r.record_signal("m", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0, sec * 1000, bid=99.99, ask=100.01)
    r.sweep_expired(5_000)   # triggers _db() -> migration + insert with spread_bps
    c = sqlite3.connect(db)
    cols = [row[1] for row in c.execute("PRAGMA table_info(shadow_path_1s)").fetchall()]
    c.close()
    assert "spread_bps" in cols, cols
    rows = _rows(db, "m")
    assert rows and all(s is not None for _, s in rows), rows
