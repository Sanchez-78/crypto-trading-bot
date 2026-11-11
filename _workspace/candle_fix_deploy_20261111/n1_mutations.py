"""Mutations for the review-79 fix (N1 stale bytecode); isolated copy only."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_deploy_pinned.py", "tests/test_deploy_env_check.py", "tests/test_deploy_bot_files_allowlist.py"]
D = "deploy/research_eval/"
CLEAN_DIRS = '  find "$tree" -name __pycache__ -type d -prune -exec rm -rf {} +\n'
CLEAN_FILES = "  find \"$tree\" -type f \\( -name '*.pyc' -o -name '*.pyo' \\) -delete\n"
LEFTOVER = ('  if [ -n "$(find "$tree" \\( -name __pycache__ -o -name \'*.pyc\' -o -name \'*.pyo\' \\) -print -quit)" ]; then\n'
            '    echo "bytecode left in validation tree" >&2; return 2\n'
            '  fi\n')
MUTATIONS = {
    "N1_no_cleanup_and_no_leftover_check": (D + "deploy_pinned.sh", [(CLEAN_DIRS, ""), (CLEAN_FILES, ""), (LEFTOVER, "")]),
    "N1_cleanup_removed_check_kept": (D + "deploy_pinned.sh", [(CLEAN_DIRS, ""), (CLEAN_FILES, "")]),
    "N1_plain_copy_in_script": (D + "deploy_bot_files.sh", [(
        'build_tree "$APP" "$PINNED" "$TREE" "$FILES"  # no bytecode in the tree (review 79, N1)',
        'mkdir -p "$TREE"; cp -r "$APP/src" "$TREE/src"; install_staged "$PINNED" "$TREE" "$FILES"')]),
    "N1_no_pycache_prefix": (D + "deploy_bot_files.sh", [(' --setenv=PYTHONPYCACHEPREFIX="$SCRATCH/pycache"', '')]),
    "N1_no_cache_assertion": (D + "deploy_bot_files.sh", [('f"bytecode cache used for {path}"', 'f"x {path}"')]),
}


def run(tmp: Path) -> dict:
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", *TESTS],
                       cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l or " error" in l]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-200:]}


def main() -> int:
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shutil.copytree(ROOT / "deploy", tmp / "deploy")
        (tmp / "tests").mkdir()
        for t in TESTS:
            shutil.copy(ROOT / t, tmp / t)
        res["baseline"] = run(tmp)
        for name, (rel, pairs) in MUTATIONS.items():
            original = (tmp / rel).read_text(encoding="utf-8")
            mutated = original
            for old, new in pairs:
                assert mutated.count(old) == 1, (name, old[:50])
                mutated = mutated.replace(old, new)
            (tmp / rel).write_text(mutated, encoding="utf-8", newline="\n")
            res[name] = run(tmp)
            (tmp / rel).write_text(original, encoding="utf-8", newline="\n")
        res["restored"] = run(tmp)
    Path(__file__).with_name("n1_mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v)
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
