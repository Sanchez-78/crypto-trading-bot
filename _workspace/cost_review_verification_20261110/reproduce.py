"""Read-only audit of commit 4313733; synthetic C1 only, frozen futures aggregates only."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/research/cost_and_learning_review.py"
spec = importlib.util.spec_from_file_location("audited_cost_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
HOUR = 3_600_000
CUTOFF = review.C1_CUTOFF_MS


def raw_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def source() -> dict:
    return {"rows": 100, "expected_rows": 100, "missing_rows": 0, "missing_ranges": []}


def futures() -> dict:
    return {stage: {
        "statistics": {hyp: {"n": 300,
            "r15": {"gross_bps": 1, "ci95_net9": [-9, -7]},
            "tpsl": {"gross_bps": 0, "ci95_net9": [-10, -8]}}
            for hyp in review.HYPOTHESES},
        "coverage": [{"symbol": symbol, "sources": {
            "futures": source(), "spot": source(), "metrics": source(), "funding": {"rows": 10}}}
            for symbol in review.UNIVERSE],
    } for stage in review.BLOCKS}


def c1() -> dict:
    return {"scored_after_ms": CUTOFF, "final_n": 1000, "min_days": 7,
        "fresh_n": 1050, "days_elapsed": 7.4, "scored_last_entry_ms": CUTOFF + 5 * 24 * HOUR,
        "scored_trade_ids": [f"synthetic-{i}" for i in range(1000)],
        "verdict": "CONTRARIAN_CONFIRMED", "variants": {"C1_contrarian": {
            "n": 1000, "upper_n": 480, "lower_n": 520, "lift_bps": 4,
            "lift_low_bps": 0.5, "lift_high_bps": 7.5,
            "day_bootstrap": {"blocks": 16, "valid": 2000, "lower_bps": 0.3, "upper_bps": 7.9}}}}


def run(result: dict, mu_value: float = -9) -> dict:
    manifest = {"contract": review.PROVENANCE_CONTRACT, "hypothesis": review.C1_HYPOTHESIS,
        "scored_after_ms": CUTOFF, "run_id": "SYNTHETIC-AUDIT",
        "evaluated_at_ms": CUTOFF + 8 * 24 * HOUR, "result_sha256": raw_hash(result),
        "id_hash_convention": review.ID_HASH_CONVENTION}
    mu = {"contract": review.MU_CONTRACT, "result_sha256": raw_hash(result),
        "scored_set_sha256": review.id_hash(result["scored_trade_ids"]), "scored_after_ms": CUTOFF,
        "unit": review.MU_UNIT, "cost_basis": review.MU_COST_BASIS, "mu_bps": mu_value}
    values = {"futures": futures(), "manifest": manifest, "result": result, "mu": mu}
    reads = []

    def loader(path):
        name = str(path)
        reads.append(name)
        obj = values[name]
        return copy.deepcopy(obj), raw_hash(obj)

    out = review.build(Path("futures"), Path("result"), Path("mu"), provenance_path=Path("manifest"),
                       provenance_sha=raw_hash(manifest), loader=loader)
    return {"reads": reads, "c1": out["c1"], "inputs": out["inputs"], "exposure": out["exposure"],
            "manifest_sha256": raw_hash(manifest), "mu_sha256": raw_hash(mu)}


def main() -> None:
    results = {}
    baseline = run(c1())
    results["valid_synthetic_baseline"] = baseline
    for name, mutate in {
        "bootstrap_valid_zero": lambda r: r["variants"]["C1_contrarian"]["day_bootstrap"].update(valid=0),
        "blocks_impossible_in_time_span": lambda r: r["variants"]["C1_contrarian"]["day_bootstrap"].update(blocks=28),
        "upper_group_exceeds_median_limit": lambda r: r["variants"]["C1_contrarian"].update(upper_n=520, lower_n=480),
        "empty_trade_id": lambda r: r["scored_trade_ids"].__setitem__(0, ""),
    }.items():
        result = c1()
        mutate(result)
        results[name] = run(result)
    results["max_possible_blocks_in_fixture"] = (
        c1()["scored_last_entry_ms"] // (6 * HOUR) - (CUTOFF + 1) // (6 * HOUR) + 1)

    for name, mutate in {
        "coverage_zero_observed_rows": lambda s: s.update(rows=0, first_ms=None, last_ms=None),
        "coverage_missing_observed_rows": lambda s: s.pop("rows"),
        "coverage_impossible_missing_count": lambda s: s.update(missing_rows=101, missing_ranges=[{}]),
    }.items():
        report = futures()
        for stage in report.values():
            for entry in stage["coverage"]:
                for kind in review.GAP_SOURCES:
                    mutate(entry["sources"][kind])
        results[name] = review.coverage_review(report)

    changed_mu = run(c1(), mu_value=9)
    results["mu_provenance_omitted"] = {
        "same_report_inputs": baseline["inputs"] == changed_mu["inputs"],
        "same_manifest": baseline["manifest_sha256"] == changed_mu["manifest_sha256"],
        "different_mu_sha": baseline["mu_sha256"] != changed_mu["mu_sha256"],
        "first_split": baseline["c1"]["split"], "second_split": changed_mu["c1"]["split"],
        "mu_hash_in_output_inputs": "mu_sha256" in baseline["inputs"],
        "provenance_hash_in_output_inputs": "c1_provenance_sha256" in baseline["inputs"],
    }

    frozen = ROOT / "_workspace/futures_flow_20261109/screen/report.json"
    previous = ROOT / "_workspace/cost_and_learning_review_20261110/review.json"
    current = review.build(frozen)
    before = json.loads(previous.read_text(encoding="utf-8"))
    matched = 0
    for hyp, blocks in before["futures_cost_table"].items():
        for stage, targets in blocks.items():
            for target, stats in targets.items():
                now = {key: value for key, value in current["futures_cost_table"][hyp][stage][target].items()
                       if key != "status"}
                assert now == stats, (hyp, stage, target)
                matched += 1
    results["frozen_aggregate_smoke"] = {"cells_matched": matched,
        "c1": current["c1"], "exposure": current["exposure"], "coverage": current["coverage"]}
    for path in (SCRIPT, ROOT / "tests/test_cost_and_learning_review.py"):
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 12))
    results["syntax_python312"] = "PASS"
    output = Path(__file__).with_name("reproductions.json")
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "accepted_invalid_c1": [name for name in ("bootstrap_valid_zero", "blocks_impossible_in_time_span",
            "upper_group_exceeds_median_limit", "empty_trade_id") if results[name]["c1"]["status"] == "CONTRARIAN_CONFIRMED"],
        "coverage_zero_rows_status": results["coverage_zero_observed_rows"]["status"],
        "coverage_no_rows_status": results["coverage_missing_observed_rows"]["status"],
        "coverage_impossible_gaps_status": results["coverage_impossible_missing_count"]["status"],
        "mu_provenance": results["mu_provenance_omitted"],
        "smoke_cells": matched, "smoke_coverage": current["coverage"]["status"],
        "syntax": "PASS", "evidence": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
