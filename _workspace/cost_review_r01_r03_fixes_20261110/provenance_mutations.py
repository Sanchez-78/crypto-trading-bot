"""Mutations of the C1 provenance producer, run in an isolated copy of src/scripts/tests."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = Path("scripts/research/learner_replay_report.py")
TESTS = ["tests/test_replay_blinding.py", "-k", "provenance or freeze or pending_or_insufficient or insufficient_data"]

MUTATIONS = {
    "result_hash_of_other_bytes": (
        '"result_sha256": hashlib.sha256(payload).hexdigest(),',
        '"result_sha256": hashlib.sha256(json.dumps(result).encode("utf-8")).hexdigest(),'),
    "evaluation_time_recomputed": (
        '"run_id": run_id or "unspecified", "evaluated_at_ms": now_ms,',
        '"run_id": run_id or "unspecified", "evaluated_at_ms": now_ms + 1,'),
    "hash_printed_on_every_run": ("        return frozen, None", "        return frozen, \"0\" * 64"),
    "no_provenance_written": ("        _write_frozen(provenance_path(path), manifest)\n", ""),
    "provenance_for_non_final": (
        '    if path is not None and result["verdict"] in {"CONTRARIAN_CONFIRMED", "CONTRARIAN_REFUTED", "CONTRARIAN_NOT_SHOWN"}:',
        '    if path is not None and result["verdict"] != "PENDING" or (path is not None and False):'),
    "run_id_dropped": ('"run_id": run_id or "unspecified",', '"run_id": "unspecified",'),
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
        for extra in ("pytest.ini", "conftest.py", "pyproject.toml"):
            if (ROOT / extra).exists():
                shutil.copy(ROOT / extra, tmp / extra)
        results["baseline"] = run(tmp)
        for name, (old, new) in MUTATIONS.items():
            if original.count(old) != 1:
                results[name] = {"exit_code": 0, "error": "pattern not found exactly once"}
                continue
            (tmp / TARGET).write_text(original.replace(old, new), encoding="utf-8")
            results[name] = run(tmp)
        (tmp / TARGET).write_text(original, encoding="utf-8")
        results["restored"] = run(tmp)
    Path(__file__).with_name("provenance_mutation_results.json").write_text(json.dumps(results, indent=2),
                                                                            encoding="utf-8")
    for name, r in results.items():
        print(f"{name}: {r.get('summary', r.get('error'))}")
    mutants = [r for n, r in results.items() if n not in ("baseline", "restored")]
    ok = (all(r["exit_code"] != 0 and not r.get("error") and not r.get("import_error") for r in mutants)
          and results["baseline"]["exit_code"] == 0 and results["restored"]["exit_code"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
