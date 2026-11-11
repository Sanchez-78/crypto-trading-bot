"""Independent synthetic reproduction of the completed-candle refresh fix (reviewer: Claude).

Simulates the live schedule against candle_cache_v1.CandleCache with an injected clock:
regular 60 s ticks at a fixed phase, sequential symbols with random jitter, random BTC
neural wakes, and optional fetch failures. No network, no runtime data.
"""
from __future__ import annotations

import importlib
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "XRPUSDT"]
MAX_AGE_MS = 90_000
START = 1_800_000_000.0  # multiple of 60


def run(flag: bool, phase: float, fail_rate: float, seed: int, minutes: int = 360) -> dict:
    os.environ["PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED"] = "true" if flag else "false"
    import src.services.candle_cache_v1 as cc
    importlib.reload(cc)
    rng = random.Random(seed)
    clock = {"t": START}
    fetches: list[tuple[str, float, bool]] = []

    def fetch(symbol, interval):
        now = clock["t"]
        ok = rng.random() >= fail_rate
        fetches.append((symbol, now, ok))
        if not ok:
            raise ConnectionError("synthetic")
        current_open = int(now // 60) * 60_000  # the still-open bar is included, like Binance
        return [{"open_time": current_open - i * 60_000} for i in range(5, -1, -1)]

    cache = cc.CandleCache(fetch_fn=fetch, now_fn=lambda: clock["t"], refresh_seconds=60.0)
    stale = evaluations = partial_promoted = 0
    evaluated_closes: dict[str, set] = {s: set() for s in SYMBOLS}

    def evaluate(symbol):
        nonlocal stale, evaluations, partial_promoted
        candles = cache.get_candles(symbol, completed_only=True)
        if not candles:
            return
        close_ms = candles[-1]["open_time"] + 60_000
        now_ms = int(clock["t"] * 1000)
        if close_ms > now_ms:
            partial_promoted += 1
        evaluations += 1
        if now_ms - close_ms > MAX_AGE_MS:
            stale += 1  # router veto REJECT_STALE_MARKET_DATA
        else:
            evaluated_closes[symbol].add(close_ms)

    events = []
    for m in range(minutes):
        events.append((START + m * 60 + phase, "tick"))
        for _ in range(rng.randint(0, 3)):  # BTC neural wakes between deadlines
            events.append((START + m * 60 + rng.uniform(0, 60), "btc"))
    for at, kind in sorted(events):
        clock["t"] = at
        for symbol in (SYMBOLS if kind == "tick" else ["BTCUSDT"]):
            evaluate(symbol)
            clock["t"] += rng.uniform(0.0, 0.8)  # per-symbol processing jitter

    per_minute = Counter((s, int(t // 60)) for s, t, _ in fetches)
    hammer = 0
    by_symbol: dict[str, list] = {}
    for s, t, ok in fetches:
        by_symbol.setdefault(s, []).append((t, ok))
    for seq in by_symbol.values():
        for (t1, ok1), (t2, _) in zip(seq, seq[1:]):
            if not ok1 and t2 - t1 < 60:
                hammer += 1
    closes_expected = minutes - 2
    missed = sum(max(0, closes_expected - len(v)) for v in evaluated_closes.values()) / len(SYMBOLS)
    return {"flag": flag, "phase_s": phase, "fail_rate": fail_rate, "evaluations": evaluations,
            "stale_share": round(stale / max(1, evaluations), 4),
            "missed_closes_per_symbol": round(missed, 1), "closes_expected_per_symbol": closes_expected,
            "max_fetches_symbol_minute": max(per_minute.values()), "fetches": len(fetches),
            "retry_within_60s_after_failure": hammer, "partial_promoted": partial_promoted}


def main() -> None:
    results = [run(flag, phase, fail, seed=7)
               for phase in (47.0, 15.0) for fail in (0.0, 0.05) for flag in (False, True)]
    out = Path(__file__).with_name("simulation.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
