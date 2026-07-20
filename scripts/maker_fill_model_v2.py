#!/usr/bin/env python3
"""Maker-fill model v2 (M2) — corrected, executable-data maker/passive fill model.

READ-ONLY. Consumes the enriched shadow dataset (M1.1 coverage integrity, M1.2
spread_bps, M1.3a admission features) and answers the one open question: does a
passive/maker execution of the DEV_FADE signal clear a realistic cost, out-of-
sample, on ADMISSIBLE trades?

Fixes the auditor v6 (verdict C) critiques of the v1 midpoint-touch model:
  * ADMISSIBLE-TRADE subset only (features_json: strict_ev_allowed or not is_blocked,
    and exposure caps open_symbol/open_total) — not raw signal candidates (§3.5).
  * data_quality='ok' only — excludes sparse / partial_shutdown truncated paths (§3.4).
  * SPREAD-AWARE fill scenarios (uses shadow_path_1s.spread_bps), not midpoint touch:
      - optimistic: passive limit at f = -E is touched (min low_bps <= -E) within TIF.
      - conservative: the executable side must trade THROUGH — require the touch to
        exceed the limit by half the spread (low_bps <= -E - spread/2) (§3.1).
  * FILL-TIME aware: P&L measured from the fill second; exit clock A (signal expiry)
    or B (fixed hold from fill) (§3.2). TIF: cancel if not filled within the window.
  * PURGED nested walk-forward with an embargo of one horizon; select (E,TIF,policy)
    on train, evaluate ONCE on test (§4). Block-bootstrap CI must exclude 0.
  * Reports the auditor §8 GO bar.

Path is stored side-aware in favorable-bps f(t): +ve = toward the trade's profit.
A passive entry E bps better means the entry basis is f = -E; on fill the gross
hold-to-exit return is (f_exit + E) bps.

Usage: python3 maker_fill_model_v2.py /path/to/shadow_excursion.sqlite
Preliminary until the enriched dataset is large + multi-regime; prints coverage.
"""
from __future__ import annotations
import json
import math
import sqlite3
import sys

E_LADDER = [1, 2, 3, 4, 6]          # passive entry offsets (bps)
TIF_SEC = [1, 3, 5, 10, 30]          # cancel if not filled within this many seconds
MAX_PER_SYMBOL = 2                     # admission exposure caps (configurable)
MAX_OPEN = 5
MAKER_COST = {"optimistic": 1.0, "conservative": 4.0}   # round-trip bp by scenario


def _load(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    # schema-tolerant: spread_bps / feature_schema_version may be absent on old DBs
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(shadow_path_1s)")}
    has_spread = "spread_bps" in pcols
    obs = {}
    for o in conn.execute(
            "SELECT observation_id, symbol, regime, signal_ts_ms, data_quality, "
            "features_json FROM shadow_excursion_observations WHERE data_quality='ok' "
            "ORDER BY signal_ts_ms ASC"):
        try:
            feats = json.loads(o["features_json"]) if o["features_json"] else {}
        except Exception:
            feats = {}
        obs[o["observation_id"]] = {
            "ts": o["signal_ts_ms"], "symbol": o["symbol"], "regime": o["regime"],
            "feats": feats, "path": []}
    spread_sel = "spread_bps" if has_spread else "NULL as spread_bps"
    for r in conn.execute(
            f"SELECT observation_id, second_offset, low_bps, close_bps, {spread_sel} "
            "FROM shadow_path_1s ORDER BY observation_id, second_offset"):
        o = obs.get(r["observation_id"])
        if o is not None:
            o["path"].append((r["second_offset"], r["low_bps"], r["close_bps"],
                              r["spread_bps"]))
    conn.close()
    return list(obs.values()), has_spread


def _admissible(o):
    """Auditor §3.5: keep only signals that would actually have been opened."""
    f = o["feats"]
    if f:
        if f.get("is_blocked") is True and not f.get("strict_ev_allowed"):
            return False
        if f.get("open_symbol") is not None and f["open_symbol"] >= MAX_PER_SYMBOL:
            return False
        if f.get("open_total") is not None and f["open_total"] >= MAX_OPEN:
            return False
    return True  # old rows w/o admission features: kept (flagged in coverage)


def _sim(o, E, tif, scenario, exit_clock="A", hold_h=30):
    """Return net P&L bps for one observation under a fill scenario, or None (no fill)."""
    path = o["path"]
    if not path:
        return None
    # fill: first second within TIF where the passive limit is touched (spread-aware)
    fill_sec = None
    for (sec, low, close, spread) in path:
        if sec > tif:
            break
        thresh = -E
        if scenario == "conservative":
            thresh -= (spread if spread is not None else 0.0) * 0.5  # trade-through
        if low <= thresh:
            fill_sec = sec
            break
    if fill_sec is None:
        return None                       # cancelled — no trade (contributes 0)
    # exit: clock A = last second (signal horizon); B = fill_sec + hold_h (capped)
    last_sec = path[-1][0]
    exit_sec = last_sec if exit_clock == "A" else min(fill_sec + hold_h, last_sec)
    f_exit = next((c for (s, l, c, sp) in reversed(path) if s <= exit_sec), path[-1][2])
    gross = f_exit + E                    # entry basis -E
    return gross - MAKER_COST[scenario]


def _uncond_exp(rows, E, tif, scenario, **kw):
    """Unconditional expectancy per admissible signal (cancelled = 0)."""
    tot, n = 0.0, 0
    for o in rows:
        n += 1
        pnl = _sim(o, E, tif, scenario, **kw)
        if pnl is not None:
            tot += pnl
    return (tot / n) if n else 0.0, n


def _block_bootstrap_ci(vals, block=8):
    if len(vals) < block:
        return None
    means = sorted(sum(vals[i:i + block]) / block
                   for i in range(0, len(vals) - block + 1))
    return means[int(0.05 * len(means))], means[int(0.95 * len(means))]


def _fill_pnls(rows, E, tif, scenario, **kw):
    """P&L of FILLED trades only (for the fill count)."""
    return [p for o in rows for p in (_sim(o, E, tif, scenario, **kw),) if p is not None]


def _uncond_series(rows, E, tif, scenario, **kw):
    """Per-admissible-signal series: filled P&L, or 0 for a cancelled signal. The
    bootstrap CI runs on THIS so it measures the same quantity as the expectancy."""
    out = []
    for o in rows:
        p = _sim(o, E, tif, scenario, **kw)
        out.append(p if p is not None else 0.0)
    return out


def walk_forward(rows, scenario):
    rows = sorted(rows, key=lambda o: o["ts"])
    if len(rows) < 60:
        return {"skipped": "insufficient admissible obs", "n": len(rows)}
    cut = int(len(rows) * 0.6)
    train, test = rows[:cut], rows[cut + 5:]     # +5 obs embargo (purge overlap)
    best, bkey = None, None
    for E in E_LADDER:
        for tif in TIF_SEC:
            e, _ = _uncond_exp(train, E, tif, scenario)
            if best is None or e > best:
                best, bkey = e, (E, tif)
    E, tif = bkey
    test_exp, test_n = _uncond_exp(test, E, tif, scenario)
    fills = _fill_pnls(test, E, tif, scenario)
    ci = _block_bootstrap_ci(_uncond_series(test, E, tif, scenario))  # same quantity as exp
    return {"scenario": scenario, "E_star": E, "tif_star": tif,
            "train_exp_bps": round(best, 3), "test_exp_bps": round(test_exp, 3),
            "n_test": test_n, "n_test_fills": len(fills),
            "test_fill_rate": round(len(fills) / test_n, 3) if test_n else 0.0,
            "boot_ci_5_95": [round(ci[0], 2), round(ci[1], 2)] if ci else None,
            "GO": bool(ci and ci[0] > 0 and test_exp > 0 and len(fills) >= 200)}


def main(argv):
    if len(argv) < 2:
        print("usage: maker_fill_model_v2.py <shadow_excursion.sqlite>", file=sys.stderr)
        return 2
    obs, has_spread = _load(argv[1])
    admissible = [o for o in obs if _admissible(o)]
    with_feats = sum(1 for o in obs if o["feats"].get("strict_ev_allowed") is not None)
    out = {
        "n_obs_ok": len(obs), "n_admissible": len(admissible),
        "has_spread_column": has_spread,
        "obs_with_admission_features": with_feats,
        "note": ("PRELIMINARY — enriched (spread+admission) rows accrue only after the "
                 "M1.2/M1.3a deploy; old rows lack them. Trust results only once "
                 "obs_with_admission_features and spread coverage are large + multi-regime."),
        "regimes": _tally(admissible),
        "walk_forward": {s: walk_forward(admissible, s)
                         for s in ("optimistic", "conservative")},
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
