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


def test_stage_copy_is_private(layout):
    root, expected = layout
    assert sh(f'stage_files new stage "{FILE}"', root).returncode == 0
    assert (root / "stage" / FILE).read_bytes() == APPROVED
