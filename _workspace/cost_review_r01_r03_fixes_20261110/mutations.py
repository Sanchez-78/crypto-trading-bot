"""Targeted mutations re-introducing R01-R03 defects, run only in an isolated temp copy."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts" / "research" / "cost_and_learning_review.py"
TEST = ROOT / "tests" / "test_cost_and_learning_review.py"

# name -> (old, new[, old2, new2 ...]); every pattern must occur exactly once.
MUTATIONS = {
    "R01_valid_not_checked": (
        "    if not C1_MIN_VALID_REPLICATES <= valid <= C1_BOOTSTRAP_REPLICATES:", "    if False:"),
    "R01_valid_missing_or_bool_accepted": (
        '    valid = _count(boot.get("valid"), "bootstrap valid replicates")',
        '    valid = boot.get("valid") if isinstance(boot.get("valid"), int) else 2000'),
    "R01_block_time_bound": (
        "    max_blocks = last_entry // C1_BLOCK_MS - (C1_CUTOFF_MS + 1) // C1_BLOCK_MS + 1",
        "    max_blocks = 10 ** 9"),
    "R01_block_trade_bound": ("    if blocks > min(len(ids), max_blocks):", "    if blocks > max_blocks:"),
    "R01_upper_half": ("    if upper_n > len(ids) // 2:", "    if False:"),
    "R01_min_group": ("    if min(upper_n, lower_n) < C1_MIN_GROUP:", "    if False:"),
    "R01_empty_id": ("    if any(not isinstance(i, str) or not i for i in ids):",
                     "    if any(not isinstance(i, str) for i in ids):"),
    "R02_rows_ignored": ("    if missing > expected or rows + missing != expected:", "    if missing > expected:"),
    "R02_counts_unchecked": ("    if missing > expected or rows + missing != expected:", "    if False:"),
    "R02_missing_rows_field_ok": (
        '    if "rows" not in src:\n        raise _MissingEvidence(f"{label}: rows missing")',
        '    if "rows" not in src:\n        src = {**src, "rows": src.get("expected_rows", 0) - src.get("missing_rows", 0)}'),
    "R02_range_length": ("        if end <= start or end - start != count * step:", "        if end <= start:"),
    "R02_range_reversed_or_length": ("        if end <= start or end - start != count * step:", "        if False:"),
    "R02_overlap": ("        if previous_end is not None and start <= previous_end:", "        if False:"),
    "R02_sum": ("    if total != missing:", "    if False:"),
    "R02_grid": (
        "        if bounds is not None and (start < bounds[0] or end > bounds[1] or (start - bounds[0]) % step):",
        "        if False:"),
    "R02_expected_span": (
        "    if bounds is not None and expected != -(-(bounds[1] - bounds[0]) // step):", "    if False:"),
    "R02_no_data_reported_ok": (
        '        status = ("NOT_VERIFIED" if problems else "NO_DATA" if no_data else',
        '        status = ("NOT_VERIFIED" if problems else'),
    "R03_mu_hash_dropped": ('        identity["c1_mu_sha256_observed"] = mu_sha', "        pass"),
    "R03_manifest_hash_dropped": ('    identity["c1_provenance_sha256_observed"] = manifest_sha', "    pass"),
    "R03_reference_reported_as_observed": (
        '"c1_provenance_sha256_observed": None,',
        '"c1_provenance_sha256_observed": provenance_sha or None,'),
    "R03_verified_flag_dropped": ('    identity["c1_provenance_verified"] = True\n', ""),
}


def run(tmp: Path) -> dict:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                          cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = proc.stdout.splitlines()
    tail = [line for line in lines if " passed" in line or " failed" in line or " error" in line]
    collection_error = any("ImportError" in line or "SyntaxError" in line for line in lines)
    return {"exit_code": proc.returncode, "summary": tail[-1] if tail else proc.stdout[-300:],
            "collection_or_import_error": collection_error}


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
            for old, new in zip(pairs[::2], pairs[1::2]):
                if mutated.count(old) != 1:
                    results[name] = {"exit_code": 0, "error": "pattern not found exactly once"}
                    break
                mutated = mutated.replace(old, new)
            else:
                target.write_text(mutated, encoding="utf-8")
                results[name] = run(tmp)
        target.write_text(original, encoding="utf-8")
        results["restored"] = run(tmp)
    Path(__file__).with_name("mutation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, r in results.items():
        print(f"{name}: {r.get('summary', r.get('error'))}")
    mutants = [r for n, r in results.items() if n not in ("baseline", "restored")]
    caught = all(r["exit_code"] != 0 and not r.get("error") and not r.get("collection_or_import_error")
                 for r in mutants)
    ok = caught and results["baseline"]["exit_code"] == 0 and results["restored"]["exit_code"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
