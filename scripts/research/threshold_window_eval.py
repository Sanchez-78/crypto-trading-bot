"""One-shot evaluation of the preregistered analysis window (docs/OPERATING_STATE.md).

Window: trades ENTERED in [T0, END) = [2026-11-25 09:00, 2026-12-02 09:00) UTC.
Cuts on predicted_net_edge_bps: >= -25 / >= -10 / >= 0. The deadline is never
extended.

Gate population (rev. 2, Codex review 2026-11-26): only trades with a valid
prediction (persisted solely for P0_8_PLUS_EVIDENCE_COLLECTION) that passed the
current gate, predicted >= -25. The 1000-trade minimum counts this population;
other trades and missing predictions are reported descriptively only.

Decision rule (preregistered before END; see
_workspace/2026-11-26_threshold_window_decision_rule.md): for c in {-10, 0},
kept = predicted >= c, newly dropped = -25 <= predicted < c. H_c: mean(kept) -
mean(newly dropped) <= 0, one-sided paired UTC-day bootstrap p-value; Holm over
the two hypotheses at family alpha 0.025 (one-sided). A cut is ELIGIBLE when H_c
is rejected and kept >= 100 and newly dropped >= 1. The recommended PAPER
threshold is the eligible cut with the highest mean net bps (tie -> looser
cut); none eligible -> keep -25. WR is reported, not used by the rule.

Stdlib only, so it can be streamed to the server: ``python3 -I - --db ...``.
SQLite opened with mode=ro + PRAGMA query_only=ON; writes only stdout.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import random
import sqlite3
import statistics
import sys
import time

T0 = 1795597200          # 2026-11-25 09:00:00 UTC
END = 1796202000         # 2026-12-02 09:00:00 UTC
SETTLE_S = 1800          # max hold is ~901 s; evaluate only after every window trade closed
MIN_TRADES = 1000
CUTS = (-25.0, -10.0, 0.0)
CURRENT_CUT = -25.0
MIN_CUT_TRADES = 100
WIN_THRESHOLD_PCT = 0.05  # == src.core.trade_metrics_contract.WIN_THRESHOLD_PCT
SEED = 20261202
REPLICATES = 4000
FAMILY_ALPHA = 0.025      # one-sided, Holm over the two stricter cuts


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def outcome(pnl_pct: float) -> str:
    if pnl_pct > WIN_THRESHOLD_PCT:
        return "WIN"
    if pnl_pct < -WIN_THRESHOLD_PCT:
        return "LOSS"
    return "FLAT"


def load(db: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT trade_id, symbol, side, entry_ts, exit_ts, pnl_usd, pnl_pct, "
            "predicted_net_edge_bps FROM closed_trades WHERE entry_ts >= ? AND entry_ts < ?",
            (T0, END))]
    finally:
        conn.close()
    return prepare(rows)


def prepare(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for row in rows:
        entry, exit_ts, pnl = _num(row.get("entry_ts")), _num(row.get("exit_ts")), _num(row.get("pnl_pct"))
        if entry is None or not (T0 <= entry < END):
            continue
        if exit_ts is None or exit_ts < entry or pnl is None:
            raise ValueError(f"invalid closed trade {row.get('trade_id')!r}")
        key = row.get("trade_id")
        if key is not None:
            if key in seen:
                raise ValueError(f"duplicate trade_id {key!r}")
            seen.add(key)
        out.append(dict(
            trade_id=key, entry_ts=entry, exit_ts=exit_ts, net_bps=pnl * 100,
            pnl_usd=_num(row.get("pnl_usd")), outcome=outcome(pnl),  # None = missing/invalid
            predicted=_num(row.get("predicted_net_edge_bps")),
            day=datetime.fromtimestamp(exit_ts, timezone.utc).date().isoformat()))
    return sorted(out, key=lambda r: (r["exit_ts"], r["entry_ts"], str(r["trade_id"])))


def _pct(ordered, p):
    i = (len(ordered) - 1) * p
    lo, hi = math.floor(i), math.ceil(i)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo)


def day_bootstrap(rows: list[dict]) -> dict:
    days = defaultdict(list)
    for r in rows:
        days[r["day"]].append(r["net_bps"])
    if not days:
        return dict(lower_bps=None, upper_bps=None, blocks=0)
    blocks = [days[d] for d in sorted(days)]
    rng = random.Random(SEED)
    means = sorted(statistics.fmean([v for b in rng.choices(blocks, k=len(blocks)) for v in b])
                   for _ in range(REPLICATES))
    return dict(lower_bps=_pct(means, .025), upper_bps=_pct(means, .975), blocks=len(blocks))


def day_difference(selected: list[dict], dropped: list[dict]) -> dict:
    """Paired UTC exit-day blocks: mean(selected) - mean(dropped); resamples missing an arm skipped."""
    days = defaultdict(lambda: ([], []))
    for i, group in enumerate((selected, dropped)):
        for r in group:
            days[r["day"]][i].append(r["net_bps"])
    result: dict = dict(lower_bps=None, upper_bps=None, valid_replicates=0, p_one_sided=None)
    if not selected or not dropped:
        return result
    blocks = [days[d] for d in sorted(days)]
    rng = random.Random(SEED)
    diffs = []
    for _ in range(REPLICATES):
        pick = rng.choices(blocks, k=len(blocks))
        a = [v for b in pick for v in b[0]]
        c = [v for b in pick for v in b[1]]
        if a and c:
            diffs.append(statistics.fmean(a) - statistics.fmean(c))
    diffs.sort()
    result["valid_replicates"] = len(diffs)
    if diffs:
        # percentile-bootstrap one-sided p for H: difference <= 0 (inverts the CI)
        p = (sum(d <= 0 for d in diffs) + 1) / (len(diffs) + 1)
        result.update(lower_bps=_pct(diffs, .025), upper_bps=_pct(diffs, .975), p_one_sided=p)
    return result


def holm(pvalues: dict, alpha: float = FAMILY_ALPHA) -> dict:
    """Holm step-down; a missing p-value is never rejected and stops the procedure."""
    rejected = {key: False for key in pvalues}
    ordered = sorted(pvalues, key=lambda k: (pvalues[k] is None, pvalues[k] if pvalues[k] is not None else 1, k))
    for i, key in enumerate(ordered):
        p = pvalues[key]
        if p is None or p > alpha / (len(ordered) - i):
            break
        rejected[key] = True
    return rejected


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    wins = sum(r["outcome"] == "WIN" for r in rows)
    losses = sum(r["outcome"] == "LOSS" for r in rows)
    # USD metrics are descriptive only; any missing/invalid pnl_usd makes them NOT_EVALUABLE
    missing_usd = sum(r["pnl_usd"] is None for r in rows)
    cum_usd = pf = None
    if not missing_usd:
        gain = sum(r["pnl_usd"] for r in rows if r["pnl_usd"] > 0)
        loss = -sum(r["pnl_usd"] for r in rows if r["pnl_usd"] < 0)
        cum_usd = sum(r["pnl_usd"] for r in rows)
        pf = (gain / loss) if loss > 0 else None
    return dict(
        n=n, wins=wins, losses=losses, flats=n - wins - losses,
        wr_pct=100 * wins / n if n else None,
        mean_net_bps=statistics.fmean(r["net_bps"] for r in rows) if n else None,
        cum_net_bps=sum(r["net_bps"] for r in rows),
        missing_pnl_usd=missing_usd,
        usd_status="NOT_EVALUABLE_MISSING_PNL_USD" if missing_usd else "OK",
        cum_pnl_usd=cum_usd, pf=pf,
        mean_ci=day_bootstrap(rows))


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        for k in order[i:j]:
            ranks[k] = (i + 1 + j) / 2
        i = j
    return ranks


def calibration(rows: list[dict]) -> dict:
    pairs = [(r["predicted"], r["net_bps"]) for r in rows if r["predicted"] is not None]
    out: dict = dict(n=len(pairs), spearman=None, pearson=None, quintiles=[])
    if len(pairs) < 5:
        return out
    xs, ys = [p for p, _ in pairs], [y for _, y in pairs]
    try:
        out["pearson"] = statistics.correlation(xs, ys)
        out["spearman"] = statistics.correlation(_ranks(xs), _ranks(ys))
    except statistics.StatisticsError:
        pass
    ordered = sorted(pairs)
    for q in range(5):
        part = ordered[q * len(ordered) // 5:(q + 1) * len(ordered) // 5]
        if part:
            out["quintiles"].append(dict(
                n=len(part), predicted_min=part[0][0], predicted_max=part[-1][0],
                mean_predicted_bps=statistics.fmean(p for p, _ in part),
                mean_realized_bps=statistics.fmean(y for _, y in part)))
    return out


def evaluate(rows: list[dict]) -> dict:
    # Gate population: valid prediction that passed the current gate (>= -25).
    gate = [r for r in rows if r["predicted"] is not None and r["predicted"] >= CURRENT_CUT]
    report: dict = dict(
        contract="threshold_window_eval_v2", t0=T0, end=END, min_trades=MIN_TRADES,
        family_alpha_one_sided=FAMILY_ALPHA,
        all_descriptive=summary(rows), gate_population=summary(gate),
        missing_prediction=sum(r["predicted"] is None for r in rows),
        below_current_cut=sum(r["predicted"] is not None and r["predicted"] < CURRENT_CUT for r in rows),
        calibration=calibration(gate), cuts={})
    if len(gate) < MIN_TRADES:
        report.update(verdict="INSUFFICIENT_DATA", recommended_cut=CURRENT_CUT, label="NO_CHANGE")
        return report
    cuts: dict[str, dict] = report["cuts"]
    pvalues = {}
    for cut in CUTS:
        kept = [r for r in gate if r["predicted"] >= cut]
        entry: dict = summary(kept)
        if cut > CURRENT_CUT:
            newly_dropped = [r for r in gate if r["predicted"] < cut]
            entry["newly_dropped"] = summary(newly_dropped)
            entry["kept_minus_newly_dropped"] = day_difference(kept, newly_dropped)
            # Both preregistered candidates always stay in the Holm family; an
            # untestable one gets None (never rejected, still counted).
            testable = len(kept) >= MIN_CUT_TRADES and bool(newly_dropped)
            entry["testable"] = testable
            pvalues[f"{cut:g}"] = entry["kept_minus_newly_dropped"]["p_one_sided"] if testable else None
        cuts[f"{cut:g}"] = entry
    rejected = holm(pvalues)
    eligible = []
    for cut in CUTS:
        entry = cuts[f"{cut:g}"]
        entry["holm_rejected"] = rejected.get(f"{cut:g}", False)
        entry["eligible"] = bool(cut > CURRENT_CUT and entry["holm_rejected"])
        if entry["eligible"]:
            eligible.append((entry["mean_net_bps"], -cut, cut))
    if not eligible:
        report.update(verdict="KEEP_CURRENT", recommended_cut=CURRENT_CUT, label="NO_CHANGE")
        return report
    # highest mean first; on a tie the larger -cut (= looser cut, more data) wins
    eligible.sort(reverse=True)
    cut = eligible[0][2]
    chosen_ci: dict = cuts[f"{cut:g}"]["mean_ci"]
    lower = chosen_ci["lower_bps"]
    report.update(verdict="TIGHTEN", recommended_cut=cut,
                  label="POSITIVE_HYPOTHESIS" if lower is not None and lower > 0 else "LOSS_REDUCTION")
    return report


def main(argv=None) -> int:
    # No time override on the CLI: tests monkeypatch time.time.
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args(argv)
    now = time.time()
    if now < END + SETTLE_S:
        print(json.dumps(dict(verdict="NOT_YET", now=now, earliest=END + SETTLE_S)))
        return 2
    report = evaluate(load(args.db))
    report["evaluated_at"] = now
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
