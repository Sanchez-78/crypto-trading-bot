"""Mutations of the hardlink fix (review 73); isolated copy of src/scripts/tests."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = Path("scripts/research/learner_replay_report.py")
TESTS = ["tests/test_replay_blinding.py", "-k",
         "b1_ or b3_"]

MUTATIONS = {
    "H_samefile_check_removed": ("            same = os.path.samefile(log, target)", "            same = False"),
    "H_identity_error_ignored": ("            raise ValueError(\"cannot verify that provenance_log is a distinct file\") from exc",
                                 "            continue"),
    "H_write_through_existing_tmp": ('    tmp.unlink(missing_ok=True)\n    with open(tmp, "xb") as handle:',
                                     '    with open(tmp, "wb") as handle:'),
    "B1_alias_check_removed": ("    if log in protected:", "    if False:"),
}


def run(tmp: Path) -> dict:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
                          cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [l for l in proc.stdout.splitlines() if " passed" in l or " failed" in l or " error" in l]
    return {"exit_code": proc.returncode, "summary": lines[-1] if lines else proc.stdout[-300:],
            "import_error": "ImportError" in proc.stdout or "SyntaxError" in proc.stdout}


def main() -> int:
    original = (ROOT / TARGET).read_text(encoding="utf-8")
    results = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "scripts", "tests"):
            shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite"))
        results["baseline"] = run(tmp)
        for name, (old, new) in MUTATIONS.items():
            if original.count(old) != 1:
                results[name] = {"exit_code": 0, "error": "pattern not found exactly once"}
                continue
            (tmp / TARGET).write_text(original.replace(old, new), encoding="utf-8")
            results[name] = run(tmp)
        (tmp / TARGET).write_text(original, encoding="utf-8")
        results["restored"] = run(tmp)
    Path(__file__).with_name("mutation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, r in results.items():
        print(f"{name}: {r.get('summary', r.get('error'))}")
    mutants = [r for n, r in results.items() if n not in ("baseline", "restored")]
    ok = (all(r["exit_code"] != 0 and not r.get("error") and not r.get("import_error") for r in mutants)
          and results["baseline"]["exit_code"] == 0 and results["restored"]["exit_code"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
