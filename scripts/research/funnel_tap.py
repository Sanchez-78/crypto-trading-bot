#!/usr/bin/env python3
"""Read-only candidate-funnel counter for the PAPER bot (research side).

The bot's journal keeps only ~15 minutes (log volume), so admission funnel
counts cannot be reconstructed later. This tap follows the journal and writes
hourly counts of funnel stages to ``<out>/YYYYMMDD.jsonl``.

Counts only: it never records prices, P/L or outcomes (exits are ignored), so it
is safe during the blind phase of the C1 preregistration.

  tap:      journalctl -f -u cryptomaster -o cat | funnel_tap.py tap --out DIR
  summary:  funnel_tap.py summary --out DIR --hours 12
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import re
import signal
import sys
import time

_P08 = re.compile(r"\[P0_8_PLUS_LIVE\] (\w+) (\w+) (BUY|SELL) .*?admitted=(True|False) code=(\w+)")
_ENTRY = re.compile(r"\[PAPER_ENTRY\] symbol=(\w+) .*?reason=(\w+)")
_BUDGET = re.compile(r"\[PAPER_LEARNING_BUDGET\] symbol=(\w+) reason=(\w+)")
_SKIP = re.compile(r"\[PAPER_EXPLORE_SKIP\] reason=(\w+) symbol=(\w+)")


def parse(line: str) -> str | None:
    """Map one journal line to a funnel key, or None for anything else."""
    if (m := _P08.search(line)):
        symbol, strategy, _side, admitted, code = m.groups()
        return f"p08|{strategy}|{symbol}|{'admit' if admitted == 'True' else code}"
    if (m := _ENTRY.search(line)):
        return f"entry|{m.group(2)}|{m.group(1)}"
    if (m := _BUDGET.search(line)):
        return f"budget|{m.group(2)}|{m.group(1)}"
    if (m := _SKIP.search(line)):
        return f"skip|{m.group(1)}|{m.group(2)}"
    return None


def _hour(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def _flush(out: pathlib.Path, hour: str, counts: collections.Counter, partial: bool) -> None:
    if not counts:
        return
    out.mkdir(parents=True, exist_ok=True)
    path = out / (hour[:10].replace("-", "") + ".jsonl")
    record = {"hour": hour, "partial": partial, "counts": dict(sorted(counts.items()))}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def tap(lines, out: pathlib.Path, clock=time.time) -> None:
    """Aggregate per UTC hour; the first and an interrupted last hour are marked partial."""
    hour, counts, partial = _hour(clock()), collections.Counter(), True
    try:
        for line in lines:
            now = _hour(clock())
            if now != hour:
                _flush(out, hour, counts, partial)
                hour, counts, partial = now, collections.Counter(), False
            key = parse(line)
            if key:
                counts[key] += 1
    finally:
        _flush(out, hour, counts, True)


def summarize(out: pathlib.Path, hours: int, now: float | None = None) -> str:
    """One-line summary of the last ``hours`` complete hours (counts only)."""
    now = time.time() if now is None else now
    first = _hour(now - hours * 3600)
    last = _hour(now)
    total, seen = collections.Counter(), set()
    for path in sorted(out.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(raw)
            if first <= rec["hour"] < last:
                seen.add(rec["hour"])
                total.update(rec["counts"])
    if not seen:
        return f"FUNNEL hours=0/{hours} unavailable"
    group = collections.Counter()
    for key, n in total.items():
        kind, a, _symbol, *rest = key.split("|")
        if kind == "p08":
            group[f"p08:{rest[0]}"] += n
        elif kind in ("entry", "budget"):
            group[f"{kind}:{a}"] += n
    p08_total = sum(n for k, n in group.items() if k.startswith("p08:"))
    top = ",".join(f"{k}={n}" for k, n in group.most_common(8))
    return f"FUNNEL hours={len(seen)}/{hours} p08_candidates={p08_total} {top}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("tap", "summary"))
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--hours", type=int, default=12)
    args = ap.parse_args(argv)
    if args.mode == "tap":
        # systemd stops with SIGTERM; turn it into SystemExit so the partial hour is flushed.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        tap(sys.stdin, args.out)
    else:
        print(summarize(args.out, args.hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
