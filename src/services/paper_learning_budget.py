"""Bounded PAPER research sampling from existing durable entry evidence.

No orders, ledger or state writes. Read positions before the immutable close
journal so a concurrent close is counted at least once; dedup by trade ID.
The existing single entry scheduler serializes admission and final recheck.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Mapping, Sequence

SOURCES = frozenset(f"{name}_paper_probe_v2" for name in (
    "trend_cost_aware", "volatility_breakout", "sideways_mean_reversion"))
HOURLY_ENTRIES = 6
DAILY_ENTRIES = 48
SYMBOL_COOLDOWN_MS = 30 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
# Optional operator overrides; unset keeps the defaults above, invalid fails closed.
LIMIT_ENV = {"hourly": ("PAPER_PROBE_HOURLY_ENTRIES", 1, 600),
             # read_entries() refuses more than 1000 rows per rolling day.
             "daily": ("PAPER_PROBE_DAILY_ENTRIES", 1, 900),
             "cooldown_s": ("PAPER_PROBE_SYMBOL_COOLDOWN_S", 0, 86400)}


@dataclass(frozen=True)
class Limits:
    hourly: int
    daily: int
    cooldown_ms: int


def limits(env: Mapping[str, str] | None = None) -> Limits:
    values = os.environ if env is None else env
    parsed = {}
    for name, (key, low, high) in LIMIT_ENV.items():
        raw = values.get(key, "").strip()
        if not raw:
            parsed[name] = None
            continue
        try:
            number = int(raw)
        except ValueError as exc:
            raise ValueError("invalid_paper_probe_limit") from exc
        if not low <= number <= high:
            raise ValueError("invalid_paper_probe_limit")
        parsed[name] = number
    cooldown_s = parsed["cooldown_s"]
    return Limits(HOURLY_ENTRIES if parsed["hourly"] is None else parsed["hourly"],
                  DAILY_ENTRIES if parsed["daily"] is None else parsed["daily"],
                  SYMBOL_COOLDOWN_MS if cooldown_s is None else cooldown_s * 1000)


@dataclass(frozen=True)
class Entry:
    trade_id: str
    symbol: str
    entry_ms: int


def pacing_reason(entries: Sequence[Entry], *, symbol: str, now_ms: int,
                  limit: Limits | None = None) -> str:
    if type(now_ms) is not int or now_ms <= 0:
        raise ValueError("invalid_probe_clock")
    limit = limits() if limit is None else limit
    unique: dict[str, Entry] = {}
    for entry in entries:
        if (not isinstance(entry, Entry) or not entry.trade_id or not entry.symbol
                or type(entry.entry_ms) is not int or not 0 < entry.entry_ms <= now_ms):
            raise ValueError("invalid_probe_entry")
        previous = unique.get(entry.trade_id)
        if previous is not None and previous != entry:
            raise ValueError("conflicting_probe_entry")
        unique[entry.trade_id] = entry
    rows = [row for row in unique.values() if now_ms - row.entry_ms < DAY_MS]
    if len(rows) >= limit.daily:
        return "rolling_day_limit"
    if sum(now_ms - row.entry_ms < 3_600_000 for row in rows) >= limit.hourly:
        return "rolling_hour_limit"
    if any(row.symbol == symbol and now_ms - row.entry_ms < limit.cooldown_ms for row in rows):
        return "symbol_cooldown"
    return "allow"


def _entry(row: Mapping) -> Entry:
    stamp = row.get("entry_ts")
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
        raise ValueError("invalid_probe_entry_timestamp")
    if not isinstance(row.get("trade_id"), str) or not isinstance(row.get("symbol"), str):
        raise ValueError("invalid_probe_entry_identity")
    return Entry(row["trade_id"], row["symbol"], round(stamp * 1000))


def read_entries(path: Path, positions: Sequence[Mapping], *, now_ms: int) -> list[Entry]:
    entries = [_entry(row) for row in positions if row.get("learning_source") in SOURCES]
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + 1.0
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        # Includes quarantined/learning-skipped and pending closes which may
        # intentionally not project to the canonical learner's closed_trades.
        rows = db.execute(
            "SELECT position FROM paper_close_journal "
            "WHERE json_extract(position,'$.learning_source') IN (?,?,?) "
            "AND (json_type(position,'$.entry_ts') IS NULL "
            "OR json_type(position,'$.entry_ts') NOT IN ('integer','real') "
            "OR json_extract(position,'$.entry_ts')<=0 "
            "OR json_extract(position,'$.entry_ts')>=?) LIMIT 1001",
            (*sorted(SOURCES), (now_ms - DAY_MS) / 1000),
        ).fetchall()
    if len(rows) > 1000:
        raise ValueError("unbounded_probe_history")
    for (payload,) in rows:
        if len(payload) > 131072:
            raise ValueError("oversized_probe_position")
        entries.append(_entry(json.loads(payload)))
    return entries


def current_reason(symbol: str, *, now_ms: int) -> str:
    from src.services import paper_trade_executor as broker
    positions = list(broker.get_open_positions().values())
    entries = read_entries(broker._paper_close_journal().path, positions, now_ms=now_ms)
    return pacing_reason(entries, symbol=symbol, now_ms=now_ms)
