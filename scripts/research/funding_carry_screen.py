#!/usr/bin/env python3
"""Funding-carry screen — a DIFFERENT information set than price (the honest pivot).

Ten price-only strategy families failed (`RESEARCH_LONGHORIZON_FINDINGS.md`): what looked
like edge was 2024 beta. Delta-neutral funding carry (long spot + short perp, equal notional)
is a documented, near-MARKET-NEUTRAL source of return — the short-perp leg receives funding
when funding>0, and the price legs cancel (minus basis drift). That directly attacks the beta
problem: carry should make money in up AND down markets if it is real.

This screen measures the FUNDING term first (the dominant carry component), from real Binance
funding history. If pure funding carry doesn't beat entry/exit + holding costs, the edge isn't
there. If it does, basis drift (spot vs perp) is the next correction to add.

Cost model (delta-neutral pair): entry = buy spot + short perp = 2 taker legs; exit = 2 more.
At VIP0+BNB ~7.5 bp/leg => ~30 bp per full round trip for the PAIR, paid once per hold episode
(NOT per funding period — the position is held and the perp rolls without re-trading).

Strategies (long-only carry; you never pay funding because you exit when it turns against you):
  A. static_all   — enter all coins at TEST start, hold to end (min cost), net = Σfunding − 60bp.
  B. timed        — per coin, hold carry only while trailing funding>0; exit when it flips
                    (pays 30bp per entry, 30bp per exit episode). Adaptive to the funding regime.
Split: TRAIN 2023-24 (context), TEST 2025-01..2026-06 OOS. Up/down market split + per-year +
bootstrap CI. Costs 30 bp base / 40 bp stress per episode round trip.

Usage: python3 funding_carry_screen.py [cache_dir]
"""
from __future__ import annotations
import csv
import datetime as _dt
import io
import json
import os
import random
import sys
import urllib.request
import zipfile

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 7)]
TEST_START = (2025, 1)
COST_RT_BPS = {"base": 30.0, "stress": 40.0}   # per delta-neutral episode round trip (both legs)
FUND_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
PERP_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1h/{s}-1h-{m}.zip"


def _dl(url, fp):
    if not os.path.exists(fp):
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return False
    return os.path.exists(fp)


def load_funding(cache):
    """{symbol: [(calc_time_ms, funding_rate_float)]} sorted."""
    os.makedirs(cache, exist_ok=True)
    out = {}
    for s in SYMBOLS:
        rows = []
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-fund-{m}.zip")
            if not _dl(FUND_URL.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():
                            rows.append((int(row[0]), float(row[2])))
            except Exception:
                pass
        rows.sort()
        out[s] = rows
        print(f"funding {s}: {len(rows)} points", file=sys.stderr)
    return out


def load_perp(cache):
    """{symbol: [(open_time_ms, close)]} 1h — for basis diagnostics."""
    out = {}
    for s in SYMBOLS:
        rows = []
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-perp-{m}.zip")
            if not _dl(PERP_URL.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():
                            ts = int(row[0])
                            if ts > 10**14:
                                ts //= 1000
                            rows.append((ts, float(row[4])))
            except Exception:
                pass
        rows.sort()
        out[s] = rows
        print(f"perp {s}: {len(rows)} bars", file=sys.stderr)
    return out


def ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def yr(t):
    return _dt.datetime.utcfromtimestamp(t / 1000).year


def perp_monthly_ret(perp):
    """Equal-weight monthly perp return -> up/down market proxy. {(y,m): ret}."""
    idx = {s: dict(v) for s, v in perp.items()}
    out = {}
    y, m = TEST_START
    while (y, m) <= (2026, 6):
        lo, hi = ms(y, m), ms(y + (m // 12), m % 12 + 1)
        rs = []
        for s in SYMBOLS:
            ks = sorted(t for t in idx[s] if lo <= t < hi)
            if len(ks) > 1:
                rs.append(idx[s][ks[-1]] / idx[s][ks[0]] - 1)
        out[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = y + (m // 12), m % 12 + 1
    return out


def static_all(funding, cost_bps):
    """Enter each coin at TEST start, hold to end: net = Σfunding(bps) − one round trip."""
    per = []
    for s in SYMBOLS:
        fs = [(t, r) for t, r in funding[s] if t >= ms(*TEST_START)]
        if len(fs) < 10:
            continue
        gross = sum(r for _, r in fs) * 1e4          # funding in bps
        per.append((s, gross - cost_bps))
    return per


def timed(funding, cost_bps, mkt):
    """Per coin, hold carry while trailing-3-point funding avg > 0; pay cost per episode.
    Returns per-EPISODE net bps tagged (symbol, exit_ts) for concentration/up-down analysis."""
    eps = []
    for s in SYMBOLS:
        fs = [(t, r) for t, r in funding[s] if t >= ms(2024, 7)]   # warmup before TEST
        if len(fs) < 20:
            continue
        in_pos, acc, ent_t = False, 0.0, None
        trail = []
        for t, r in fs:
            trail.append(r)
            if len(trail) > 3:
                trail.pop(0)
            avg = sum(trail) / len(trail)
            if not in_pos and avg > 0:
                in_pos, acc, ent_t = True, 0.0, t
            elif in_pos:
                acc += r
                if avg <= 0:
                    if t >= ms(*TEST_START):
                        eps.append((s, t, acc * 1e4 - cost_bps))
                    in_pos = False
        if in_pos and ent_t is not None and fs[-1][0] >= ms(*TEST_START):
            eps.append((s, fs[-1][0], acc * 1e4 - cost_bps))
    return eps


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "exp_bps": round(sum(vals) / n, 1), "total_bps": round(sum(vals), 0),
            "wr": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


def boot_ci(vals, B=2000, seed=7):
    n = len(vals)
    if n < 15:
        return None
    rng = random.Random(seed)
    ms_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(ms_[int(0.05 * B)], 1), round(ms_[int(0.95 * B)], 1)


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    funding = load_funding(cache)
    perp = load_perp(cache)
    mkt = perp_monthly_ret(perp)
    out = {"note": ("Funding-carry (delta-neutral long spot/short perp) — FUNDING TERM ONLY, "
                    "first-order (basis drift not yet added). Near-market-neutral by construction; "
                    "the up/down-market split tests that. Costs 30/40 bp per episode. TEST OOS "
                    "2025-01..2026-06. Positive + market-neutral + CI>0 => first real lead."),
           "avg_funding_bps_per_8h": {s: round(sum(r for _, r in funding[s]) / max(1, len(funding[s])) * 1e4, 3)
                                      for s in SYMBOLS}}
    for scen, cost in COST_RT_BPS.items():
        A = static_all(funding, cost)
        B = timed(funding, cost, mkt)
        b_vals = [v for _, _, v in B]
        up = sum(v for _, t, v in B if mkt.get((yr(t), _dt.datetime.utcfromtimestamp(t/1000).month), 0) >= 0)
        dn = sum(v for _, t, v in B if mkt.get((yr(t), _dt.datetime.utcfromtimestamp(t/1000).month), 0) < 0)
        prof = {}
        for s, _, v in B:
            if v > 0:
                prof[s] = prof.get(s, 0.0) + v
        tot = sum(prof.values())
        out[f"scenario_{scen}"] = {
            "static_all_hold": {"per_coin_net_bps": {s: round(v, 0) for s, v in A},
                                "mean_net_bps": round(sum(v for _, v in A) / len(A), 0) if A else None},
            "timed": {**stats(b_vals), "boot_ci_5_95_bps": boot_ci(b_vals),
                      "net_up_market_bps": round(up, 0), "net_down_market_bps": round(dn, 0),
                      "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None},
        }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
