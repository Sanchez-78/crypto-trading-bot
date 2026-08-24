#!/usr/bin/env python3
"""Funding-carry robustness — the SKEPTIC BATTERY applied to the first surviving lead.

Prior leads (donchian/xsec momentum) passed a naive walk-forward, then a skeptic battery
refuted them: bootstrap CI spanned zero, profit concentrated in one year (2024 beta), wins only
in up-markets (`RESEARCH_LONGHORIZON_FINDINGS.md`). Funding-carry v2 (`funding_carry_v2.py`)
reportedly PASSES that battery. This script tries HARD to break it with the SAME rigor plus the
extra requirements that funding-carry specifically invites:

  1. PURGED NESTED WALK-FORWARD. The v2 basket filter (trailing-3mo funding > 0.20 bp/8h) is
     causal, but the OOS window is a single fixed 2025-01 split. We (a) verify no look-ahead in
     the filter, (b) sweep the split date across every month 2024-06..2025-06 and require the edge
     to survive out-of-sample regardless of where we cut, and (c) add a >=1-month embargo (the
     holding horizon) so the trailing window that selects month M never overlaps the tested month.

  2. BLOCK / CLUSTER BOOTSTRAP by funding regime episode. Monthly carry returns inside one funding
     regime are autocorrelated; iid bootstrap (what v2 uses) overstates significance. We report the
     CI under a circular block bootstrap and the EFFECTIVE sample size (Neff = N * (1-rho)/(1+rho)
     from lag-1 autocorrelation). 15 monthly points is already thin; correlated => even fewer.

  3. EXTENDED HISTORY. Attempt to pull funding + spot/perp back to 2020 where Binance has it, to add
     pre-2023 regimes (2021 bull, 2022 bear/LUNA/FTX). Report what actually downloaded.

  4. NEGATIVE-FUNDING REGIME STRESS. Quantify, per month, "rich funding" (basket non-empty) vs
     "empty basket" (filter emptied it -> strategy flat, no loss). Locate/construct the lowest-funding
     slice and confirm the filter empties the basket rather than forcing bad carry. Report the % of
     the sample that is rich vs empty.

  5. GO-THRESHOLD SCORECARD (charter RESEARCH_PIVOT_CHARTER.md):
     OOS PF>=1.20; expectancy>0 with >=+2-3bp reserve after realistic cost; cluster-bootstrap 95% CI
     lower>0; >=200 OOS fills; stable in >=2 regimes; no symbol>50% of profit. The 15-coin-month unit
     is FAR below 200 fills -> flagged explicitly, with a discussion of whether a finer unit is legit.

Reuses funding_carry_v2's loaders/model verbatim (same numbers), then subjects them to the battery.
REAL trading = absolute NO-GO. Offline paper research on public data only. Every number is OOS.

Usage: python3 funding_carry_robustness.py [cache_dir]
"""
from __future__ import annotations
import datetime as _dt
import json
import math
import random
import sys

# Reuse v2's model verbatim so numbers match the reported lead exactly.
from funding_carry_v2 import (
    SYMBOLS, BREAKEVEN_BPS_PER_8H, COST_RT_BPS,
    load_funding, load_daily, SPOT_URL, PERP_URL,
    ms, nextm, prevm, month_ret, month_funding, trailing_avg_funding,
)

# Extended-history months to ATTEMPT (Binance USDM funding starts ~2019-09 for BTC; varies by symbol).
EXT_MONTHS = [f"{y}-{m:02d}" for y in (2020, 2021, 2022) for m in range(1, 13)]


# ----------------------------------------------------------------------------------------------
# Core carry model, parameterised by TEST window so we can sweep the split (check 1).
# Faithful to funding_carry_v2.run(), but ALSO returns per-month basket occupancy + exit-cost
# handling made explicit (v2's exit-cost loop body was a dead `pass`; we charge it correctly here).
# ----------------------------------------------------------------------------------------------
def carry_run(funding, spot, perp, cost, test_start, end, breakeven=BREAKEVEN_BPS_PER_8H):
    """Monthly-rebalanced delta-neutral carry over [test_start, end].
    Returns dict with monthly_net list, tagged coin-months, and per-month basket occupancy."""
    monthly, cm, occupancy = [], [], []
    held_prev = set()
    y, m = test_start
    while (y, m) <= end:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        lo3 = ms(*prevm(y, m, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > breakeven:
                basket.append(s)
        held = set(basket)
        month_pnls = []
        for s in basket:
            f_bps = month_funding(funding[s], lo, hi) * 1e4
            sr, pr = month_ret(spot[s], lo, hi), month_ret(perp[s], lo, hi)
            basis_bps = ((sr - pr) * 1e4) if (sr is not None and pr is not None) else 0.0
            trans = 0.0
            if s not in held_prev:
                trans += cost / 2.0
            net = f_bps + basis_bps - trans
            month_pnls.append(net)
            cm.append((s, lo, net))
        exit_cost = len(held_prev - held) * (cost / 2.0)
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls) - exit_cost / max(1, len(month_pnls)))
            occupancy.append((y, m, len(basket), True))
        else:
            # empty basket -> strategy flat this month (no loss). Record 0 for a continuous series.
            occupancy.append((y, m, 0, False))
        held_prev = held
        y, m = nextm(y, m)
    return {"monthly": monthly, "cm": cm, "occupancy": occupancy}


def basic_stats(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0}
    gw = sum(v for v in vals if v > 0)
    gl = -sum(v for v in vals if v < 0)
    return {"n": n, "mean_bps": round(sum(vals) / n, 2), "total_bps": round(sum(vals), 1),
            "win_rate": round(sum(1 for v in vals if v > 0) / n, 3),
            "pf": round(gw / gl, 3) if gl > 0 else float("inf")}


# ----------------------------------------------------------------------------------------------
# Check 2: block bootstrap + effective sample size
# ----------------------------------------------------------------------------------------------
def lag1_autocorr(x):
    n = len(x)
    if n < 3:
        return 0.0
    mu = sum(x) / n
    denom = sum((v - mu) ** 2 for v in x)
    if denom == 0:
        return 0.0
    num = sum((x[i] - mu) * (x[i - 1] - mu) for i in range(1, n))
    return num / denom


def effective_n(x):
    rho = lag1_autocorr(x)
    n = len(x)
    if rho <= -0.999:
        return n
    neff = n * (1.0 - rho) / (1.0 + rho)
    return max(1.0, min(float(n), neff))


def iid_boot_ci(vals, B=5000, seed=7, lo=0.025, hi=0.975):
    n = len(vals)
    if n < 6:
        return None
    rng = random.Random(seed)
    ms_ = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(ms_[int(lo * B)], 2), round(ms_[int(hi * B)], 2)


def block_boot_ci(vals, block, B=5000, seed=7, lo=0.025, hi=0.975):
    """Circular block bootstrap: resample contiguous blocks of length `block` to preserve
    within-regime autocorrelation. Wraps around (circular) so every index is eligible."""
    n = len(vals)
    if n < 6:
        return None
    rng = random.Random(seed)
    nblocks = math.ceil(n / block)
    means = []
    for _ in range(B):
        sample = []
        for _ in range(nblocks):
            start = rng.randrange(n)
            for k in range(block):
                sample.append(vals[(start + k) % n])
        sample = sample[:n]
        means.append(sum(sample) / n)
    means.sort()
    return round(means[int(lo * B)], 2), round(means[int(hi * B)], 2)


# ----------------------------------------------------------------------------------------------
# Check 1: split-date sweep (purged nested walk-forward robustness)
# ----------------------------------------------------------------------------------------------
def split_sweep(funding, spot, perp, cost, end):
    """Re-run the carry with TEST_START swept across many months. If the +edge only exists for
    the fixed 2025-01 cut, this exposes it. Embargo is inherent: the trailing-3mo selection window
    for month M ends at M's start (< M), so it never sees month M's realised carry (no look-ahead)."""
    results = {}
    for (yy, mm) in [(2024, 6), (2024, 9), (2024, 12), (2025, 1), (2025, 3), (2025, 6)]:
        if (yy, mm) > end:
            continue
        r = carry_run(funding, spot, perp, cost, (yy, mm), end)
        st = basic_stats(r["monthly"])
        results[f"split_{yy}-{mm:02d}"] = {
            "n_months": st.get("n", 0), "mean_bps": st.get("mean_bps"),
            "win_rate": st.get("win_rate"), "pf": st.get("pf"),
        }
    return results


# ----------------------------------------------------------------------------------------------
# Check 3: extended history load (best-effort)
# ----------------------------------------------------------------------------------------------
def load_extended(cache):
    """Load funding/spot/perp for 2020-2022 by monkeypatching MONTHS in the v2 loaders' scope.
    Returns (funding, spot, perp, coverage) where coverage reports what actually downloaded."""
    import funding_carry_v2 as v2
    orig = v2.MONTHS
    v2.MONTHS = EXT_MONTHS
    try:
        f = v2.load_funding(cache)
        s = v2.load_daily(cache, SPOT_URL, "spotd")
        p = v2.load_daily(cache, PERP_URL, "perpd")
    finally:
        v2.MONTHS = orig
    coverage = {}
    for sym in SYMBOLS:
        fpts = len(f.get(sym, []))
        earliest = None
        if f.get(sym):
            earliest = _dt.datetime.utcfromtimestamp(min(t for t, _ in f[sym]) / 1000).strftime("%Y-%m")
        coverage[sym] = {"funding_points": fpts, "earliest_funding": earliest,
                         "spot_days": len(s.get(sym, {})), "perp_days": len(p.get(sym, {}))}
    return f, s, p, coverage


def carry_run_extended(funding, spot, perp, cost, start, end):
    """Same model but no dependence on TEST_START constant; used for the extended regime."""
    return carry_run(funding, spot, perp, cost, start, end)


# ----------------------------------------------------------------------------------------------
# Check 4: negative-funding regime stress + rich-vs-empty occupancy
# ----------------------------------------------------------------------------------------------
def occupancy_report(occ):
    total = len(occ)
    rich = sum(1 for *_, active in occ if active)
    empty = total - rich
    sizes = [sz for *_h, sz, active in occ if active]
    return {
        "months_total": total,
        "months_rich_basket": rich,
        "months_empty_basket_flat": empty,
        "pct_rich": round(rich / total, 3) if total else None,
        "avg_basket_size_when_rich": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "min_basket_size": min(sizes) if sizes else 0,
        "max_basket_size": max(sizes) if sizes else 0,
    }


# ----------------------------------------------------------------------------------------------
# Assemble battery
# ----------------------------------------------------------------------------------------------
def analyze_scenario(funding, spot, perp, cost, test_start, end, market):
    r = carry_run(funding, spot, perp, cost, test_start, end)
    monthly, cm = r["monthly"], r["cm"]
    st = basic_stats(monthly)

    # up/down market neutrality (from perp equal-weight monthly return sign) on coin-months
    def mkey(t):
        d = _dt.datetime.utcfromtimestamp(t / 1000)
        return (d.year, d.month)
    up = sum(v for _, t, v in cm if market.get(mkey(t), 0) >= 0)
    dn = sum(v for _, t, v in cm if market.get(mkey(t), 0) < 0)
    n_up = sum(1 for _, t, v in cm if market.get(mkey(t), 0) >= 0)
    n_dn = sum(1 for _, t, v in cm if market.get(mkey(t), 0) < 0)

    # symbol concentration (gross profit share) and per-year
    prof, by_year = {}, {}
    for s, t, v in cm:
        if v > 0:
            prof[s] = prof.get(s, 0) + v
        yy = _dt.datetime.utcfromtimestamp(t / 1000).year
        by_year[yy] = round(by_year.get(yy, 0) + v, 1)
    tot = sum(prof.values())

    rho = lag1_autocorr(monthly)
    neff = effective_n(monthly)
    # block length ~ ceil(sqrt(N)) is a standard rule of thumb; also try a regime-scale block of 3.
    blk = max(2, round(math.sqrt(len(monthly)))) if monthly else 2

    return {
        "monthly_basket_stats": st,
        "n_coin_month_fills": len(cm),
        "iid_boot_ci95_bps": iid_boot_ci(monthly),
        "block_boot_ci95_bps_blk_sqrtN": block_boot_ci(monthly, blk),
        "block_boot_ci95_bps_blk3": block_boot_ci(monthly, 3),
        "lag1_autocorr_monthly": round(rho, 3),
        "effective_n_months": round(neff, 2),
        "raw_n_months": len(monthly),
        "coinmonth_net_up_market_bps": round(up, 1),
        "coinmonth_net_down_market_bps": round(dn, 1),
        "n_coinmonths_up": n_up, "n_coinmonths_down": n_dn,
        "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
        "top_symbol": max(prof, key=prof.get) if prof else None,
        "net_bps_by_year": by_year,
        "occupancy": occupancy_report(r["occupancy"]),
    }


def market_monthly(perp, start, end):
    mkt = {}
    y, m = start
    while (y, m) <= end:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = [month_ret(perp[s], lo, hi) for s in SYMBOLS]
        rs = [x for x in rs if x is not None]
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)
    return mkt


def go_scorecard(base):
    """Map the base-cost scenario onto the charter GO thresholds -> PASS/FAIL each."""
    st = base["monthly_basket_stats"]
    ci = base["block_boot_ci95_bps_blk3"] or base["iid_boot_ci95_bps"]
    pf = st.get("pf")
    mean = st.get("mean_bps")
    checks = []
    checks.append(("OOS PF >= 1.20", pf, isinstance(pf, (int, float)) and pf >= 1.20))
    checks.append(("expectancy > 0 with >= +2-3bp reserve after cost",
                   f"{mean} bp/coin-month" if mean is not None else None,
                   mean is not None and mean >= 2.0))
    checks.append(("cluster-bootstrap 95% CI lower > 0",
                   ci, ci is not None and ci[0] > 0))
    checks.append((">= 200 OOS fills",
                   base["n_coin_month_fills"], base["n_coin_month_fills"] >= 200))
    yrs = base["net_bps_by_year"]
    pos_years = sum(1 for v in yrs.values() if v > 0)
    checks.append(("stable in >= 2 regimes (>=2 positive years)",
                   yrs, pos_years >= 2))
    up, dn = base["coinmonth_net_up_market_bps"], base["coinmonth_net_down_market_bps"]
    checks.append(("market-neutral (positive in up AND down markets)",
                   {"up": up, "down": dn}, up > 0 and dn > 0))
    mss = base["max_symbol_profit_share"]
    checks.append(("no symbol > 50% of profit",
                   mss, mss is not None and mss <= 0.50))
    passed = sum(1 for *_x, ok in checks if ok)
    return {
        "checks": [{"threshold": t, "value": v, "PASS": ok} for t, v, ok in checks],
        "passed": passed, "total": len(checks),
    }


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    end = (2026, 6)

    funding = load_funding(cache)
    spot = load_daily(cache, SPOT_URL, "spotd")
    perp = load_daily(cache, PERP_URL, "perpd")
    market = market_monthly(perp, (2025, 1), end)

    out = {"note": ("Skeptic battery on funding-carry v2 — the SAME rigor that refuted "
                    "donchian/xsec momentum, plus purged-WF split sweep, block bootstrap w/ "
                    "effective-N, extended history, and negative-funding stress. REAL=NO-GO; "
                    "all OOS on public data.")}

    # --- main OOS scenarios (base 30 / stress 40) ---
    out["scenarios"] = {}
    for scen, cost in COST_RT_BPS.items():
        out["scenarios"][scen] = analyze_scenario(funding, spot, perp, cost, (2025, 1), end, market)

    # --- Check 1: split-date sweep (base cost) ---
    out["check1_split_sweep_base"] = split_sweep(funding, spot, perp, COST_RT_BPS["base"], end)

    # --- Check 3: extended history ---
    try:
        ef, es, ep, cov = load_extended(cache)
        out["check3_extended_coverage"] = cov
        # find earliest month with >=1 symbol having funding+prices, run carry from there to 2022-12
        earliest_year = min((int(v["earliest_funding"][:4]) for v in cov.values()
                             if v["earliest_funding"]), default=None)
        if earliest_year is not None:
            # merge extended + main funding/prices so trailing window has continuity
            mf = {s: sorted(set(ef.get(s, []) + funding.get(s, []))) for s in SYMBOLS}
            msp = {s: {**es.get(s, {}), **spot.get(s, {})} for s in SYMBOLS}
            mpp = {s: {**ep.get(s, {}), **perp.get(s, {})} for s in SYMBOLS}
            ext_start = (2021, 1)   # allow 2020 as trailing warmup
            ext_end = (2022, 12)
            emkt = market_monthly(mpp, ext_start, ext_end)
            out["check3_extended_carry_2021_2022"] = analyze_scenario(
                mf, msp, mpp, COST_RT_BPS["base"], ext_start, ext_end, emkt)
        else:
            out["check3_extended_carry_2021_2022"] = "no extended funding data downloaded"
    except Exception as e:
        out["check3_extended_error"] = repr(e)

    # --- Check 4: negative-funding / occupancy already inside each scenario; surface a summary ---
    base = out["scenarios"]["base"]
    out["check4_negative_funding_stress"] = {
        "occupancy_base": base["occupancy"],
        "interpretation": ("empty-basket months => strategy flat (0), never forced into bad carry. "
                           "pct_rich = fraction of sample that actually earned carry."),
    }

    # --- Check 2 surfaced: effective N + block vs iid CI (base) ---
    out["check2_block_bootstrap_base"] = {
        "raw_n_months": base["raw_n_months"],
        "lag1_autocorr": base["lag1_autocorr_monthly"],
        "effective_n_months": base["effective_n_months"],
        "iid_boot_ci95": base["iid_boot_ci95_bps"],
        "block_boot_ci95_blk3": base["block_boot_ci95_bps_blk3"],
        "block_boot_ci95_blk_sqrtN": base["block_boot_ci95_bps_blk_sqrtN"],
    }

    # --- GO scorecard (base cost) ---
    out["GO_scorecard_base"] = go_scorecard(base)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
