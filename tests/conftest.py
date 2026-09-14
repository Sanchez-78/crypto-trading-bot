"""pytest configuration for CryptoMaster test suite."""
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path so 'src' module can be imported
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# ── Test-write sink separation (2026-09-14) ─────────────────────────────────
# Several modules resolve a writable path from a module-level constant at
# import time. Those paths pointed at real bot data:
#
#   local_persistent_cache  -> local_learning_storage/cache.sqlite
#   local_learning_storage  -> learning_database.sqlite, and NOT merely
#                              CWD-relative: it probes network shares first, so
#                              on a machine with the NAS mounted it resolved to
#                              SHARED NETWORK STORAGE
#   paper_trade_executor    -> data/paper_open_positions.json
#   paper_adaptive_learning -> server_local_backups/paper_adaptive_learning_state.json
#                              (the bot's durable LEARNED PARAMETERS)
#
# pytest runs from the repo root, so before this redirect every test that
# closed a position or saved learning state wrote real bot data. Phase 0
# forensics measured the damage on cache.sqlite alone: 116 of 472 rows (24.6%)
# were synthetic test writes, and the 35 TEST/MANUAL rows among them are all
# wins, so they inflated every win rate read from that file.
#
# This must run at conftest IMPORT time, before any test module imports those
# modules, because each reads its env var at its own import.
# src.core.test_sink_guard.assert_not_production_sink() is the fail-closed
# backstop if this is ever bypassed.
#
# Set CRYPTOMASTER_TEST_SINK_ROOT yourself to inspect the test sinks;
# otherwise each session gets a throwaway temp directory.
_sink_root = os.environ.get("CRYPTOMASTER_TEST_SINK_ROOT", "").strip()
if not _sink_root:
    _sink_root = tempfile.mkdtemp(prefix="cryptomaster_test_sink_")
    os.environ["CRYPTOMASTER_TEST_SINK_ROOT"] = _sink_root

# Deliberately NOT named after the production directories: a sink that
# accidentally falls back to its default must land somewhere obviously wrong
# rather than in a temp directory that merely looks production-shaped.
for _var, _sub in (
    ("CRYPTOMASTER_LEARNING_STORAGE_DIR", "learning_sink"),
    ("CRYPTOMASTER_PAPER_STATE_DIR", "paper_state_sink"),
    ("CRYPTOMASTER_BACKUP_STATE_DIR", "backup_state_sink"),
):
    if not os.environ.get(_var, "").strip():
        _target = os.path.join(_sink_root, _sub)
        os.makedirs(_target, exist_ok=True)
        os.environ[_var] = _target


import pytest  # noqa: E402  (must follow the env setup above)


@pytest.fixture(autouse=True)
def _deterministic_paper_state():
    """Give every test the same paper-state starting point.

    `open_paper_position()` fails closed unless `_PAPER_STATE_STATUS` is
    "READY" (the STATE-02 guard). The module deliberately does NOT initialize
    at import -- `tests/test_state_01_import_purity.py` enforces that -- so in
    a test process the status is whatever the previously-run test happened to
    leave behind.

    The visible symptom was 9 tests that PASSED in a combined run and FAILED in
    isolation, because some earlier test had initialized the state for them.
    That is falsely green: the combined-run pass proved nothing about the code
    under test, only about collection order.

    This pins the starting point to READY, which is what production actually
    runs with (`_init_paper_state_once()` runs at startup there). Tests that
    exercise the not-ready paths still monkeypatch the status themselves, and
    that continues to work because this only sets the value at setup.

    Import purity is preserved: the module is never imported here. If a test
    has not (yet) imported it, the fixture is a no-op.
    """
    mod = sys.modules.get("src.services.paper_trade_executor")
    if mod is None:
        yield
        return

    previous = getattr(mod, "_PAPER_STATE_STATUS", None)
    previous_init = getattr(mod, "_PAPER_STATE_INITIALIZED", None)
    mod._PAPER_STATE_STATUS = "READY"
    mod._PAPER_STATE_INITIALIZED = True
    try:
        yield
    finally:
        mod._PAPER_STATE_STATUS = previous
        mod._PAPER_STATE_INITIALIZED = previous_init
