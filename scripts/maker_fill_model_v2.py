#!/usr/bin/env python3
"""Maker-fill model v2 (M2) — corrected, executable-data maker/passive fill model.

READ-ONLY. Consumes the enriched shadow dataset (M1.1 coverage integrity, M1.2
spread_bps, M1.3a admission features) and answers the one open question: does a
passive/maker execution of DEV_FADE clear a realistic cost, out-of-sample, on
ADMISSIBLE trades?

Addresses external audit v6 (verdict C) critiques of the v1 midpoint-touch model.

⚠️ EXECUTABILITY DISCLOSURE (audit §3.1): `shadow_path_1s.low_bps` is derived from
the recorder's MIDPOINT favorable-bps path. So:
  * "midpoint" scenario = passive limit touched at midpoint = the v1 upper bound,
    NOT executable — reported only as an optimistic ceiling.
  * "conservative" scenario subtracts spread/2 (≈ the bid/ask side must trade
    through) using the recorded `spread_bps` — an executable LOWER bound.
  * The truth is between; a precise executable fill needs aggTrade (M1.3b). The GO
    decision is taken on the CONSERVATIVE (executable) scenario only.

Path is side-aware favorable-bps f(t): +ve = toward the trade's profit. A passive
entry E bps better has entry basis f=-E; on fill the gross hold-to-exit = f_exit+E.

Usage: python3 maker_fill_model_v2.py /path/to/shadow_excursion.sqlite
PRELIMINARY until the enriched dataset is large + multi-regime; prints coverage,
and the GO gate is hard-locked off unless coverage/regime/fill thresholds are met.

Memory: each ok observation can hold up to horizon_s (default 300) 1s path rows, so
weeks of observe-mode recording is millions of rows. The loader counts coverage over
ALL ok observations but only MATERIALISES paths for the most-recent MFM2_MAX_OBS
admissible ones (compact arrays), so a run on the live box (shared with the bot) stays
memory-bounded instead of being OOM-killed. Truncation is reported, never silent.
"""
from __future__ import annotations
import array
import json
import os
import random
import sqlite3
import sys

E_LADDER = [1, 2, 3, 4, 6]                 # passive entry offsets (bps)
TIF_SEC = [1, 3, 5, 10, 30]                # cancel if unfilled within this many seconds (inclusive)
EXIT_POLICIES = [("A", None), ("B", 30), ("B", 60)]  # A: signal expiry; B: fixed hold from fill
MAKER_COST = {"midpoint": 1.0, "conservative": 4.0}  # round-trip bp by scenario
MAX_OBS = int(os.getenv("MFM2_MAX_OBS", "15000"))    # cap materialised obs (memory bound, shared box)
# GO hard gates (audit §8) — GO can only be True if ALL are met:
GO_MIN_FILLS = 200
GO_MIN_ADMISSION_FRAC = 0.8   # most obs must carry admission features (not legacy rows)
GO_MIN_REGIMES = 2
GO_MIN_PF = 1.20              # auditor §8: OOS profit factor
GO_MAX_SYMBOL_SHARE = 0.50    # auditor §8: no single symbol > 50% of gross profit


def _admissible_feats(f):
    """Audit §3.5: keep only signals the live bot would actually have opened. Trust
    the RECORDED decision (is_blocked / strict_ev_allowed) — do not re-derive caps
    (an analyst guess could diverge from the bot's live config). Legacy rows without
    admission features are kept but counted separately in coverage."""
    if "is_blocked" in f or "strict_ev_allowed" in f:
        return bool(f.get("strict_ev_allowed")) or not bool(f.get("is_blocked"))
    return True


def _load(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA cache_size=-8000")  # ~8MB page cache — the DB shares a small box with the bot
    except sqlite3.Error:
        pass
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(shadow_path_1s)")}
    has_spread = "spread_bps" in pcols

    # Pass 1 — observation METADATA only (no path rows). Coverage counts run over ALL
    # ok observations; only the most-recent MAX_OBS ADMISSIBLE ones are kept for
    # simulation, so Pass 2 stays memory-bounded (see module docstring).
    n_ok = with_feats = n_admissible = 0
    regimes = {}
    keep = {}
    for row in conn.execute(
            "SELECT observation_id, symbol, regime, signal_ts_ms, horizon_ms, features_json "
            "FROM shadow_excursion_observations WHERE data_quality='ok' "
            "ORDER BY signal_ts_ms DESC"):
        n_ok += 1
        try:
            feats = json.loads(row["features_json"]) if row["features_json"] else {}
        except Exception:
            feats = {}
        if feats.get("strict_ev_allowed") is not None:
            with_feats += 1
        if not _admissible_feats(feats):
            continue
        n_admissible += 1
        regimes[row["regime"]] = regimes.get(row["regime"], 0) + 1
        if len(keep) < MAX_OBS:
            keep[row["observation_id"]] = {
                "ts": row["signal_ts_ms"], "symbol": row["symbol"],
                "regime": row["regime"], "horizon_ms": row["horizon_ms"],
                "sec": array.array("i"), "low": array.array("d"),
                "close": array.array("d"), "spread": array.array("d")}

    # Pass 2 — path rows for the KEPT observations only. JOIN to data_quality='ok'
    # (and floor on the oldest kept ts) so SQLite yields far fewer rows storage-side;
    # PK(observation_id, second_offset) satisfies the ORDER BY with no temp sort.
    if keep:
        ts_floor = min(o["ts"] for o in keep.values())
        spread_col = "p.spread_bps" if has_spread else "NULL"
        for r in conn.execute(
                f"SELECT p.observation_id AS oid, p.second_offset AS so, p.low_bps AS lo, "
                f"p.close_bps AS cl, {spread_col} AS sp "
                "FROM shadow_path_1s p JOIN shadow_excursion_observations o "
                "ON o.observation_id = p.observation_id "
                "WHERE o.data_quality='ok' AND o.signal_ts_ms >= ? "
                "ORDER BY p.observation_id, p.second_offset", (ts_floor,)):
            o = keep.get(r["oid"])
            if o is None:
                continue
            o["sec"].append(int(r["so"]))
            o["low"].append(float(r["lo"]) if r["lo"] is not None else 0.0)
            o["close"].append(float(r["cl"]) if r["cl"] is not None else 0.0)
            sp = r["sp"]
            o["spread"].append(float(sp) if sp is not None else float("nan"))
    conn.close()

    coverage = {
        "n_obs_ok": n_ok, "with_feats": with_feats, "n_admissible": n_admissible,
        "n_loaded": len(keep), "truncated": n_admissible > len(keep),
        "admission_frac": round((with_feats / n_ok), 3) if n_ok else 0.0,
        "regimes": dict(sorted(regimes.items(), key=lambda kv: -kv[1])[:8]),
    }
    return list(keep.values()), has_spread, coverage


def _sim(o, E, tif, scenario, exit_clock="A", hold_h=None):
    """Net P&L bps for one observation, or None (no fill within TIF)."""
    sec, low, close, spread = o["sec"], o["low"], o["close"], o["spread"]
    n = len(sec)
    if n == 0:
        return None
    fill_i = None
    for i in range(n):
        if sec[i] > tif:
            break
        thresh = -E
        if scenario == "conservative":
            sp = spread[i]
            thresh -= (sp if sp == sp else 0.0) * 0.5   # sp != sp -> NaN (missing spread)
        if low[i] <= thresh:
            fill_i = i
            break
    if fill_i is None:
        return None
    last_sec = sec[n - 1]
    exit_sec = last_sec if exit_clock == "A" else min(sec[fill_i] + (hold_h or 0), last_sec)
    f_exit = close[n - 1]
    for j in range(n - 1, -1, -1):
        if sec[j] <= exit_sec:
            f_exit = close[j]
            break
    return (f_exit + E) - MAKER_COST[scenario]


def _uncond_series(rows, E, tif, scenario, exit_clock, hold_h):
    """Per-admissible-signal series: filled P&L, or 0 for a cancelled signal."""
    out = []
    for o in rows:
        p = _sim(o, E, tif, scenario, exit_clock, hold_h)
        out.append(p if p is not None else 0.0)
    return out


def _fill_details(rows, E, tif, scenario, exit_clock, hold_h):
    """(symbol, pnl) for every FILLED test trade — for PF + symbol concentration."""
    out = []
    for o in rows:
        p = _sim(o, E, tif, scenario, exit_clock, hold_h)
        if p is not None:
            out.append((o["symbol"], p))
    return out


def _profit_factor(pnls):
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    if gl <= 0:
        return float("inf") if gw > 0 else 0.0
    return gw / gl


def _max_symbol_profit_share(details):
    """Largest single symbol's share of gross PROFIT (auditor §8: must be ≤ 0.5)."""
    by_sym = {}
    for sym, p in details:
        if p > 0:
            by_sym[sym] = by_sym.get(sym, 0.0) + p
    tot = sum(by_sym.values())
    return (max(by_sym.values()) / tot) if tot > 0 else 1.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _block_bootstrap_ci(vals, block=8, B=2000, seed=12345, lo=0.05, hi=0.95):
    """Moving-block bootstrap CI of the MEAN (preserves autocorrelation). Resamples
    ceil(n/block) blocks WITH REPLACEMENT to a length-n series, B times; returns the
    (lo,hi) percentiles of the bootstrap means. Shrinks with n (a real CI), unlike a
    percentile of block means. Deterministic via seed."""
    n = len(vals)
    if n < block * 2:
        return None
    rng = random.Random(seed)
    starts = list(range(0, n - block + 1))
    nblocks = -(-n // block)
    means = []
    for _ in range(B):
        acc = []
        for _b in range(nblocks):
            s = rng.choice(starts)
            acc.extend(vals[s:s + block])
        acc = acc[:n]
        means.append(sum(acc) / len(acc))
    means.sort()
    return means[int(lo * B)], means[int(hi * B)]


def walk_forward(rows, scenario, has_spread):
    if scenario == "conservative" and not has_spread:
        return {"scenario": scenario, "skipped": "no spread_bps column — conservative "
                "(executable) scenario needs it"}
    rows = sorted(rows, key=lambda o: o["ts"])
    if len(rows) < 80:
        return {"scenario": scenario, "skipped": "insufficient admissible obs", "n": len(rows)}
    cut = int(len(rows) * 0.6)
    # HORIZON-AWARE embargo: drop test obs whose signal starts within one horizon
    # (+ max hold) of the train/test boundary timestamp, so no test path overlaps train.
    boundary_ts = rows[cut - 1]["ts"]
    max_hold_ms = max((h or 0) for _, h in EXIT_POLICIES) * 1000
    embargo_ms = (rows[cut - 1]["horizon_ms"] or 0) + max_hold_ms
    train = rows[:cut]
    test = [o for o in rows[cut:] if o["ts"] - boundary_ts >= embargo_ms]
    if len(test) < 30:
        return {"scenario": scenario, "skipped": "insufficient test obs after embargo",
                "n_train": len(train), "n_test": len(test)}
    # select (E, TIF, exit policy) on TRAIN only
    best, bkey = None, None
    for E in E_LADDER:
        for tif in TIF_SEC:
            for (ec, hh) in EXIT_POLICIES:
                e = _mean(_uncond_series(train, E, tif, scenario, ec, hh))
                if best is None or e > best:
                    best, bkey = e, (E, tif, ec, hh)
    E, tif, ec, hh = bkey
    test_series = _uncond_series(test, E, tif, scenario, ec, hh)
    test_exp = _mean(test_series)
    details = _fill_details(test, E, tif, scenario, ec, hh)
    nf = len(details)
    ci = _block_bootstrap_ci(test_series)
    pf = _profit_factor([p for _, p in details])
    sym_share = _max_symbol_profit_share(details)
    return {"scenario": scenario, "E_star": E, "tif_star": tif,
            "exit_clock": ec, "hold_h": hh,
            "train_exp_bps": round(best, 3), "test_exp_bps": round(test_exp, 3),
            "n_test": len(test), "n_test_fills": nf,
            "test_fill_rate": round(nf / len(test), 3) if test else 0.0,
            "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            "max_symbol_profit_share": round(sym_share, 3),
            "boot_ci_5_95": [round(ci[0], 2), round(ci[1], 2)] if ci else None}


def main(argv):
    if len(argv) < 2:
        print("usage: maker_fill_model_v2.py <shadow_excursion.sqlite>", file=sys.stderr)
        return 2
    admissible, has_spread, cov = _load(argv[1])
    regimes = cov["regimes"]
    admission_frac = cov["admission_frac"]
    wf = {s: walk_forward(admissible, s, has_spread) for s in ("midpoint", "conservative")}

    # GO is taken on the CONSERVATIVE (executable) scenario ONLY, and hard-gated on
    # coverage so a thin / legacy / single-regime dataset can never print GO: true.
    cons = wf.get("conservative", {})
    ci = cons.get("boot_ci_5_95")
    coverage_ok = (has_spread and admission_frac >= GO_MIN_ADMISSION_FRAC
                   and len(regimes) >= GO_MIN_REGIMES)
    _pf = cons.get("profit_factor", 0)
    _pf_ok = (_pf == "inf") or (isinstance(_pf, (int, float)) and _pf >= GO_MIN_PF)
    go = bool(coverage_ok and ci and ci[0] > 0
              and cons.get("test_exp_bps", -1) > 0
              and cons.get("n_test_fills", 0) >= GO_MIN_FILLS
              and _pf_ok
              and cons.get("max_symbol_profit_share", 1.0) <= GO_MAX_SYMBOL_SHARE)
    out = {
        "n_obs_ok": cov["n_obs_ok"], "n_admissible": cov["n_admissible"],
        "n_loaded_for_sim": cov["n_loaded"], "sim_truncated_to_recent": cov["truncated"],
        "max_obs_cap": MAX_OBS,
        "has_spread_column": has_spread,
        "obs_with_admission_features": cov["with_feats"],
        "admission_feature_fraction": admission_frac,
        "regimes": regimes,
        "coverage_ok_for_GO": coverage_ok,
        "GO": go,
        "GO_basis": "conservative (executable) scenario, hard-gated on coverage",
        "note": ("PRELIMINARY. Enriched (spread+admission) rows accrue only after the "
                 "M1.2/M1.3a deploy; legacy rows lack them and are kept but flagged. "
                 "Paths are materialised for at most MFM2_MAX_OBS=%d most-recent "
                 "admissible obs (memory bound on the shared live box; "
                 "sim_truncated_to_recent flags when older obs were dropped). GO is "
                 "locked off unless has_spread AND admission_fraction>=%.2f AND regimes>=%d "
                 "AND >=%d conservative OOS fills AND CI lower>0. 'midpoint' is a non-"
                 "executable ceiling; aggTrade (M1.3b) needed for a precise base scenario."
                 % (MAX_OBS, GO_MIN_ADMISSION_FRAC, GO_MIN_REGIMES, GO_MIN_FILLS)),
        "walk_forward": wf,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
