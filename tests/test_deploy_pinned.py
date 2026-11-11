"""deploy_pinned.sh: the validated bytes are the installed bytes (review 78, R1). Runs real bash."""
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

HELPERS = Path(__file__).resolve().parents[1] / "deploy" / "research_eval" / "deploy_pinned.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")
FILE = "src/services/candle_cache_v1.py"
APPROVED = b"APPROVED = True\n"
TAMPERED = b"APPROVED = False  # swapped after the check\n"


def sh(script: str, cwd: Path) -> subprocess.CompletedProcess:
    helpers = HELPERS.as_posix()
    return subprocess.run([BASH, "-c", f'set -euo pipefail; . "{helpers}"; {script}'], cwd=cwd,
                          capture_output=True, text=True)


@pytest.fixture
def layout(tmp_path):
    for d in ("new", "stage", "app/src/services"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "new" / "candle_cache_v1.py").write_bytes(APPROVED)
    (tmp_path / "app" / FILE).write_bytes(b"OLD = True\n")
    expected = f"{FILE}={hashlib.sha256(APPROVED).hexdigest()}"
    return tmp_path, expected


def test_source_swapped_after_check_never_reaches_the_app(layout):
    root, expected = layout
    staged = sh(f'stage_files new stage "{FILE}" && verify_pinned stage "{FILE}" "{expected}"', root)
    assert staged.returncode == 0, staged.stderr
    (root / "new" / "candle_cache_v1.py").write_bytes(TAMPERED)  # the race window (positions wait)
    installed = sh(f'verify_pinned stage "{FILE}" "{expected}" && install_staged stage app "{FILE}" '
                   f'&& verify_pinned app "{FILE}" "{expected}"', root)
    assert installed.returncode == 0, installed.stderr
    assert (root / "app" / FILE).read_bytes() == APPROVED


def test_tampered_stage_is_refused_before_install(layout):
    root, expected = layout
    assert sh(f'stage_files new stage "{FILE}"', root).returncode == 0
    (root / "stage" / FILE).write_bytes(TAMPERED)
    result = sh(f'verify_pinned stage "{FILE}" "{expected}" && install_staged stage app "{FILE}"', root)
    assert result.returncode != 0 and "hash mismatch" in result.stderr
    assert (root / "app" / FILE).read_bytes() == b"OLD = True\n"


def test_installed_bytes_are_compared_with_the_pinned_hash_not_the_source(layout):
    root, expected = layout
    (root / "new" / "candle_cache_v1.py").write_bytes(TAMPERED)
    (root / "app" / FILE).write_bytes(TAMPERED)  # app equals the (tampered) source ...
    result = sh(f'verify_pinned app "{FILE}" "{expected}"', root)
    assert result.returncode != 0  # ... yet the pinned check fails


def test_missing_pin_is_refused(layout):
    root, _ = layout
    assert sh(f'stage_files new stage "{FILE}"', root).returncode == 0
    result = sh(f'verify_pinned stage "{FILE}" "src/services/other.py=abc"', root)
    assert result.returncode != 0 and "no EXPECTED_SHA256" in result.stderr


MOD = "src/services/candidate.py"
OLD_SRC = "VALUE = 'old'\n"
NEW_SRC = "VALUE = 'new'\n"  # same size as OLD_SRC on purpose


def _app_with_stale_bytecode(root: Path, mode: str) -> None:
    import os
    import py_compile
    services = root / "app" / "src" / "services"
    services.mkdir(parents=True, exist_ok=True)
    (root / "app" / "src" / "__init__.py").write_text("", encoding="utf-8")
    (services / "__init__.py").write_text("", encoding="utf-8")
    source = root / "app" / MOD
    source.write_bytes(OLD_SRC.encode())  # bytes, not text: no CRLF translation on Windows
    os.utime(source, (1_700_000_000, 1_700_000_000))
    invalidation = (py_compile.PycInvalidationMode.UNCHECKED_HASH if mode == "unchecked_hash"
                    else py_compile.PycInvalidationMode.TIMESTAMP)
    py_compile.compile(str(source), doraise=True, invalidation_mode=invalidation)
    (root / "new").mkdir(exist_ok=True)
    (root / "new" / "candidate.py").write_bytes(NEW_SRC.encode())


def _import_value(tree: Path, prefix: Path) -> str:
    import os
    import subprocess as sp
    import sys
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from src.services import candidate; "
            "print(candidate.VALUE, candidate.__spec__.cached)")
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(prefix)}
    out = sp.run([sys.executable, "-B", "-c", code, str(tree)], capture_output=True, text=True, env=env, check=True)
    return out.stdout.split()[0]


@pytest.mark.parametrize("mode", ["timestamp_same_size_mtime", "unchecked_hash"])
def test_validation_tree_imports_pinned_source_not_stale_bytecode(tmp_path, mode):
    import os
    _app_with_stale_bytecode(tmp_path, mode)
    expected = f"{MOD}={hashlib.sha256(NEW_SRC.encode()).hexdigest()}"
    result = sh(f'stage_files new stage "{MOD}" && verify_pinned stage "{MOD}" "{expected}" '
                f'&& build_tree app stage tree "{MOD}"', tmp_path)
    assert result.returncode == 0, result.stderr
    tree_src = tmp_path / "tree" / MOD
    os.utime(tree_src, (1_700_000_000, 1_700_000_000))  # worst case: same mtime/size as the stale .pyc
    assert not list((tmp_path / "tree").rglob("*.pyc")) and not list((tmp_path / "tree").rglob("__pycache__"))
    prefix = tmp_path / "scratch" / "pycache"
    prefix.mkdir(parents=True)
    assert _import_value(tmp_path / "tree", prefix) == "new"
    # The live app's own bytecode is left untouched by build_tree.
    assert list((tmp_path / "app").rglob("*.pyc"))


def test_stale_bytecode_would_be_imported_without_the_guard(tmp_path):
    """Control: the hazard is real -- a plain copy with __pycache__ imports the old code."""
    import shutil as sh_util
    _app_with_stale_bytecode(tmp_path, "unchecked_hash")
    sh_util.copytree(tmp_path / "app", tmp_path / "plain")
    (tmp_path / "plain" / MOD).write_text("VALUE = 'new_source_of_other_size'\n", encoding="utf-8")
    import os
    import subprocess as sp
    import sys
    code = "import sys; sys.path.insert(0, sys.argv[1]); from src.services import candidate; print(candidate.VALUE)"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPYCACHEPREFIX"}
    out = sp.run([sys.executable, "-B", "-c", code, str(tmp_path / "plain")], capture_output=True, text=True,
                 env=env, check=True)
    assert out.stdout.strip() == "old"


def test_stage_copy_is_private(layout):
    root, expected = layout
    assert sh(f'stage_files new stage "{FILE}"', root).returncode == 0
    assert (root / "stage" / FILE).read_bytes() == APPROVED
