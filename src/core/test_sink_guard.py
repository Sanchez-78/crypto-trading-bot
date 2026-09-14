"""Shared fail-closed guard keeping test runs out of production data sinks.

Several modules resolve a writable path from a module-level constant at import
time. Historically each was relative to the process CWD (or, for the learning
database, a probed network share), and pytest runs from the repo root -- so any
test that closed a position or saved learning state wrote real bot data.

Phase 0 forensics (2026-09-14) measured the damage on one of them: 116 of 472
rows (24.6%) of `cache.sqlite` were synthetic test writes, and the 35
TEST/MANUAL rows among them are all wins, so they inflated every win rate ever
read from that file.

This module exists so the fix is ONE implementation rather than one copy per
sink. This codebase already has a documented regression caused by two functions
reading the same parameter with different defaults (WR 57% -> 0%); N hand-rolled
copies of a safety guard is that same hazard with worse consequences.

Production runs are never affected: `under_pytest()` is false there, so every
guard call is a no-op.
"""
from __future__ import annotations

import os
from pathlib import PurePath

# Set by tests/conftest.py to a throwaway per-session directory. Every
# redirected sink must resolve inside it.
SESSION_SINK_ROOT_ENV = "CRYPTOMASTER_TEST_SINK_ROOT"

# Directory names that mean "real bot data", wherever they appear in a path.
# Matching on the name rather than one absolute prefix is deliberate: the same
# logical sink appears as a repo-relative dir locally, as
# /opt/cryptomaster/... on the host, and as a mounted UNC share on a developer
# machine where the NAS is available.
_PRODUCTION_DIR_NAMES = frozenset({
    "local_learning_storage",
    "server_local_backups",
    "data",
    "network_cache",
    "cryptomaster",  # the \\MYCLOUD-...\Public\Cryptomaster network share root
})


def under_pytest() -> bool:
    """True while a pytest test is executing."""
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def resolve_dir(env_var: str, default: str) -> str:
    """Return the override from `env_var`, else `default`.

    Read at module import so a test session that sets the variable before
    importing the module gets the redirect for free.
    """
    return (os.getenv(env_var, "") or "").strip() or default


def assert_not_production_sink(path, under_test: bool | None = None) -> None:
    """Refuse to touch a production data sink from inside a test run.

    Args:
        path: The resolved sink path (file or directory).
        under_test: Override the pytest detection; used by the guard's own
            tests so they need not mutate PYTEST_CURRENT_TEST.

    Raises:
        RuntimeError: if running under pytest and `path` lands in a directory
            recognised as real bot data.
    """
    if under_test is None:
        under_test = under_pytest()
    if not under_test:
        return

    # Normalise separators so a Windows UNC/backslash path and a POSIX path are
    # examined the same way.
    parts = {p.strip().lower() for p in PurePath(str(path).replace("\\", "/")).parts}
    hit = parts & _PRODUCTION_DIR_NAMES
    if hit:
        raise RuntimeError(
            "refusing to touch a production data sink from a test run: "
            f"{path!r} (matched {sorted(hit)}). Redirect it via the module's "
            "SINK_DIR_ENV_VAR, or set "
            f"{SESSION_SINK_ROOT_ENV} for the whole session."
        )
