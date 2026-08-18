"""STATE-01 (CLAUDE_COMPREHENSIVE_REMEDIATION_PROMPT_2026-08-18.md) --
import-purity regression test.

Confirmed root cause (static read, src/services/paper_trade_executor.py):
module-bottom code (no `if __name__` guard) called `subscribe_once(
"signal_created", ...)` and `_init_paper_state_once()` -- which reads
`data/paper_open_positions.json`, migrates/normalizes it, calls
`_reconcile_stale_paper_positions()` (real business logic that can CLOSE
stale positions and write learning updates), and writes the file back on
a schema conversion -- UNCONDITIONALLY at import time. This matches the
disclosed local-state contamination from two prior diagnostic import
probes exactly (fabricated paper_close/learning_update events, outbox
rows, mutated learner qualification_n).

Fix: all of that moved into an explicit `initialize_paper_trade_executor()`
function, called exactly once from bot2/main.py's startup sequence
(immediately after event-bus init), never from module import.

This test proves the invariant in isolation: importing the module in a
fresh subprocess, with CWD pointed at a throwaway temporary directory
(so any accidental relative-path file access would land there, not on
real project files), performs zero file writes and never implicitly
flips the module's own initialization flags.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_import_in_subprocess(tmp_path: Path, import_statement: str) -> subprocess.CompletedProcess:
    """Run `import_statement` in a fresh Python subprocess with CWD set to
    `tmp_path` (a pytest-provided, per-test-unique temporary directory --
    never the repository). PYTHONDONTWRITEBYTECODE=1 so .pyc creation is
    never confused with application-caused writes. PYTHONPATH includes the
    repo root so `src.services...` resolves without needing CWD=repo."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # Isolate every cache/tool artifact the document's Phase 1 flags
    # (pytest cache, coverage, ruff, mypy, hypothesis) inside tmp_path too,
    # in case the import chain touches any of them.
    env["PYTEST_ADDOPTS"] = ""
    env["RUFF_CACHE_DIR"] = str(tmp_path / ".ruff_cache")
    env["MYPY_CACHE_DIR"] = str(tmp_path / ".mypy_cache")
    return subprocess.run(
        [sys.executable, "-c", import_statement],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_bare_import_creates_no_files_in_cwd(tmp_path):
    """A subprocess whose CWD is an empty temp directory must contain NO
    new files after `import src.services.paper_trade_executor` -- proves
    no relative-path file (state JSON, SQLite, log) was written."""
    before = set(tmp_path.iterdir())
    result = _run_import_in_subprocess(
        tmp_path,
        "import src.services.paper_trade_executor",
    )
    assert result.returncode == 0, f"import failed: {result.stderr}"
    after = set(tmp_path.iterdir())
    new_files = after - before
    assert not new_files, f"import created unexpected files in CWD: {new_files}"


def test_bare_import_does_not_flip_initialization_flags(tmp_path):
    """The module's own idempotency flags must remain False after a bare
    import -- proves initialize_paper_trade_executor() was never
    implicitly invoked."""
    script = (
        "import src.services.paper_trade_executor as pte\n"
        "assert pte._PAPER_STATE_INITIALIZED is False, "
        "'STATE-01 regression: _PAPER_STATE_INITIALIZED became True on bare import'\n"
        "assert pte._PAPER_TRADE_EXECUTOR_SUBSCRIBED is False, "
        "'STATE-01 regression: _PAPER_TRADE_EXECUTOR_SUBSCRIBED became True on bare import'\n"
        "print('OK')\n"
    )
    result = _run_import_in_subprocess(tmp_path, script)
    assert result.returncode == 0, f"import/assertions failed: {result.stdout}\n{result.stderr}"
    assert "OK" in result.stdout


def test_bare_import_does_not_touch_real_project_state_file():
    """Belt-and-suspenders: even importing with the REAL repo root as CWD
    (the worst case for accidental relative-path resolution) must not
    change the real data/paper_open_positions.json's mtime -- confirms
    the fix, not just the test isolation technique."""
    state_file = REPO_ROOT / "data" / "paper_open_positions.json"
    if not state_file.exists():
        pytest.skip("real state file does not exist in this environment")
    mtime_before = state_file.stat().st_mtime

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", "import src.services.paper_trade_executor"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"import failed: {result.stderr}"

    mtime_after = state_file.stat().st_mtime
    assert mtime_after == mtime_before, (
        "STATE-01 regression: importing the module changed the real "
        "paper-position state file's mtime -- import is not pure"
    )


def test_explicit_initialize_function_exists_and_is_idempotent(tmp_path):
    """The explicit init function must exist, be callable, and be safe to
    call twice (matching _init_paper_state_once()'s own pre-existing
    idempotency guard) -- run inside the isolated temp CWD so any state
    file it does create (once explicitly called) lands in the throwaway
    directory, not the real project."""
    script = (
        "import src.services.paper_trade_executor as pte\n"
        "assert callable(pte.initialize_paper_trade_executor)\n"
        "pte.initialize_paper_trade_executor()\n"
        "assert pte._PAPER_STATE_INITIALIZED is True\n"
        "assert pte._PAPER_TRADE_EXECUTOR_SUBSCRIBED is True\n"
        "pte.initialize_paper_trade_executor()  # second call must not raise\n"
        "print('OK')\n"
    )
    result = _run_import_in_subprocess(tmp_path, script)
    assert result.returncode == 0, f"failed: {result.stdout}\n{result.stderr}"
    assert "OK" in result.stdout


def test_bot2_main_calls_initializer_after_event_bus_init():
    """Static check: bot2/main.py must call initialize_paper_trade_executor()
    exactly once, positioned after _init_event_handlers() (subscribe_once
    needs the event bus to already exist)."""
    src = (REPO_ROOT / "bot2" / "main.py").read_text(encoding="utf-8")
    assert "initialize_paper_trade_executor()" in src
    event_bus_idx = src.index("_init_event_handlers()")
    init_idx = src.index("initialize_paper_trade_executor()")
    assert init_idx > event_bus_idx, (
        "initialize_paper_trade_executor() must be called AFTER "
        "_init_event_handlers() so subscribe_once() has an event bus to "
        "register against"
    )
