"""Mutations of the C1 provenance producer after the B1-B3 fix; isolated copy of src/scripts/tests."""
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
         "b1_ or b2_ or b3_ or a1_ or a2_ or provenance or freeze or insufficient_data or written_once"]

MUTATIONS = {
    "B1_alias_check_removed": ("    if log in protected:", "    if False:"),
    "B1_tmp_not_protected": ('                 for p in (base, base.with_name(base.name + ".tmp"))}',
                             "                 for p in (base,)}"),
    "B1_manifest_not_protected": ("    protected = {p.resolve() for base in (path, provenance_path(path))",
                                  "    protected = {p.resolve() for base in (path,)"),
    "B1_log_not_resolved": ("    log = provenance_log.resolve()", "    log = provenance_log"),
    "B1_cli_check_removed": ("            validate_freeze_inputs(args.prereg_result, args.run_id, args.provenance_log)",
                             "            pass"),
    "B2_run_id_unchecked": ("    if not RUN_ID_PATTERN.fullmatch(run_id):", "    if False:"),
    "B2_run_id_pattern_too_wide": ('RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")',
                                   'RUN_ID_PATTERN = re.compile(r"[^\\s]{1,64}")'),
    "B3_no_content_fsync": ("        handle.write(payload)\n        handle.flush()\n        os.fsync(handle.fileno())\n",
                            "        handle.write(payload)\n"),
    "B3_no_dir_fsync_after_rename": ("    path.chmod(0o444)\n    _fsync_dir(path.parent)\n", "    path.chmod(0o444)\n"),
    "B3_no_dir_fsync_for_new_log": ("    if created:\n        _fsync_dir(log.parent)\n", ""),
    "A1_log_after_marker": (
        "        _append_reference(provenance_log, run_id, manifest_sha, result_sha)\n        _write_frozen(path, payload)\n",
        "        _write_frozen(path, payload)\n        _append_reference(provenance_log, run_id, manifest_sha, result_sha)\n"),
    "A2_missing_args_accepted": ("    if not run_id or provenance_log is None:\n        raise ValueError",
                                 "    if False:\n        raise ValueError"),
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
