"""Independent offline reproduction for review 80; touches only a temporary fixture."""

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
HELPER = HERE.parents[1] / "deploy" / "research_eval" / "deploy_pinned.sh"
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
ROOT = Path(tempfile.mkdtemp(prefix="review80-", dir=HERE)).resolve()
assert ROOT.is_relative_to(HERE.resolve()) and ROOT.name.startswith("review80-")

try:
    mod = "src/services/candidate.py"
    old = b"VALUE = 'old'\n"
    new = b"VALUE = 'new'\n"
    app_source = ROOT / "app" / mod
    app_source.parent.mkdir(parents=True)
    (ROOT / "app/src/__init__.py").write_bytes(b"")
    (ROOT / "app/src/services/__init__.py").write_bytes(b"")
    app_source.write_bytes(old)
    os.utime(app_source, (1_700_000_000, 1_700_000_000))
    py_compile.compile(str(app_source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
    (ROOT / "new").mkdir()
    (ROOT / "new/candidate.py").write_bytes(new)
    pin = hashlib.sha256(new).hexdigest()
    command = (
        f'set -euo pipefail; . "{HELPER.as_posix()}"; '
        f'stage_files new stage "{mod}"; '
        f'verify_pinned stage "{mod}" "{mod}={pin}"; '
        f'build_tree app stage tree_timestamp "{mod}"'
    )
    built = subprocess.run([BASH, "-c", command], cwd=ROOT, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    tree_source = ROOT / "tree_timestamp" / mod
    assert tree_source.read_bytes() == new
    assert list((ROOT / "app").rglob("*.pyc"))
    assert not list((ROOT / "tree_timestamp").rglob("*.pyc"))
    assert not list((ROOT / "tree_timestamp").rglob("__pycache__"))

    checker = """
import hashlib, importlib, os, sys
sys.path.insert(0, os.environ['STAGE_DIR'])
path = os.environ['FILES']
source = os.path.join(os.environ['STAGE_DIR'], path)
raw = open(source, 'rb').read()
assert hashlib.sha256(raw).hexdigest() == os.environ['PIN']
compile(raw, source, 'exec')
module = importlib.import_module(path.removesuffix('.py').replace('/', '.'))
assert os.path.realpath(module.__file__) == os.path.realpath(source)
cached = module.__spec__.cached
assert cached is None or (cached.startswith(os.environ['PYTHONPYCACHEPREFIX']) and not os.path.exists(cached))
print(module.VALUE, sys.flags.optimize)
"""
    env = os.environ.copy()
    env.update(STAGE_DIR=str(ROOT / "tree_timestamp"), FILES=mod, PIN=pin,
               PYTHONPYCACHEPREFIX=str(ROOT / "scratch/pycache"))
    env.pop("PYTHONOPTIMIZE", None)
    normal = subprocess.run([sys.executable, "-B", "-c", checker], env=env, cwd=ROOT,
                            capture_output=True, text=True)
    assert normal.returncode == 0 and normal.stdout.strip() == "new 0", (normal.stdout, normal.stderr)

    # Rebuild from the second original hazard: an unchecked-hash cache.
    py_compile.compile(str(app_source), doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    unchecked_command = (
        f'set -euo pipefail; . "{HELPER.as_posix()}"; '
        f'build_tree app stage tree_unchecked "{mod}"'
    )
    rebuilt = subprocess.run([BASH, "-c", unchecked_command], cwd=ROOT, capture_output=True, text=True)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert not list((ROOT / "tree_unchecked").rglob("*.pyc"))
    assert not list((ROOT / "tree_unchecked").rglob("__pycache__"))
    tree_source = ROOT / "tree_unchecked" / mod
    env["STAGE_DIR"] = str(ROOT / "tree_unchecked")
    normal_unchecked = subprocess.run([sys.executable, "-B", "-c", checker], env=env, cwd=ROOT,
                                      capture_output=True, text=True)
    assert normal_unchecked.returncode == 0 and normal_unchecked.stdout.strip() == "new 0", (
        normal_unchecked.stdout, normal_unchecked.stderr)

    # Change only this temporary validation copy; the live fixture and pinned stage stay intact.
    tree_source.write_bytes(old)
    rejected = subprocess.run([sys.executable, "-B", "-c", checker], env=env, cwd=ROOT,
                              capture_output=True, text=True)
    assert rejected.returncode != 0 and "AssertionError" in rejected.stderr
    env["PYTHONOPTIMIZE"] = "1"
    optimized = subprocess.run([sys.executable, "-B", "-c", checker], env=env, cwd=ROOT,
                               capture_output=True, text=True)
    assert optimized.returncode == 0 and optimized.stdout.strip() == "old 1", (optimized.stdout, optimized.stderr)

    # An earlier import from another sys.path entry must be rejected by the origin check.
    tree_source.write_bytes(new)
    outside = ROOT / "outside/src/services"
    outside.mkdir(parents=True)
    (ROOT / "outside/src/__init__.py").write_bytes(b"")
    (outside / "__init__.py").write_bytes(b"")
    (outside / "candidate.py").write_bytes(old)
    preload = ("import os, sys; sys.path.insert(0, os.environ['OUTSIDE']); "
               "from src.services import candidate\n")
    env["OUTSIDE"] = str(ROOT / "outside")
    env.pop("PYTHONOPTIMIZE")
    wrong_origin = subprocess.run([sys.executable, "-B", "-c", preload + checker], env=env, cwd=ROOT,
                                  capture_output=True, text=True)
    assert wrong_origin.returncode != 0 and "AssertionError" in wrong_origin.stderr
    env["PYTHONOPTIMIZE"] = "1"
    optimized_origin = subprocess.run([sys.executable, "-B", "-c", preload + checker], env=env, cwd=ROOT,
                                      capture_output=True, text=True)
    assert optimized_origin.returncode == 0 and optimized_origin.stdout.strip() == "old 1", (
        optimized_origin.stdout, optimized_origin.stderr)
    print(json.dumps({"timestamp_cache_refused": True,
                      "unchecked_hash_cache_refused": True,
                      "build_tree_strips_cache": True,
                      "normal_pin_mismatch_refused": True,
                      "normal_wrong_origin_refused": True,
                      "optimized_wrong_origin_accepted": True,
                      "optimized_pin_mismatch_accepted": True,
                      "optimized_output": optimized.stdout.strip()}, sort_keys=True))
finally:
    assert ROOT.resolve().is_relative_to(HERE.resolve()) and ROOT.name.startswith("review80-")
    shutil.rmtree(ROOT)
