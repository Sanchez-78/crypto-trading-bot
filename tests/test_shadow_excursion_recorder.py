"""Offline unit tests for the F8b shadow (observation-only) excursion recorder.

Deterministic: all timestamps are passed in explicitly (the recorder never reads
the system clock), so synthetic tick streams fully exercise the 1s bucketing,
first-crossing ladder, side-aware bps, and once-per-observation persistence.
"""
import os
import sqlite3

import pytest

from src.services import shadow_excursion_recorder as R


def _rec(tmp_path, **kw):
    return R.ShadowExcursionRecorder(
        db_path=str(tmp_path / "shadow.sqlite"),
        horizon_s=kw.get("horizon_s", 10),
        ladder_bps=kw.get("ladder_bps", "5,10,20,30"),
        second_ms=kw.get("second_ms", 1000),
    )


def _query(tmp_path, sql, args=()):
    conn = sqlite3.connect(str(tmp_path / "shadow.sqlite"))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_enabled_respects_env(monkeypatch):
    monkeypatch.delenv("PAPER_DATA_COLLECTION_ONLY", raising=False)
    assert R.enabled() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("PAPER_DATA_COLLECTION_ONLY", v)
        assert R.enabled() is True
    monkeypatch.setenv("PAPER_DATA_COLLECTION_ONLY", "false")
    assert R.enabled() is False


def test_favorable_bps_side_aware():
    # BUY: price up is favorable (+), down adverse (-)
    assert R._favorable_bps("BUY", 100.0, 100.30) == pytest.approx(30.0)
    assert R._favorable_bps("BUY", 100.0, 99.70) == pytest.approx(-30.0)
    # SELL: price down is favorable (+)
    assert R._favorable_bps("SELL", 100.0, 99.70) == pytest.approx(30.0)
    assert R._favorable_bps("SHORT", 100.0, 100.30) == pytest.approx(-30.0)
    assert R._favorable_bps("BUY", 0.0, 100.0) == 0.0  # guard bad entry_ref


def test_ladder_parsing():
    assert R._parse_ladder("5, 10 ,20,20,x,-3,54") == [5, 10, 20, 54]
    assert R._parse_ladder(None) == sorted(set(int(x) for x in R.DEFAULT_LADDER_BPS.split(",")))


def test_buy_observation_records_path_and_first_crossing(tmp_path):
    rec = _rec(tmp_path)
    t0 = 1_000_000
    assert rec.record_signal("obs1", "ETHUSDT", "BUY", "BULL_TREND", t0, 100.0) is True
    # ticks: sec0 rises 0->10, sec1 20, sec2 30 (peak), sec3 back to 5
    rec.on_tick("ETHUSDT", 100.00, t0 + 0)
    rec.on_tick("ETHUSDT", 100.10, t0 + 500)     # +10 bps
    rec.on_tick("ETHUSDT", 100.20, t0 + 1000)    # sec1 +20
    rec.on_tick("ETHUSDT", 100.30, t0 + 2000)    # sec2 +30 (peak)
    rec.on_tick("ETHUSDT", 100.05, t0 + 3000)    # sec3 +5
    assert rec.active_count == 1
    # a tick past the horizon finalizes + persists
    rec.on_tick("ETHUSDT", 100.00, t0 + 11000)
    assert rec.active_count == 0

    obs = _query(tmp_path, "SELECT symbol, side, regime, completed, sample_count FROM shadow_excursion_observations WHERE observation_id='obs1'")
    assert obs == [("ETHUSDT", "BUY", "BULL_TREND", 1, 5)]

    # first-crossing: fav 5 & 10 at +500 (bps hit 10), 20 at +1000, 30 at +2000; no adverse
    fc = dict(((d, lvl), ts) for d, lvl, ts in _query(
        tmp_path, "SELECT direction, level_bps, first_cross_ms FROM shadow_first_crossing WHERE observation_id='obs1'"))
    assert fc[("fav", 5)] == t0 + 500
    assert fc[("fav", 10)] == t0 + 500
    assert fc[("fav", 20)] == t0 + 1000
    assert fc[("fav", 30)] == t0 + 2000
    assert not any(d == "adv" for (d, _lvl) in fc)   # never went adverse

    # 1s path: sec0 open 0 high 10 close 10; sec2 high 30
    path = {so: (o, hi, lo, cl) for so, o, hi, lo, cl in _query(
        tmp_path, "SELECT second_offset, open_bps, high_bps, low_bps, close_bps FROM shadow_path_1s WHERE observation_id='obs1'")}
    assert path[0][0] == pytest.approx(0.0) and path[0][1] == pytest.approx(10.0)
    assert path[2][1] == pytest.approx(30.0)   # peak second


def test_sell_side_favorable_is_price_down(tmp_path):
    rec = _rec(tmp_path)
    t0 = 5_000_000
    rec.record_signal("s1", "ADAUSDT", "SELL", "BEAR_TREND", t0, 100.0)
    rec.on_tick("ADAUSDT", 99.80, t0 + 500)      # price down 20bps -> favorable +20
    rec.on_tick("ADAUSDT", 100.10, t0 + 1500)    # price up -> adverse -10
    rec.flush_all(t0 + 2000)
    fc = dict(((d, lvl), ts) for d, lvl, ts in _query(
        tmp_path, "SELECT direction, level_bps, first_cross_ms FROM shadow_first_crossing WHERE observation_id='s1'"))
    assert fc[("fav", 20)] == t0 + 500        # favorable = down for a short
    assert fc[("adv", 10)] == t0 + 1500       # adverse = up for a short


def test_first_extreme_orders_high_low_within_second(tmp_path):
    rec = _rec(tmp_path)
    t0 = 2_000_000
    rec.record_signal("o", "BTCUSDT", "BUY", "?", t0, 100.0)
    # within second 0: first goes low (-8) then high (+12) -> first_extreme should be "low"
    rec.on_tick("BTCUSDT", 99.92, t0 + 100)     # -8 bps
    rec.on_tick("BTCUSDT", 100.12, t0 + 800)    # +12 bps
    rec.flush_all(t0 + 1000)
    row = _query(tmp_path, "SELECT first_extreme, first_high_ms, first_low_ms FROM shadow_path_1s WHERE observation_id='o' AND second_offset=0")
    fe, fh, fl = row[0]
    assert fl < fh and fe == "low"


def test_data_quality_sparse_vs_ok(tmp_path):
    rec = _rec(tmp_path, horizon_s=10)   # wants >= 10 samples for "ok"
    t0 = 7_000_000
    rec.record_signal("sp", "SOLUSDT", "BUY", "?", t0, 100.0)
    rec.on_tick("SOLUSDT", 100.1, t0 + 100)      # only 1 sample
    rec.flush_all(t0 + 500)
    q = _query(tmp_path, "SELECT data_quality FROM shadow_excursion_observations WHERE observation_id='sp'")
    assert q == [("sparse",)]


def test_duplicate_observation_id_rejected(tmp_path):
    rec = _rec(tmp_path)
    assert rec.record_signal("dup", "ETHUSDT", "BUY", "?", 1000, 100.0) is True
    assert rec.record_signal("dup", "ETHUSDT", "BUY", "?", 1000, 100.0) is False
    assert rec.record_signal("bad", "ETHUSDT", "BUY", "?", 1000, 0.0) is False  # invalid entry_ref


def test_horizon_finalize_persists_once_and_removes(tmp_path):
    rec = _rec(tmp_path, horizon_s=5)
    t0 = 9_000_000
    rec.record_signal("h", "XRPUSDT", "BUY", "?", t0, 100.0)
    rec.on_tick("XRPUSDT", 100.1, t0 + 1000)
    rec.on_tick("XRPUSDT", 100.2, t0 + 6000)   # past 5s horizon -> finalize
    assert rec.active_count == 0
    # a further tick must not create rows or resurrect the observer
    rec.on_tick("XRPUSDT", 100.3, t0 + 7000)
    n = _query(tmp_path, "SELECT COUNT(*) FROM shadow_excursion_observations WHERE observation_id='h'")
    assert n == [(1,)]


def test_module_hooks_are_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_DATA_COLLECTION_ONLY", "false")
    R._singleton = None
    assert R.get_recorder() is None
    # the thin hooks must not raise and must not persist anything
    assert R.record_signal("x", "ETHUSDT", "BUY", "?", 1, 100.0) is False
    R.record_tick("ETHUSDT", 100.0, 2)   # no-op, no error


def test_persist_works_across_threads(tmp_path):
    """Reviewer: the cached sqlite connection may be created on a tick thread and
    reused from the main thread (flush_all on shutdown). check_same_thread=False +
    the lock must make that safe — without it sqlite raises ProgrammingError and
    the observation is lost."""
    import threading
    rec = _rec(tmp_path, horizon_s=5)
    t0 = 3_000_000

    def worker():
        rec.record_signal("wt", "ETHUSDT", "BUY", "?", t0, 100.0)
        rec.on_tick("ETHUSDT", 100.1, t0 + 1000)
        rec.on_tick("ETHUSDT", 100.2, t0 + 6000)   # finalize on THIS (worker) thread

    th = threading.Thread(target=worker)
    th.start(); th.join()
    # now persist a second observation from the MAIN thread using the same conn
    rec.record_signal("mt", "ADAUSDT", "BUY", "?", t0, 100.0)
    rec.on_tick("ADAUSDT", 100.1, t0 + 1000)
    assert rec.flush_all(t0 + 2000) == 1          # must not raise ProgrammingError
    ids = {r[0] for r in _query(tmp_path, "SELECT observation_id FROM shadow_excursion_observations")}
    assert ids == {"wt", "mt"}


def test_sweep_expired_finalizes_silent_observers(tmp_path):
    rec = _rec(tmp_path, horizon_s=5)
    t0 = 4_000_000
    rec.record_signal("a", "ETHUSDT", "BUY", "?", t0, 100.0)
    rec.record_signal("b", "SOLUSDT", "BUY", "?", t0, 100.0)
    rec.on_tick("ETHUSDT", 100.1, t0 + 1000)
    # both symbols go silent; a periodic sweep past the horizon must finalize both
    assert rec.sweep_expired(t0 + 1000) == 0       # not yet elapsed
    assert rec.sweep_expired(t0 + 6000) == 2       # both elapsed -> persisted
    assert rec.active_count == 0
    n = _query(tmp_path, "SELECT COUNT(*) FROM shadow_excursion_observations")
    assert n == [(2,)]


def test_no_trading_side_effects_surface():
    """The recorder must not IMPORT or CALL any order/close/learning/firebase path
    (checked via AST identifiers, so docstring prose describing what it avoids does
    not trip the test)."""
    import ast
    tree = ast.parse(open(R.__file__, encoding="utf-8").read())
    imported, called = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    forbidden_substr = ("firebase", "firestore", "event_bus", "firebase_client",
                        "paper_trade_executor", "learning")
    for mod in imported:
        assert not any(s in mod.lower() for s in forbidden_substr), \
            f"recorder must not import trading/learning/firebase module {mod}"
    for name in ("open_paper_position", "market_order", "close_paper_position", "publish"):
        assert name not in called, f"recorder must not call {name}"
