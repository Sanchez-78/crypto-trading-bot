# -*- coding: utf-8 -*-
"""Readiness under the real dashboard sandbox model (2026-11-18 post-C1 audit, P2).

The dashboard unit has InaccessiblePaths=/opt/cryptomaster/.env. Importing
paper_trade_executor (module-level load_dotenv) from readiness_monitor raised
Permission denied every minute. These tests reproduce that sandbox in-process:
.env reads raise PermissionError, paper_trade_executor cannot be imported,
threads/sqlite outside tmp are forbidden during import, and both modules are
imported fresh with TRADING_MODE=paper_train.
"""
import builtins
import importlib
import importlib.abc
import os
import sqlite3
import sys
import threading

import pytest

pytest.importorskip("flask")


class _BlockExecutor(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "src.services.paper_trade_executor":
            raise PermissionError("[Errno 13] Permission denied: '/opt/cryptomaster/.env' (simulated)")
        return None


@pytest.fixture
def sandboxed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADING_MODE", "paper_train")
    monkeypatch.setenv("DASHBOARD_SECURITY_ENABLED", "0")
    monkeypatch.setenv("DASHBOARD_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("DASHBOARD_AUTH_DISABLED", "1")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    env_reads = []
    real_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        if os.path.basename(str(file)) == ".env":
            env_reads.append(str(file))
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    real_connect = sqlite3.connect
    tmp = str(tmp_path.resolve())

    def guarded_connect(database, *args, **kwargs):
        target = str(database).removeprefix("file:").split("?")[0]
        if not os.path.realpath(target).startswith(tmp):
            raise AssertionError(f"sqlite outside tmp: {database}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    blocker = _BlockExecutor()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])
    import src.services as services_pkg
    for name in ("src.services.dashboard_web", "src.services.readiness_monitor",
                 "src.services.paper_trade_executor"):
        monkeypatch.delitem(sys.modules, name, raising=False)
        # A fresh import also rebinds the package attribute; restore it on teardown
        # so later tests patch the same module object their endpoints import.
        short = name.rsplit(".", 1)[1]
        monkeypatch.setattr(services_pkg, short, getattr(services_pkg, short, None), raising=False)
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name))
    readiness = importlib.import_module("src.services.readiness_monitor")
    dashboard = importlib.import_module("src.services.dashboard_web")
    import_threads = list(started)
    return readiness, dashboard, env_reads, import_threads


def test_readiness_module_has_no_import_side_effects(sandboxed):
    readiness, _dashboard, env_reads, import_threads = sandboxed
    assert import_threads == []  # no monitoring thread auto-started in paper mode
    assert readiness.get_current_metrics() is None
    assert env_reads == []
    assert "src.services.paper_trade_executor" not in sys.modules


def test_readiness_endpoint_reports_paper_only_without_env_or_executor(sandboxed):
    _readiness, dashboard, env_reads, _ = sandboxed
    resp = dashboard.app.test_client().get("/api/dashboard/readiness")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "paper_only"
    assert data["is_ready_for_trading"] is False  # never a fake ready=true
    assert data["readiness_score"] == 0
    assert data["blocker_reasons"] == ["paper_only_policy"]
    assert "error" not in data
    assert env_reads == []
    assert "src.services.paper_trade_executor" not in sys.modules


def test_metrics_endpoint_still_works_with_inaccessible_env(sandboxed):
    _readiness, dashboard, env_reads, _ = sandboxed
    resp = dashboard.app.test_client().get("/api/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("open_positions", "total_trades", "win_rate_pct", "profit_factor", "last_update_utc"):
        assert key in data, key
    assert env_reads == []
    assert "src.services.paper_trade_executor" not in sys.modules
