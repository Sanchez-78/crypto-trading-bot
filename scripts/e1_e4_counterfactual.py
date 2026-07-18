#!/usr/bin/env python3
"""E1–E4 offline TP/SL counterfactual over the F8b shadow observation dataset.

External audit v5 §5.3/§10. Given the shadow_excursion.sqlite that the
observation-only recorder fills (shadow_excursion_observations / shadow_path_1s /
shadow_first_crossing), this sweeps candidate (TP, SL) barrier pairs from the
first-crossing ladder and, using a TIME-BASED walk-forward split, produces a
GO / NO-GO verdict on whether ANY configuration has a validated out-of-sample edge.

Counterfactual per observation, per (tp_bps, sl_bps): whichever barrier the price
crossed FIRST determines the outcome (+tp if favorable-first, −sl if adverse-first);
if neither is crossed within the horizon it is a TIMEOUT closing at the realized
favorable-direction bps of the last 1s bucket. A round-trip cost (bps) is charged
to every trade.

Auditor gates (all must hold to return GO):
  * ≥ MIN_OBS observations (default 200) and ≥ MIN_SEG per primary segment;
  * OOS (untouched test split) profit factor ≥ 1.20;
  * OOS expectancy > 0 after the full cost (default 18 bps), AND still ≥ 0 under a
    stress cost (default 25 bps);
  * 95% bootstrap CI of OOS expectancy not clearly negative (lower bound > 0);
  * no single symbol > 40% of OOS gross profit, no hour > 40%, no regime > 50%.

Nothing here trades, deploys, or mutates state — it only READS the shadow sqlite
and prints a report. Deterministic (fixed RNG seed) for reproducibility.

Usage:  python3 scripts/e1_e4_counterfactual.py [db_path] [--json]
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DB = "local_learning_storage/shadow_excursion.sqlite"
COST_BPS = 18.0
STRESS_COST_BPS = 25.0
MIN_OBS = 200
MIN_SEG = 30
PF_GATE = 1.20
MAX_SYMBOL_SHARE = 0.40
MAX_HOUR_SHARE = 0.40
MAX_REGIME_SHARE = 0.50
BOOTSTRAP_N = 2000
SEED = 12345


class Observation:
    __slots__ = ("oid", "symbol", "side", "regime", "signal_ts_ms", "hour",
                 "first_cross", "final_close_bps", "data_quality")

    def __init__(self, oid, symbol, side, regime, signal_ts_ms, first_cross,
                 final_close_bps, data_quality):
        self.oid = oid
        self.symbol = symbol
        self.side = side
        self.regime = regime
        self.signal_ts_ms = signal_ts_ms
        self.hour = int((signal_ts_ms // 3_600_000) % 24)
        self.first_cross = first_cross          # {("fav"|"adv", level_bps): ms}
        self.final_close_bps = final_close_bps
        self.data_quality = data_quality


def load_observations(db_path: str, require_quality_ok: bool = True) -> List[Observation]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        c = conn.cursor()
        obs_rows = c.execute(
            "SELECT observation_id, symbol, side, regime, signal_ts_ms, data_quality "
            "FROM shadow_excursion_observations WHERE completed=1").fetchall()
        crossings: Dict[str, Dict[Tuple[str, int], int]] = defaultdict(dict)
        for oid, d, lvl, ms in c.execute(
                "SELECT observation_id, direction, level_bps, first_cross_ms "
                "FROM shadow_first_crossing"):
            crossings[oid][(d, int(lvl))] = int(ms)
        finals: Dict[str, float] = {}
        for oid, close_bps in c.execute(
                "SELECT observation_id, close_bps FROM shadow_path_1s p1 "
                "WHERE second_offset = (SELECT MAX(second_offset) FROM shadow_path_1s p2 "
                "WHERE p2.observation_id = p1.observation_id)"):
            finals[oid] = float(close_bps)
    finally:
        conn.close()

    out: List[Observation] = []
    for oid, symbol, side, regime, ts, dq in obs_rows:
        if require_quality_ok and dq != "ok":
            continue
        out.append(Observation(oid, symbol, side or "?", regime or "?", int(ts),
                               crossings.get(oid, {}), finals.get(oid, 0.0), dq))
    out.sort(key=lambda o: o.signal_ts_ms)   # chronological for walk-forward
    return out


def ladder_levels(observations: List[Observation]) -> List[int]:
    lv = set()
    for o in observations:
        for (_d, lvl) in o.first_cross:
            lv.add(lvl)
    return sorted(lv)


def simulate(o: Observation, tp: int, sl: int, cost: float) -> float:
    """Net favorable-direction bps for one observation under (tp, sl), after cost.
    First-crossing semantics; TIMEOUT closes at the realized final bps."""
    fav = o.first_cross.get(("fav", tp))
    adv = o.first_cross.get(("adv", sl))
    if fav is not None and adv is not None:
        gross = float(tp) if fav <= adv else float(-sl)
    elif fav is not None:
        gross = float(tp)
    elif adv is not None:
        gross = float(-sl)
    else:
        gross = o.final_close_bps
    return gross - cost


def evaluate(observations: List[Observation], tp: int, sl: int, cost: float) -> Dict[str, Any]:
    outcomes = [simulate(o, tp, sl, cost) for o in observations]
    n = len(outcomes)
    if n == 0:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "expectancy_bps": 0.0, "sum_bps": 0.0}
    wins = [x for x in outcomes if x > 0]
    losses = [x for x in outcomes if x < 0]
    gp, gl = sum(wins), -sum(losses)
    return {
        "n": n,
        "wr": len(wins) / n,
        "pf": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0),
        "expectancy_bps": sum(outcomes) / n,
        "sum_bps": sum(outcomes),
    }


def _bootstrap_ci(observations: List[Observation], tp: int, sl: int, cost: float,
                  n_boot: int = BOOTSTRAP_N) -> Tuple[float, float]:
    outcomes = [simulate(o, tp, sl, cost) for o in observations]
    if not outcomes:
        return (0.0, 0.0)
    rng = random.Random(SEED)
    m = len(outcomes)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(m):
            s += outcomes[rng.randrange(m)]
        means.append(s / m)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[min(int(0.975 * n_boot), n_boot - 1)]
    return (lo, hi)


def _concentration(observations: List[Observation], tp: int, sl: int, cost: float,
                   key) -> Tuple[float, Dict[str, float]]:
    """Share of total GROSS PROFIT (positive outcomes only) held by the top bucket."""
    by: Dict[str, float] = defaultdict(float)
    total = 0.0
    for o in observations:
        x = simulate(o, tp, sl, cost)
        if x > 0:
            by[str(key(o))] += x
            total += x
    if total <= 0:
        return (0.0, {})
    shares = {k: v / total for k, v in by.items()}
    return (max(shares.values()), shares)


def walk_forward(observations: List[Observation], cost: float = COST_BPS,
                 stress_cost: float = STRESS_COST_BPS,
                 split: Tuple[float, float] = (0.6, 0.2)) -> Dict[str, Any]:
    """Time-based train/validation/test. Select the (tp, sl) with the best
    train+validation expectancy, then evaluate it ONCE on the untouched test split."""
    levels = ladder_levels(observations)
    n = len(observations)
    result: Dict[str, Any] = {"n_total": n, "levels": levels, "verdict": "NO-GO",
                              "reasons": []}
    if n < MIN_OBS:
        result["reasons"].append(f"insufficient observations: {n} < {MIN_OBS}")
        return result
    if len(levels) < 1:
        result["reasons"].append("no first-crossing ladder levels present")
        return result

    n_train = int(split[0] * n)
    n_val = int(split[1] * n)
    train, val, test = (observations[:n_train],
                        observations[n_train:n_train + n_val],
                        observations[n_train + n_val:])
    dev = train + val   # selection set (in-sample); test stays untouched

    best = None
    for tp in levels:
        for sl in levels:
            e = evaluate(dev, tp, sl, cost)
            if e["n"] == 0:
                continue
            if best is None or e["expectancy_bps"] > best[2]["expectancy_bps"]:
                best = (tp, sl, e)
    if best is None:
        result["reasons"].append("no evaluable (tp, sl) pair")
        return result
    tp, sl, dev_eval = best

    oos = evaluate(test, tp, sl, cost)
    oos_stress = evaluate(test, tp, sl, stress_cost)
    ci_lo, ci_hi = _bootstrap_ci(test, tp, sl, cost)
    sym_share, sym_map = _concentration(test, tp, sl, cost, lambda o: o.symbol)
    hour_share, _ = _concentration(test, tp, sl, cost, lambda o: o.hour)
    regime_share, _ = _concentration(test, tp, sl, cost, lambda o: o.regime)

    # per-segment sample sufficiency on the FULL dataset (by symbol): every symbol
    # we would trade needs enough total support to trust its contribution.
    seg_counts: Dict[str, int] = defaultdict(int)
    for o in observations:
        seg_counts[o.symbol] += 1
    thin_segments = sorted(s for s, c in seg_counts.items() if c < MIN_SEG)

    reasons: List[str] = []
    if oos["n"] < MIN_SEG:
        reasons.append(f"test split too small: {oos['n']} < {MIN_SEG}")
    if thin_segments:
        reasons.append(f"segments with < {MIN_SEG} observations: {thin_segments}")
    if not (oos["pf"] >= PF_GATE):
        reasons.append(f"OOS PF {oos['pf']:.3f} < {PF_GATE}")
    if not (oos["expectancy_bps"] > 0):
        reasons.append(f"OOS expectancy {oos['expectancy_bps']:.2f} bps <= 0 after {cost} bps cost")
    if not (oos_stress["expectancy_bps"] >= 0):
        reasons.append(f"stress expectancy {oos_stress['expectancy_bps']:.2f} bps < 0 at {stress_cost} bps cost")
    if not (ci_lo > 0):
        reasons.append(f"95% bootstrap CI lower bound {ci_lo:.2f} bps not > 0")
    if sym_share > MAX_SYMBOL_SHARE:
        reasons.append(f"symbol concentration {sym_share:.0%} > {MAX_SYMBOL_SHARE:.0%}")
    if hour_share > MAX_HOUR_SHARE:
        reasons.append(f"hour concentration {hour_share:.0%} > {MAX_HOUR_SHARE:.0%}")
    if regime_share > MAX_REGIME_SHARE:
        reasons.append(f"regime concentration {regime_share:.0%} > {MAX_REGIME_SHARE:.0%}")

    result.update({
        "verdict": "GO" if not reasons else "NO-GO",
        "reasons": reasons,
        "selected": {"tp_bps": tp, "sl_bps": sl},
        "in_sample": dev_eval,
        "oos": oos,
        "oos_stress": oos_stress,
        "oos_ci95_bps": [round(ci_lo, 3), round(ci_hi, 3)],
        "concentration": {"symbol": round(sym_share, 3), "hour": round(hour_share, 3),
                          "regime": round(regime_share, 3), "symbol_shares": {k: round(v, 3) for k, v in sym_map.items()}},
        "split_sizes": {"train": len(train), "val": len(val), "test": len(test)},
        "cost_bps": cost, "stress_cost_bps": stress_cost,
    })
    return result


def format_report(r: Dict[str, Any]) -> str:
    lines = ["=" * 64, "E1–E4 counterfactual — shadow observation dataset", "=" * 64,
             f"observations: {r.get('n_total', 0)}   ladder(bps): {r.get('levels', [])}"]
    if "selected" in r:
        s, oos, dev = r["selected"], r["oos"], r["in_sample"]
        lines += [
            f"split: {r['split_sizes']}   cost={r['cost_bps']}bps stress={r['stress_cost_bps']}bps",
            f"selected TP={s['tp_bps']}bps SL={s['sl_bps']}bps",
            f"  in-sample : n={dev['n']} WR={dev['wr']:.1%} PF={dev['pf']:.3f} E={dev['expectancy_bps']:.2f}bps",
            f"  OOS test  : n={oos['n']} WR={oos['wr']:.1%} PF={oos['pf']:.3f} E={oos['expectancy_bps']:.2f}bps",
            f"  OOS stress: E={r['oos_stress']['expectancy_bps']:.2f}bps   CI95={r['oos_ci95_bps']}",
            f"  concentration: symbol={r['concentration']['symbol']:.0%} hour={r['concentration']['hour']:.0%} regime={r['concentration']['regime']:.0%}",
        ]
    lines.append("-" * 64)
    lines.append(f"VERDICT: {r['verdict']}")
    for reason in r.get("reasons", []):
        lines.append(f"  ✗ {reason}")
    if r["verdict"] == "GO":
        lines.append("  ✓ all auditor gates cleared — candidate has a validated OOS edge")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv
    db_path = args[0] if args else DEFAULT_DB
    try:
        observations = load_observations(db_path)
    except sqlite3.OperationalError as e:
        print(f"cannot read shadow dataset at {db_path}: {e}", file=sys.stderr)
        return 2
    r = walk_forward(observations)
    print(json.dumps(r, indent=2) if as_json else format_report(r))
    return 0 if r["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
