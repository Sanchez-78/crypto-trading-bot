"""Proves the production-data integrity backstop actually fires.

External audit 2026-09-15 (Q3): the `PYTEST_CURRENT_TEST` sink guard is
bypassable -- a subprocess spawned without the inherited environment, a
multiprocessing worker, a fixture that clears `os.environ`, or a hardcoded
absolute path that never consults the redirected constant. Both real
contamination incidents in this work were caught only because an operator was
hashing files by hand. That proves the discipline worked, not that the system
was safe.

`tests/conftest.py` now snapshots the watched production files at
`pytest_sessionstart` and re-checks them at `pytest_sessionfinish`, failing the
session on any create/modify/delete. Because it observes the filesystem
directly, it does not care HOW the write happened.

A safety net nobody has seen trip is just another unverified claim, so these
tests run NESTED pytest sessions against a throwaway tree
(`CRYPTOMASTER_INTEGRITY_ROOT`) and assert the real hooks fire. No real bot
data is touched: the nested runs watch a tmp_path, never the repository.

The bypass is simulated the way it actually happens in the wild -- the inner
test writes via `subprocess`, with `PYTEST_CURRENT_TEST` scrubbed from the
child environment, so the env guard genuinely cannot see it.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_WATCHED_REL = "data/paper_open_positions.json"


def _make_fake_production_tree(root: Path) -> Path:
    target = root / _WATCHED_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    return target


def _run_nested_pytest(tmp_path: Path, inner_test_src: str, integrity_root: Path):
    """Run a nested pytest session driven by the REAL repo conftest hooks.

    The repo's `tests/conftest.py` is COPIED next to the generated test so
    pytest loads it as the rootdir conftest. That means the actual
    pytest_sessionstart/pytest_sessionfinish implementation is what runs here,
    not a reimplementation of it -- the point is to exercise the shipping code.
    """
    import os
    import shutil

    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "tests" / "conftest.py", session_dir / "conftest.py")

    test_file = session_dir / "test_inner_probe.py"
    test_file.write_text(textwrap.dedent(inner_test_src), encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["CRYPTOMASTER_INTEGRITY_ROOT"] = str(integrity_root)
    # Let the nested session establish its own sink redirect from scratch.
    for var in ("CRYPTOMASTER_TEST_SINK_ROOT", "CRYPTOMASTER_PAPER_STATE_DIR",
                "CRYPTOMASTER_LEARNING_STORAGE_DIR",
                "CRYPTOMASTER_BACKUP_STATE_DIR"):
        env.pop(var, None)

    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file),
         "-p", "no:cacheprovider", "-q", "--no-header"],
        cwd=str(session_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_backstop_detects_a_modification_made_via_subprocess(tmp_path):
    """A write the env guard cannot see must still fail the session."""
    fake_root = tmp_path / "fakerepo"
    target = _make_fake_production_tree(fake_root)

    # repr() so Windows backslashes survive into the generated source as a
    # valid literal rather than being read as escape sequences.
    inner = f"""
        import subprocess, sys
        def test_contaminate_via_subprocess():
            # A child process with no PYTEST_CURRENT_TEST: the env-var guard
            # is structurally blind to this, which is the whole point.
            target = {str(target)!r}
            subprocess.run(
                [sys.executable, "-c",
                 "import sys; open(sys.argv[1], 'w').write('CONTAMINATED')",
                 target],
                env={{}}, check=True,
            )
    """
    proc = _run_nested_pytest(tmp_path, inner, fake_root)

    combined = proc.stdout + proc.stderr
    assert "PRODUCTION DATA INTEGRITY VIOLATION" in combined, combined[-3000:]
    assert _WATCHED_REL in combined
    assert "MODIFIED" in combined
    assert proc.returncode != 0, "a contaminated session must not exit clean"


def test_backstop_detects_a_deletion(tmp_path):
    """Deletion is the incident git status could never have shown."""
    fake_root = tmp_path / "fakerepo"
    target = _make_fake_production_tree(fake_root)

    inner = f"""
        import os
        def test_delete_production_file():
            os.remove({str(target)!r})
    """
    proc = _run_nested_pytest(tmp_path, inner, fake_root)

    combined = proc.stdout + proc.stderr
    assert "PRODUCTION DATA INTEGRITY VIOLATION" in combined, combined[-3000:]
    assert "DELETED" in combined
    assert proc.returncode != 0


def test_backstop_stays_silent_on_a_clean_run(tmp_path):
    """No false positives -- a well-behaved session must pass untouched."""
    fake_root = tmp_path / "fakerepo"
    _make_fake_production_tree(fake_root)

    inner = """
        def test_touches_nothing():
            assert True
    """
    proc = _run_nested_pytest(tmp_path, inner, fake_root)

    combined = proc.stdout + proc.stderr
    assert "PRODUCTION DATA INTEGRITY VIOLATION" not in combined, combined[-3000:]
    assert proc.returncode == 0, combined[-3000:]
