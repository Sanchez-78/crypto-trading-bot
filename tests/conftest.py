"""pytest configuration for CryptoMaster test suite."""
import sys
import os
import tempfile
import shutil
from pathlib import Path
import pytest

# Add project root to path so 'src' module can be imported
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def isolate_adaptive_learner_singleton():
    """Isolate adaptive learner singleton with temp state file for all tests.

    Ensures that:
    - Tests use temporary state files instead of production paths
    - Singleton learner is reset before/after each test
    - No runtime state files are created in repository
    """
    import src.services.paper_adaptive_learning as pal_mod

    tmpdir = tempfile.mkdtemp()
    original_state_file = pal_mod._STATE_FILE
    pal_mod._STATE_FILE = os.path.join(tmpdir, "test_adaptive_state.json")
    pal_mod._learner = None

    yield

    pal_mod._STATE_FILE = original_state_file
    pal_mod._learner = None
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_paper_positions_file(tmp_path, monkeypatch):
    """Redirect paper positions file to tmp_path for test isolation.

    Ensures that tests do not create or modify repository-relative
    data/paper_open_positions.json during test execution.
    """
    import src.services.paper_trade_executor as pte_mod

    # Create temp positions file with empty schema
    temp_positions_file = tmp_path / "paper_open_positions.json"
    temp_positions_file.write_text("{}\n")

    # Monkeypatch the positions file path in the module
    original_file = pte_mod._STATE_FILE
    monkeypatch.setattr(pte_mod, '_STATE_FILE', str(temp_positions_file))

    yield

    # Restore original path
    monkeypatch.setattr(pte_mod, '_STATE_FILE', original_file)


@pytest.fixture(autouse=True)
def reset_starvation_and_sampler_state():
    """Reset adaptive starvation telemetry and sampler globals for test isolation."""
    import src.services.paper_training_sampler as pts_mod

    # Reset starvation state if present
    if hasattr(pts_mod, '_ADAPTIVE_STARVATION_STATE'):
        pts_mod._ADAPTIVE_STARVATION_STATE.clear()
        pts_mod._ADAPTIVE_STARVATION_STATE["window_start_ts"] = 0.0
        pts_mod._ADAPTIVE_STARVATION_STATE["positive_candidates"] = 0
        pts_mod._ADAPTIVE_STARVATION_STATE["negative_ev_rejects"] = 0
        pts_mod._ADAPTIVE_STARVATION_STATE["policy_reads"] = 0
        pts_mod._ADAPTIVE_STARVATION_STATE["admitted_recovery"] = 0
        pts_mod._ADAPTIVE_STARVATION_STATE["canonical_closes"] = 0
        pts_mod._ADAPTIVE_STARVATION_STATE["last_log_ts"] = 0.0

    # Reset rate-cap tracking
    for name in ("_entry_times_minute", "_entry_times_hour"):
        obj = getattr(pts_mod, name, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear deduplication caches
    for name in ("_recent_dedupe", "_recent_dup_candidate"):
        obj = getattr(pts_mod, name, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear skip log state
    for name in ("_SKIP_LOG_TS", "_SKIP_COUNTERS"):
        obj = getattr(pts_mod, name, None)
        if hasattr(obj, "clear"):
            obj.clear()

    yield

    # Cleanup after test
    if hasattr(pts_mod, '_ADAPTIVE_STARVATION_STATE'):
        pts_mod._ADAPTIVE_STARVATION_STATE.clear()


@pytest.fixture(autouse=True)
def isolate_paper_executor_state():
    """Isolate paper_trade_executor in-memory state for test isolation.

    Ensures V5 bridge tests don't run against live PAPER positions.
    Clears _POSITIONS and related state before each test to avoid:
    - max_open_exceeded failures when live data exists
    - interference from concurrent trading state
    - false test failures due to runtime state

    Does NOT modify the JSON state file, Firebase, or runtime behavior.
    """
    import src.services.paper_trade_executor as pte_mod

    # Save original state
    original_positions = pte_mod._POSITIONS.copy() if hasattr(pte_mod, '_POSITIONS') else {}
    original_closed_trades = pte_mod._CLOSED_TRADES_THIS_SESSION.copy() if hasattr(pte_mod, '_CLOSED_TRADES_THIS_SESSION') else set()

    # Clear in-memory state for test isolation
    if hasattr(pte_mod, '_POSITIONS'):
        pte_mod._POSITIONS.clear()
    if hasattr(pte_mod, '_CLOSED_TRADES_THIS_SESSION'):
        pte_mod._CLOSED_TRADES_THIS_SESSION.clear()

    # Reset state initialization flag if present
    if hasattr(pte_mod, '_PAPER_STATE_INITIALIZED'):
        pte_mod._PAPER_STATE_INITIALIZED = False

    yield

    # Restore original state after test
    if hasattr(pte_mod, '_POSITIONS'):
        pte_mod._POSITIONS.clear()
        pte_mod._POSITIONS.update(original_positions)
    if hasattr(pte_mod, '_CLOSED_TRADES_THIS_SESSION'):
        pte_mod._CLOSED_TRADES_THIS_SESSION.clear()
        pte_mod._CLOSED_TRADES_THIS_SESSION.update(original_closed_trades)
