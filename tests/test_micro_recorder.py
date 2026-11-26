import csv
import gzip
import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("micro_recorder", ROOT / "scripts" / "research" / "micro_recorder.py")
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

T = 1_795_700_000          # 2026-11-26 UTC


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:      # concatenated gzip members read as one stream
        return list(csv.DictReader(fh))


def depth(e_ms, bid=100.0, ask=100.02, qty=1.0):
    return {"E": e_ms, "b": [[f"{bid - i * 0.01:.2f}", str(qty)] for i in range(20)],
            "a": [[f"{ask + i * 0.01:.2f}", str(qty)] for i in range(20)]}


def test_book_features_bands_imbalance_and_coverage():
    row = m.book_features("btcusdt", T, T * 1000, 2, [["100", "2"], ["99.95", "1"], ["99", "5"]],
                          [["100.02", "1"], ["100.2", "3"]])
    mid = 100.01
    assert row["symbol"] == "BTCUSDT" and row["bid1"] == 100 and row["ask1"] == 100.02
    assert row["spread_bps"] == pytest.approx(0.02 / mid * 1e4, abs=1e-4)
    assert row["bid_notional_10bps"] == pytest.approx(100 * 2 + 99.95 * 1)          # 99 is ~100 bps away
    assert row["ask_notional_10bps"] == pytest.approx(100.02)
    assert row["ask_notional_25bps"] == pytest.approx(100.02 + 100.2 * 3)
    assert row["bid_range_bps"] == pytest.approx((mid - 99) / mid * 1e4, abs=1e-3)
    b, a = row["bid_notional_10bps"], row["ask_notional_10bps"]
    assert row["imbalance_10bps"] == pytest.approx((b - a) / (b + a), abs=1e-6)
    assert m.book_features("x", T, 0, 1, [["100", "1"]], [["99", "1"]]) is None      # crossed
    assert m.book_features("x", T, 0, 1, [], [["99", "1"]]) is None
    assert m.book_features("x", T, 0, 1, [["nan", "1"], ["100", "1"]], [["101", "1"]])["bid1"] == 100


def test_liquidation_row_parsing():
    payload = {"E": 5, "o": {"s": "ETHUSDT", "S": "SELL", "o": "LIMIT", "X": "FILLED", "p": "3000", "ap": "2990",
                             "q": "2", "z": "2", "T": 4}}
    row = m.liquidation_row(payload)
    assert row["symbol"] == "ETHUSDT" and row["side"] == "SELL" and row["notional"] == pytest.approx(5980)
    assert m.liquidation_row({"o": {"p": "x"}}) is None
    assert m.liquidation_row({"o": {"p": "nan", "ap": "1", "q": "1", "z": "1"}}) is None


def test_one_row_per_second_with_the_last_snapshot_and_update_count(tmp_path):
    rec = m.Recorder(tmp_path, clock=Clock(T + 10))
    rec.on_depth("btcusdt", depth(T * 1000 + 100, bid=100.0))
    rec.on_depth("btcusdt", depth(T * 1000 + 600, bid=100.01, ask=100.03))
    rec.on_depth("btcusdt", depth((T + 1) * 1000 + 100, bid=101.0, ask=101.02))
    rec.flush()
    rows = read_rows(tmp_path / "book" / f"{time.strftime('%Y-%m-%d', time.gmtime(T))}.csv.gz")
    assert [r["ts_s"] for r in rows] == [str(T), str(T + 1)]
    assert rows[0]["bid1"] == "100.01" and rows[0]["updates"] == "2"
    assert rows[1]["updates"] == "1"


def test_open_second_is_not_closed_early(tmp_path):
    clock = Clock(T)
    rec = m.Recorder(tmp_path, clock=clock)
    rec.on_depth("ethusdt", depth(T * 1000 + 100))
    rec.flush()                                   # second T still running -> nothing written
    assert not (tmp_path / "book").exists()
    clock.t = T + 1
    rec.flush()
    assert len(read_rows(next((tmp_path / "book").glob("*.csv.gz")))) == 1


def test_appended_gzip_members_keep_a_single_header(tmp_path):
    clock = Clock(T + 5)
    rec = m.Recorder(tmp_path, clock=clock)
    for k in range(3):
        rec.on_depth("solusdt", depth((T + k) * 1000))
        clock.t = T + k + 1
        rec.flush()
    rows = read_rows(next((tmp_path / "book").glob("*.csv.gz")))
    assert len(rows) == 3 and all(r["symbol"] == "SOLUSDT" for r in rows)


def test_buffer_cap_drops_and_records_a_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MAX_BUFFER", 2)
    rec = m.Recorder(tmp_path, clock=Clock(T + 100))
    for k in range(5):
        rec.on_liquidation({"E": T * 1000 + k, "o": {"s": "BTCUSDT", "S": "BUY", "o": "LIMIT", "X": "FILLED",
                                                    "p": "1", "ap": "1", "q": "1", "z": "1", "T": 1}})
    rec.flush()
    assert len(read_rows(next((tmp_path / "liq_sampled").glob("*.csv.gz")))) == 2
    gaps = read_rows(next((tmp_path / "gaps").glob("*.csv.gz")))
    assert gaps[-1]["kind"] == "dropped_rows" and gaps[-1]["detail"] == "3"


def test_low_disk_drops_data_but_records_the_loss_window_on_recovery(tmp_path, monkeypatch):
    logs = []
    clock = Clock(T + 100)
    rec = m.Recorder(tmp_path, clock=clock, log=logs.append)
    free = {"v": m.MIN_FREE_BYTES - 1}
    monkeypatch.setattr(m.shutil, "disk_usage", lambda _p: type("U", (), {"free": free["v"]})())
    rec.gap("connect")
    for k in range(3):                                   # three flushes while the disk is low
        rec.on_depth("btcusdt", depth((T + 10 * k) * 1000 + 5))
        rec.on_liquidation({"E": (T + 10 * k) * 1000, "o": {"s": "BTCUSDT", "S": "BUY", "o": "LIMIT", "X": "FILLED",
                                                           "p": "1", "ap": "1", "q": "1", "z": "1", "T": 1}})
        clock.t = T + 10 * k + 1
        rec.flush()
    assert not any(tmp_path.glob("*/*.csv.gz"))
    assert rec.skipped_disk == 6 and len(logs) == 1     # one log line per LOG_EVERY_S
    free["v"] = m.MIN_FREE_BYTES + 1                     # disk recovered
    clock.t = T + 100
    rec.flush()
    gaps = read_rows(next((tmp_path / "gaps").glob("*.csv.gz")))
    skip = [g for g in gaps if g["kind"] == "disk_skip"]
    assert len(skip) == 1
    detail = json.loads(skip[0]["detail"])
    assert detail == {"from_ms": T * 1000, "to_ms": (T + 20) * 1000, "rows": {"book": 3, "liq_sampled": 3}}
    assert any(g["kind"] == "connect" for g in gaps)     # gap markers survived the low-disk period
    assert not (tmp_path / "book").exists()              # dropped data is not resurrected
    assert rec.loss is None


def test_low_disk_without_data_opens_no_loss_window(tmp_path, monkeypatch):
    rec = m.Recorder(tmp_path, clock=Clock(T + 100))
    monkeypatch.setattr(m.shutil, "disk_usage", lambda _p: type("U", (), {"free": 0})())
    rec.flush()
    assert rec.loss is None


def test_prune_by_age_then_by_total_size_but_never_today(tmp_path, monkeypatch):
    clock = Clock(T)
    rec = m.Recorder(tmp_path, clock=clock)
    today = time.strftime("%Y-%m-%d", time.gmtime(T))
    old = time.strftime("%Y-%m-%d", time.gmtime(T - (m.RETENTION_DAYS + 1) * 86400))
    mid1 = time.strftime("%Y-%m-%d", time.gmtime(T - 10 * 86400))
    mid2 = time.strftime("%Y-%m-%d", time.gmtime(T - 5 * 86400))
    for kind, day, size in (("book", old, 10), ("book", mid1, 100), ("liq_sampled", mid2, 100), ("book", today, 100)):
        p = tmp_path / kind / f"{day}.csv.gz"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    monkeypatch.setattr(m, "MAX_TOTAL_BYTES", 250)
    removed = {p.name for p in rec.prune()}
    assert removed == {f"{old}.csv.gz", f"{mid1}.csv.gz"}
    assert (tmp_path / "book" / f"{today}.csv.gz").exists() and (tmp_path / "liq_sampled" / f"{mid2}.csv.gz").exists()


def test_dispatch_routes_streams_and_ignores_unknown(tmp_path):
    rec = m.Recorder(tmp_path, clock=Clock(T + 10))
    rec.dispatch(json.dumps({"stream": "xrpusdt@depth20@500ms", "data": depth(T * 1000)}))
    rec.dispatch(json.dumps({"stream": "dogeusdt@depth20@500ms", "data": depth(T * 1000)}))
    rec.dispatch("not json")
    rec.dispatch(json.dumps({"stream": "xrpusdt@forceOrder", "data": {"E": T * 1000, "o": {
        "s": "XRPUSDT", "S": "SELL", "o": "LIMIT", "X": "FILLED", "p": "1", "ap": "1", "q": "5", "z": "5", "T": 1}}}))
    assert list(rec.pending) == ["xrpusdt"] and len(rec.buffers["liq_sampled"]) == 1
    url = m.stream_url()
    assert url.startswith("wss://fstream.binance.com/stream?streams=") and url.count("@depth20@500ms") == 7
    assert url.count("@forceOrder") == 7
