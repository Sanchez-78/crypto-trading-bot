#!/usr/bin/env python3
"""Maker/passive-fill counterfactual for DEV_FADE, run against the shadow dataset.

READ-ONLY. Answers the one open strategy question: does the tiny (~1 bp) DEV_FADE
edge survive *passive* (maker) execution once adverse selection is priced in?

Data model (see shadow_excursion_recorder.py): every recorded observation stores
the 1-second path in SIGNED favorable-direction bps (side-aware):
  f(t) = +ve  → price moved toward the trade's profit
         -ve  → price moved against it
So we can reason entirely in favorable-bps space, no BUY/SELL split.

Execution models compared, per passive entry offset E (bps better than reference):
  * TAKER-both        : enter at f=0 immediately, exit at horizon. gross = F_hz.
  * MAKER-entry/taker-exit (PRIMARY, realistic): post a passive limit E bps better,
    i.e. it fills ONLY if the path first reaches f <= -E (price moved E against you).
    On fill the entry basis is -E, so hold-to-horizon gross = F_hz + E.
    Unfilled observations = no trade (0 P&L) — this is the adverse-selection cost:
    you systematically MISS the ones that reverted immediately (the easy winners)
    and only catch the ones that first went against you.

For each E we report: fill rate, gross expectancy of FILLED trades, the
adverse-selection gap (filled-subset outcome vs the full-sample outcome), and the
UNCONDITIONAL expectancy (unfilled counted as 0) across a round-trip cost sweep.
Finally a time-based walk-forward: pick E* on TRAIN, evaluate ONCE on TEST.

Caveats (must be read with the numbers): passive EXIT is not modelled (exit is
taker/hold-to-horizon) — modelling passive exit too would be more optimistic, not
less. Dataset is small and regime-skewed; treat as directional, not a verdict.

Usage: python3 maker_fill_model.py /path/to/shadow_excursion.sqlite
"""
from __future__ import annotations
import json
import sqlite3
import sys

E_LADDER = list(range(0, 13))          # passive entry offsets in bps (0..12)
COST_SWEEP = [0, 1, 2, 3, 4, 5, 18]    # round-trip cost in bps
MAKER_COST_FOR_SELECTION = 3           # cost used to pick E* in the walk-forward


def _load(db_path: str):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    obs = conn.execute(
        """SELECT observation_id, symbol, side, regime, signal_ts_ms
             FROM shadow_excursion_observations
            WHERE data_quality = 'ok'
            ORDER BY signal_ts_ms ASC"""
    ).fetchall()
    # Aggregate the path per observation in one pass: horizon close (last second),
    # min low (max adverse), max high (max favorable).
    path = {}
    for r in conn.execute(
        """SELECT observation_id, second_offset, low_bps, high_bps, close_bps
             FROM shadow_path_1s ORDER BY observation_id, second_offset"""
    ):
        oid = r["observation_id"]
        p = path.get(oid)
        if p is None:
            path[oid] = {"min_low": r["low_bps"], "max_high": r["high_bps"],
                         "last_close": r["close_bps"], "last_sec": r["second_offset"]}
        else:
            if r["low_bps"] < p["min_low"]:
                p["min_low"] = r["low_bps"]
            if r["high_bps"] > p["max_high"]:
                p["max_high"] = r["high_bps"]
            if r["second_offset"] >= p["last_sec"]:
                p["last_sec"] = r["second_offset"]
                p["last_close"] = r["close_bps"]
    conn.close()

    rows = []
    for o in obs:
        p = path.get(o["observation_id"])
        if not p:
            continue
        rows.append({
            "ts": o["signal_ts_ms"], "symbol": o["symbol"], "regime": o["regime"],
            "F": float(p["last_close"]),          # favorable bps at horizon
            "min_low": float(p["min_low"]),        # most-adverse bps reached
            "max_high": float(p["max_high"]),      # most-favorable bps reached
        })
    return rows


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _stats_for_E(rows, E):
    """Return fill-rate + gross filled/all expectancy for a passive offset E."""
    filled_F = [r["F"] for r in rows if r["min_low"] <= -E]  # fills iff price hit -E
    n = len(rows)
    fr = len(filled_F) / n if n else 0.0
    filled_gross = _mean(filled_F) + E if filled_F else 0.0   # entry basis -E
    all_F = _mean([r["F"] for r in rows])
    return {
        "E": E,
        "fill_rate": round(fr, 4),
        "n_filled": len(filled_F),
        "filled_horizon_F_mean": round(_mean(filled_F), 3) if filled_F else None,
        "all_horizon_F_mean": round(all_F, 3),
        # adverse selection: filled subset's raw F vs full-sample F (negative = adverse)
        "adverse_selection_bps": round(_mean(filled_F) - all_F, 3) if filled_F else None,
        "filled_gross_pnl_bps": round(filled_gross, 3) if filled_F else None,
    }


def _uncond_exp(rows, E, cost):
    """Unconditional expectancy: unfilled obs contribute 0 P&L."""
    tot = 0.0
    for r in rows:
        if r["min_low"] <= -E:                 # filled
            tot += (r["F"] + E) - cost
        # else: no trade, 0
    return tot / len(rows) if rows else 0.0


def _taker_exp(rows, cost):
    return _mean([r["F"] - cost for r in rows])


def analyze(rows):
    out = {"n_observations": len(rows)}
    if not rows:
        out["error"] = "no observations"
        return out

    out["horizon_F_mean_bps"] = round(_mean([r["F"] for r in rows]), 3)
    out["regimes"] = _tally(rows, "regime")
    out["symbols"] = _tally(rows, "symbol")

    # Baseline taker (sanity: at cost=18 should reproduce the known NO-GO).
    out["taker_expectancy_by_cost"] = {c: round(_taker_exp(rows, c), 3) for c in COST_SWEEP}

    # Per-E fill / adverse-selection table.
    out["by_offset"] = [_stats_for_E(rows, E) for E in E_LADDER]

    # Unconditional maker-entry expectancy: E × cost grid.
    grid = {}
    for E in E_LADDER:
        grid[E] = {c: round(_uncond_exp(rows, E, c), 3) for c in COST_SWEEP}
    out["maker_uncond_expectancy_grid"] = grid

    # Best unconditional expectancy per cost (over all E), for a quick read.
    best = {}
    for c in COST_SWEEP:
        bE, bV = max(((E, grid[E][c]) for E in E_LADDER), key=lambda kv: kv[1])
        best[c] = {"best_E": bE, "expectancy_bps": bV}
    out["best_maker_by_cost"] = best

    # Time-based walk-forward: pick E* on train at a realistic maker cost, test once.
    out["walk_forward"] = _walk_forward(rows)
    return out


def _walk_forward(rows):
    rows = sorted(rows, key=lambda r: r["ts"])
    cut = int(len(rows) * 0.6)
    train, test = rows[:cut], rows[cut:]
    if len(train) < 30 or len(test) < 30:
        return {"skipped": "insufficient train/test size", "n_train": len(train), "n_test": len(test)}
    c = MAKER_COST_FOR_SELECTION
    Estar, _ = max(((E, _uncond_exp(train, E, c)) for E in E_LADDER), key=lambda kv: kv[1])
    res = {
        "selection_cost_bps": c, "E_star": Estar,
        "n_train": len(train), "n_test": len(test),
        "train_expectancy_bps": round(_uncond_exp(train, Estar, c), 3),
        "test_expectancy_bps": round(_uncond_exp(test, Estar, c), 3),
        "test_fill_rate": round(sum(1 for r in test if r["min_low"] <= -Estar) / len(test), 4),
    }
    # Also report OOS test at zero and full-taker cost for context.
    res["test_expectancy_at_cost0_bps"] = round(_uncond_exp(test, Estar, 0), 3)
    res["test_expectancy_at_cost18_bps"] = round(_uncond_exp(test, Estar, 18), 3)
    res["verdict"] = "positive-OOS" if res["test_expectancy_bps"] > 0 else "NO-GO-OOS"
    return res


def _tally(rows, key):
    d = {}
    for r in rows:
        d[r[key]] = d.get(r[key], 0) + 1
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:8])


def main(argv):
    if len(argv) < 2:
        print("usage: maker_fill_model.py <shadow_excursion.sqlite>", file=sys.stderr)
        return 2
    rows = _load(argv[1])
    print(json.dumps(analyze(rows), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
