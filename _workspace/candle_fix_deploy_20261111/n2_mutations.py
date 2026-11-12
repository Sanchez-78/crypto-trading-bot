"""Mutations for the review-80 fix (N2: explicit refusals, isolated interpreter); isolated copy only."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_deploy_pinned.py", "tests/test_deploy_env_check.py", "tests/test_deploy_bot_files_allowlist.py"]
D = "deploy/research_eval/"
MUTATIONS = {
    "N2_hash_check_as_assert": (D + "deploy_env_check.py", [(
        '        if hashlib.sha256(raw).hexdigest() != pinned[path]:\n            raise Refused(f"tree bytes differ from pin: {path}")\n',
        '        assert hashlib.sha256(raw).hexdigest() == pinned[path], f"tree bytes differ from pin: {path}"\n')]),
    "N2_origin_check_as_assert": (D + "deploy_env_check.py", [(
        '        if os.path.realpath(getattr(module, "__file__", "") or "") != os.path.realpath(source):\n'
        '            raise Refused(f"imported elsewhere: {path}")\n',
        '        assert os.path.realpath(module.__file__) == os.path.realpath(source), f"imported elsewhere: {path}"\n')]),
    "N2_no_prefix_check": (D + "deploy_env_check.py", [(
        '    if not pycache_prefix or os.path.realpath(sys.pycache_prefix or "") != os.path.realpath(pycache_prefix):\n',
        '    if False:\n')]),
    "N2_interpreter_not_isolated": (D + "deploy_bot_files.sh", [(
        '/usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" -', '/usr/bin/python3 -B -')]),
    "N2_assert_back_in_heredoc": (D + "deploy_bot_files.sh", [(
        'pinned = dict(e.split("=", 1) for e in os.environ["EXPECTED_SHA256"].split())\n',
        'pinned = dict(e.split("=", 1) for e in os.environ["EXPECTED_SHA256"].split())\nassert pinned\n')]),
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
    Path(__file__).with_name("n2_mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v)
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
