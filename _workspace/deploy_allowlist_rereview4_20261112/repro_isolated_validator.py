"""Independent offline check of review 80/N2 fix against current deploy helpers."""

import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
HELPER = REPO / "deploy/research_eval/deploy_pinned.sh"
ENV_HELPER = REPO / "deploy/research_eval/deploy_env_check.py"
MOD = "src/services/candidate.py"
OLD = b"VALUE = 'old'\n"
NEW = b"VALUE = 'new'\n"
ROOT = Path(tempfile.mkdtemp(prefix="review81-", dir=HERE)).resolve()
assert ROOT.parent == HERE.resolve() and ROOT.name.startswith("review81-")


def run_validator(case: Path, *, pin: str, preload: bool = False, prefix_override: bool = False):
    tree = case / "tree"
    prefix = case / "scratch/pycache"
    prefix.mkdir(parents=True, exist_ok=True)
    code = """
import importlib, os, sys
if os.environ['PRELOAD'] == '1':
    sys.path.insert(0, os.environ['SHADOW'])
    importlib.import_module('src.services.candidate')
sys.path.insert(0, os.environ['TREE'])
import deploy_env_check as d
try:
    d.verify_staged_import(os.environ['TREE'], [os.environ['MOD']],
                           {os.environ['MOD']: os.environ['PIN']}, os.environ['PREFIX_ARG'])
except d.Refused as exc:
    print('REFUSED', exc)
    raise SystemExit(2)
print('OK', sys.flags.optimize, sys.flags.ignore_environment, sys.pycache_prefix)
"""
    env = os.environ.copy()
    env.update(TREE=str(tree), SHADOW=str(case / "shadow"), PRELOAD="1" if preload else "0",
               MOD=MOD, PIN=pin, PREFIX_ARG=str(case / "wrong_prefix" if prefix_override else prefix),
               PYTHONOPTIMIZE="2", PYTHONHOME=str(case / "nonexistent_python_home"),
               PYTHONPATH=str(case / "shadow"), PYTHONPYCACHEPREFIX=str(case / "wrong_prefix"))
    return subprocess.run([sys.executable, "-I", "-B", "-X", f"pycache_prefix={prefix}", "-c", code],
                          cwd=case, env=env, capture_output=True, text=True)


try:
    results = {}
    for mode in ("timestamp", "unchecked_hash"):
        case = ROOT / mode
        app_source = case / "app" / MOD
        app_source.parent.mkdir(parents=True)
        (case / "app/src/__init__.py").write_bytes(b"")
        (case / "app/src/services/__init__.py").write_bytes(b"")
        app_source.write_bytes(OLD)
        os.utime(app_source, (1_700_000_000, 1_700_000_000))
        invalidation = (py_compile.PycInvalidationMode.TIMESTAMP if mode == "timestamp"
                        else py_compile.PycInvalidationMode.UNCHECKED_HASH)
        py_compile.compile(str(app_source), doraise=True, invalidation_mode=invalidation)
        (case / "new").mkdir()
        (case / "new/candidate.py").write_bytes(NEW)
        pin = hashlib.sha256(NEW).hexdigest()
        command = (f'set -euo pipefail; . "{HELPER.as_posix()}"; '
                   f'stage_files new stage "{MOD}"; verify_pinned stage "{MOD}" "{MOD}={pin}"; '
                   f'build_tree app stage tree "{MOD}"')
        built = subprocess.run([BASH, "-c", command], cwd=case, capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        shutil.copyfile(ENV_HELPER, case / "tree/deploy_env_check.py")
        assert not list((case / "tree").rglob("*.pyc"))
        assert list((case / "app").rglob("*.pyc"))

        good = run_validator(case, pin=pin)
        assert good.returncode == 0 and good.stdout.startswith("OK 0 1 "), (good.stdout, good.stderr)
        results[mode] = "pinned source imported with optimization env ignored"

        bad_hash = run_validator(case, pin="0" * 64)
        assert bad_hash.returncode == 2 and "tree bytes differ from pin" in bad_hash.stdout
        missing_prefix = run_validator(case, pin=pin, prefix_override=True)
        assert missing_prefix.returncode == 2 and "pycache prefix" in missing_prefix.stdout

        shadow = case / "shadow/src/services"
        shadow.mkdir(parents=True)
        (case / "shadow/src/__init__.py").write_bytes(b"")
        (shadow / "__init__.py").write_bytes(b"")
        (shadow / "candidate.py").write_bytes(OLD)
        wrong_origin = run_validator(case, pin=pin, preload=True)
        assert wrong_origin.returncode == 2 and "imported elsewhere" in wrong_origin.stdout
    results["bad_hash_refused"] = True
    results["missing_prefix_refused"] = True
    results["preloaded_elsewhere_refused"] = True
    print(json.dumps(results, sort_keys=True))
finally:
    assert ROOT.resolve().parent == HERE.resolve() and ROOT.name.startswith("review81-")
    shutil.rmtree(ROOT)
