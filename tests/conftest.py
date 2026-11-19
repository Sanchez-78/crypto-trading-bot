"""pytest configuration for CryptoMaster test suite."""
import atexit
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock
import pytest

# Add project root to path so 'src' module can be imported
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


# ── Runtime-DB isolation (2026-11-18 incident, _workspace/2026-11-18_claude_cache_isolation_repair.md)
# local_persistent_cache runs _init_db() at import time against the RELATIVE path
# local_learning_storage/cache.sqlite and can ALTER an older schema. Test modules import it
# during collection (before any fixture can redirect it), so running pytest from the project
# root wrote to the real local DB. This conftest is loaded before those modules: import the
# cache module once with cwd in a private temp dir and point its paths there, so later imports
# reuse this module object and never initialise the runtime path.
#
# Detection (extended 2026-11-19 after server_local_backups/*.json changed during a root pytest
# run): the six protected files from AGENTS.md are hashed when this conftest loads and again at
# session end; any file appearing, disappearing or changing under runtime/ or src/runtime/ also
# fails the run.
_PROTECTED_FILES = [project_root / p for p in (
    "local_learning_storage/cache.sqlite",
    "data/paper_open_positions.json",
    "server_local_backups/paper_adaptive_learning_state.json",
    "server_local_backups/learning_state_phase1.json",
    "runtime/v5_quota_usage.sqlite",
    "src/runtime/v5_quota_usage.sqlite",
)]
_RUNTIME_DIRS = [project_root / "runtime", project_root / "src" / "runtime"]


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _protected_snapshot() -> dict:
    # Content hashes for every file (metadata alone misses same-size rewrites with a restored
    # mtime, review 2026-11-19 B1). Limits: end-state only (a file created and removed between
    # the two snapshots is missed); a concurrent process changing these files, or a SQLite
    # -wal/-shm/-journal left behind by one, also fails the run and is reported as "during tests".
    snap = {str(p.relative_to(project_root)): _sha256(p) for p in _PROTECTED_FILES}
    for d in _RUNTIME_DIRS:
        if d.is_dir():
            for p in d.rglob("*"):
                rel = str(p.relative_to(project_root))
                if p.is_file() and rel not in snap:
                    snap[rel] = _sha256(p)
    return snap


_PROTECTED_AT_START = _protected_snapshot()


def _isolate_local_cache_module() -> None:
    if "src.services.local_persistent_cache" in sys.modules:
        return
    sandbox = tempfile.mkdtemp(prefix="cm_test_local_cache_")
    atexit.register(shutil.rmtree, sandbox, True)
    previous_cwd = os.getcwd()
    try:
        os.chdir(sandbox)
        import src.services.local_persistent_cache as lpc
    finally:
        os.chdir(previous_cwd)
    lpc.LOCAL_CACHE_DIR = os.path.join(sandbox, "local_learning_storage")
    lpc.LOCAL_DB_PATH = os.path.join(lpc.LOCAL_CACHE_DIR, "cache.sqlite")
    lpc.LOCAL_STATE_DIR = os.path.join(lpc.LOCAL_CACHE_DIR, "state")


_isolate_local_cache_module()


def pytest_sessionfinish(session, exitstatus):
    """Fail the run loudly if anything changed a protected runtime file."""
    now = _protected_snapshot()
    changed = {k: (_PROTECTED_AT_START.get(k), now.get(k))
               for k in sorted(set(_PROTECTED_AT_START) | set(now))
               if _PROTECTED_AT_START.get(k) != now.get(k)}
    if changed:
        lines = "".join(f"  {k}: {a} -> {b}\n" for k, (a, b) in changed.items())
        sys.stderr.write("\nPROTECTED RUNTIME FILES CHANGED DURING TESTS (stop and report, AGENTS.md):\n" + lines)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def initialized_paper_executor(monkeypatch, tmp_path):
    """Explicit lifecycle for broker unit tests, with disposable position state.

    Admission tests must start with a successfully initialized executor. State
    failure/subscription tests deliberately do not use this fixture.
    """
    from src.services import paper_trade_executor as pte
    monkeypatch.setattr(pte, "_STATE_FILE", str(tmp_path / "paper_positions.json"))
    monkeypatch.setattr(pte, "_POSITIONS", {})
    monkeypatch.setattr(pte, "_CLOSED_TRADES_THIS_SESSION", set())
    monkeypatch.setattr(pte, "_PAPER_STATE_STATUS", "UNINITIALIZED")
    monkeypatch.setattr(pte, "_PAPER_STATE_INITIALIZED", False)
    monkeypatch.setattr(pte, "_PAPER_TRADE_EXECUTOR_SUBSCRIBED", False)
    monkeypatch.setattr(pte, "subscribe_once", Mock())
    assert pte.initialize_paper_trade_executor() is True
    yield pte


@pytest.fixture
def broker_with_admitted_strategy(monkeypatch, initialized_paper_executor):
    """Broker lifecycle tests inject admission; P0 policy has its own suites."""
    pte = initialized_paper_executor
    monkeypatch.setattr(pte, "_should_skip_segment_p0_strict_ev", lambda *_, **__: (False, {
        "strict_ev_allowed": True, "reason": "unit_test_admission", "readiness_eligible": True,
    }))
    return pte
