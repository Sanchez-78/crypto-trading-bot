"""M1.3b: the shadow recorder captures per-1s aggressor traded volume (aggTrade)
so the maker-fill 'base' (traded-through) scenario can be modelled, with an
idempotent migration for pre-existing DBs.
"""
import sqlite3

from src.services.shadow_excursion_recorder import ShadowExcursionRecorder


def _agg(db, oid, sec):
    c = sqlite3.connect(db)
    r = c.execute("SELECT agg_buy_qty, agg_sell_qty FROM shadow_path_1s "
                  "WHERE observation_id=? AND second_offset=?", (oid, sec)).fetchone()
    c.close()
    return r


def test_aggtrade_volume_captured(tmp_path):
    db = str(tmp_path / "shadow.sqlite")
    r = ShadowExcursionRecorder(db_path=db, horizon_s=5, second_ms=1000)
    r.record_signal("a", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0, sec * 1000)          # create buckets
    # second 1: aggressor sell 10 (is_buyer_maker=True), aggressor buy 5 (False)
    r.on_aggtrade("ETHUSDT", 100.0, 10.0, True, 1000)
    r.on_aggtrade("ETHUSDT", 100.0, 5.0, False, 1500)
    r.sweep_expired(5_000)
    buy, sell = _agg(db, "a", 1)
    assert abs(buy - 5.0) < 1e-9 and abs(sell - 10.0) < 1e-9, (buy, sell)
    # a second with no aggTrades -> 0/0
    assert _agg(db, "a", 3) == (0.0, 0.0)


def test_aggtrade_outside_horizon_ignored(tmp_path):
    db = str(tmp_path / "shadow.sqlite")
    r = ShadowExcursionRecorder(db_path=db, horizon_s=5, second_ms=1000)
    r.record_signal("a", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0, sec * 1000)
    r.on_aggtrade("ETHUSDT", 100.0, 99.0, True, 9000)     # sec 9 >> horizon 5
    r.sweep_expired(5_000)
    # no bucket at sec 9 -> nothing recorded there; total sell across path stays 0
    c = sqlite3.connect(db)
    tot = c.execute("SELECT COALESCE(SUM(agg_sell_qty),0) FROM shadow_path_1s "
                    "WHERE observation_id='a'").fetchone()[0]
    c.close()
    assert tot == 0.0, tot


def test_migration_adds_agg_columns(tmp_path):
    db = str(tmp_path / "old.sqlite")
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE shadow_path_1s (observation_id TEXT NOT NULL, second_offset INTEGER "
        "NOT NULL, open_bps REAL, high_bps REAL, low_bps REAL, close_bps REAL, "
        "first_high_ms INTEGER, first_low_ms INTEGER, first_extreme TEXT, "
        "sample_count INTEGER NOT NULL, PRIMARY KEY(observation_id, second_offset));")
    c.commit(); c.close()
    r = ShadowExcursionRecorder(db_path=db, horizon_s=5, second_ms=1000)
    r.record_signal("m", "ETHUSDT", "BUY", "BULL_TREND", 0, 100.0)
    for sec in range(5):
        r.on_tick("ETHUSDT", 100.0, sec * 1000)
    r.on_aggtrade("ETHUSDT", 100.0, 7.0, True, 2000)
    r.sweep_expired(5_000)
    c = sqlite3.connect(db)
    cols = [row[1] for row in c.execute("PRAGMA table_info(shadow_path_1s)").fetchall()]
    c.close()
    assert "agg_buy_qty" in cols and "agg_sell_qty" in cols, cols
    assert _agg(db, "m", 2) == (0.0, 7.0)
