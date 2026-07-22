#!/usr/bin/env python3
"""Walk-forward ADAPTIVE long-horizon screen — the honest test of self-learning.

The fixed-config screen (longhorizon_screen.py) showed every long-horizon family
overfits: great on TRAIN 2023-24, strongly negative on TEST 2025-26. That kills the
*fixed* strategy. This asks the harder, fairer question the operator posed — can a
strategy that RE-LEARNS as the market changes ("reacts to all market situations")
capture edge the fixed version can't?

Mechanism (this IS the self-learning loop, tested honestly):
  * For each test month M (2024-01 .. 2026-06):
      - train window = trailing 12 months before M
      - per family, select the config with best net expectancy ON THE TRAIN WINDOW
        (>= MIN_TRAIN_TRADES trades), i.e. the loop adapts its parameters to the
        recent regime;
      - trade month M with the just-selected config; collect those trades.
  * Aggregate ALL test-month trades per family -> true out-of-sample, no peeking:
    every trade is decided using only data strictly before it.
  * Costs 15 bp RT base / 20 bp stress. Long-only (spot).

A positive, cost-surviving walk-forward result here would be the first honest sign of
a viable learning target. A negative one is decisive: even an adaptive learner has no
edge in these families on these pairs -> the goal needs a different data source or
strategy space, not more tuning.

Usage: python3 longhorizon_walkforward.py [cache_dir]
"""
from __future__ import annotations
import datetime as _dt
import json
import sys

from longhorizon_screen import (
    SYMBOLS, COST_RT_BPS, load_series,
    tsmom_trades, ma_trades, donchian_trades, xsec_trades,
    TSMOM_LOOKBACK_H, TSMOM_HOLD_H, MA_FILTER_H, DONCHIAN_H, XSEC_TOP_K,
    _trades_to_stats,
)

MIN_TRAIN_TRADES = 10
TRAIN_MONTHS = 12
FIRST_TEST = (2024, 1)
LAST_TEST = (2026, 6)


def month_ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def add_months(y, m, d):
    idx = (y * 12 + (m - 1)) + d
    return idx // 12, idx % 12 + 1


def all_configs(series):
    """Compute every config's full trade list once: {family: {cfg: [(ts,ret_bps)]}}."""
    fams = {"tsmom": {}, "ma": {}, "donchian": {}, "xsec": {}}
    for k in TSMOM_LOOKBACK_H:
        for h in TSMOM_HOLD_H:
            fams["tsmom"][f"k{k}_h{h}"] = [t for s in SYMBOLS for t in tsmom_trades(series[s], k, h)]
    for k in MA_FILTER_H:
        fams["ma"][f"ma{k}"] = [t for s in SYMBOLS for t in ma_trades(series[s], k)]
    for k in DONCHIAN_H:
        fams["donchian"][f"dc{k}"] = [t for s in SYMBOLS for t in donchian_trades(series[s], k)]
    for k in XSEC_TOP_K:
        fams["xsec"][f"top{k}"] = xsec_trades(series, k)
    return fams


def walk_forward(fams):
    results = {}
    for fam, cfgs in fams.items():
        test_trades, picks = [], []
        y, m = FIRST_TEST
        while (y, m) <= LAST_TEST:
            t_lo, t_hi = month_ms(y, m), month_ms(*add_months(y, m, 1))
            tr_lo = month_ms(*add_months(y, m, -TRAIN_MONTHS))
            best_cfg, best_exp = None, None
            for cfg, trades in cfgs.items():
                tw = [r for ts, r in trades if tr_lo <= ts < t_lo]
                st = _trades_to_stats(tw, COST_RT_BPS["base"])
                if st.get("n", 0) >= MIN_TRAIN_TRADES and (best_exp is None or st["exp_bps"] > best_exp):
                    best_cfg, best_exp = cfg, st["exp_bps"]
            if best_cfg is not None:
                mt = [r for ts, r in cfgs[best_cfg] if t_lo <= ts < t_hi]
                test_trades.extend(mt)
                picks.append(f"{y}-{m:02d}:{best_cfg}({len(mt)})")
            y, m = add_months(y, m, 1)
        results[fam] = {
            "walkforward_TEST_base15bp": _trades_to_stats(test_trades, COST_RT_BPS["base"]),
            "walkforward_TEST_stress20bp": _trades_to_stats(test_trades, COST_RT_BPS["stress"]),
            "n_test_months": len(picks),
            "picks_sample": picks[:6] + (["..."] if len(picks) > 6 else []),
        }
    return results


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/klines_cache"
    series = load_series(cache)
    out = {
        "note": ("WALK-FORWARD adaptive long-only screen: per test month, re-select the "
                 "best family config on the trailing 12mo window, trade the next month. "
                 "True OOS (every trade uses only prior data). Costs 15bp/20bp RT. "
                 "This is the honest self-learning test; a positive cost-surviving result "
                 "is the first viable learning target, a negative one is decisive."),
        "test_span": f"{FIRST_TEST} .. {LAST_TEST}",
        "families": walk_forward(all_configs(series)),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
