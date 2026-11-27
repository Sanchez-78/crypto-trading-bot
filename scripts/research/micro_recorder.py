#!/usr/bin/env python3
"""Order-book + liquidation recorder for research (Binance USD-M public websocket). Never imports bot code.

Design + limits: _workspace/2026-11-26_micro_recorder_design.md. Stdlib + websocket-client only.

Streams, two connections (rev. 6; Binance split the USD-M websocket endpoints and the legacy /stream URL no
longer delivers forceOrder, probe 2026-11-27):
  public  wss://fstream.binance.com/public/stream  <sym>@depth20@500ms (PARTIAL top-20 snapshots, not a full book)
  market  wss://fstream.binance.com/market/stream  <sym>@forceOrder
Binance publishes at most ONE liquidation per symbol per 1000 ms (since 2026-04 the largest in the interval), so
the liquidation output is a SAMPLED proxy, never the complete set of liquidations. Each connection writes its own
connect/disconnect gap markers (detail = connection name); message counts are logged hourly.
Outputs under --out (a systemd StateDirectory), one gzip member appended per flush:
  book/YYYY-MM-DD.csv.gz         one row per symbol per second (last snapshot of that second, derived features)
  liq_sampled/YYYY-MM-DD.csv.gz  one row per received forceOrder event (sampled upstream, see above)
  gaps/YYYY-MM-DD.csv.gz         start / connect / disconnect / dropped_rows / disk_skip markers
Guards: bounded buffers (rows dropped and recorded as dropped_rows beyond MAX_BUFFER); data rows not written when
free disk < MIN_FREE_BYTES, the loss window (from/to ms, rows per kind) recorded as a disk_skip gap row on
recovery; retention (files older than RETENTION_DAYS or beyond MAX_TOTAL_BYTES pruned oldest first, never
today); rate-limited logs. A write error exits (systemd restart); the hole then ends at the next 'start' marker.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import shutil
import sys
import threading
import time
from pathlib import Path

SYMBOLS = ("btcusdt", "ethusdt", "solusdt", "adausdt", "bnbusdt", "dotusdt", "xrpusdt")
WS_PUBLIC = "wss://fstream.binance.com/public/stream?streams="
WS_MARKET = "wss://fstream.binance.com/market/stream?streams="
STATS_EVERY_S = 3600
BANDS_BPS = (5, 10, 25)
FLUSH_SECONDS = 60
MAX_BUFFER = 50_000
MIN_FREE_BYTES = 5 * 1024 ** 3
MAX_TOTAL_BYTES = 4 * 1024 ** 3
RETENTION_DAYS = 120
LOG_EVERY_S = 300

BOOK_FIELDS = ["ts_s", "symbol", "event_ms", "updates", "bid1", "ask1", "spread_bps", "bid1_qty", "ask1_qty",
               *[f"bid_notional_{b}bps" for b in BANDS_BPS], *[f"ask_notional_{b}bps" for b in BANDS_BPS],
               "bid_notional_20lvl", "ask_notional_20lvl", "bid_range_bps", "ask_range_bps", "imbalance_10bps"]
LIQ_FIELDS = ["event_ms", "trade_ms", "symbol", "side", "order_type", "status", "price", "avg_price",
              "qty", "filled_qty", "notional"]
GAP_FIELDS = ["ts_ms", "kind", "detail"]


def _levels(raw) -> list[tuple[float, float]]:
    out = []
    for item in raw or ():
        price, qty = float(item[0]), float(item[1])
        if math.isfinite(price) and math.isfinite(qty) and price > 0 and qty >= 0:
            out.append((price, qty))
    return out


def book_features(symbol: str, ts_s: int, event_ms: int, updates: int, bids_raw, asks_raw) -> dict | None:
    """Derived features of one partial-depth snapshot; None when the book is empty or crossed."""
    bids = sorted(_levels(bids_raw), key=lambda x: -x[0])
    asks = sorted(_levels(asks_raw), key=lambda x: x[0])
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        return None
    bid1, ask1 = bids[0][0], asks[0][0]
    mid = (bid1 + ask1) / 2
    row = {"ts_s": ts_s, "symbol": symbol.upper(), "event_ms": event_ms, "updates": updates,
           "bid1": bid1, "ask1": ask1, "spread_bps": round((ask1 - bid1) / mid * 1e4, 4),
           "bid1_qty": bids[0][1], "ask1_qty": asks[0][1]}
    for band in BANDS_BPS:
        lo, hi = mid * (1 - band / 1e4), mid * (1 + band / 1e4)
        row[f"bid_notional_{band}bps"] = round(sum(p * q for p, q in bids if p >= lo), 2)
        row[f"ask_notional_{band}bps"] = round(sum(p * q for p, q in asks if p <= hi), 2)
    row["bid_notional_20lvl"] = round(sum(p * q for p, q in bids), 2)
    row["ask_notional_20lvl"] = round(sum(p * q for p, q in asks), 2)
    row["bid_range_bps"] = round((mid - bids[-1][0]) / mid * 1e4, 4)
    row["ask_range_bps"] = round((asks[-1][0] - mid) / mid * 1e4, 4)
    b, a = row["bid_notional_10bps"], row["ask_notional_10bps"]
    row["imbalance_10bps"] = round((b - a) / (b + a), 6) if b + a > 0 else None
    return row


def liquidation_row(payload: dict) -> dict | None:
    o = payload.get("o") or {}
    try:
        price, avg, qty, filled = (float(o.get(k)) for k in ("p", "ap", "q", "z"))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (price, avg, qty, filled)):
        return None
    return {"event_ms": int(payload.get("E", 0)), "trade_ms": int(o.get("T", 0)), "symbol": str(o.get("s", "")).upper(),
            "side": o.get("S"), "order_type": o.get("o"), "status": o.get("X"), "price": price, "avg_price": avg,
            "qty": qty, "filled_qty": filled, "notional": round((avg or price) * (filled or qty), 2)}


def log_line(message: str) -> None:
    # stdout is block-buffered under systemd and os._exit() skips buffer flushing: flush every line
    print(message, flush=True)


class Recorder:
    """Holds the per-second state and bounded buffers; all file I/O goes through flush()."""

    def __init__(self, out: Path, clock=time.time, log=log_line):
        self.out, self.clock, self.log = Path(out), clock, log
        self.lock = threading.Lock()
        self.pending: dict[str, tuple] = {}      # symbol -> (ts_s, event_ms, updates, bids, asks)
        self.buffers: dict[str, list[dict]] = {"book": [], "liq_sampled": [], "gaps": []}
        self.dropped = 0
        self.skipped_disk = 0
        self.loss: dict | None = None            # open low-disk loss window, written as a gap row on recovery
        self._last_log: dict[str, float] = {}

    def _rate_log(self, key: str, message: str) -> None:
        now = self.clock()
        if now - self._last_log.get(key, -1e18) >= LOG_EVERY_S:
            self._last_log[key] = now
            self.log(message)

    def _append(self, kind: str, row: dict) -> None:
        buf = self.buffers[kind]
        if len(buf) >= MAX_BUFFER:
            self.dropped += 1
            return
        buf.append(row)

    def on_depth(self, symbol: str, data: dict) -> None:
        event_ms = int(data.get("E", 0))
        ts_s = event_ms // 1000
        with self.lock:
            prev = self.pending.get(symbol)
            if prev and prev[0] != ts_s:
                self._close_second(symbol, prev)
                prev = None
            updates = (prev[2] if prev else 0) + 1
            self.pending[symbol] = (ts_s, event_ms, updates, data.get("b"), data.get("a"))

    def _close_second(self, symbol: str, state: tuple) -> None:
        row = book_features(symbol, *state)
        if row is not None:
            self._append("book", row)

    def on_liquidation(self, payload: dict) -> None:
        row = liquidation_row(payload)
        if row is not None:
            with self.lock:
                self._append("liq_sampled", row)

    def gap(self, kind: str, detail: str = "") -> None:
        with self.lock:
            self._append("gaps", {"ts_ms": int(self.clock() * 1000), "kind": kind, "detail": detail[:200]})

    def flush(self) -> None:
        with self.lock:
            now_s = int(self.clock())
            for symbol, state in list(self.pending.items()):
                if state[0] < now_s:                 # the second is over: no more snapshots can join it
                    self._close_second(symbol, state)
                    del self.pending[symbol]
            if self.dropped:
                self.buffers["gaps"].append({"ts_ms": now_s * 1000, "kind": "dropped_rows", "detail": str(self.dropped)})
                self.dropped = 0
            batches = {k: v for k, v in self.buffers.items() if v}
            self.buffers = {"book": [], "liq_sampled": [], "gaps": []}
        self.out.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.out).free
        if free < MIN_FREE_BYTES:
            # Data rows are dropped, but the loss is kept as a window (first/last ms, rows per kind) and written
            # to gaps/ as one 'disk_skip' row as soon as writing resumes. Gap markers themselves are kept
            # (re-queued, bounded by MAX_BUFFER) so connect/disconnect evidence is not lost either.
            data = {k: v for k, v in batches.items() if k != "gaps"}
            if data:
                stamps = [self._row_ms(k, r) for k, rows in data.items() for r in rows]
                loss = self.loss or {"from_ms": min(stamps), "to_ms": max(stamps), "rows": {}}
                loss["from_ms"], loss["to_ms"] = min(loss["from_ms"], *stamps), max(loss["to_ms"], *stamps)
                for k, rows in data.items():
                    loss["rows"][k] = loss["rows"].get(k, 0) + len(rows)
                self.loss = loss
            with self.lock:
                for row in batches.get("gaps", []):
                    self._append("gaps", row)
            self.skipped_disk += sum(len(v) for v in data.values())
            self._rate_log("disk", f"[MICRO] free disk {free} < {MIN_FREE_BYTES}: not writing data "
                                   f"(skipped rows so far {self.skipped_disk})")
            return
        if self.loss is not None:
            batches.setdefault("gaps", []).insert(0, {"ts_ms": now_s * 1000, "kind": "disk_skip",
                                                      "detail": json.dumps(self.loss, sort_keys=True)})
            self.loss = None
        if not batches:
            return
        for kind, rows in batches.items():
            fields = {"book": BOOK_FIELDS, "liq_sampled": LIQ_FIELDS, "gaps": GAP_FIELDS}[kind]
            by_day: dict[str, list[dict]] = {}
            for row in rows:
                ms = self._row_ms(kind, row)
                by_day.setdefault(time.strftime("%Y-%m-%d", time.gmtime(ms / 1000)), []).append(row)
            for day, day_rows in by_day.items():
                self._write(self.out / kind / f"{day}.csv.gz", fields, day_rows)

    @staticmethod
    def _row_ms(kind: str, row: dict) -> int:
        if kind == "book":
            return int(row.get("ts_s", 0)) * 1000
        return int(row.get("event_ms" if kind == "liq_sampled" else "ts_ms", 0))

    @staticmethod
    def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore")
        if not path.exists():
            writer.writeheader()
        writer.writerows(rows)
        with open(path, "ab") as fh:              # a new gzip member per flush; gzip readers concatenate members
            fh.write(gzip.compress(text.getvalue().encode("utf-8")))
            fh.flush()
            os.fsync(fh.fileno())

    def prune(self) -> list[Path]:
        """Delete data files older than RETENTION_DAYS, then oldest first while the total exceeds MAX_TOTAL_BYTES."""
        files = sorted(self.out.glob("*/*.csv.gz"), key=lambda p: p.name)
        removed = []
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(self.clock() - RETENTION_DAYS * 86400))
        for p in files:
            if p.name[:10] < cutoff:
                p.unlink()
                removed.append(p)
        files = [p for p in files if p not in removed]
        total = sum(p.stat().st_size for p in files)
        today = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        for p in files:
            if total <= MAX_TOTAL_BYTES:
                break
            if p.name.startswith(today):
                continue
            total -= p.stat().st_size
            p.unlink()
            removed.append(p)
        return removed

    def dispatch(self, message: str) -> None:
        try:
            msg = json.loads(message)
        except ValueError:
            return
        stream, data = str(msg.get("stream", "")), msg.get("data") or {}
        symbol = stream.split("@", 1)[0]
        if symbol not in SYMBOLS:
            return
        if stream.endswith("@depth20@500ms"):
            self.on_depth(symbol, data)
        elif stream.endswith("@forceOrder"):
            self.on_liquidation(data)


def stream_urls(symbols=SYMBOLS) -> dict[str, str]:
    """Connection name -> combined-stream URL (order book on /public, liquidations on /market)."""
    return {"public": WS_PUBLIC + "/".join(f"{s}@depth20@500ms" for s in symbols),
            "market": WS_MARKET + "/".join(f"{s}@forceOrder" for s in symbols)}


def connection_loop(rec: "Recorder", name: str, url: str, run_once, stop: threading.Event,
                    counts: dict, clock=time.time, sleep=time.sleep) -> None:
    """Reconnect forever: connect/disconnect gap markers carry the connection name; backoff 1..60 s."""
    backoff = 1
    while not stop.is_set():
        rec.gap("connect", name)
        started = clock()

        def on_message(message, _name=name):
            counts[_name] = counts.get(_name, 0) + 1
            rec.dispatch(message)
        run_once(url, on_message)
        rec.gap("disconnect", name)
        backoff = 1 if clock() - started > 300 else min(60, backoff * 2)
        sleep(backoff)


def hourly_stats(rec, counts: dict) -> dict:
    """Per-connection message counts of the last hour: logged AND kept as a `msgs_hour` row in gaps/,
    because the server's in-memory journal holds only minutes of history (the bot logs ~290 lines/s)."""
    snapshot = dict(counts)
    counts.clear()
    detail = json.dumps({name: snapshot.get(name, 0) for name in ("public", "market")}, sort_keys=True)
    rec.log(f"[MICRO] messages in the last hour: {detail}")
    rec.gap("msgs_hour", detail)
    return snapshot


def run(out: Path) -> int:  # pragma: no cover - network loop, exercised on the server only
    import websocket  # websocket-client
    rec = Recorder(out)
    stop = threading.Event()
    counts: dict[str, int] = {}

    def run_once(url, on_message):
        ws = websocket.WebSocketApp(url, on_message=lambda _ws, m: on_message(m),
                                    on_error=lambda _ws, e: rec._rate_log("ws", f"[MICRO] ws error {e!r}"))
        ws.run_forever(ping_interval=0)

    def flusher():
        last_prune = last_stats = time.time()
        while not stop.wait(FLUSH_SECONDS):
            try:
                rec.flush()
                if time.time() - last_prune > 3600:
                    rec.prune()
                    last_prune = time.time()
            except OSError as exc:
                rec.log(f"[MICRO] write failed, exiting for a systemd restart: {exc!r}")
                os._exit(3)
            if time.time() - last_stats >= STATS_EVERY_S:
                hourly_stats(rec, counts)
                last_stats = time.time()

    def guarded(name, url):
        try:
            connection_loop(rec, name, url, run_once, stop, counts)
        except Exception as exc:  # a dead connection thread must not leave a silent half-recorder
            rec.log(f"[MICRO] connection {name} crashed, exiting for a systemd restart: {exc!r}")
            os._exit(4)

    threading.Thread(target=flusher, daemon=True).start()
    rec.gap("start", f"pid={os.getpid()}")      # after a crash/restart the hole ends at this marker
    threads = [threading.Thread(target=guarded, args=item, daemon=True) for item in stream_urls().items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


def main(argv=None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="order book + liquidation research recorder")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.out)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
