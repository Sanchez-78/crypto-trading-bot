#!/usr/bin/env python3
"""Skeptic battery for the two walk-forward survivors (donchian, xsec).

A positive walk-forward screen is a LEAD, not an edge. The maker story looked
positive too and the auditor returned verdict C. Before anyone gets excited, the
adaptive walk-forward trade streams for the two survivors must pass:
  1. alpha-vs-beta: split P&L by up/down market months (equal-weight 7-coin monthly
     return). A strategy that only wins in up-markets is levered beta, not alpha.
  2. symbol concentration: no single symbol may supply >50% of gross profit.
  3. time concentration: per-year net; is it one lucky year?
  4. bootstrap CI of mean net per trade (iid bootstrap, B=2000); lower bound > 0?
All at 15 bp base and 20 bp stress. Long-only (spot).

Usage: python3 longhorizon_robustness.py [cache_dir]
"""
from __future__ import annotations
import datetime as _dt
import json
import random
import sys

from longhorizon_screen import SYMBOLS, COST_RT_BPS, load_series, DONCHIAN_H, XSEC_TOP_K

MIN_TRAIN_TRADES = 10
TRAIN_MONTHS = 12
FIRST_TEST = (2024, 1)
LAST_TEST = (2026, 6)
XSEC_REBAL = 168


def month_ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def add_months(y, m, d):
    idx = (y * 12 + (m - 1)) + d
    return idx // 12, idx % 12 + 1


def donchian_tagged(closes, k, sym):
    out, in_pos, entry = [], False, 0.0
    vals = [c for _, c in closes]
    for i in range(k, len(vals)):
        if not in_pos and vals[i] >= max(vals[i - k:i]):
            in_pos, entry = True, vals[i]
        elif in_pos and vals[i] <= min(vals[max(0, i - k // 2):i]):
            out.append((closes[i][0], (vals[i] / entry - 1) * 1e4, sym))
            in_pos = False
    return out


def xsec_tagged(series, top_k):
    idx = {s: {ts: c for ts, c in v} for s, v in series.items()}
    all_ts = sorted(set.intersection(*(set(d.keys()) for d in idx.values())))
    out = []
    for j in range(168, len(all_ts) - XSEC_REBAL, XSEC_REBAL):
        t0, t1 = all_ts[j], all_ts[j + XSEC_REBAL]
        mom = sorted(((idx[s][t0] / idx[s][all_ts[j - 168]] - 1, s) for s in SYMBOLS), reverse=True)
        for mval, s in mom[:top_k]:
            if mval > 0:
                out.append((t0, (idx[s][t1] / idx[s][t0] - 1) * 1e4, s))
    return out


def market_monthly(series):
    """Equal-weight 7-coin return per calendar month -> sign = up/down market."""
    idx = {s: {ts: c for ts, c in v} for s, v in series.items()}
    out = {}
    y, m = FIRST_TEST
    while (y, m) <= LAST_TEST:
        lo, hi = month_ms(y, m), month_ms(*add_months(y, m, 1))
        rets = []
        for s in SYMBOLS:
            ks = [t for t in idx[s] if lo <= t < hi]
            if len(ks) > 1:
                ks.sort()
                rets.append(idx[s][ks[-1]] / idx[s][ks[0]] - 1)
        out[(y, m)] = sum(rets) / len(rets) if rets else 0.0
        y, m = add_months(y, m, 1)
    return out


def walk_forward_tagged(cfg_trades):
    """cfg_trades: {cfg_name: [(ts,ret,sym)]}. Returns realized adaptive test trades."""
    test = []
    y, m = FIRST_TEST
    while (y, m) <= LAST_TEST:
        t_lo, t_hi = month_ms(y, m), month_ms(*add_months(y, m, 1))
        tr_lo = month_ms(*add_months(y, m, -TRAIN_MONTHS))
        best_cfg, best_exp = None, None
        for cfg, trades in cfg_trades.items():
            tw = [r for ts, r, _ in trades if tr_lo <= ts < t_lo]
            if len(tw) >= MIN_TRAIN_TRADES:
                exp = sum(x - COST_RT_BPS["base"] for x in tw) / len(tw)
                if best_exp is None or exp > best_exp:
                    best_cfg, best_exp = cfg, exp
        if best_cfg is not None:
            test.extend((ts, r, s) for ts, r, s in cfg_trades[best_cfg] if t_lo <= ts < t_hi)
        y, m = add_months(y, m, 1)
    return test


def boot_ci(net, B=2000, seed=7, lo=0.05, hi=0.95):
    n = len(net)
    if n < 20:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        means.append(sum(net[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return round(means[int(lo * B)], 2), round(means[int(hi * B)], 2)


def analyze(test, mkt, cost):
    net = [(ts, r - cost, s) for ts, r, s in test]
    vals = [x for _, x, _ in net]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    # symbol concentration (gross profit share)
    prof = {}
    for _, x, s in net:
        if x > 0:
            prof[s] = prof.get(s, 0.0) + x
    tot = sum(prof.values())
    top_sym = max(prof.items(), key=lambda kv: kv[1]) if prof else (None, 0)
    # yearly
    by_year = {}
    for ts, x, _ in net:
        yr = _dt.datetime.utcfromtimestamp(ts / 1000).year
        by_year[yr] = round(by_year.get(yr, 0.0) + x, 1)
    # alpha vs beta: bucket net by up/down market month (equal-weight 7-coin monthly sign)
    def _mkt_sign(ts):
        d = _dt.datetime.utcfromtimestamp(ts / 1000)
        return mkt.get((d.year, d.month), 0.0)
    up = sum(x for ts, x, _ in net if _mkt_sign(ts) >= 0)
    down = sum(x for ts, x, _ in net if _mkt_sign(ts) < 0)
    gw = sum(x for x in vals if x > 0)
    gl = -sum(x for x in vals if x < 0)
    return {
        "n": n, "exp_bps": round(sum(vals) / n, 2), "total_bps": round(sum(vals), 1),
        "wr": round(sum(1 for x in vals if x > 0) / n, 3),
        "pf": round(gw / gl, 3) if gl > 0 else float("inf"),
        "boot_ci_5_95_bps": boot_ci(vals),
        "max_symbol_profit_share": round(top_sym[1] / tot, 3) if tot > 0 else None,
        "top_symbol": top_sym[0],
        "net_bps_by_year": by_year,
        "net_bps_up_market": round(up, 1),
        "net_bps_down_market": round(down, 1),
    }


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/klines_cache"
    series = load_series(cache)
    mkt = market_monthly(series)
    dc = {f"dc{k}": [t for s in SYMBOLS for t in donchian_tagged(series[s], k, s)] for k in DONCHIAN_H}
    xs = {f"top{k}": xsec_tagged(series, k) for k in XSEC_TOP_K}
    out = {"note": ("Skeptic battery on walk-forward survivors. Real edge must: beat costs, "
                    "have CI lower>0, no symbol>50% of profit, make money in DOWN markets too "
                    "(else it's beta), and not depend on one year."),
           "market_up_down_months": {f"{y}-{m:02d}": round(v, 4) for (y, m), v in mkt.items()}}
    for name, cfgs in (("donchian", dc), ("xsec", xs)):
        test = walk_forward_tagged(cfgs)
        out[name] = {"base_15bp": analyze(test, mkt, COST_RT_BPS["base"]),
                     "stress_20bp": analyze(test, mkt, COST_RT_BPS["stress"])}
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
