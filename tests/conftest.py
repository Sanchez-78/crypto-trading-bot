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
    ("CRYPTOMASTER_RUNTIME_DIR", "runtime_sink"),
):
    if not os.environ.get(_var, "").strip():
        _target = os.path.join(_sink_root, _sub)
        os.makedirs(_target, exist_ok=True)
        os.environ[_var] = _target


import pytest  # noqa: E402  (must follow the env setup above)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
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
    exercise the not-ready paths still set the status themselves inside the
    test body, which continues to work because this only applies just before
    that body runs.

    A `pytest_runtest_call` hookwrapper rather than an autouse fixture: the
    fixture version ran BEFORE the test's own fixtures, so when a module-level
    `executor` fixture was what first imported the executor, the module was not
    yet in sys.modules and the fixture silently no-opped. That left exactly the
    FIRST test of such a file failing while its siblings passed -- the
    `test_observe_gate_choke.py::...[1]` regression the 2026-09-16 re-review
    found, a hole in the very mechanism meant to remove order-dependence. This
    hook runs after all fixture setup and immediately before the test body, so
    the import has already happened.

    Import purity is preserved: the module is never imported here. If a test
    genuinely never imports it, this is a no-op.
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


# ── Production data integrity backstop (2026-09-15, external audit Q3) ───────
# The env-var guard in src/core/test_sink_guard.py is necessary but bypassable:
# a subprocess spawned without the inherited environment, a multiprocessing
# worker, a fixture that clears os.environ, or a hardcoded absolute path that
# never consults the redirected constant at all will all slip past it.
#
# Both real contamination incidents in this work (a row written into
# cache.sqlite, and a deleted data/paper_open_positions.json) were caught only
# because an operator happened to be hashing these files by hand before and
# after runs. That proves the DISCIPLINE worked, not that the system was safe.
#
# This makes that discipline automatic and unconditional. It observes the
# filesystem directly, so it does not care HOW a write happened -- subprocess,
# multiprocessing, absolute path or otherwise. It is a backstop layered on top
# of the env guard, not a replacement for it: the guard prevents, this detects.
#
# Deliberately NOT watched: the NAS share. Hashing a network path can stall the
# whole session, and the env guard already refuses it by directory name.

_PRODUCTION_WATCH = (
    "local_learning_storage/cache.sqlite",
    "local_learning_storage/learning_database.sqlite",
    "local_learning_storage/learning_database.sqlite-wal",
    "local_learning_storage/learning_database.sqlite-shm",
    "server_local_backups/paper_adaptive_learning_state.json",
    "server_local_backups/learning_state_phase1.json",
    "data/paper_open_positions.json",
    "data/paper_trades.db",
    # Added 2026-09-16 (re-review item 3): the reviewer's own run silently
    # modified/deleted these three with no banner, because they were not
    # watched at all. Same incident class, different files.
    "runtime/v5_quota_usage.sqlite",
    "runtime/v5_trade_outbox.sqlite",
    "src/runtime/v5_quota_usage.sqlite",
)

_integrity_baseline = {}


def _snapshot_production_files():
    """Map watched path -> sha256, or None when absent. Absence is a state."""
    import hashlib

    # Root is overridable ONLY so this backstop can prove it actually fires,
    # against a throwaway tree instead of real bot data -- an untested safety
    # net is the same unverified claim the audit objected to. Production and
    # ordinary test runs never set it and always watch the real repository.
    _override = (os.environ.get("CRYPTOMASTER_INTEGRITY_ROOT") or "").strip()
    root = Path(_override) if _override else project_root

    snapshot = {}
    for rel in _PRODUCTION_WATCH:
        target = root / rel
        try:
            snapshot[rel] = hashlib.sha256(target.read_bytes()).hexdigest()
        except (FileNotFoundError, NotADirectoryError):
            snapshot[rel] = None
        except OSError as exc:  # locked/unreadable -- record, don't crash
            snapshot[rel] = f"UNREADABLE:{exc.__class__.__name__}"
    return snapshot


def pytest_sessionstart(session):
    _integrity_baseline.update(_snapshot_production_files())


def pytest_sessionfinish(session, exitstatus):
    after = _snapshot_production_files()
    violations = []
    for rel, before in _integrity_baseline.items():
        now = after.get(rel)
        if before == now:
            continue
        if before is None:
            violations.append(f"{rel}: CREATED by the test run")
        elif now is None:
            violations.append(f"{rel}: DELETED by the test run")
        else:
            violations.append(
                f"{rel}: MODIFIED ({before[:12]} -> "
                f"{(now or 'None')[:12]})"
            )

    if not violations:
        return

    # Fail the session hard. A contaminated production file is not a warning:
    # every downstream WR number is computed from these, and a corrupted
    # adaptive-learning state changes what the bot trades.
    session.exitstatus = 1
    banner = "=" * 70
    print(f"\n{banner}", file=sys.stderr)
    print("PRODUCTION DATA INTEGRITY VIOLATION -- the test run wrote real bot data",
          file=sys.stderr)
    for v in violations:
        print(f"  * {v}", file=sys.stderr)
    print(
        "\nThe env-var sink guard was bypassed (subprocess, multiprocessing, "
        "cleared environment, or a hardcoded absolute path).\n"
        "Restore the affected file(s) before trusting any metric derived from "
        "them, then fix the offending test to use the redirected sink.",
        file=sys.stderr,
    )
    print(banner, file=sys.stderr)
