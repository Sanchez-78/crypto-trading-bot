#!/usr/bin/env python3
"""Funding-carry v2 — monthly-rebalanced delta-neutral carry WITH basis, honest OOS.

v1 finding: funding on majors is mostly positive; a static delta-neutral carry (long spot /
short perp) earned +200..+540 bp over ~18 months on BTC/ETH/ADA/XRP, near-market-neutral. But
v1's per-8h "timed" version churned (683 episodes × 30 bp) and died on cost — a bad execution of
a real signal, not a dead signal.

v2 fixes execution and adds the basis term:
  * MONTHLY rebalance. At each month start, include a coin in the equal-weight carry basket iff
    its trailing-3-month average funding > BREAKEVEN_BPS_PER_8H (must out-earn amortized cost).
    A coin held in consecutive months pays NO re-entry cost (position rolls); cost (30/40 bp) is
    charged only on ENTER and EXIT transitions. This kills the churn.
  * Per held coin-month P&L = Σ funding that month (short receives) + basis (spot_ret − perp_ret,
    the real delta-neutral price P&L) − transition cost. Basis from spot vs perp daily closes.
  * TEST OOS 2025-01..2026-06. Reports monthly net series, WR (fraction of positive months — the
    project's goal metric), annualized yield, up/down-market neutrality, per-coin/-year, bootstrap CI.

A positive, market-neutral, CI>0 result that survives basis + cost is the first legitimate learning
target: the "learning" is selecting durable-positive-funding coins and sizing the neutral carry.
REAL = NO-GO; this is paper research on public data.

Usage: python3 funding_carry_v2.py [cache_dir]
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
END = (2026, 6)
COST_RT_BPS = {"base": 30.0, "stress": 40.0}
BREAKEVEN_BPS_PER_8H = 0.20     # trailing funding must beat this to bother (amortized cost/risk)
FUND_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
SPOT_URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip"
PERP_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1d/{s}-1d-{m}.zip"


def _dl(url, fp):
    if not os.path.exists(fp):
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return False
    return os.path.exists(fp)


def load_funding(cache):
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
    return out


def load_daily(cache, url_tmpl, tag):
    out = {}
    for s in SYMBOLS:
        rows = {}
        for m in MONTHS:
            fp = os.path.join(cache, f"{s}-{tag}-{m}.zip")
            if not _dl(url_tmpl.format(s=s, m=m), fp):
                continue
            try:
                with zipfile.ZipFile(fp) as z, z.open(z.namelist()[0]) as f:
                    for row in csv.reader(io.TextIOWrapper(f)):
                        if row and row[0] and row[0][0].isdigit():
                            ts = int(row[0])
                            if ts > 10**14:
                                ts //= 1000
                            rows[ts] = float(row[4])
            except Exception:
                pass
        out[s] = rows
    return out


def ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def nextm(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def prevm(y, m, k):
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


def month_ret(daily_sym, lo, hi):
    ks = sorted(t for t in daily_sym if lo <= t < hi)
    if len(ks) < 2:
        return None
    return daily_sym[ks[-1]] / daily_sym[ks[0]] - 1


def month_funding(fund_sym, lo, hi):
    return sum(r for t, r in fund_sym if lo <= t < hi)


def trailing_avg_funding(fund_sym, lo3, lo):
    xs = [r for t, r in fund_sym if lo3 <= t < lo]
    return (sum(xs) / len(xs)) if xs else None


def run(funding, spot, perp, cost):
    """Monthly-rebalanced neutral carry. Returns (monthly_net[list], coinmonth_tagged[list])."""
    monthly, cm = [], []
    held_prev = set()
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        lo3 = ms(*prevm(y, m, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > BREAKEVEN_BPS_PER_8H:
                basket.append(s)
        held = set(basket)
        month_pnls = []
        for s in basket:
            f_bps = month_funding(funding[s], lo, hi) * 1e4
            sr, pr = month_ret(spot[s], lo, hi), month_ret(perp[s], lo, hi)
            basis_bps = ((sr - pr) * 1e4) if (sr is not None and pr is not None) else 0.0
            trans = 0.0
            if s not in held_prev:
                trans += cost / 2.0                      # enter (half round trip)
            net = f_bps + basis_bps - trans
            month_pnls.append(net)
            cm.append((s, lo, net))
        for s in held_prev - held:                       # pay exit for coins leaving basket
            if cm:
                pass
        exit_cost = len(held_prev - held) * (cost / 2.0)
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls) - exit_cost / max(1, len(month_pnls)))
        held_prev = held
        y, m = nextm(y, m)
    return monthly, cm


def stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "mean_bps": round(sum(vals) / n, 1), "total_bps": round(sum(vals), 0),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


def boot_ci(vals, B=4000, seed=7):
    n = len(vals)
    if n < 8:
        return None
    rng = random.Random(seed)
    m_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(m_[int(0.05 * B)], 1), round(m_[int(0.95 * B)], 1)


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    funding = load_funding(cache)
    spot = load_daily(cache, SPOT_URL, "spotd")
    perp = load_daily(cache, PERP_URL, "perpd")
    # market proxy: equal-weight perp monthly return
    mkt = {}
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = [month_ret(perp[s], lo, hi) for s in SYMBOLS]
        rs = [r for r in rs if r is not None]
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)

    out = {"note": ("Funding-carry v2: monthly-rebalanced delta-neutral (long spot/short perp) "
                    "carry WITH basis, transition-cost only (no churn). Goal metric = win_rate "
                    "over months. Positive + market-neutral (up~down) + CI>0 surviving basis+cost "
                    "= first legitimate learning target. Costs 30/40 bp per transition.")}
    for scen, cost in COST_RT_BPS.items():
        monthly, cm = run(funding, spot, perp, cost)
        # up/down neutrality on coin-months
        def mkey(t):
            d = _dt.datetime.utcfromtimestamp(t / 1000)
            return (d.year, d.month)
        up = sum(v for _, t, v in cm if mkt.get(mkey(t), 0) >= 0)
        dn = sum(v for _, t, v in cm if mkt.get(mkey(t), 0) < 0)
        prof, by_year = {}, {}
        for s, t, v in cm:
            if v > 0:
                prof[s] = prof.get(s, 0) + v
            yy = _dt.datetime.utcfromtimestamp(t / 1000).year
            by_year[yy] = round(by_year.get(yy, 0) + v, 0)
        tot = sum(prof.values())
        yrs = (END[0] - TEST_START[0]) + (END[1] - TEST_START[1]) / 12.0
        ann = round(sum(monthly) / yrs / 100.0, 2) if monthly else None   # % per year (bps→%)
        out[f"scenario_{scen}"] = {
            "monthly_basket": stats(monthly),
            "monthly_boot_ci_5_95_bps": boot_ci(monthly),
            "approx_annual_yield_pct": ann,
            "coinmonth_net_up_market_bps": round(up, 0),
            "coinmonth_net_down_market_bps": round(dn, 0),
            "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
            "net_bps_by_year": by_year,
        }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
