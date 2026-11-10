"""Targeted mutations re-introducing F01-F04 defects, run only in an isolated temp copy."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts" / "research" / "cost_and_learning_review.py"
TEST = ROOT / "tests" / "test_cost_and_learning_review.py"

MUTATIONS = {
    "F01_read_mu_before_c1_check": ("    def refuse_mu(reason: str) -> None:",
                                    "    if mu_path is not None:\n        loader(mu_path)\n\n    def refuse_mu(reason: str) -> None:"),
    "F01_mu_not_refused": ("        if mu_path is not None:\n            raise BlindingRefusal",
                           "        if False:\n            raise BlindingRefusal"),
    "F02_result_read_without_provenance": ("    if provenance_path is None or not provenance_sha:\n        refuse_mu(\"no trusted provenance\")",
                                           "    if False:\n        refuse_mu(\"no trusted provenance\")"),
    "F02_duplicate_ids_accepted": ("    if len(set(ids)) != len(ids):", "    if False:"),
    "F02_counts_not_checked": ("    if upper_n + lower_n != len(ids) or", "    if False and"),
    "F02_cutoff_from_input": ("    if result.get(\"scored_after_ms\") != C1_CUTOFF_MS:", "    if False:"),
    "F02_blocks_not_checked": ("    if blocks < C1_MIN_BLOCKS:", "    if False:"),
    "F02_time_margin_not_checked": ("    if evaluated < last_entry + C1_COMPLETE_MARGIN_MS:", "    if False:"),
    # Original defect: absent coverage counted as zero gaps. Both guards removed together;
    # removing either alone is an equivalent mutation (the other still yields NOT_VERIFIED).
    "F03_missing_coverage_ok": ("        if not isinstance(coverage, list) or not coverage:\n            problems.append(\"coverage missing or empty\")",
                                "        if not isinstance(coverage, list) or not coverage:\n            pass",
                                "                problems.append(f\"symbol {symbol} missing\")",
                                "                pass"),
    "F03_hypotheses_not_required": ("        for hyp in HYPOTHESES:\n            entry = statistics.get(hyp)",
                                    "        for hyp in statistics:\n            entry = statistics.get(hyp)"),
    "F03_nested_n_conflict_ignored": ("                if \"n\" in stats and stats[\"n\"] != entry.get(\"n\"):",
                                      "                if False:"),
    "F04_reversed_interval_accepted": ("    if lower > upper:", "    if False:"),
    "F04_zero_n_budgets": ("    if n == 0:\n        return {\"status\": \"NO_DATA\", \"n\": 0}", "    if False:\n        pass"),
}


def run(tmp: Path) -> dict:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                          cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    tail = [line for line in proc.stdout.splitlines() if "passed" in line or "failed" in line or "error" in line]
    return {"exit_code": proc.returncode, "summary": tail[-1] if tail else proc.stdout[-300:]}


def main() -> int:
    original = SRC.read_text(encoding="utf-8")
    results = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "scripts" / "research").mkdir(parents=True)
        (tmp / "tests").mkdir()
        shutil.copy(TEST, tmp / "tests" / TEST.name)
        target = tmp / "scripts" / "research" / SRC.name
        target.write_text(original, encoding="utf-8")
        results["baseline"] = run(tmp)
        for name, pairs in MUTATIONS.items():
            mutated = original
            missing = False
            for old, new in zip(pairs[::2], pairs[1::2]):
                if mutated.count(old) != 1:
                    missing = True
                    break
                mutated = mutated.replace(old, new)
            if missing:
                results[name] = {"exit_code": 0, "error": "pattern not found exactly once"}
                continue
            target.write_text(mutated, encoding="utf-8")
            results[name] = run(tmp)
        target.write_text(original, encoding="utf-8")
        results["restored"] = run(tmp)
    out = Path(__file__).with_name("mutation_results.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, r in results.items():
        print(f"{name}: {r.get('summary', r.get('error'))}")
    caught = all(r.get("exit_code", 0) != 0 for n, r in results.items() if n not in ("baseline", "restored"))
    ok = caught and results["baseline"]["exit_code"] == 0 and results["restored"]["exit_code"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
