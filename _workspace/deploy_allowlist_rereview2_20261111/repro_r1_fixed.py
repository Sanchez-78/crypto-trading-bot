"""Independent synthetic race check against the current deploy_pinned.sh."""

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
HELPER = HERE.parents[1] / "deploy" / "research_eval" / "deploy_pinned.sh"
BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
FILE = "src/services/candle_cache_v1.py"
APPROVED = b"VALUE = 'approved'\n"
CHANGED = b"VALUE = 'changed_after_pin'\n"


def run_bash(root: Path, commands: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BASH), "-c", f'set -euo pipefail; . "{HELPER.as_posix()}"; {commands}'],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


root = Path(tempfile.mkdtemp(prefix="repro-r1-", dir=HERE)).resolve()
assert root.is_relative_to(HERE) and root.name.startswith("repro-r1-")
try:
    (root / "new").mkdir()
    (root / "app" / "src" / "services").mkdir(parents=True)
    (root / "new" / "candle_cache_v1.py").write_bytes(APPROVED)
    (root / "app" / FILE).write_bytes(b"OLD = True\n")
    expected = hashlib.sha256(APPROVED).hexdigest()
    pin = f"{FILE}={expected}"

    first = run_bash(root, f'stage_files new stage "{FILE}"; verify_pinned stage "{FILE}" "{pin}"')
    assert first.returncode == 0, first.stderr

    (root / "new" / "candle_cache_v1.py").write_bytes(CHANGED)
    second = run_bash(root, f'verify_pinned stage "{FILE}" "{pin}"; '
                            f'install_staged stage app "{FILE}"; verify_pinned app "{FILE}" "{pin}"')
    assert second.returncode == 0, second.stderr
    assert (root / "app" / FILE).read_bytes() == APPROVED

    (root / "stage" / FILE).write_bytes(CHANGED)
    third = run_bash(root, f'verify_pinned stage "{FILE}" "{pin}"; install_staged stage app "{FILE}"')
    assert third.returncode != 0
    assert (root / "app" / FILE).read_bytes() == APPROVED

    print(json.dumps({
        "source_swapped_after_pin": True,
        "installed_sha256": hashlib.sha256((root / "app" / FILE).read_bytes()).hexdigest(),
        "approved_sha256": expected,
        "tampered_stage_refused": True,
        "changed_source_not_installed": True,
    }, sort_keys=True))
finally:
    # Before recursive deletion, verify the resolved target is our own workspace temp dir.
    assert root.resolve().is_relative_to(HERE.resolve()) and root.name.startswith("repro-r1-")
    shutil.rmtree(root)
