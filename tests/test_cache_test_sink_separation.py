"""Production-linked RED gate: test runs must never write to the production cache.

Phase 0 forensics found 116/472 rows (24.6%) of
`local_learning_storage/cache.sqlite` were synthetic test writes -- 76 rows
stamped with a fake 1970 clock, 35 `TEST`/`MANUAL` exits (all of them wins,
so they inflate every WR number read from this file), and 3 `SYM0/1/2` rows.

Root cause: `local_persistent_cache.LOCAL_DB_PATH` is a module-level RELATIVE
path (`local_learning_storage/cache.sqlite`) resolved against the process CWD,
with no override. pytest runs from the repo root, so every test that closes a
paper position wrote straight into the same database the dashboard reads.

Per-test monkeypatch discipline is not a fix -- several suites already do it
correctly and the contamination happened anyway, because the ones that forget
are exactly the ones that cause it. The contract asserted here is structural:

* RED-1: the storage directory is resolved from an env override, so a test
  session can redirect the whole sink in one place.
* RED-2: a write attempt that resolves to the PRODUCTION path while running
  under pytest is refused (fail-closed), not silently performed.
* RED-3: the repo's own conftest actually redirects the sink, so the guard in
  RED-2 is a backstop rather than the primary mechanism.

PAPER-only: no position is opened and no production path is written.
"""

import importlib
import os
import sqlite3

import pytest

from src.services import local_persistent_cache as lpc

PROD_DEFAULT = "local_learning_storage"


def test_storage_dir_is_env_overridable():
    """RED-1: an explicit override knob exists and is honoured at import."""
    assert hasattr(lpc, "STORAGE_DIR_ENV_VAR"), \
        "local_persistent_cache exposes no storage-dir override knob"

    # RESTORE the session redirect afterwards, never pop it: popping and
    # reloading would reset the module back to the production sink for every
    # test that runs after this one -- reintroducing the exact contamination
    # this suite exists to prevent.
    original = os.environ[lpc.STORAGE_DIR_ENV_VAR]
    os.environ[lpc.STORAGE_DIR_ENV_VAR] = "/tmp/cryptomaster_probe_dir"
    try:
        reloaded = importlib.reload(lpc)
        assert reloaded.LOCAL_CACHE_DIR == "/tmp/cryptomaster_probe_dir"
        assert reloaded.LOCAL_DB_PATH.startswith("/tmp/cryptomaster_probe_dir")
    finally:
        os.environ[lpc.STORAGE_DIR_ENV_VAR] = original
        importlib.reload(lpc)


def test_write_to_production_path_under_pytest_is_refused(monkeypatch):
    """RED-2: fail-closed -- a test run cannot write the production sink."""
    assert hasattr(lpc, "_assert_not_production_sink"), \
        "no production-sink guard exists"

    # Simulate the exact pre-fix condition: the module pointed at the real,
    # CWD-relative production path while running under pytest.
    monkeypatch.setattr(lpc, "LOCAL_CACHE_DIR", PROD_DEFAULT)
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", f"{PROD_DEFAULT}/cache.sqlite")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe::test")

    with pytest.raises(RuntimeError, match="production"):
        lpc._assert_not_production_sink()


def test_conftest_redirects_the_sink_away_from_production():
    """RED-3: the live sink during this very test session is NOT production."""
    resolved = os.path.abspath(lpc.LOCAL_DB_PATH)
    prod = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), PROD_DEFAULT, "cache.sqlite")
    )
    assert resolved != prod, (
        "the test session is still pointed at the production cache.sqlite; "
        f"resolved={resolved}"
    )


def test_a_real_close_write_lands_in_the_redirected_sink():
    """RED-4: save_closed_trade() writes to the redirected sink, end to end."""
    trade = {
        "trade_id": "paper_sinkprobe01",
        "symbol": "BTCUSDT",
        "entry_ts": 1_700_000_000.0,
        "exit_ts": 1_700_000_060.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl_usd": 1.0,
        "pnl_pct": 1.0,
        "win": 1,
        "exit_reason": "TP",
        "regime": "BULL_TREND",
        "side": "BUY",
    }
    lpc.save_closed_trade(trade)

    conn = sqlite3.connect(f"file:{lpc.LOCAL_DB_PATH}?mode=ro", uri=True, timeout=2)
    try:
        row = conn.execute(
            "SELECT symbol FROM closed_trades WHERE trade_id=?",
            ("paper_sinkprobe01",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == "BTCUSDT"
