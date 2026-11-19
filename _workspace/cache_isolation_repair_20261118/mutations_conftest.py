"""Mutations of tests/conftest.py detection; isolated copy only (no runtime files)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = "tests/test_conftest_runtime_db_isolation.py"
MUTATIONS = {
    "only_cache_sqlite": ('    "data/paper_open_positions.json",\n'
                          '    "server_local_backups/paper_adaptive_learning_state.json",\n'
                          '    "server_local_backups/learning_state_phase1.json",\n', ''),
    "no_runtime_dir_scan": ('_RUNTIME_DIRS = [project_root / "runtime", project_root / "src" / "runtime"]',
                            '_RUNTIME_DIRS = []'),
    "exitstatus_not_set": ('        session.exitstatus = pytest.ExitCode.TESTS_FAILED', '        pass'),
    "no_prevention": ('\n_isolate_local_cache_module()\n', '\n'),
    "runtime_dirs_by_metadata": ('                    snap[rel] = _sha256(p)',
                                 '                    st = p.stat()\n'
                                 '                    snap[rel] = f"size={st.st_size} mtime_ns={st.st_mtime_ns}"'),
    "deletion_ignored": ('for k in sorted(set(_PROTECTED_AT_START) | set(now))',
                         'for k in sorted(set(_PROTECTED_AT_START) & set(now))'),
    "omit_adaptive_learning_state": ('    "server_local_backups/paper_adaptive_learning_state.json",\n', ''),
    "omit_src_runtime_quota": ('    "src/runtime/v5_quota_usage.sqlite",\n', ''),
}


def run(tmp):
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", TEST], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-300:]}


def main():
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "tests"):
            shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
        shutil.copy(ROOT / "AGENTS.md", tmp / "AGENTS.md")  # read-only input of the coverage test
        res["baseline"] = run(tmp)
        target = tmp / "tests" / "conftest.py"
        original = target.read_bytes()
        for name, (old, new) in MUTATIONS.items():
            text = original.decode("utf-8").replace("\r\n", "\n")
            assert text.count(old) == 1, name
            # the regression test reads the REAL conftest via ROOT; point it at the mutated copy
            target.write_text(text.replace(old, new), encoding="utf-8")
            res[name] = run(tmp)
            target.write_bytes(original)
        res["restored"] = run(tmp)
    Path(__file__).with_name("mutation_conftest_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v["summary"])
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")


if __name__ == "__main__":
    main()
