#!/usr/bin/env python3
"""Offline, preregistered EVENT screen (E1 shock reaction, E2 funding settlement); never imports bot code.

Protocol: _workspace/2026-11-26_event_screen_protocol.md (fixed before any TRAIN/TEST/HOLDOUT statistic).
Reuses the checksum-verified public-archive loaders of futures_flow_screen.py. TRAIN selection is frozen before
TEST is computed, TEST before HOLDOUT. A historical cost-wall screen, not an executable-fill engine.

Timing (as screen 64): a 1m bar stamped t is known at t+1m; entry at the open of the bar after that (t+2m);
R_H = signed ln(close of the H-th held bar / entry open) in bps. Any missing bar in the held window, or a window
crossing the block end, drops the sample. Funding settled at calc_time is used only from calc_time +
funding_interval_hours (conservative, as screen 64).

E1 (12 configs): r5 = ln(close_t / close_{t-5}); v5 = volume of bars t-4..t; z by trailing 7 days (closed left,
  >= 80 % coverage). Signal iff |z_r5| >= k and z_v5 >= 2. k in {3,4,5}; orientation fade (-sign r5) or
  follow (+sign r5); H in {60, 240}.
E2 (8 configs): each funding settlement T of the symbol; f = newest funding available at the decision; z(f) over
  the previous 30 available funding values. Signal iff |z(f)| >= k, k in {1, 2}; orientation fade (-sign f) or
  follow (+sign f); window pre (decision bar T-62m, entry T-60m, H 60) or post (decision bar T-1m, entry T+1m,
  H 120).
Per config at most one open sample per symbol (next signal only after the previous exit).
Selection per family on TRAIN: max mean net9 (= mean R_H - 9 bps) among configs with >= 200 TRAIN samples;
ties by config id. Stats: day-block bootstrap over all calendar days of the block (2000, seed 20261126),
95 % percentile CI of mean net9, one-sided p from the centred bootstrap, Holm over the 2 families per stage.
LEAD (TEST and HOLDOUT): net9 > +3 bps, CI lower > 0, Holm p <= 0.05, n >= 200 (TEST) / >= 100 (HOLDOUT),
  net9 > 0 in BTC-24h UP and DOWN (n >= 20 each) and, in TEST, in both halves; max symbol share of positive
  net9 sum <= 50 %. Else NO_EDGE; missing selection/data -> NOT_EVALUABLE. LEAD is not a deployment.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import futures_flow_screen as ff  # noqa: E402  (public-archive loaders only)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SYMBOLS = ff.SYMBOLS
MINUTE, DAY = ff.MINUTE, ff.DAY
SEED = 20261126
BOOT = 2000
COST = 9.0
START, TRAIN_END = "2024-01-01", "2025-07-01"
TEST_START, TEST_END = "2025-07-02", "2026-04-01"
HOLDOUT_START = "2026-04-02"
MIN_TRAIN_N = 200
LEAD_N = {"TEST": 200, "HOLDOUT": 100}
FUNDING_LOOKBACK = 30


@dataclass(frozen=True)
class Config:
    family: str
    k: float
    orientation: str      # fade | follow
    horizon: int          # minutes held
    window: str = ""      # E2: pre | post

    @property
    def id(self) -> str:
        tail = f"_{self.window}" if self.window else ""
        return f"{self.family}_k{self.k:g}_{self.orientation}_H{self.horizon}{tail}"


def grid() -> list[Config]:
    e1 = [Config("E1", k, o, h) for k in (3, 4, 5) for o in ("fade", "follow") for h in (60, 240)]
    e2 = [Config("E2", k, o, 60 if w == "pre" else 120, w) for k in (1, 2) for o in ("fade", "follow")
          for w in ("pre", "post")]
    return e1 + e2


# ---------------------------------------------------------------- features and samples

def minute_frame(futures: pd.DataFrame) -> pd.DataFrame:
    """Complete 1m grid (missing bars NaN) indexed by bar open time."""
    return ff.indexed(futures, complete_grid=True)


def e1_features(bars: pd.DataFrame) -> pd.DataFrame:
    close, volume = bars["close"], bars["volume"]
    r5 = np.log(close / close.shift(5))
    v5 = volume.rolling(5, min_periods=5).sum()
    return pd.DataFrame({"r5": r5, "z_r5": ff.trailing_z(r5, interval_minutes=1),
                         "z_v5": ff.trailing_z(v5, interval_minutes=1)}, index=bars.index)


def realized_bps(bars: pd.DataFrame, entry_ms: int, horizon: int, side: int, end_ms: int):
    """Signed ln return in bps from the open of the entry bar to the close of the horizon-th bar."""
    if entry_ms + horizon * MINUTE > end_ms:
        return None
    start = pd.Timestamp(entry_ms, unit="ms", tz="UTC")
    window = bars.loc[start:start + pd.Timedelta(minutes=horizon - 1)]
    if len(window) != horizon or window[["open", "close"]].isna().any().any():
        return None
    return side * 1e4 * math.log(window["close"].iloc[-1] / window["open"].iloc[0])


def e1_samples(symbol: str, bars: pd.DataFrame, features: pd.DataFrame, config: Config,
               start_ms: int, end_ms: int) -> list[dict]:
    hit = features[(features.z_r5.abs() >= config.k) & (features.z_v5 >= 2.0)]
    out, free_from = [], start_ms
    for stamp, row in hit.iterrows():
        decision = int(pd.Timestamp(stamp).value // 1_000_000)
        entry = decision + 2 * MINUTE
        if decision < start_ms or entry < free_from:
            continue
        side = int(-np.sign(row.r5) if config.orientation == "fade" else np.sign(row.r5))
        if side == 0:
            continue
        value = realized_bps(bars, entry, config.horizon, side, end_ms)
        if value is None:
            continue
        out.append({"symbol": symbol, "decision_ms": decision, "side": side, "r": value})
        free_from = entry + config.horizon * MINUTE
    return out


def funding_available(funding: pd.DataFrame) -> pd.DataFrame:
    """(available_ms, funding) sorted; a rate settled at calc_time is used from calc_time + interval."""
    if funding.empty:
        return pd.DataFrame(columns=["available_ms", "funding"])
    avail = funding["time"].astype("int64") + (funding["funding_interval_hours"] * 3_600_000).astype("int64")
    return pd.DataFrame({"available_ms": avail.to_numpy(), "funding": funding["funding"].to_numpy(dtype=float)}
                        ).sort_values("available_ms").reset_index(drop=True)


def e2_samples(symbol: str, bars: pd.DataFrame, funding: pd.DataFrame, config: Config,
               start_ms: int, end_ms: int) -> list[dict]:
    avail = funding_available(funding)
    a_ms, a_val = avail["available_ms"].to_numpy(), avail["funding"].to_numpy()
    out, free_from = [], start_ms
    for settle in funding["time"].astype("int64").to_numpy():
        settle_min = int(settle // MINUTE * MINUTE)
        decision = settle_min - 62 * MINUTE if config.window == "pre" else settle_min - MINUTE
        entry = decision + 2 * MINUTE
        if decision < start_ms or entry < free_from:
            continue
        known_at = decision + MINUTE            # the decision bar closes one minute after its stamp
        pos = int(np.searchsorted(a_ms, known_at, side="right")) - 1
        if pos < FUNDING_LOOKBACK:
            continue
        history = a_val[pos - FUNDING_LOOKBACK:pos]
        sd = float(np.std(history, ddof=1))
        if not sd > 1e-12:
            continue
        f = float(a_val[pos])
        z = (f - float(np.mean(history))) / sd
        if abs(z) < config.k or f == 0:
            continue
        side = int(-np.sign(f) if config.orientation == "fade" else np.sign(f))
        value = realized_bps(bars, entry, config.horizon, side, end_ms)
        if value is None:
            continue
        out.append({"symbol": symbol, "decision_ms": decision, "side": side, "r": value})
        free_from = entry + config.horizon * MINUTE
    return out


def btc_market(btc_bars: pd.DataFrame) -> pd.Series:
    """Sign of the known BTC 24h log return at each bar (UP / DOWN / FLAT)."""
    ret = np.log(btc_bars["close"] / btc_bars["close"].shift(1440))
    return pd.Series(np.where(ret > 0, "UP", np.where(ret < 0, "DOWN", "FLAT")), index=btc_bars.index).where(ret.notna())


def attach_market(samples: pd.DataFrame, market: pd.Series) -> pd.DataFrame:
    if samples.empty:
        return samples.assign(market=pd.Series(dtype=object))
    idx = pd.to_datetime(samples.decision_ms, unit="ms", utc=True)
    return samples.assign(market=market.reindex(idx).to_numpy())


# ---------------------------------------------------------------- statistics

def stats(samples: pd.DataFrame, start_ms: int, end_ms: int) -> dict:
    n = len(samples)
    r = samples["r"].to_numpy(dtype=float) if n else np.empty(0)
    out = {"n": n, "gross_bps": float(r.mean()) if n else None, "net9_bps": float(r.mean() - COST) if n else None,
           "net18_bps": float(r.mean() - 2 * COST) if n else None,
           "wr_net9": float(np.mean(r > COST)) if n else None}
    days = math.ceil(end_ms / DAY) - start_ms // DAY
    counts, sums = np.zeros(days), np.zeros(days)
    if n:
        d = (samples.decision_ms.to_numpy(dtype="int64") // DAY - start_ms // DAY).astype(int)
        if np.any((d < 0) | (d >= days)):
            raise ValueError("sample outside block")
        np.add.at(counts, d, 1)
        np.add.at(sums, d, r - COST)
    boots, null_boots = [], []
    if np.count_nonzero(counts) >= 2:
        net = float(r.mean() - COST)
        # Null (H0: mean net9 = 0) built explicitly: every sample's net9 is centred by the observed mean,
        # so each day's sum becomes sums - net * counts; the same day draws give the null means.
        null_sums = sums - net * counts
        rng = np.random.default_rng(SEED)
        for begin in range(0, BOOT, 100):
            draw = rng.integers(0, days, size=(min(100, BOOT - begin), days))
            den = counts[draw].sum(axis=1)
            ok = den > 0
            boots.append(sums[draw].sum(axis=1)[ok] / den[ok])
            null_boots.append(null_sums[draw].sum(axis=1)[ok] / den[ok])
    boots = np.concatenate(boots) if boots else np.empty(0)
    null_boots = np.concatenate(null_boots) if null_boots else np.empty(0)
    out["bootstrap_valid"] = int(len(boots))
    out["ci95_net9"] = np.quantile(boots, [.025, .975]).tolist() if len(boots) else None
    # one-sided p for H1: mean net9 > 0 = share of null means at least as large as the observed mean
    out["p_one_sided"] = (float((1 + np.count_nonzero(null_boots >= out["net9_bps"])) / (len(null_boots) + 1))
                          if len(null_boots) else 1.0)
    if n:
        g = samples.groupby("symbol")["r"].agg(["sum", "count"])
        positive = (g["sum"] - COST * g["count"]).clip(lower=0)
        out["max_symbol_share"] = float(positive.max() / positive.sum()) if positive.sum() > 0 else None
    else:
        out["max_symbol_share"] = None

    def point(sub):
        return {"n": len(sub), "net9_bps": float(sub["r"].mean() - COST) if len(sub) else None}
    out["market"] = {k: point(samples[samples.market == k]) if n else {"n": 0, "net9_bps": None} for k in ("UP", "DOWN")}
    mid = (start_ms + end_ms) // 2
    out["halves"] = [point(samples[samples.decision_ms < mid]) if n else {"n": 0, "net9_bps": None},
                     point(samples[samples.decision_ms >= mid]) if n else {"n": 0, "net9_bps": None}]
    out["side"] = {str(s): point(samples[samples.side == s]) if n else {"n": 0, "net9_bps": None} for s in (-1, 1)}
    out["symbols"] = {s: point(samples[samples.symbol == s]) if n else {"n": 0, "net9_bps": None} for s in SYMBOLS}
    return out


def lead_failures(st: dict, stage: str) -> list[str]:
    reasons = []
    if st["n"] < LEAD_N[stage]:
        reasons.append(f"n_below_{LEAD_N[stage]}")
    if st["net9_bps"] is None or st["net9_bps"] <= 3:
        reasons.append("net9_not_above_3")
    if not st["ci95_net9"] or st["ci95_net9"][0] <= 0:
        reasons.append("ci_not_positive")
    if st.get("p_holm", 1.0) > 0.05:
        reasons.append("holm_not_significant")
    if st["max_symbol_share"] is None or st["max_symbol_share"] > 0.5:
        reasons.append("symbol_concentration")
    groups = [("market_" + k, st["market"][k]) for k in ("UP", "DOWN")]
    if stage == "TEST":
        groups += [("half_" + str(i), h) for i, h in enumerate(st["halves"])]
    for name, g in groups:
        if g["n"] < 20 or g["net9_bps"] is None or g["net9_bps"] <= 0:
            reasons.append(name + "_not_positive_or_insufficient")
    return reasons


def select(train_stats: dict) -> dict:
    """Per family the config with max TRAIN net9 among n >= 200; ties by id."""
    chosen = {}
    for family in ("E1", "E2"):
        candidates = [(cid, s) for cid, s in train_stats.items()
                      if cid.startswith(family + "_") and s["n"] >= MIN_TRAIN_N]
        if not candidates:
            chosen[family] = None
            continue
        chosen[family] = sorted(candidates, key=lambda item: (-item[1]["net9_bps"], item[0]))[0][0]
    return chosen


# ---------------------------------------------------------------- stages

def block_samples(cache: Path, manifest: list[dict], configs: list[Config], start: str, end: str) -> dict:
    start_ms, end_ms = ff.stamp(start), ff.stamp(end)
    load_from = start_ms - 8 * DAY           # warm-up for 7-day z and BTC 24h, never sampled
    btc = minute_frame(ff.load_series(cache, manifest, "futures", "BTCUSDT", load_from, end_ms))
    market = btc_market(btc) if len(btc) else pd.Series(dtype=object)
    per = {c.id: [] for c in configs}
    for symbol in SYMBOLS:
        raw = ff.load_series(cache, manifest, "futures", symbol, load_from, end_ms)
        if raw.empty:
            continue
        bars = minute_frame(raw)
        feats = e1_features(bars) if any(c.family == "E1" for c in configs) else None
        funding = ff.load_series(cache, manifest, "funding", symbol, start_ms - 40 * DAY, end_ms)
        for c in configs:
            if c.family == "E1":
                per[c.id] += e1_samples(symbol, bars, feats, c, start_ms, end_ms)
            else:
                per[c.id] += e2_samples(symbol, bars, funding, c, start_ms, end_ms)
    cols = ["symbol", "decision_ms", "side", "r"]
    return {cid: attach_market(pd.DataFrame(rows, columns=cols), market) for cid, rows in per.items()}


def signature(manifest: list[dict]) -> str:
    me = Path(__file__).read_bytes()
    body = json.dumps({"script": hashlib.sha256(me).hexdigest(),
                       "data": [[m["key"], m.get("sha256")] for m in manifest]}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def expected_jobs(end: str) -> list[tuple[str, str, str]]:
    return [(kind, s, p) for s in SYMBOLS for kind in ("futures", "funding") for p in ff.month_keys("2024-01", end)]


def check_complete(manifest: list[dict], end: str) -> None:
    """Fail closed before any stage: every preregistered (kind, symbol, month) archive present and verified."""
    expected = {ff.archive_key(*job) for job in expected_jobs(end)}
    ok = {m["key"] for m in manifest if m.get("status") == "OK" and m.get("sha256")}
    missing = sorted(expected - ok)
    if missing:
        raise SystemExit(f"NOT_EVALUABLE: {len(missing)} of {len(expected)} expected archives missing or "
                         f"unverified, e.g. {missing[:3]}")


def run(cache: Path, out: Path, end: str, offline: bool) -> dict:
    manifest = sorted((ff.fetch_archive(cache, *j, offline=offline) for j in expected_jobs(end)), key=lambda m: m["key"])
    missing = [m["key"] for m in manifest if m["status"] != "OK"]
    ff.write_json(out / "manifest.json", {"end": end, "missing": missing, "rows": manifest})
    check_complete(manifest, end)
    sig = signature(manifest)
    holdout_end = (pd.Period(end, freq="M") + 1).to_timestamp().strftime("%Y-%m-%d")
    configs = grid()

    def train():
        samples = block_samples(cache, manifest, configs, START, TRAIN_END)
        st = {cid: stats(s, ff.stamp(START), ff.stamp(TRAIN_END)) for cid, s in samples.items()}
        return {"role": "IN_SAMPLE_SELECTION_DESCRIPTIVE_ONLY (CI/p here are not confirmatory; "
                        "TEST and HOLDOUT are the only confirmatory stages)",
                "stats": st, "chosen": select(st)}
    tr = ff.sealed_stage(out / "train.json", sig, train)
    chosen = {f: c for f, c in tr["chosen"].items() if c}
    chosen_cfg = [c for c in configs if c.id in chosen.values()]

    def evaluate(start, stop, stage):
        def compute():
            samples = block_samples(cache, manifest, chosen_cfg, start, stop)
            st = {f: stats(samples[cid], ff.stamp(start), ff.stamp(stop)) for f, cid in chosen.items()}
            adj = ff.holm({f: s["p_one_sided"] for f, s in st.items()}) if st else {}
            for f in st:
                st[f]["p_holm"] = adj[f]
                st[f]["lead_failures"] = lead_failures(st[f], stage)
            return {"stats": st, "chosen": chosen}
        return compute
    te = ff.sealed_stage(out / "test.json", sig, evaluate(TEST_START, TEST_END, "TEST"), requires=(out / "train.json",))
    ho = ff.sealed_stage(out / "holdout.json", sig, evaluate(HOLDOUT_START, holdout_end, "HOLDOUT"),
                         requires=(out / "train.json", out / "test.json"))
    verdict = {}
    for family in ("E1", "E2"):
        if family not in chosen or family not in te["stats"] or family not in ho["stats"]:
            verdict[family] = "NOT_EVALUABLE"
        elif not te["stats"][family]["lead_failures"] and not ho["stats"][family]["lead_failures"]:
            verdict[family] = "LEAD"
        else:
            verdict[family] = "NO_EDGE"
    result = {"signature": sig, "end": end, "missing_archives": missing, "chosen": tr["chosen"], "verdict": verdict,
              "train_role": "in-sample selection, descriptive only"}
    ff.write_json(out / "verdict.json", result)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--end", default="2026-10", help="last complete month to use")
    p.add_argument("--offline", action="store_true")
    a = p.parse_args(argv)
    print(json.dumps(run(a.cache, a.out, a.end, a.offline), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
