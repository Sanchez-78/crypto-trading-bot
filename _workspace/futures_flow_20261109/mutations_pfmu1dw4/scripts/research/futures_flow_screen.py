#!/usr/bin/env python3
"""Offline, preregistered futures-flow cost-wall screen; never imports bot code.

Public ZIPs are checksum-verified and read without extraction. TRAIN selections
are frozen before TEST; TEST is frozen before any HOLDOUT price data is parsed.
This is a historical price screen, not an executable-fill or trading engine.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import numpy as np
import pandas as pd

LOG = logging.getLogger("futures_flow_screen")
BASE_URL = "https://data.binance.vision/"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "XRPUSDT")
MINUTE = 60_000
DAY = 86_400_000
SEED = 20261109
FEATURES = ("H1_5", "H1_60", "H2_5", "H2_15", "H3_5", "H3_60",
            "H4_5", "H4_15", "H5_5", "H5_15", "H6_1", "H6_5")
FAMILIES = tuple(f"H{i}" for i in range(1, 8))
METRICS = ("sum_open_interest", "sum_open_interest_value",
           "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
           "count_long_short_ratio", "sum_taker_long_short_vol_ratio")


def stamp(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


@dataclass(frozen=True)
class Protocol:
    start: str = "2024-01-01"
    train_end: str = "2025-07-01"
    test_start: str = "2025-07-02"
    test_end: str = "2026-04-01"
    holdout_start: str = "2026-04-02"
    seed: int = SEED
    bootstrap: int = 2000
    horizon_minutes: int = 15
    tp_bps: float = 35.0
    sl_bps: float = 25.0


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("xb") as handle:
            handle.write(json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def month_keys(start: str, end: str) -> list[str]:
    return [str(period) for period in pd.period_range(start[:7], end[:7], freq="M")]


def archive_key(kind: str, symbol: str, period: str) -> str:
    if symbol not in SYMBOLS:
        raise ValueError("unsupported symbol")
    if kind == "metrics":
        date.fromisoformat(period)
        return f"data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{period}.zip"
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", period):
        raise ValueError("invalid month")
    if kind == "funding":
        return f"data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{period}.zip"
    if kind not in ("futures", "spot"):
        raise ValueError("invalid kind")
    venue = "futures/um" if kind == "futures" else "spot"
    return f"data/{venue}/monthly/klines/{symbol}/1m/{symbol}-1m-{period}.zip"


def download_bytes(url: str, *, limit: int, timeout: float = 20) -> bytes:
    if not url.startswith(BASE_URL + "data/"):
        raise ValueError("non-archive URL")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("archive response too large")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or exc.code < 500 or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    raise RuntimeError("unreachable download state")


def fetch_archive(cache: Path, kind: str, symbol: str, period: str, *, offline: bool = False) -> dict:
    key = archive_key(kind, symbol, period)
    path = cache / key
    checksum_path = path.with_suffix(".zip.CHECKSUM")
    row = dict(kind=kind, symbol=symbol, period=period, key=key)
    try:
        if checksum_path.exists():
            checksum = checksum_path.read_bytes()
        elif offline:
            return {**row, "status": "MISSING_LOCAL"}
        else:
            checksum = download_bytes(BASE_URL + key + ".CHECKSUM", limit=1024)
        expected = checksum.decode("ascii").split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("invalid checksum document")
        if path.exists():
            content = path.read_bytes()
        elif offline:
            return {**row, "status": "MISSING_LOCAL"}
        else:
            content = download_bytes(BASE_URL + key, limit=128 * 1024 * 1024)
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise ValueError(f"checksum mismatch: {key}")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.part")
            temporary.write_bytes(content)
            os.replace(temporary, path)
        if not checksum_path.exists():
            checksum_path.write_bytes(checksum)
        return {**row, "status": "OK", "sha256": actual, "bytes": len(content)}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {**row, "status": "NOT_FOUND"}
        raise


def discover_end(cache: Path, requested: str, *, offline: bool) -> str:
    # File availability only; no TEST/HOLDOUT prices or features are read.
    for month in reversed(month_keys("2024-01", requested)):
        rows = [fetch_archive(cache, kind, "BTCUSDT", month, offline=offline)
                for kind in ("futures", "spot")]
        if all(row["status"] == "OK" for row in rows):
            return month
    raise RuntimeError("NOT_RUN: no available BTC futures/spot archive")


def download_all(cache: Path, end: str, workers: int, *, offline: bool = False) -> list[dict]:
    months = month_keys("2024-01", end)
    last_day = pd.Period(end, freq="M").end_time.date()
    days = [day.date().isoformat() for day in pd.date_range("2024-01-01", last_day)]
    jobs = [(kind, symbol, period) for symbol in SYMBOLS
            for kind, periods in (("futures", months), ("spot", months),
                                  ("funding", months), ("metrics", days)) for period in periods]
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_archive, cache, *job, offline=offline): job for job in jobs}
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows) % 100 == 0:
                LOG.info("[FLOW_DOWNLOAD] completed=%s total=%s missing=%s", len(rows), len(jobs),
                         sum(row["status"] != "OK" for row in rows))
    return sorted(rows, key=lambda row: row["key"])


def read_archive(path: Path, kind: str, expected_sha: str) -> pd.DataFrame:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha:
        raise ValueError("cached archive changed since manifest")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) != 1 or not members[0].filename.endswith(".csv") or members[0].file_size > 512 * 1024 * 1024:
            raise ValueError("invalid archive members")
        with archive.open(members[0]) as stream:
            if kind in ("futures", "spot"):
                first = stream.readline().decode("utf-8-sig")
                has_header = not first.split(",")[0].isdigit()
        with archive.open(members[0]) as stream:
            frame = pd.read_csv(stream, header=0 if kind not in ("futures", "spot") or has_header else None)
    return normalize_frame(frame, kind)


def numeric_ms(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="raise").astype("int64")
    # Binance spot archives changed from milliseconds to microseconds in 2025.
    return numbers.where(numbers < 100_000_000_000_000, numbers // 1000)


def normalize_frame(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
    if kind in ("futures", "spot"):
        if frame.shape[1] != 12:
            raise ValueError("unexpected kline schema")
        frame = frame.iloc[:, [0, 1, 2, 3, 4, 5, 9]].copy()
        frame.columns = ["time", "open", "high", "low", "close", "volume", "taker"]
        frame["time"] = numeric_ms(frame["time"])
        for key in frame.columns[1:]:
            frame[key] = pd.to_numeric(frame[key], errors="raise")
        if (not np.isfinite(frame.to_numpy()).all() or (frame[["open", "high", "low", "close"]] <= 0).any().any()
                or (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any()
                or (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any()
                or (frame["volume"] < 0).any() or (frame["taker"] < 0).any()
                or (frame["taker"] > frame["volume"] + 1e-8).any()):
            raise ValueError("invalid OHLCV")
    elif kind == "metrics":
        if not {"create_time", *METRICS}.issubset(frame.columns):
            raise ValueError("unexpected metrics schema")
        frame = frame.assign(time=pd.to_datetime(frame["create_time"], utc=True, errors="raise").dt.as_unit("ms").astype("int64"))
        frame = frame[["time", *METRICS]].copy()
        for key in METRICS:
            frame[key] = pd.to_numeric(frame[key], errors="coerce").replace([np.inf, -np.inf], np.nan)
            frame.loc[frame[key] < 0, key] = np.nan
        frame.loc[frame["sum_open_interest"] <= 0, "sum_open_interest"] = np.nan
    elif kind == "funding":
        required = {"calc_time", "funding_interval_hours", "last_funding_rate"}
        if not required.issubset(frame.columns):
            raise ValueError("unexpected funding schema")
        frame = frame.rename(columns={"calc_time": "time", "last_funding_rate": "funding"})
        frame = frame[["time", "funding_interval_hours", "funding"]].copy()
        frame["time"] = numeric_ms(frame["time"])
        for key in ("funding_interval_hours", "funding"):
            frame[key] = pd.to_numeric(frame[key], errors="raise")
        if not np.isfinite(frame.to_numpy()).all() or not frame["funding_interval_hours"].between(1, 24).all():
            raise ValueError("invalid funding")
    else:
        raise ValueError("unknown kind")
    # Funding settlements can carry a millisecond offset (e.g. ...0001).
    # Preserve it; rounding down would publish the rate before its availability.
    if kind != "funding" and (frame["time"] % (MINUTE if kind != "metrics" else 5 * MINUTE)).any():
        raise ValueError("unaligned timestamps")
    if frame["time"].duplicated().any():
        raise ValueError("duplicate timestamps")
    return frame.sort_values("time").reset_index(drop=True)


def load_series(cache: Path, manifest: list[dict], kind: str, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    chunks = []
    for item in manifest:
        if item["kind"] != kind or item["symbol"] != symbol or item["status"] != "OK":
            continue
        begin = stamp(item["period"] + ("-01" if len(item["period"]) == 7 else ""))
        finish = begin + DAY if kind == "metrics" else int((pd.Timestamp(begin, unit="ms", tz="UTC") + pd.offsets.MonthBegin(1)).timestamp() * 1000)
        if finish <= start_ms or begin >= end_ms:
            continue
        chunk = read_archive(cache / item["key"], kind, item["sha256"])
        chunks.append(chunk.loc[(chunk.time >= start_ms) & (chunk.time < end_ms)])
    if not chunks:
        columns = ["time", "open", "high", "low", "close", "volume", "taker"] if kind in ("futures", "spot") else (
            ["time", *METRICS] if kind == "metrics" else ["time", "funding_interval_hours", "funding"])
        return pd.DataFrame(columns=columns)
    result = pd.concat(chunks, ignore_index=True).sort_values("time")
    if result.time.duplicated().any():
        raise ValueError("overlapping archive timestamps")
    return result.reset_index(drop=True)


def indexed(frame: pd.DataFrame, *, complete_grid: bool = False) -> pd.DataFrame:
    result = frame.drop(columns="time").copy()
    result.index = pd.to_datetime(frame["time"].to_numpy(dtype="int64"), unit="ms", utc=True)
    if complete_grid and len(result):
        result = result.reindex(pd.date_range(result.index[0], result.index[-1], freq="min"))
    return result.astype(float)


def index_ms(index: pd.DatetimeIndex) -> np.ndarray:
    return index.as_unit("ms").asi8


def trailing_z(series: pd.Series, *, interval_minutes: int | None) -> pd.Series:
    minimum = max(2, int(7 * 1440 / interval_minutes * .8)) if interval_minutes else 8
    history = series.rolling("7D", closed="left", min_periods=minimum)
    deviation = history.std(ddof=1).where(lambda x: x > 1e-12)
    result = (series - history.mean()) / deviation
    if len(series):
        result.loc[result.index < series.index[0] + pd.Timedelta(days=7)] = np.nan
    return result.replace([np.inf, -np.inf], np.nan)


def available_asof(series: pd.Series, target: pd.DatetimeIndex, *, max_age_ms: int) -> pd.Series:
    """Backward join by availability time; NaN in the newest record stays NaN."""
    result = np.full(len(target), np.nan)
    if len(series):
        source_ms, target_ms = index_ms(series.index), index_ms(target)
        if np.any(np.diff(source_ms) <= 0):
            raise ValueError("availability timestamps must increase")
        positions = np.searchsorted(source_ms, target_ms, side="right") - 1
        safe = np.maximum(positions, 0)
        ages = target_ms - source_ms[safe]
        valid = (positions >= 0) & (ages >= 0) & (ages < max_age_ms)
        result[valid] = series.to_numpy(dtype=float)[safe[valid]]
    return pd.Series(result, index=target)


def build_features(futures: pd.DataFrame, spot: pd.DataFrame, metrics: pd.DataFrame,
                   funding: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    """Only past, completed observations. Targets are deliberately separate."""
    f = indexed(futures, complete_grid=True)
    f.index += pd.Timedelta(minutes=1)
    s = indexed(spot, complete_grid=True)
    s.index += pd.Timedelta(minutes=1)
    b = indexed(btc, complete_grid=True)
    b.index += pd.Timedelta(minutes=1)
    result = pd.DataFrame(np.nan, index=f.index, columns=[*FEATURES, "efficiency", "market_return"])
    if f.empty:
        return result
    for lookback in (1, 5):
        move = b["close"].pct_change(lookback, fill_method=None)
        result[f"H6_{lookback}"] = trailing_z(move, interval_minutes=1).reindex(f.index)
    result["market_return"] = b["close"].pct_change(1440, fill_method=None).reindex(f.index)
    travel = f["close"].diff().abs().rolling(60, min_periods=60).sum()
    result["efficiency"] = (f["close"] - f["close"].shift(60)).abs() / travel.where(travel > 0)
    imbalance = ((2 * f["taker"] - f["volume"]) / f["volume"].where(f["volume"] > 0)
                 + ((2 * s["taker"] - s["volume"]) / s["volume"].where(s["volume"] > 0)).reindex(f.index)) / 2
    for lookback in (5, 15):
        total = imbalance.rolling(lookback, min_periods=lookback).sum()
        result[f"H4_{lookback}"] = trailing_z(total, interval_minutes=1)
    m = indexed(metrics)
    m.index += pd.Timedelta(minutes=5)
    if len(m):
        for lookback in (5, 60):
            prior = m["sum_open_interest"].reindex(m.index - pd.Timedelta(minutes=lookback)).to_numpy()
            delta = m["sum_open_interest"] / prior - 1
            price_now = f["close"].reindex(m.index).to_numpy()
            price_old = f["close"].reindex(m.index - pd.Timedelta(minutes=lookback)).to_numpy()
            score = np.sign(delta) * np.sign(price_now / price_old - 1) * trailing_z(delta, interval_minutes=5).abs()
            result[f"H1_{lookback}"] = available_asof(score, f.index, max_age_ms=5 * MINUTE)
            difference = m["sum_toptrader_long_short_ratio"] - m["count_long_short_ratio"]
            score = trailing_z(difference.rolling(f"{lookback}min", min_periods=lookback // 5).mean(), interval_minutes=5)
            result[f"H3_{lookback}"] = available_asof(score, f.index, max_age_ms=5 * MINUTE)
        for lookback in (5, 15):
            ratio = m["sum_taker_long_short_vol_ratio"].rolling(f"{lookback}min", min_periods=lookback // 5).mean()
            result[f"H2_{lookback}"] = available_asof(trailing_z(ratio, interval_minutes=5), f.index, max_age_ms=5 * MINUTE)
    if len(funding):
        funds = funding.copy()
        funds["available"] = funds.time + (funds.funding_interval_hours * 60 * MINUTE).astype("int64")
        # If interval lengths change, two settlements can become available at
        # the same instant. Prefer the later original settlement, never a future one.
        funds = funds.sort_values(["available", "time"]).drop_duplicates("available", keep="last")
        available = pd.to_datetime(funds.available.to_numpy(), unit="ms", utc=True)
        rates = pd.Series(funds.funding.to_numpy(), index=available)
        expiry = pd.Series((funds.available + funds.funding_interval_hours * 60 * MINUTE).to_numpy(), index=available)
        known = available_asof(rates, f.index, max_age_ms=DAY)
        z = available_asof(trailing_z(rates, interval_minutes=None), f.index, max_age_ms=DAY)
        expires = available_asof(expiry, f.index, max_age_ms=DAY)
        z = z.where(index_ms(f.index) < expires.to_numpy())
        for lookback in (5, 15):
            move = f["close"].pct_change(lookback, fill_method=None)
            result[f"H5_{lookback}"] = (-z).where(np.sign(known) == np.sign(move), 0).where(z.notna() & move.notna())
    return result.replace([np.inf, -np.inf], np.nan).astype("float32")


def simulate_tpsl(entry: float, side: int, bars: pd.DataFrame, protocol: Protocol = Protocol()) -> float:
    """Reference single-path implementation, also used to test vector labels."""
    if side not in (-1, 1) or not math.isfinite(entry) or entry <= 0 or len(bars) != protocol.horizon_minutes:
        raise ValueError("invalid simulation")
    values = bars[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("missing or invalid path")
    tp = entry * (1 + side * protocol.tp_bps / 10_000)
    sl = entry * (1 - side * protocol.sl_bps / 10_000)
    for opening, high, low, close in values:
        stop = low <= sl if side == 1 else high >= sl
        target = high >= tp if side == 1 else low <= tp
        if stop:
            fill = min(opening, sl) if side == 1 else max(opening, sl)
            return side * (fill / entry - 1) * 10_000
        if target:
            return protocol.tp_bps
    return side * (values[-1, 3] / entry - 1) * 10_000


def make_targets(futures: pd.DataFrame, protocol: Protocol = Protocol()) -> pd.DataFrame:
    bars = indexed(futures, complete_grid=True)
    n, horizon = len(bars), protocol.horizon_minutes
    result = pd.DataFrame(np.nan, index=bars.index + pd.Timedelta(minutes=1),
                          columns=["r15_long", "r15_short", "tpsl_long", "tpsl_short"])
    count = n - horizon - 1
    if count <= 0:
        return result
    entry = bars.open.to_numpy()[2:2 + count]
    terminal = bars.close.to_numpy()[horizon + 1:horizon + 1 + count]
    valid = np.isfinite(entry) & (entry > 0)
    for offset in range(horizon):
        path = bars.iloc[2 + offset:2 + offset + count][["open", "high", "low", "close"]].to_numpy()
        valid &= np.isfinite(path).all(axis=1) & (path > 0).all(axis=1)
    gross = (terminal / entry - 1) * 10_000
    for side, suffix in ((1, "long"), (-1, "short")):
        payoff = side * gross.copy()
        active = valid.copy()
        tp = entry * (1 + side * protocol.tp_bps / 10_000)
        sl = entry * (1 - side * protocol.sl_bps / 10_000)
        for offset in range(horizon):
            path = bars.iloc[2 + offset:2 + offset + count]
            opening, high, low = (path[key].to_numpy() for key in ("open", "high", "low"))
            stop = active & ((low <= sl) if side == 1 else (high >= sl))
            fill = np.minimum(opening, sl) if side == 1 else np.maximum(opening, sl)
            payoff[stop] = side * (fill[stop] / entry[stop] - 1) * 10_000
            active[stop] = False
            target = active & ((high >= tp) if side == 1 else (low <= tp))
            payoff[target] = protocol.tp_bps
            active[target] = False
        result.iloc[:count, result.columns.get_loc(f"r15_{suffix}")] = np.where(valid, side * gross, np.nan)
        result.iloc[:count, result.columns.get_loc(f"tpsl_{suffix}")] = np.where(valid, payoff, np.nan)
    return result.astype("float32")


def embargo_mask(decision_ms: np.ndarray, start_ms: int, end_ms: int,
                 protocol: Protocol = Protocol()) -> np.ndarray:
    entry_ms = decision_ms + MINUTE
    exit_ms = entry_ms + protocol.horizon_minutes * MINUTE
    return (decision_ms >= start_ms) & (exit_ms < end_ms)


def nonoverlapping(times: np.ndarray, *, horizon_ms: int = 15 * MINUTE) -> np.ndarray:
    if horizon_ms <= 0 or np.any(np.diff(times) < 0):
        raise ValueError("invalid sampling chronology")
    chosen, position = [], 0
    while position < len(times):
        chosen.append(position)
        position = int(np.searchsorted(times, times[position] + horizon_ms, side="left"))
    return np.asarray(chosen, dtype="int64")


def panel_for_stage(cache: Path, manifest: list[dict], start_ms: int, end_ms: int,
                    protocol: Protocol) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    warmup = max(stamp(protocol.start), start_ms - 9 * DAY)
    btc = load_series(cache, manifest, "futures", "BTCUSDT", warmup, end_ms)
    panels, coverage = {}, []
    for symbol in SYMBOLS:
        sources = {kind: load_series(cache, manifest, kind, symbol, warmup, end_ms)
                   for kind in ("futures", "spot", "metrics", "funding")}
        raw = sources["futures"]
        LOG.info("[FLOW_FEATURES] symbol=%s start=%s rows=%s", symbol, start_ms, len(raw))
        feats = build_features(raw, sources["spot"], sources["metrics"], sources["funding"], btc)
        panel = feats.join(make_targets(raw, protocol))
        panel = panel.loc[embargo_mask(index_ms(panel.index), start_ms, end_ms, protocol)]
        panels[symbol] = panel
        coverage.append(dict(symbol=symbol, rows={kind: len(frame) for kind, frame in sources.items()},
                             eligible_rows=len(panel), feature_valid={key: int(panel[key].notna().sum()) for key in FEATURES},
                             complete_paths=int(panel.r15_long.notna().sum())))
    return panels, coverage


@dataclass(frozen=True)
class Rule:
    family: str
    feature: str
    threshold: float
    orientation: int = 1

    @property
    def identity(self) -> str:
        return f"{self.feature}:{self.threshold:g}:{self.orientation:+d}"


def rule_grid() -> list[Rule]:
    return [Rule(feature.split("_")[0], feature, threshold, orientation)
            for feature in FEATURES for threshold in (1., 1.5, 2.) for orientation in (-1, 1)]


def trades_for_rule(panels: dict[str, pd.DataFrame], rule: Rule, regime_threshold: float,
                    *, probabilities: dict[str, pd.Series] | None = None,
                    protocol: Protocol = Protocol()) -> pd.DataFrame:
    trades = []
    for symbol, panel in panels.items():
        if rule.family == "H6" and symbol == "BTCUSDT":
            continue
        if rule.family == "H7":
            probability = probabilities.get(symbol, pd.Series(dtype=float)).reindex(panel.index)
            direction = np.where(probability >= .5, 1, -1)
            eligible = probability.notna() & (np.maximum(probability, 1 - probability) >= rule.threshold)
        else:
            score = panel[rule.feature]
            direction = np.sign(score.fillna(0)).to_numpy() * rule.orientation
            eligible = score.abs() >= rule.threshold
        eligible &= panel[["r15_long", "r15_short", "tpsl_long", "tpsl_short", "efficiency", "market_return"]].notna().all(axis=1)
        rows = np.flatnonzero(eligible.to_numpy())
        rows = rows[nonoverlapping(index_ms(panel.index)[rows], horizon_ms=protocol.horizon_minutes * MINUTE)]
        if not len(rows):
            continue
        selected = panel.iloc[rows]
        side = direction[rows].astype(int)
        trades.append(pd.DataFrame({
            "symbol": symbol, "decision_ms": index_ms(selected.index), "side": side,
            "regime": np.where(selected.efficiency > regime_threshold, "TREND", "CHOP"),
            "market": np.where(selected.market_return > 0, "UP", np.where(selected.market_return < 0, "DOWN", "FLAT")),
            "r15": np.where(side == 1, selected.r15_long, selected.r15_short),
            "tpsl": np.where(side == 1, selected.tpsl_long, selected.tpsl_short),
        }))
    columns = ["symbol", "decision_ms", "side", "regime", "market", "r15", "tpsl"]
    return pd.concat(trades, ignore_index=True).sort_values(["decision_ms", "symbol"]) if trades else pd.DataFrame(columns=columns)


def selection_score(trades: pd.DataFrame) -> float:
    if len(trades) < 200:
        return -math.inf
    return min(float(trades.r15.mean()), float(trades.tpsl.mean())) - 9


def model_inputs(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    valid = panel[list(FEATURES)].notna().all(axis=1).to_numpy()
    return np.clip(panel.loc[valid, list(FEATURES)].to_numpy(dtype=float), -10, 10), valid


def fit_logistic(x: np.ndarray, y: np.ndarray, regularization: float, seed: int) -> dict:
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    if len(y) < 200 or len(np.unique(y)) != 2:
        raise ValueError("insufficient logistic training labels")
    scaler = StandardScaler().fit(x)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model = LogisticRegression(C=regularization, solver="lbfgs", max_iter=300,
                                   random_state=seed).fit(scaler.transform(x), y)
    return dict(C=regularization, mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                coefficients=model.coef_[0].tolist(), intercept=float(model.intercept_[0]), n_fit=len(y))


def predict_logistic(panel: pd.DataFrame, model: dict) -> pd.Series:
    x, valid = model_inputs(panel)
    x = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    logits = x @ np.asarray(model["coefficients"]) + model["intercept"]
    probability = 1 / (1 + np.exp(-np.clip(logits, -50, 50)))
    result = pd.Series(np.nan, index=panel.index)
    result.iloc[np.flatnonzero(valid)] = probability
    return result


def fit_sample(panels: dict[str, pd.DataFrame], start_ms: int, end_ms: int,
               protocol: Protocol) -> tuple[np.ndarray, np.ndarray]:
    features, labels = [], []
    for panel in panels.values():
        times = index_ms(panel.index)
        valid = (embargo_mask(times, start_ms, end_ms, protocol) & ((times // MINUTE) % 15 == 0)
                 & panel[list(FEATURES)].notna().all(axis=1).to_numpy() & panel.r15_long.notna().to_numpy())
        features.append(np.clip(panel.loc[valid, list(FEATURES)].to_numpy(dtype=float), -10, 10))
        labels.append((panel.loc[valid, "r15_long"].to_numpy() > 0).astype(int))
    return np.concatenate(features), np.concatenate(labels)


def choose_logistic(panels: dict[str, pd.DataFrame], protocol: Protocol) -> tuple[dict | None, dict, list[dict]]:
    folds = (("2024-07-01", "2025-01-01"), ("2025-01-01", "2025-04-01"),
             ("2025-04-01", protocol.train_end))
    records, candidates = [], []
    for c in (.1, 1., 10.):
        oof = {symbol: pd.Series(np.nan, index=panel.index) for symbol, panel in panels.items()}
        losses, failed = [], None
        for boundary, finish in folds:
            cut, end = stamp(boundary), stamp(finish)
            x, y = fit_sample(panels, stamp(protocol.start), cut, protocol)
            try:
                model = fit_logistic(x, y, c, protocol.seed)
                vx, vy = fit_sample(panels, cut + DAY, end, protocol)
                if len(vy) < 200 or len(np.unique(vy)) != 2:
                    raise ValueError("insufficient CV validation labels")
                logits = ((vx - np.asarray(model["mean"])) / np.asarray(model["scale"])) @ np.asarray(model["coefficients"]) + model["intercept"]
                loss = float(np.mean(np.logaddexp(0, logits) - vy * logits))
                losses.append(loss)
                for symbol, panel in panels.items():
                    valid = embargo_mask(index_ms(panel.index), cut + DAY, end, protocol)
                    predictions = predict_logistic(panel.loc[valid], model)
                    oof[symbol].loc[predictions.index] = predictions
                records.append(dict(C=c, fold_end=finish, n_train=len(y), n_validation=len(vy), log_loss=loss))
            except (ValueError, Warning) as exc:
                failed = str(exc)
                records.append(dict(C=c, fold_end=finish, error=failed))
                break
        if failed is None:
            candidates.append((float(np.mean(losses)), c, oof))
    if not candidates:
        return None, {}, records
    _, c, oof = min(candidates, key=lambda row: (row[0], row[1]))
    x, y = fit_sample(panels, stamp(protocol.start), stamp(protocol.train_end), protocol)
    return fit_logistic(x, y, c, protocol.seed), oof, records


def point_stats(trades: pd.DataFrame) -> dict:
    result = {"n": len(trades)}
    for name in ("r15", "tpsl"):
        values = trades[name].to_numpy(dtype=float)
        result[name] = {
            "gross_bps": float(values.mean()) if len(values) else None,
            "net9_bps": float(values.mean() - 9) if len(values) else None,
            "net18_bps": float(values.mean() - 18) if len(values) else None,
            "wr_gross": float(np.mean(values > 0)) if len(values) else None,
            "wr_net9": float(np.mean(values > 9)) if len(values) else None,
            "wr_net18": float(np.mean(values > 18)) if len(values) else None,
        }
    return result


def block_statistics(trades: pd.DataFrame, start_ms: int, end_ms: int, protocol: Protocol) -> dict:
    result = point_stats(trades)
    number_days = math.ceil(end_ms / DAY) - start_ms // DAY
    counts = np.zeros(number_days, dtype=float)
    sums = np.zeros((number_days, 2), dtype=float)
    if len(trades):
        day = (trades.decision_ms.to_numpy(dtype="int64") // DAY - start_ms // DAY).astype(int)
        if np.any((day < 0) | (day >= number_days)):
            raise ValueError("trade outside statistics window")
        np.add.at(counts, day, 1)
        np.add.at(sums, day, trades[["r15", "tpsl"]].to_numpy(dtype=float) - 9)
    result["calendar_days"] = number_days
    result["active_days"] = int(np.count_nonzero(counts))
    bootstrap = []
    if np.count_nonzero(counts) >= 2:
        rng = np.random.default_rng(protocol.seed)
        for begin in range(0, protocol.bootstrap, 100):
            draw = rng.integers(0, number_days, size=(min(100, protocol.bootstrap - begin), number_days))
            denominator = counts[draw].sum(axis=1)
            numerator = sums[draw].sum(axis=1)
            bootstrap.append(numerator[denominator > 0] / denominator[denominator > 0, None])
    boots = np.concatenate(bootstrap) if bootstrap else np.empty((0, 2))
    result["bootstrap_valid"] = len(boots)
    for index, name in enumerate(("r15", "tpsl")):
        net = result[name]["net9_bps"]
        result[name]["ci95_net9"] = np.quantile(boots[:, index], [.025, .975]).tolist() if len(boots) else None
        result[name]["ci95_net18"] = [x - 9 for x in result[name]["ci95_net9"]] if len(boots) else None
        result[name]["p_one_sided"] = float((1 + np.count_nonzero(boots[:, index] - net >= net)) / (len(boots) + 1)) if len(boots) else 1.
        profit = trades.groupby("symbol")[name].agg(["sum", "count"]) if len(trades) else pd.DataFrame(columns=["sum", "count"])
        positive = (profit["sum"] - 9 * profit["count"]).clip(lower=0)
        result[name]["max_symbol_profit_share"] = float(positive.max() / positive.sum()) if positive.sum() > 0 else None
    result["p_joint"] = max(result[name]["p_one_sided"] for name in ("r15", "tpsl"))
    for name, values in (("side", (-1, 1)), ("regime", ("CHOP", "TREND")), ("market", ("UP", "DOWN", "FLAT"))):
        result[name] = {str(value): point_stats(trades.loc[trades[name] == value]) for value in values}
    midpoint = (start_ms + end_ms) // 2
    result["halves"] = [point_stats(trades.loc[trades.decision_ms < midpoint]),
                        point_stats(trades.loc[trades.decision_ms >= midpoint])]
    result["symbols"] = {symbol: point_stats(trades.loc[trades.symbol == symbol]) for symbol in SYMBOLS}
    return result


def holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], key))
    adjusted, prior = {}, 0.
    for rank, key in enumerate(ordered):
        prior = max(prior, min(1., p_values[key] * (len(ordered) - rank)))
        adjusted[key] = prior
    return adjusted


def stage_failures(stats: dict, *, test: bool) -> list[str]:
    reasons = []
    if stats["n"] < 200:
        reasons.append("n_below_200")
    for name in ("r15", "tpsl"):
        row = stats[name]
        if row["net9_bps"] is None or row["net9_bps"] <= 3:
            reasons.append(name + "_net9_not_above_3")
        if not row["ci95_net9"] or row["ci95_net9"][0] <= 0:
            reasons.append(name + "_ci_not_positive")
        if row["max_symbol_profit_share"] is None or row["max_symbol_profit_share"] > .5:
            reasons.append(name + "_symbol_concentration")
    if stats.get("p_holm", 1.) > .05:
        reasons.append("holm_not_significant")
    groups = [("side_" + key, stats["side"][key]) for key in ("-1", "1")]
    groups += [("market_" + key, stats["market"][key]) for key in ("UP", "DOWN")]
    groups += [("regime_" + key, stats["regime"][key]) for key in ("CHOP", "TREND")]
    if test:
        groups += [("half_" + str(index), value) for index, value in enumerate(stats["halves"])]
    for name, group in groups:
        if group["n"] < 20 or any(group[target]["net9_bps"] is None or group[target]["net9_bps"] <= 0 for target in ("r15", "tpsl")):
            reasons.append(name + "_not_positive_or_insufficient")
    return reasons


def sealed_stage(path: Path, signature: str, compute, *, requires: tuple[Path, ...] = ()) -> dict:
    """A stage is evaluated once. An interrupted first evaluation needs review."""
    for dependency in requires:
        if not dependency.exists() or json.loads(dependency.read_text(encoding="utf-8")).get("signature") != signature:
            raise ValueError("previous stage is not frozen under this study signature")
    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("signature") != signature:
            raise ValueError("frozen stage signature mismatch")
        return result
    write_json(path.with_suffix(".started.json"), {"signature": signature, "stage": path.stem,
               "started_utc": datetime.now(timezone.utc).isoformat()}, exclusive=True)
    result = {"signature": signature, **compute()}
    write_json(path, result, exclusive=True)
    return result


def train_stage(cache: Path, manifest: list[dict], protocol: Protocol) -> dict:
    start, end = stamp(protocol.start), stamp(protocol.train_end)
    panels, coverage = panel_for_stage(cache, manifest, start, end, protocol)
    efficiencies = np.concatenate([panel.efficiency.dropna().to_numpy() for panel in panels.values()])
    if not len(efficiencies):
        raise ValueError("no TRAIN regime observations")
    regime = float(np.median(efficiencies))
    selected, candidate_records, statistics = {}, [], {}
    for family in FAMILIES[:-1]:
        ranked = []
        for rule in (rule for rule in rule_grid() if rule.family == family):
            trades = trades_for_rule(panels, rule, regime, protocol=protocol)
            score = selection_score(trades)
            candidate_records.append(dict(rule=asdict(rule), **point_stats(trades), score=score if math.isfinite(score) else None))
            if math.isfinite(score):
                ranked.append((score, rule.identity, rule))
        if ranked:
            rule = sorted(ranked, key=lambda row: (-row[0], row[1]))[0][2]
            selected[family] = asdict(rule)
            statistics[family] = block_statistics(trades_for_rule(panels, rule, regime, protocol=protocol), start, end, protocol)
        else:
            selected[family], statistics[family] = None, None
        LOG.info("[FLOW_TRAIN] family=%s selected=%s", family, selected[family])
    model, oof, cv = choose_logistic(panels, protocol)
    selected["H7"], statistics["H7"] = None, None
    if model:
        ranked = []
        for threshold in (.55, .60, .65):
            rule = Rule("H7", "logistic", threshold)
            trades = trades_for_rule(panels, rule, regime, probabilities=oof, protocol=protocol)
            score = selection_score(trades)
            candidate_records.append(dict(rule=asdict(rule), **point_stats(trades), score=score if math.isfinite(score) else None))
            if math.isfinite(score):
                ranked.append((score, rule.identity, rule))
        if ranked:
            rule = sorted(ranked, key=lambda row: (-row[0], row[1]))[0][2]
            selected["H7"] = asdict(rule)
            statistics["H7"] = block_statistics(trades_for_rule(panels, rule, regime, probabilities=oof, protocol=protocol), start, end, protocol)
    return dict(selected=selected, model=model, regime_threshold=regime, coverage=coverage,
                candidates=candidate_records, cv=cv, statistics=statistics,
                trade_configurations_evaluated=len(candidate_records), regularization_candidates=3,
                cv_fits_succeeded=sum("error" not in row for row in cv), train_h7_statistics="OOF_only")


def evaluate_stage(cache: Path, manifest: list[dict], start_ms: int, end_ms: int,
                   trained: dict, protocol: Protocol) -> dict:
    if end_ms <= start_ms:
        return dict(statistics={family: None for family in FAMILIES}, coverage=[], status="NOT_VERIFIED: no period")
    panels, coverage = panel_for_stage(cache, manifest, start_ms, end_ms, protocol)
    probabilities = {symbol: predict_logistic(panel, trained["model"]) for symbol, panel in panels.items()} if trained["model"] else {}
    statistics = {}
    for family in FAMILIES:
        saved = trained["selected"].get(family)
        if saved is None:
            statistics[family] = None
            continue
        rule = Rule(**saved)
        trades = trades_for_rule(panels, rule, trained["regime_threshold"], probabilities=probabilities, protocol=protocol)
        statistics[family] = block_statistics(trades, start_ms, end_ms, protocol)
        LOG.info("[FLOW_EVALUATE] family=%s n=%s", family, len(trades))
    adjusted = holm({family: row["p_joint"] if row else 1. for family, row in statistics.items()})
    for family, row in statistics.items():
        if row:
            row["p_holm"] = adjusted[family]
    return dict(statistics=statistics, coverage=coverage, start_ms=start_ms, end_ms=end_ms)


def markdown_report(result: dict) -> str:
    lines = ["# Futures flow — offline cost-wall screen", "", "Bez změn bota; fixní náklady jsou scénář, nikoli důkaz executable fills.", "",
             "| Hypotéza | Blok | n | R15 gross / net9 / net18 bps | R15 CI95 net9 | TPSL gross / net9 / net18 bps | TPSL CI95 net9 | WR TPSL net9 | Max symbol share R15 / TPSL |",
             "|---|---|---:|---|---|---|---|---:|---|"]
    def format_value(value):
        return "N/A" if value is None else f"{value:.4f}"
    def triple(row):
        return " / ".join(format_value(row[key]) for key in ("gross_bps", "net9_bps", "net18_bps"))
    def interval(row):
        return str([round(x, 4) for x in row["ci95_net9"]]) if row["ci95_net9"] else "N/A"
    for family in FAMILIES:
        for stage in ("TRAIN", "TEST", "HOLDOUT"):
            stats = result[stage]["statistics"].get(family)
            if not stats:
                lines.append(f"| {family} | {stage} | 0 | NOT_VERIFIED | N/A | NOT_VERIFIED | N/A | N/A | N/A |")
                continue
            r, t = stats["r15"], stats["tpsl"]
            lines.append(f"| {family} | {stage} | {stats['n']} | {triple(r)} | {interval(r)} | {triple(t)} | {interval(t)} | {format_value(t['wr_net9'])} | {format_value(r['max_symbol_profit_share'])} / {format_value(t['max_symbol_profit_share'])} |")
    lines += ["", "## Verdikty", ""]
    for family, verdict in result["verdicts"].items():
        lines.append(f"- {family}: **{verdict['verdict']}**; " + "; ".join(verdict["reasons"]))
    lines += ["", f"Konfigurace pravidel: {result['TRAIN']['trade_configurations_evaluated']}; C kandidáti: 3; úspěšné CV fity: {result['TRAIN']['cv_fits_succeeded']}.",
              "", "TRAIN H7 statistiky jsou OOF. Podrobné režimy, poloviny, směry, symboly, CV, datové pokrytí a Holm p jsou v report.json.",
              "", "Data schema: https://github.com/binance/binance-public-data (spot od 2025 používá mikrosekundy).", ""]
    return "\n".join(lines)


def run_screen(args, manifest: list[dict], end: str) -> int:
    protocol = Protocol()
    signature_payload = dict(protocol=asdict(protocol), end_month=end,
                             source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                             manifest_sha256=hashlib.sha256(json_bytes(manifest)).hexdigest())
    signature = hashlib.sha256(json_bytes(signature_payload)).hexdigest()
    study = args.out / "study.json"
    if study.exists():
        if json.loads(study.read_text(encoding="utf-8")) != signature_payload:
            raise ValueError("study code/data/protocol changed; do not re-evaluate TEST/HOLDOUT")
    else:
        write_json(study, signature_payload, exclusive=True)
    train_path, test_path, holdout_path = (args.out / (name + ".json") for name in ("train", "test", "holdout"))
    trained = sealed_stage(train_path, signature, lambda: train_stage(args.cache, manifest, protocol))
    tested = sealed_stage(test_path, signature, lambda: evaluate_stage(
        args.cache, manifest, stamp(protocol.test_start), min(stamp(protocol.test_end),
        int((pd.Period(end, freq="M") + 1).start_time.tz_localize("UTC").timestamp() * 1000)), trained, protocol), requires=(train_path,))
    end_ms = int((pd.Period(end, freq="M") + 1).start_time.tz_localize("UTC").timestamp() * 1000)
    held = sealed_stage(holdout_path, signature, lambda: evaluate_stage(
        args.cache, manifest, stamp(protocol.holdout_start), end_ms, trained, protocol), requires=(train_path, test_path))
    verdicts = {}
    for family in FAMILIES:
        a, b = tested["statistics"].get(family), held["statistics"].get(family)
        if not a or not b or a["n"] == 0 or b["n"] == 0:
            verdicts[family] = dict(verdict="NOT_VERIFIED", reasons=["missing_selection_or_evaluation_data"])
            continue
        reasons = ["TEST:" + reason for reason in stage_failures(a, test=True)]
        reasons += ["HOLDOUT:" + reason for reason in stage_failures(b, test=False)]
        verdicts[family] = dict(verdict="NO_EDGE" if reasons else "LEAD", reasons=reasons)
    result = dict(study=signature_payload, TRAIN=trained, TEST=tested, HOLDOUT=held, verdicts=verdicts)
    write_json(args.out / "report.json", result)
    (args.out / "report.md").write_text(markdown_report(result), encoding="utf-8")
    LOG.info("[FLOW_COMPLETE] verdicts=%s", {key: value["verdict"] for key, value in verdicts.items()})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/research/binance_futures"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--end-month", default="2026-10")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=6)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--manifest", type=Path, help="Reuse a checksum manifest; no network calls")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", args.end_month) or not "2024-01" <= args.end_month <= "2026-10":
        parser.error("end-month must be a complete month in 2024-01..2026-10")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.manifest:
        saved = json.loads(args.manifest.read_text(encoding="utf-8"))
        end, manifest = saved["end_month"], saved["files"]
        if not "2024-01" <= end <= args.end_month:
            parser.error("manifest month outside requested range")
        if any(item["key"] != archive_key(item["kind"], item["symbol"], item["period"]) for item in manifest):
            parser.error("invalid archive manifest key")
    else:
        end = discover_end(args.cache, args.end_month, offline=args.offline)
        LOG.info("[FLOW_DOWNLOAD] last_available_month=%s", end)
        manifest = download_all(args.cache, end, args.workers, offline=args.offline)
        write_json(args.out / "downloads.json", dict(end_month=end, files=manifest))
    if args.download_only:
        return 0
    return run_screen(args, manifest, end)


if __name__ == "__main__":
    raise SystemExit(main())
