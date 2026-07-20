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
"""
from __future__ import annotations
import json
import random
import sqlite3
import sys

E_LADDER = [1, 2, 3, 4, 6]                 # passive entry offsets (bps)
TIF_SEC = [1, 3, 5, 10, 30]                # cancel if unfilled within this many seconds (inclusive)
EXIT_POLICIES = [("A", None), ("B", 30), ("B", 60)]  # A: signal expiry; B: fixed hold from fill
MAKER_COST = {"midpoint": 1.0, "conservative": 4.0}  # round-trip bp by scenario
# GO hard gates (audit §8) — GO can only be True if ALL are met:
GO_MIN_FILLS = 200
GO_MIN_ADMISSION_FRAC = 0.8   # most obs must carry admission features (not legacy rows)
GO_MIN_REGIMES = 2


def _load(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(shadow_path_1s)")}
    has_spread = "spread_bps" in pcols
    obs = {}
    for o in conn.execute(
            "SELECT observation_id, symbol, regime, side, signal_ts_ms, horizon_ms, "
            "features_json FROM shadow_excursion_observations WHERE data_quality='ok' "
            "ORDER BY signal_ts_ms ASC"):
        try:
            feats = json.loads(o["features_json"]) if o["features_json"] else {}
        except Exception:
            feats = {}
        obs[o["observation_id"]] = {
            "ts": o["signal_ts_ms"], "symbol": o["symbol"], "regime": o["regime"],
            "horizon_ms": o["horizon_ms"], "feats": feats, "path": []}
    spread_sel = "spread_bps" if has_spread else "NULL as spread_bps"
    for r in conn.execute(
            f"SELECT observation_id, second_offset, low_bps, close_bps, {spread_sel} "
            "FROM shadow_path_1s ORDER BY observation_id, second_offset"):
        o = obs.get(r["observation_id"])
        if o is not None:
            o["path"].append((r["second_offset"], r["low_bps"], r["close_bps"], r["spread_bps"]))
    conn.close()
    return list(obs.values()), has_spread


def _admissible(o):
    """Audit §3.5: keep only signals the live bot would actually have opened. Trust
    the RECORDED decision (is_blocked / strict_ev_allowed) — do not re-derive caps
    (an analyst guess could diverge from the bot's live config). Legacy rows without
    admission features are kept but counted separately in coverage."""
    f = o["feats"]
    if "is_blocked" in f or "strict_ev_allowed" in f:
        return bool(f.get("strict_ev_allowed")) or not bool(f.get("is_blocked"))
    return True


def _sim(o, E, tif, scenario, exit_clock="A", hold_h=None):
    """Net P&L bps for one observation, or None (no fill within TIF)."""
    path = o["path"]
    if not path:
        return None
    fill_sec = None
    for (sec, low, close, spread) in path:
        if sec > tif:
            break
        thresh = -E
        if scenario == "conservative":
            thresh -= (spread if spread is not None else 0.0) * 0.5
        if low <= thresh:
            fill_sec = sec
            break
    if fill_sec is None:
        return None
    last_sec = path[-1][0]
    exit_sec = last_sec if exit_clock == "A" else min(fill_sec + (hold_h or 0), last_sec)
    f_exit = next((c for (s, l, c, sp) in reversed(path) if s <= exit_sec), path[-1][2])
    return (f_exit + E) - MAKER_COST[scenario]


def _uncond_series(rows, E, tif, scenario, exit_clock, hold_h):
    """Per-admissible-signal series: filled P&L, or 0 for a cancelled signal."""
    out = []
    for o in rows:
        p = _sim(o, E, tif, scenario, exit_clock, hold_h)
        out.append(p if p is not None else 0.0)
    return out


def _n_fills(rows, E, tif, scenario, exit_clock, hold_h):
    return sum(1 for o in rows
               if _sim(o, E, tif, scenario, exit_clock, hold_h) is not None)


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
    nf = _n_fills(test, E, tif, scenario, ec, hh)
    ci = _block_bootstrap_ci(test_series)
    return {"scenario": scenario, "E_star": E, "tif_star": tif,
            "exit_clock": ec, "hold_h": hh,
            "train_exp_bps": round(best, 3), "test_exp_bps": round(test_exp, 3),
            "n_test": len(test), "n_test_fills": nf,
            "test_fill_rate": round(nf / len(test), 3) if test else 0.0,
            "boot_ci_5_95": [round(ci[0], 2), round(ci[1], 2)] if ci else None}


def main(argv):
    if len(argv) < 2:
        print("usage: maker_fill_model_v2.py <shadow_excursion.sqlite>", file=sys.stderr)
        return 2
    obs, has_spread = _load(argv[1])
    admissible = [o for o in obs if _admissible(o)]
    with_feats = sum(1 for o in obs if o["feats"].get("strict_ev_allowed") is not None)
    regimes = _tally(admissible)
    admission_frac = (with_feats / len(obs)) if obs else 0.0
    wf = {s: walk_forward(admissible, s, has_spread) for s in ("midpoint", "conservative")}

    # GO is taken on the CONSERVATIVE (executable) scenario ONLY, and hard-gated on
    # coverage so a thin / legacy / single-regime dataset can never print GO: true.
    cons = wf.get("conservative", {})
    ci = cons.get("boot_ci_5_95")
    coverage_ok = (has_spread and admission_frac >= GO_MIN_ADMISSION_FRAC
                   and len(regimes) >= GO_MIN_REGIMES)
    go = bool(coverage_ok and ci and ci[0] > 0
              and cons.get("test_exp_bps", -1) > 0
              and cons.get("n_test_fills", 0) >= GO_MIN_FILLS)
    out = {
        "n_obs_ok": len(obs), "n_admissible": len(admissible),
        "has_spread_column": has_spread,
        "obs_with_admission_features": with_feats,
        "admission_feature_fraction": round(admission_frac, 3),
        "regimes": regimes,
        "coverage_ok_for_GO": coverage_ok,
        "GO": go,
        "GO_basis": "conservative (executable) scenario, hard-gated on coverage",
        "note": ("PRELIMINARY. Enriched (spread+admission) rows accrue only after the "
                 "M1.2/M1.3a deploy; legacy rows lack them and are kept but flagged. GO "
                 "is locked off unless has_spread AND admission_fraction>=%.2f AND regimes>=%d "
                 "AND >=%d conservative OOS fills AND CI lower>0. 'midpoint' is a non-"
                 "executable ceiling; aggTrade (M1.3b) needed for a precise base scenario."
                 % (GO_MIN_ADMISSION_FRAC, GO_MIN_REGIMES, GO_MIN_FILLS)),
        "walk_forward": wf,
    }
    print(json.dumps(out, indent=2))
    return 0


def _tally(rows):
    d = {}
    for o in rows:
        d[o["regime"]] = d.get(o["regime"], 0) + 1
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:8])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
