#!/usr/bin/env python3
"""Funding-carry v3 — honest EXECUTION model for delta-neutral carry (long spot / short perp).

v2 answered "does carry survive basis + transition cost?" at monthly resolution:
  OOS 2025-01..2026-06, 73% months positive, boot CI[+5.9,+31.0]bp, market-neutral, ~2%/yr net.
But v2 measured funding as a monthly SUM and basis from month-boundary daily closes ONLY. That
hides three things the operator asked us to model honestly before believing ~2%/yr:

v3 deepens execution WITHOUT changing v2's correct no-churn design (transition cost at enter/exit
only; a coin held in consecutive months rolls and pays nothing mid-position):

  1. SHORT-PERP FUNDING, intra-month path (8h cadence). Binance USDⓈ-M convention: funding>0 ->
     longs pay shorts. Our carry is SHORT perp, so short RECEIVES funding when funding>0. We accrue
     each 8h event on the *current* perp-leg notional (which drifts as the perp price moves), not a
     flat monthly sum. Verified sign below (SIGN_CHECK).
  2. INTRA-MONTH BASIS / delta-neutral drift, at 8h klines. Delta-neutral is set 1:1 in notional at
     entry; as spot and perp diverge intra-month the legs are no longer equal, so the position is
     only *approximately* neutral. We compute the true two-leg mark-to-market path:
        spot leg (long):  +Q_spot * (S_t - S_entry)
        perp leg (short): -Q_perp * (P_t - P_entry)
     with Q_spot*S_entry = Q_perp*P_entry = 1 unit notional at entry. We report BOTH:
        - NO intra-month rebalance (drift left to run, realistic for a low-churn book)
        - DAILY re-hedge to neutral (resize perp each day; costs perp fills — models churn tradeoff)
  3. REALISTIC PER-LEG FILLS. Spot fill and perp fill are separate instruments with separate
     half-spread + fee. Three scenarios OPTIMISTIC / BASE / CONSERVATIVE (bar requires BASE and
     CONSERVATIVE to hold). Transition costs BOTH legs on enter and on exit.
  4. CAPITAL / MARGIN EFFICIENCY. Delta-neutral ties up capital on BOTH legs: spot fully funded
     (1.0 notional) + perp initial margin (1/leverage) + a margin buffer to avoid liquidation on
     the short as price rises. Yield is expressed on TRUE deployed capital, not single-leg notional.
        deployed = spot_notional(1.0) + perp_margin(1/L) + buffer   [per 1.0 unit of carry notional]
     A "~2%/yr on single-leg" becomes materially smaller on true deployed capital.

Everything is OOS 2025-01..2026-06, public data (data.binance.vision), PAPER research only.
REAL trading = absolute NO-GO.

Usage: python3 funding_carry_v3.py [cache_dir]   (default /tmp/fund_cache)
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
# fetch a trailing warmup window before TEST_START so the 3-month funding filter is populated
MONTHS = [f"2024-{m:02d}" for m in range(9, 13)] + \
         [f"2025-{m:02d}" for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 7)]
TEST_START = (2025, 1)
END = (2026, 6)

# --- capital / margin model (per 1.0 unit of carry notional) ---
PERP_LEVERAGE = 3.0          # conservative isolated-margin leverage on the short perp leg
MARGIN_BUFFER = 0.15         # extra collateral held idle to survive adverse perp moves (fraction of notional)

# --- per-leg execution scenarios: (spot_half_spread_bp, spot_fee_bp, perp_half_spread_bp, perp_fee_bp)
#     fee = per-side taker/maker fee applied per leg per side; half_spread paid per leg per side.
#     Round-trip transition cost per leg = 2 * (half_spread + fee)  (enter + exit).
FILL_SCENARIOS = {
    # optimistic: patient maker on both legs, tight majors spread, maker fee ~1bp
    "optimistic": dict(spot_hs=0.5, spot_fee=1.0, perp_hs=0.5, perp_fee=1.8),
    # base: cross the half-spread once, blended maker/taker, realistic majors
    "base":       dict(spot_hs=1.0, spot_fee=5.0, perp_hs=1.5, perp_fee=4.0),
    # conservative: taker both legs, wider effective spread, retail-tier fees
    "conservative": dict(spot_hs=2.5, spot_fee=7.5, perp_hs=3.0, perp_fee=5.0),
}
BREAKEVEN_BPS_PER_8H = 0.20     # trailing funding must beat this to include a coin

FUND_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
SPOT_URL = "https://data.binance.vision/data/spot/monthly/klines/{s}/8h/{s}-8h-{m}.zip"
PERP_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/8h/{s}-8h-{m}.zip"


def _dl(url, fp):
    if not os.path.exists(fp):
        try:
            with urllib.request.urlopen(url, timeout=45) as r, open(fp, "wb") as f:
                f.write(r.read())
        except Exception:
            return False
    return os.path.exists(fp)


def load_funding(cache):
    """symbol -> sorted list of (calc_time_ms, funding_rate). Header row skipped."""
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
                        if row and row[0] and row[0][0].isdigit():   # skips 'calc_time' header
                            rows.append((int(row[0]), float(row[2])))
            except Exception:
                pass
        rows.sort()
        out[s] = rows
    return out


def load_klines(cache, url_tmpl, tag):
    """symbol -> sorted list of (open_time_ms, close_price). 8h bars. Handles us/ms + header."""
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
                        if row and row[0] and row[0][0].isdigit():   # skips 'open_time' header
                            ts = int(row[0])
                            if ts > 10**14:      # spot 8h ts are in microseconds
                                ts //= 1000
                            rows[ts] = float(row[4])                 # close
            except Exception:
                pass
        out[s] = sorted(rows.items())
    return out


def ms(y, m):
    return int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)


def nextm(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def prevm(y, m, k):
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


def trailing_avg_funding(fund_sym, lo3, lo):
    xs = [r for t, r in fund_sym if lo3 <= t < lo]
    return (sum(xs) / len(xs)) if xs else None


def _slice(series, lo, hi):
    """list of (ts, val) with lo<=ts<hi, ts ascending."""
    return [(t, v) for t, v in series if lo <= t < hi]


def sign_check(funding, perp):
    """Verify short-perp receives funding when funding>0. Report a concrete month."""
    s = "BTCUSDT"
    lo, hi = ms(2025, 3), ms(2025, 4)
    ev = _slice(funding[s], lo, hi)
    pos = sum(r for _, r in ev if r > 0)
    neg = sum(r for _, r in ev if r < 0)
    net = sum(r for _, r in ev)
    return {
        "symbol": s, "month": "2025-03",
        "n_funding_events": len(ev),
        "sum_positive_rate": round(pos, 6), "sum_negative_rate": round(neg, 6),
        "net_rate": round(net, 6),
        "short_perp_pnl_bps_if_flat_notional": round(net * 1e4, 2),
        "convention": ("Binance USD-M: funding>0 => longs pay shorts. Carry is SHORT perp => "
                       "RECEIVES funding when funding>0. short-leg funding P&L = +rate*perp_notional "
                       "per 8h event."),
    }


def coinmonth_pnl(funding_sym, spot_sym, perp_sym, lo, hi, entry_this_month, exit_this_month,
                  fills, rehedge_daily):
    """
    True two-leg mark-to-market for one coin held over [lo,hi), per 1.0 unit carry notional.
    Returns dict with funding_bps, basis_bps (drift MtM), trans_bps, net_bps, and rehedge_cost_bps.

    Legs at entry (1.0 notional each): Q_spot = 1/S_entry (long), Q_perp = 1/P_entry (short).
      spot MtM  = +Q_spot*(S_t - S_entry)          (long profits when spot rises)
      perp MtM  = -Q_perp*(P_t - P_entry)          (short profits when perp falls)
    Funding accrues each 8h event on current perp notional Q_perp*P_t: +rate*Q_perp*P_t.
    If rehedge_daily: at each 08:00-boundary day start, resize Q_perp back to current-neutral
      (Q_perp = current_spot_leg_notional / P_t), paying a perp round-trip half-spread+fee on the
      resized delta.
    """
    perp_bars = _slice(perp_sym, lo, hi)
    spot_bars = _slice(spot_sym, lo, hi)
    fund_ev = _slice(funding_sym, lo, hi)
    if len(perp_bars) < 2 or len(spot_bars) < 2:
        return None

    # align on common timestamps (8h spot/perp share the same 00/08/16 boundaries)
    spot_map = dict(spot_bars)
    perp_map = dict(perp_bars)
    common = sorted(set(spot_map) & set(perp_map))
    if len(common) < 2:
        return None

    S0, P0 = spot_map[common[0]], perp_map[common[0]]
    Q_spot = 1.0 / S0          # long spot units, 1.0 notional
    Q_perp = 1.0 / P0          # short perp units, 1.0 notional

    funding_pnl = 0.0
    rehedge_cost = 0.0
    perp_hs, perp_fee = fills["perp_hs"], fills["perp_fee"]

    # index funding events by timestamp -> rate
    fund_at = {}
    for t, r in fund_ev:
        fund_at[t] = r

    last_day = None
    for t in common:
        S_t, P_t = spot_map[t], perp_map[t]
        # funding: any funding event at (or effectively at) this 8h boundary accrues on current perp notional
        if t in fund_at:
            funding_pnl += fund_at[t] * (Q_perp * P_t)     # short receives when rate>0

        if rehedge_daily:
            day = _dt.datetime.utcfromtimestamp(t / 1000).date()
            if last_day is not None and day != last_day:
                # target neutral: match current spot-leg notional
                spot_notional_now = Q_spot * S_t
                Q_perp_target = spot_notional_now / P_t
                delta_notional = abs(Q_perp_target - Q_perp) * P_t
                rehedge_cost += delta_notional * ((perp_hs + perp_fee) / 1e4)
                Q_perp = Q_perp_target
            last_day = day

    S_end, P_end = spot_map[common[-1]], perp_map[common[-1]]
    spot_mtm = Q_spot * (S_end - S0)
    perp_mtm = -Q_perp * (P_end - P0)
    basis_mtm = spot_mtm + perp_mtm        # the true delta-neutral price P&L (drift)

    # transition cost: cost BOTH legs, only on enter and/or exit this month
    trans = 0.0
    per_leg_rt = lambda hs, fee: (hs + fee) / 1e4   # one side (enter OR exit) per leg, in fraction
    if entry_this_month:
        trans += per_leg_rt(fills["spot_hs"], fills["spot_fee"])   # spot enter
        trans += per_leg_rt(perp_hs, perp_fee)                     # perp enter
    if exit_this_month:
        trans += per_leg_rt(fills["spot_hs"], fills["spot_fee"])   # spot exit
        trans += per_leg_rt(perp_hs, perp_fee)                     # perp exit

    net = funding_pnl + basis_mtm - trans - rehedge_cost
    return {
        "funding_bps": funding_pnl * 1e4,
        "basis_bps": basis_mtm * 1e4,
        "trans_bps": trans * 1e4,
        "rehedge_bps": rehedge_cost * 1e4,
        "net_bps": net * 1e4,
    }


def run(funding, spot, perp, fills, rehedge_daily):
    """Monthly-rebalanced neutral carry with intra-month path. Returns (monthly_net, coinmonth_tagged)."""
    monthly, cm = [], []
    held_prev = set()
    y, m = TEST_START
    # first, discover the full held-schedule so we know exit months
    schedule = []
    yy, mm = TEST_START
    while (yy, mm) <= END:
        lo, hi = ms(yy, mm), ms(*nextm(yy, mm))
        lo3 = ms(*prevm(yy, mm, 3))
        basket = []
        for s in SYMBOLS:
            ta = trailing_avg_funding(funding[s], lo3, lo)
            if ta is not None and ta * 1e4 > BREAKEVEN_BPS_PER_8H:
                basket.append(s)
        schedule.append(((yy, mm), set(basket)))
        yy, mm = nextm(yy, mm)

    for i, ((yy, mm), held) in enumerate(schedule):
        lo, hi = ms(yy, mm), ms(*nextm(yy, mm))
        next_held = schedule[i + 1][1] if i + 1 < len(schedule) else set()
        month_pnls = []
        for s in held:
            entry = s not in held_prev
            exit_ = s not in next_held           # leaving after this month (or end of test)
            r = coinmonth_pnl(funding[s], spot[s], perp[s], lo, hi, entry, exit_, fills, rehedge_daily)
            if r is None:
                continue
            month_pnls.append(r["net_bps"])
            cm.append((s, lo, r))
        if month_pnls:
            monthly.append(sum(month_pnls) / len(month_pnls))
        held_prev = held
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


def market_proxy(perp):
    """equal-weight perp monthly return per (y,m), for up/down neutrality split."""
    mkt = {}
    y, m = TEST_START
    while (y, m) <= END:
        lo, hi = ms(y, m), ms(*nextm(y, m))
        rs = []
        for s in SYMBOLS:
            bars = _slice(perp[s], lo, hi)
            if len(bars) >= 2:
                rs.append(bars[-1][1] / bars[0][1] - 1)
        mkt[(y, m)] = sum(rs) / len(rs) if rs else 0.0
        y, m = nextm(y, m)
    return mkt


def deployed_capital_per_notional():
    """True deployed capital per 1.0 unit of carry notional (both legs)."""
    return 1.0 + (1.0 / PERP_LEVERAGE) + MARGIN_BUFFER


def analyze(monthly, cm, mkt):
    def mkey(t):
        d = _dt.datetime.utcfromtimestamp(t / 1000)
        return (d.year, d.month)
    up = sum(r["net_bps"] for _, t, r in cm if mkt.get(mkey(t), 0) >= 0)
    dn = sum(r["net_bps"] for _, t, r in cm if mkt.get(mkey(t), 0) < 0)
    prof, by_year, comp = {}, {}, {"funding": 0.0, "basis": 0.0, "trans": 0.0, "rehedge": 0.0}
    for s, t, r in cm:
        if r["net_bps"] > 0:
            prof[s] = prof.get(s, 0) + r["net_bps"]
        yy = _dt.datetime.utcfromtimestamp(t / 1000).year
        by_year[yy] = round(by_year.get(yy, 0) + r["net_bps"], 0)
        comp["funding"] += r["funding_bps"]; comp["basis"] += r["basis_bps"]
        comp["trans"] += r["trans_bps"]; comp["rehedge"] += r["rehedge_bps"]
    tot = sum(prof.values())
    yrs = (END[0] - TEST_START[0]) + (END[1] - TEST_START[1]) / 12.0
    mean_month_bps = (sum(monthly) / len(monthly)) if monthly else 0.0
    # yield on single-leg notional vs true deployed capital
    ann_singleleg_pct = round(mean_month_bps * 12 / 100.0, 3)
    dep = deployed_capital_per_notional()
    ann_deployed_pct = round((mean_month_bps * 12 / 100.0) / dep, 3)
    return {
        "monthly_basket": stats(monthly),
        "monthly_boot_ci_5_95_bps": boot_ci(monthly),
        "annual_yield_singleleg_pct": ann_singleleg_pct,
        "true_deployed_capital_per_notional": round(dep, 3),
        "annual_yield_on_true_deployed_capital_pct": ann_deployed_pct,
        "coinmonth_net_up_market_bps": round(up, 0),
        "coinmonth_net_down_market_bps": round(dn, 0),
        "max_symbol_profit_share": round(max(prof.values()) / tot, 3) if tot > 0 else None,
        "net_bps_by_year": by_year,
        "pnl_decomposition_bps": {k: round(v, 0) for k, v in comp.items()},
    }


def main():
    cache = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fund_cache"
    os.makedirs(cache, exist_ok=True)
    funding = load_funding(cache)
    spot = load_klines(cache, SPOT_URL, "spot8h")
    perp = load_klines(cache, PERP_URL, "perp8h")
    mkt = market_proxy(perp)

    out = {
        "note": ("Funding-carry v3: HONEST EXECUTION model. Intra-month 8h funding path on drifting "
                 "perp notional + true two-leg delta-neutral MtM (drift) + per-leg fills (spot & perp "
                 "separately) + both-leg transition cost + capital/margin efficiency. No mid-position "
                 "churn (v2 design preserved). OOS 2025-01..2026-06. PAPER only; REAL=NO-GO."),
        "sign_check": sign_check(funding, perp),
        "capital_model": {
            "perp_leverage": PERP_LEVERAGE, "margin_buffer_frac": MARGIN_BUFFER,
            "deployed_per_1.0_notional": round(deployed_capital_per_notional(), 3),
            "explanation": ("spot leg fully funded (1.0) + perp initial margin (1/L) + idle buffer "
                            "to survive adverse short moves. Yield on this, not single-leg."),
        },
        "data_coverage": {s: {"funding_ev": len(funding[s]), "spot_8h_bars": len(spot[s]),
                              "perp_8h_bars": len(perp[s])} for s in SYMBOLS},
    }

    for hedge_label, rehedge in (("no_rehedge", False), ("daily_rehedge", True)):
        out[hedge_label] = {}
        for scen, fills in FILL_SCENARIOS.items():
            monthly, cm = run(funding, spot, perp, fills, rehedge)
            out[hedge_label][scen] = analyze(monthly, cm, mkt)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
