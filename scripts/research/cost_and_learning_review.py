#!/usr/bin/env python3
"""Offline cost-sensitivity and learning-vs-profit review from FROZEN inputs only.

Consumer of existing evidence, not a simulator or evaluator:
- futures-flow screen report.json (already consumed HOLDOUT; no re-run, no bootstrap);
- optionally the immutable C1 prereg_result.json. Without a conclusive frozen C1 the
  report says PENDING and never opens post-cutoff outcome data.

No DB, network, Firebase or executor imports. Output: review.json + review.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
COSTS_BPS = (0.0, 9.0, 15.0, 18.0, 20.0)
RESERVE_BPS = 3.0
TP_BPS, SL_BPS = 35.0, 25.0
C1_HYPOTHESIS = "C1_contrarian"
C1_FINAL = {"CONTRARIAN_CONFIRMED", "CONTRARIAN_REFUTED", "CONTRARIAN_NOT_SHOWN"}
BLOCKS = ("TRAIN", "TEST", "HOLDOUT")
TARGETS = ("r15", "tpsl")

# Public schedule checked 2026-11-10 (not account-verified; re-check before use).
FEE_SCENARIOS = {
    "effective_date": "2026-11-10",
    "paper_settlement": {"fee_round_trip_bps": 8.0, "slippage_round_trip_bps": 1.0,
                         "source": "PAPER_FEE_PCT=0.0008, PAPER_SLIPPAGE_PCT=0.0001 (server env)"},
    "binance_spot_vip0": {"maker_bps_per_side": 10.0, "taker_bps_per_side": 10.0,
                          "bnb_discount_bps_per_side": 7.5, "source": "https://www.binance.com/en/fee/trading"},
    "binance_usdm_regular": {"maker_bps_per_side": 2.0, "taker_bps_per_side": 5.0, "bnb_discount": "10 %",
                             "source": "https://www.binance.com/support/faq/360033544231"},
}


class ReviewError(ValueError):
    pass


def pct_to_bps(fraction: float) -> float:
    """Fraction (0.0008) -> bps (8). 0.01 % = 0.0001 = 1 bps."""
    _finite(fraction, "fraction")
    return fraction * 10_000.0


def round_trip_bps(per_side_bps: float) -> float:
    _finite(per_side_bps, "per_side_bps")
    return 2.0 * per_side_bps


def two_point_breakeven_wr(cost_bps: float) -> dict:
    """WR_BE = (SL + c) / (TP + SL). Approximation: only valid if every exit is exactly TP or SL."""
    _finite(cost_bps, "cost_bps")
    return {"cost_bps": cost_bps, "wr_be": (SL_BPS + cost_bps) / (TP_BPS + SL_BPS),
            "status": "APPROXIMATION_TWO_POINT", "invalid_with_timeouts": True}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReviewError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _reject_constant(token: str) -> None:
    raise ReviewError(f"non-finite JSON constant {token}")


def _no_duplicates(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ReviewError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def load_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"corrupt JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError(f"{path} must contain a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def sensitivity(stats: dict, label: str) -> dict:
    """Arithmetic shift of the frozen gross mean and its existing CI by constant costs."""
    n = stats.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ReviewError(f"{label}: invalid n {n!r}")
    gross = _finite(stats.get("gross_bps"), f"{label}.gross_bps")
    ci9 = stats.get("ci95_net9")
    if not isinstance(ci9, list) or len(ci9) != 2:
        raise ReviewError(f"{label}: missing ci95_net9")
    lo9, hi9 = (_finite(v, f"{label}.ci95_net9") for v in ci9)
    gross_ci = (lo9 + 9.0, hi9 + 9.0)  # existing interval, re-expressed gross; no new bootstrap
    return {
        "n": n, "gross_bps": gross, "gross_ci95": list(gross_ci),
        "net": {f"{c:g}": {"mean_bps": gross - c, "ci95": [gross_ci[0] - c, gross_ci[1] - c]} for c in COSTS_BPS},
        "breakeven_cost_bps": gross,
        "cost_budget_with_reserve_bps": gross - RESERVE_BPS,
        "conservative_budget_from_ci_low_bps": gross_ci[0] - RESERVE_BPS,
        "derivation": "net(c) = gross - c; CI shifted by c; budgets are arithmetic derivations, not new tests",
    }


def futures_cost_table(report: dict) -> dict:
    table: dict = {}
    for block in BLOCKS:
        statistics = report.get(block, {}).get("statistics")
        if not isinstance(statistics, dict):
            raise ReviewError(f"report missing {block}.statistics")
        for hyp in sorted(statistics):
            for target in TARGETS:
                stats = statistics[hyp].get(target)
                if stats is None:
                    raise ReviewError(f"report missing {block}.{hyp}.{target}")
                # The frozen screen stores n per hypothesis, shared by both targets.
                stats = {"n": statistics[hyp].get("n"), **stats}
                table.setdefault(hyp, {}).setdefault(block, {})[target] = sensitivity(stats, f"{block}.{hyp}.{target}")
    return table


def split_means(mu: float, lift: float, upper_n: int, lower_n: int) -> dict:
    """Group means implied by overall mean mu and lift for the SAME scored set (no CI)."""
    for name, value in (("upper_n", upper_n), ("lower_n", lower_n)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ReviewError(f"{name} must be a positive int")
    _finite(mu, "mu")
    _finite(lift, "lift")
    q = upper_n / (upper_n + lower_n)
    return {"q": q, "mean_upper_bps": mu + (1 - q) * lift, "mean_lower_bps": mu - q * lift,
            "status": "DERIVED_POINT_ESTIMATE_NO_CI"}


def c1_section(result: dict | None, mu_input: dict | None) -> dict:
    if result is None:
        return {"status": "PENDING", "reason": "no frozen prereg_result.json supplied",
                "post_cutoff_outcomes_opened": False}
    verdict = result.get("verdict")
    if verdict not in C1_FINAL:
        return {"status": "PENDING", "reason": f"verdict {verdict!r} is not a frozen final result",
                "post_cutoff_outcomes_opened": False}
    hyp = (result.get("variants") or {}).get(C1_HYPOTHESIS)
    ids = result.get("scored_trade_ids")
    if not isinstance(hyp, dict) or not isinstance(ids, list) or not ids:
        raise ReviewError("frozen C1 result lacks hypothesis variant or scored_trade_ids")
    boot = hyp.get("day_bootstrap") or {}
    out = {
        "status": verdict, "lift_bps": hyp.get("lift_bps"),
        "lift_ci95_welch": [hyp.get("lift_low_bps"), hyp.get("lift_high_bps")],
        "lift_ci95_block_bootstrap": [boot.get("lower_bps"), boot.get("upper_bps")],
        "bootstrap_unit": "6h UTC blocks", "bootstrap_blocks": boot.get("blocks"),
        "upper_n": hyp.get("upper_n"), "lower_n": hyp.get("lower_n"), "scored_n": len(ids),
        "scored_set_sha256": hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest(),
        "post_cutoff_outcomes_opened": False,
        "profitability": "NOT_VERIFIED",
    }
    if mu_input is not None:
        if mu_input.get("scored_set_sha256") != out["scored_set_sha256"]:
            raise ReviewError("mu input belongs to a different scored set")
        out["split"] = split_means(_finite(mu_input.get("mu_bps"), "mu_bps"), _finite(out["lift_bps"], "lift_bps"),
                                   out["upper_n"], out["lower_n"])
    return out


def four_questions(c1: dict, coverage_gaps: int) -> list[dict]:
    learner = c1["status"] if c1["status"] != "PENDING" else "PENDING"
    return [
        {"question": "Jsou data použitelná?", "status": "PARTIAL" if coverage_gaps else "OK",
         "evidence": f"{coverage_gaps} mezer v pokrytí futures screenu; checksum != coverage"},
        {"question": "Umí learner lépe seřadit kandidáty?", "status": learner,
         "evidence": "jen zmrazený verdikt C1"},
        {"question": "Má vybraná politika kladný net?", "status": "NOT_VERIFIED",
         "evidence": "kladný lift není důkaz kladného post-cost výsledku"},
        {"question": "Je připravena změna bota?", "status": "NO",
         "evidence": "vyžaduje nový protokol, review a autorizovanou replikaci"},
    ]


def coverage_gaps(report: dict) -> int:
    gaps = 0
    for block in BLOCKS:
        for entry in report.get(block, {}).get("coverage") or []:
            for source in (entry.get("sources") or {}).values() if isinstance(entry, dict) else ():
                gaps += len(source.get("missing_ranges") or []) if isinstance(source, dict) else 0
    return gaps


def render(review: dict) -> str:
    lines = ["# Přehled nákladů a učení (offline, zmrazené vstupy)", "",
             f"Schéma {review['schema_version']}. Ceník k {FEE_SCENARIOS['effective_date']} (veřejný, neověřený pro účet).", "",
             "## Čtyři otázky", "", "| Otázka | Stav | Důkaz |", "|---|---|---|"]
    lines += [f"| {q['question']} | {q['status']} | {q['evidence']} |" for q in review["four_questions"]]
    lines += ["", "## Bod zvratu WR (dvoubodová aproximace, neplatí při timeoutech)", "",
              "| náklad bps | WR_BE |", "|---:|---:|"]
    lines += [f"| {w['cost_bps']:g} | {w['wr_be'] * 100:.2f} % |" for w in review["breakeven_wr"]]
    lines += ["", "## Futures screen: náklad bodu zvratu (HOLDOUT, odvození)", "",
              "| Hyp. | Target | n | gross [CI] | bod zvratu | rozpočet s rezervou 3 | konzervativně z dolní meze |",
              "|---|---|---:|---|---:|---:|---:|"]
    for hyp, blocks in review["futures_cost_table"].items():
        for target, s in blocks["HOLDOUT"].items():
            lo, hi = s["gross_ci95"]
            lines.append(f"| {hyp} | {target} | {s['n']} | {s['gross_bps']:.2f} [{lo:.2f}; {hi:.2f}] | "
                         f"{s['breakeven_cost_bps']:.2f} | {s['cost_budget_with_reserve_bps']:.2f} | "
                         f"{s['conservative_budget_from_ci_low_bps']:.2f} |")
    c1 = review["c1"]
    lines += ["", "## C1", "", f"Stav: **{c1['status']}**. Post-cutoff výsledky otevřeny: ne.", ""]
    if c1["status"] != "PENDING":
        lines.append(f"Lift {c1['lift_bps']} bps, Welch {c1['lift_ci95_welch']}, bootstrap (6h bloky) "
                     f"{c1['lift_ci95_block_bootstrap']}, upper_n {c1['upper_n']}, lower_n {c1['lower_n']}. "
                     "Ziskovost: NOT_VERIFIED.")
    lines += ["", "Záporný rozpočet = rezerva nevychází ani při nulovém nákladu. Maker mění i výběr a ceny fillů; "
              "nelze odvodit pouhým odečtením menšího fee.", ""]
    return "\n".join(lines)


def build(report_path: Path, c1_path: Path | None, mu_path: Path | None) -> dict:
    report, report_sha = load_json(report_path)
    c1_result, c1_sha = load_json(c1_path) if c1_path else (None, None)
    mu_input, mu_sha = load_json(mu_path) if mu_path else (None, None)
    if mu_input is not None and c1_result is None:
        raise ReviewError("mu input requires a frozen C1 result")
    c1 = c1_section(c1_result, mu_input)
    gaps = coverage_gaps(report)
    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {"futures_report_sha256": report_sha, "c1_result_sha256": c1_sha, "mu_sha256": mu_sha},
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "units": "bps; 1 bps = 0.01 % = 0.0001 fraction; costs are round-trip unless named per_side",
        "fee_scenarios": FEE_SCENARIOS,
        "breakeven_wr": [two_point_breakeven_wr(c) for c in COSTS_BPS],
        "futures_cost_table": futures_cost_table(report),
        "coverage_gap_ranges": gaps,
        "c1": c1,
        "four_questions": four_questions(c1, gaps),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--futures-report", type=Path, required=True)
    parser.add_argument("--c1-result", type=Path, help="frozen prereg_result.json (optional)")
    parser.add_argument("--c1-mu", type=Path, help="JSON {scored_set_sha256, mu_bps} for the same scored set")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = {p.resolve() for p in (args.futures_report, args.c1_result, args.c1_mu) if p}
    targets = [args.out / "review.json", args.out / "review.md"]
    for target in targets:
        if target.resolve() in inputs:
            raise ReviewError(f"refusing to overwrite input {target}")
        if target.exists():
            raise ReviewError(f"refusing to overwrite existing output {target}; use a new --out")
    review = build(args.futures_report, args.c1_result, args.c1_mu)
    args.out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(review, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    targets[1].write_text(render(review), encoding="utf-8")
    print(f"c1={review['c1']['status']} gaps={review['coverage_gap_ranges']} out={args.out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
