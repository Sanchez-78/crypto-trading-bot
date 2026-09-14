"""Production-linked RED gate: EVERY writable sink is redirected under pytest.

`cache.sqlite` was fixed first, but it was never the only sink resolved from a
module-level path at import time:

    local_learning_storage.py:44  STORAGE_PATH  -> learning_database.sqlite
    paper_trade_executor.py:184   _STATE_FILE = "data/paper_open_positions.json"
    paper_adaptive_learning.py:40 _STATE_FILE =
                                  "server_local_backups/paper_adaptive_learning_state.json"

The third is the durable adaptive-learning state (~70 KB locally) the dashboard
reads for lifetime metrics -- a test overwriting it corrupts the bot's learned
parameters, not merely a metrics table.

That this was a known hazard is on disk: a previous audit left
`server_local_backups/o1a1b_audit_20260525T082414Z/state_hash_before_tests.txt`
and a `.before_validation.json` copy -- somebody hashed the learning state
before running tests and restored it by hand. This replaces that manual ritual
with a structural guarantee.

`local_learning_storage` is NOT merely CWD-relative: it probes a list of
network shares first, and on a developer machine where
`\\\\MYCLOUD-G07Y2M\\Public\\Cryptomaster` is mounted it resolves there. A test
writing that sink would reach SHARED NETWORK STORAGE, so "is it inside the repo"
is too weak a question. The invariant asserted here is the strong one:

    under pytest, every sink must resolve inside the session temp root.

That holds regardless of whether the production target is a repo subdirectory,
an absolute /opt path, or a mounted UNC share.

PAPER-only: asserts on path resolution; opens no position, writes no
production file.
"""

import importlib
import os
from pathlib import Path

import pytest

from src.core import test_sink_guard as guard

# (module path, attribute holding the resolved sink path)
SINKS = (
    ("src.services.local_persistent_cache", "LOCAL_DB_PATH"),
    ("src.services.local_learning_storage", "DB_PATH"),
    ("src.services.paper_trade_executor", "_STATE_FILE"),
    ("src.services.paper_adaptive_learning", "_STATE_FILE"),
)


def _resolved(module_name, attr):
    mod = importlib.import_module(module_name)
    return Path(os.path.abspath(str(getattr(mod, attr))))


@pytest.mark.parametrize("module_name,attr", SINKS)
def test_sink_resolves_inside_the_session_temp_root(module_name, attr):
    """RED: no sink may resolve outside the throwaway session root."""
    root = os.environ.get(guard.SESSION_SINK_ROOT_ENV)
    assert root, f"{guard.SESSION_SINK_ROOT_ENV} is not set for this session"
    root_path = Path(os.path.abspath(root))

    resolved = _resolved(module_name, attr)
    assert root_path == resolved or root_path in resolved.parents, (
        f"{module_name}.{attr} resolves to {resolved}, outside the session "
        f"temp root {root_path}. A test run writes real bot state there."
    )


@pytest.mark.parametrize("module_name,attr", SINKS)
def test_sink_is_env_overridable(module_name, attr):
    """RED: each sink exposes an override knob, so one place redirects it."""
    mod = importlib.import_module(module_name)
    assert hasattr(mod, "SINK_DIR_ENV_VAR"), (
        f"{module_name} exposes no SINK_DIR_ENV_VAR; its sink cannot be "
        "redirected without monkeypatching module internals"
    )
    assert os.environ.get(mod.SINK_DIR_ENV_VAR), (
        f"{mod.SINK_DIR_ENV_VAR} is not set for this test session"
    )


def test_shared_guard_refuses_every_production_sink_shape():
    """RED: one shared fail-closed guard, not N divergent copies.

    This project has a documented regression from two functions reading the
    same parameter with different defaults; N hand-rolled copies of a safety
    guard is that same hazard.
    """
    for bad in (
        "local_learning_storage/cache.sqlite",
        "local_learning_storage/learning_database.sqlite",
        "data/paper_open_positions.json",
        "server_local_backups/paper_adaptive_learning_state.json",
        "/opt/cryptomaster/local_learning_storage/cache.sqlite",
        r"\\MYCLOUD-G07Y2M\Public\Cryptomaster\learning_database.sqlite",
    ):
        with pytest.raises(RuntimeError, match="production"):
            guard.assert_not_production_sink(bad, under_test=True)

    # A redirected temp path is fine, and production runs are never blocked.
    guard.assert_not_production_sink("/tmp/whatever/cache.sqlite", under_test=True)
    guard.assert_not_production_sink(
        "local_learning_storage/cache.sqlite", under_test=False
    )


def test_durable_learning_state_file_is_untouched_by_this_session():
    """RED: the real adaptive-learning state must not be the test target."""
    from src.services import paper_adaptive_learning as pal

    resolved = Path(os.path.abspath(str(pal._STATE_FILE)))
    real = (
        Path(__file__).resolve().parents[1]
        / "server_local_backups" / "paper_adaptive_learning_state.json"
    ).resolve()
    assert resolved != real, (
        "tests are pointed at the real adaptive-learning state file; a single "
        "test save would overwrite the bot's learned parameters"
    )
