#!/usr/bin/env python3
"""Long-horizon (1h bars) strategy screen — the cost-viable pivot candidate (H1).

Motivation (RESEARCH_M5_COST_ARITHMETIC.md): second-scale strategies cannot clear the
~15 bp attainable round-trip on Binance spot. At multi-hour holds, typical crypto moves
are 100-500 bp, so 15 bp is friction, not a wall. This screen asks — honestly — whether
simple, LONG-ONLY (spot cannot short), pre-registered strategy families clear realistic
costs out-of-sample on our 7 traded USDT pairs.

Discipline:
  * PRE-REGISTERED families + parameter grids (below). No post-hoc additions.
  * Costs: 15 bp round-trip base (VIP0+BNB taker both ways), 20 bp stress.
  * Split: TRAIN 2023-01..2024-12 (selection), TEST 2025-01..2026-06 (untouched OOS).
    Selection picks ONE config per family on TRAIN net expectancy; TEST is reported
    for the selected config only.
  * Data: data.binance.vision monthly 1h spot klines (public archive), cached locally.
  * Output: JSON to stdout. This is a SCREEN, not a GO decision — anything that looks
    alive here still needs the full M-series-style validation before paper deployment.

Usage: python3 longhorizon_screen.py [cache_dir]
"""
from __future__ import annotations
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 7)]
TRAIN_END_MS = 1735689600000        # 2025-01-01T00:00:00Z — TEST starts here
COST_RT_BPS = {"base": 15.0, "stress": 20.0}
BASE = "https://data.binance.vision/data/spot/monthly/klines/{s}/1h/{s}-1h-{m}.zip"

# ── pre-registered families (long-only) ──────────────────────────────────────
TSMOM_LOOKBACK_H = [24, 72, 168]     # long if past-k-hour return > 0, else cash
TSMOM_HOLD_H = [24, 48]              # re-evaluate every hold period
MA_FILTER_H = [100, 200, 400]        # long while close > SMA(k), else cash
DONCHIAN_H = [48, 168]               # long on new k-hour high; exit on k/2-hour low
XSEC_TOP_K = [2, 3]                  # weekly: long top-k by 168h momentum if positive
XSEC_REBALANCE_H = 168


def fetch(symbol: str, month: str, cache: str):
    os.makedirs(cache, exist_ok=True)
    fp = os.path.join(cache, f"{symbol}-1h-{month}.zip")
    if not os.path.exists(fp):
        url = BASE.format(s=symbol, m=month)
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return None
    try:
        with zipfile.ZipFile(fp) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                rows = []
                for row in csv.reader(io.TextIOWrapper(f)):
                    ts = int(row[0])
                    if ts > 10**14:          # microseconds → ms
                        ts //= 1000
                    rows.append((ts, float(row[4])))   # close
                return rows
    except Exception:
        return None


def load_series(cache: str):
    out = {}
    for s in SYMBOLS:
        series = []
        for m in MONTHS:
            r = fetch(s, m, cache)
            if r:
                series.extend(r)
        series.sort()
        out[s] = series
        print(f"loaded {s}: {len(series)} bars", file=sys.stderr)
    return out


def _trades_to_stats(rets_bps, cost_bps):
    net = [r - cost_bps for r in rets_bps]
    n = len(net)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for r in net if r > 0)
    gw = sum(r for r in net if r > 0)
    gl = -sum(r for r in net if r < 0)
    return {"n": n, "exp_bps": round(sum(net) / n, 2), "wr": round(wins / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else (float("inf") if gw > 0 else 0.0),
            "total_bps": round(sum(net), 1)}


def tsmom_trades(closes, k, hold):
    """Enter long at bar i if return over past k bars > 0; hold `hold` bars; repeat."""
    out = []
    i = k
    while i + hold < len(closes):
        if closes[i][1] > closes[i - k][1]:
            out.append((closes[i][0], (closes[i + hold][1] / closes[i][1] - 1) * 1e4))
            i += hold
        else:
            i += 1
    return out


def ma_trades(closes, k):
    """Long while close > SMA(k); one trade = entry..exit round trip."""
    out, s, in_pos, entry = [], 0.0, False, 0.0
    vals = [c for _, c in closes]
    for i in range(len(vals)):
        s += vals[i]
        if i >= k:
            s -= vals[i - k]
        if i < k:
            continue
        sma = s / k
        if not in_pos and vals[i] > sma:
            in_pos, entry = True, vals[i]
        elif in_pos and vals[i] < sma:
            out.append((closes[i][0], (vals[i] / entry - 1) * 1e4))
            in_pos = False
    return out


def donchian_trades(closes, k):
    """Long on new k-bar high; exit on (k//2)-bar low."""
    out, in_pos, entry = [], False, 0.0
    vals = [c for _, c in closes]
    for i in range(k, len(vals)):
        if not in_pos and vals[i] >= max(vals[i - k:i]):
            in_pos, entry = True, vals[i]
        elif in_pos and vals[i] <= min(vals[max(0, i - k // 2):i]):
            out.append((closes[i][0], (vals[i] / entry - 1) * 1e4))
            in_pos = False
    return out


def xsec_trades(series, top_k):
    """Weekly cross-sectional: long top_k symbols by 168h momentum (only if positive)."""
    idx = {s: {ts: c for ts, c in v} for s, v in series.items()}
    all_ts = sorted(set.intersection(*(set(d.keys()) for d in idx.values())))
    out = []
    for j in range(168, len(all_ts) - XSEC_REBALANCE_H, XSEC_REBALANCE_H):
        t0, t1 = all_ts[j], all_ts[j + XSEC_REBALANCE_H]
        mom = sorted(((idx[s][t0] / idx[s][all_ts[j - 168]] - 1, s) for s in SYMBOLS),
                     reverse=True)
        for m, s in mom[:top_k]:
            if m > 0:
                out.append((t0, (idx[s][t1] / idx[s][t0] - 1) * 1e4))
    return out


def split(trades):
    tr = [r for ts, r in trades if ts < TRAIN_END_MS]
    te = [r for ts, r in trades if ts >= TRAIN_END_MS]
    return tr, te


def screen(series):
    results = {}
    # per-symbol families: pool trades across symbols per config
    fams = {}
    fams.update({f"tsmom_k{k}_h{h}": [t for s in SYMBOLS for t in tsmom_trades(series[s], k, h)]
                 for k in TSMOM_LOOKBACK_H for h in TSMOM_HOLD_H})
    fams.update({f"ma_{k}": [t for s in SYMBOLS for t in ma_trades(series[s], k)]
                 for k in MA_FILTER_H})
    fams.update({f"donchian_{k}": [t for s in SYMBOLS for t in donchian_trades(series[s], k)]
                 for k in DONCHIAN_H})
    fams.update({f"xsec_top{k}": xsec_trades(series, k) for k in XSEC_TOP_K})

    for fam_prefix in ("tsmom", "ma", "donchian", "xsec"):
        cfgs = {k: v for k, v in fams.items() if k.startswith(fam_prefix)}
        best_cfg, best_exp, best_split = None, None, None
        for cfg, trades in cfgs.items():
            tr, te = split(trades)
            st = _trades_to_stats(tr, COST_RT_BPS["base"])
            if st.get("n", 0) >= 30 and (best_exp is None or st["exp_bps"] > best_exp):
                best_cfg, best_exp, best_split = cfg, st["exp_bps"], (tr, te)
        if best_cfg is None:
            results[fam_prefix] = {"skipped": "no config with >=30 train trades"}
            continue
        tr, te = best_split
        results[fam_prefix] = {
            "selected_on_train": best_cfg,
            "train": _trades_to_stats(tr, COST_RT_BPS["base"]),
            "TEST_base15bp": _trades_to_stats(te, COST_RT_BPS["base"]),
            "TEST_stress20bp": _trades_to_stats(te, COST_RT_BPS["stress"]),
        }
    return results


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/klines_cache"
    series = load_series(cache)
    bars = {s: len(v) for s, v in series.items()}
    out = {
        "note": ("PRE-REGISTERED long-only 1h screen, costs 15bp RT base / 20bp stress, "
                 "TRAIN 2023-2024 selection, TEST 2025-2026H1 OOS (selected config only). "
                 "A positive TEST here is a screen pass, NOT a GO — full validation "
                 "(regime stability, bootstrap CI, symbol concentration) must follow."),
        "bars": bars,
        "families": screen(series),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
