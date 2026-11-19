# -*- coding: utf-8 -*-
"""Collection-time import of local_persistent_cache must not write the runtime DB (2026-11-18).

Runs a nested pytest from the root of an isolated copy (tmp_path) whose
local_learning_storage/cache.sqlite is a SYNTHETIC older-schema database. The real
local_learning_storage/** is never opened by the nested run.
"""
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "conftest.py"
PROBE = (
    "import src.services.local_persistent_cache as lpc  # module-level, like test_dashboard_contract_fixes\n"
    "def test_probe():\n"
    "    assert lpc.LOCAL_DB_PATH\n"
)
OLD_CONFTEST = (  # the pre-fix form: only sys.path, no isolation
    "import sys\nfrom pathlib import Path\n"
    "project_root = Path(__file__).parent.parent\n"
    "sys.path.insert(0, str(project_root))\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(tmp_path: Path, conftest_text: str) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "src", root / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(conftest_text, encoding="utf-8")
    (root / "tests" / "test_probe.py").write_text(PROBE, encoding="utf-8")
    # Synthetic "runtime" DB with an OLDER schema: build the current one, then drop `side`, a column
    # that _init_db() re-adds via ALTER in every version of the module (not just the working tree).
    builder = tmp_path / "builder"
    builder.mkdir()
    code = "import sys; sys.path.insert(0, sys.argv[1]); import src.services.local_persistent_cache"
    subprocess.run([sys.executable, "-B", "-c", code, str(root)], cwd=builder, check=True, capture_output=True)
    db = root / "local_learning_storage" / "cache.sqlite"
    db.parent.mkdir()
    shutil.copy(builder / "local_learning_storage" / "cache.sqlite", db)
    with sqlite3.connect(db) as conn:
        conn.execute("insert into closed_trades (trade_id, symbol, entry_ts, pnl_usd) values ('syn','X',1.0,0.1)")
        conn.execute("alter table closed_trades drop column side")
    return root


def _run_pytest(root: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    return subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_probe.py"],
                          cwd=root, capture_output=True, text=True, env=env)


@pytest.fixture
def real_db_guard():
    real = ROOT / "local_learning_storage" / "cache.sqlite"
    before = _sha(real) if real.exists() else None
    yield
    assert (_sha(real) if real.exists() else None) == before, "real runtime DB changed"


def test_fixed_conftest_keeps_runtime_db_unchanged(tmp_path, real_db_guard):
    root = _tree(tmp_path, CONFTEST.read_text(encoding="utf-8"))
    db = root / "local_learning_storage" / "cache.sqlite"
    before = _sha(db)
    out = _run_pytest(root)
    assert out.returncode == 0, out.stdout + out.stderr
    assert _sha(db) == before


def test_old_conftest_form_writes_runtime_db(tmp_path, real_db_guard):
    """Control: proves the hazard is real (and that this test would catch a regression)."""
    root = _tree(tmp_path, OLD_CONFTEST)
    db = root / "local_learning_storage" / "cache.sqlite"
    before = _sha(db)
    out = _run_pytest(root)
    assert out.returncode == 0, out.stdout + out.stderr
    assert _sha(db) != before
    cols = [r[1] for r in sqlite3.connect(db).execute("pragma table_info(closed_trades)")]
    assert "side" in cols  # the import-time ALTER ran on the "runtime" DB


def test_detection_fails_the_run_if_prevention_is_bypassed(tmp_path, real_db_guard):
    text = CONFTEST.read_text(encoding="utf-8").replace("\n_isolate_local_cache_module()\n", "\n")
    assert "\n_isolate_local_cache_module()\n" not in text
    root = _tree(tmp_path, text)
    out = _run_pytest(root)
    assert out.returncode != 0
    assert "PROTECTED RUNTIME FILES CHANGED DURING TESTS" in out.stderr
    assert "cache.sqlite" in out.stderr


WRITER_PROBE = (
    "from pathlib import Path\n"
    "def test_writes():\n"
    "    Path({target!r}).parent.mkdir(parents=True, exist_ok=True)\n"
    "    Path({target!r}).write_text('changed', encoding='utf-8')\n"
)


@pytest.mark.parametrize("target, preexisting", [
    ("server_local_backups/learning_state_phase1.json", True),      # 2026-11-19 incident shape
    ("data/paper_open_positions.json", True),
    ("src/runtime/v5_trade_outbox.sqlite", False),                  # new file under a runtime dir
    ("runtime/anything.json", False),
])
def test_detection_covers_all_protected_files_and_runtime_dirs(tmp_path, real_db_guard, target, preexisting):
    root = _tree(tmp_path, CONFTEST.read_text(encoding="utf-8"))
    path = root / target
    if preexisting:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original", encoding="utf-8")
    (root / "tests" / "test_probe.py").write_text(WRITER_PROBE.format(target=target), encoding="utf-8")
    out = _run_pytest(root)
    assert out.returncode != 0, out.stdout + out.stderr
    assert "PROTECTED RUNTIME FILES CHANGED DURING TESTS" in out.stderr
    assert target in out.stderr.replace("\\", "/")


REWRITE_PROBE = (
    "import os\nfrom pathlib import Path\n"
    "def test_rewrite():\n"
    "    p = Path({target!r})\n"
    "    st = p.stat()\n"
    "    p.write_bytes(b'BBBB')  # same size as the original b'AAAA'\n"
    "    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # restore the timestamp\n"
)
DELETE_PROBE = "from pathlib import Path\ndef test_delete():\n    Path({target!r}).unlink()\n"


@pytest.mark.parametrize("target", ["runtime/sample.sqlite", "src/runtime/v5_trade_outbox.sqlite",
                                    "runtime/v5_quota_usage.sqlite"])
def test_detection_catches_same_size_rewrite_with_restored_mtime(tmp_path, real_db_guard, target):
    """Review 2026-11-19 B1: size + mtime alone missed this."""
    root = _tree(tmp_path, CONFTEST.read_text(encoding="utf-8"))
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_bytes(b"AAAA")
    (root / "tests" / "test_probe.py").write_text(REWRITE_PROBE.format(target=target), encoding="utf-8")
    out = _run_pytest(root)
    assert out.returncode != 0, out.stdout + out.stderr
    assert target in out.stderr.replace("\\", "/")


@pytest.mark.parametrize("target", ["runtime/sample.sqlite", "server_local_backups/paper_adaptive_learning_state.json"])
def test_detection_catches_deleted_existing_file(tmp_path, real_db_guard, target):
    root = _tree(tmp_path, CONFTEST.read_text(encoding="utf-8"))
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_text("x", encoding="utf-8")
    (root / "tests" / "test_probe.py").write_text(DELETE_PROBE.format(target=target), encoding="utf-8")
    out = _run_pytest(root)
    assert out.returncode != 0, out.stdout + out.stderr
    assert target in out.stderr.replace("\\", "/")


def test_every_agents_md_protected_file_is_guarded():
    import re
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`((?:local_learning_storage|data|server_local_backups|runtime|src/runtime)/[\w./]+)`",
                            agents.split("## Runtime data", 1)[1].split("## Nikdy", 1)[0]))
    guarded = set(re.findall(r'^\s+"([\w./]+)",$', CONFTEST.read_text(encoding="utf-8"), re.M))
    assert len(listed) == 6 and listed <= guarded


def test_detection_quiet_when_nothing_protected_changes(tmp_path, real_db_guard):
    root = _tree(tmp_path, CONFTEST.read_text(encoding="utf-8"))
    (root / "server_local_backups").mkdir()
    (root / "server_local_backups" / "learning_state_phase1.json").write_text("x", encoding="utf-8")
    (root / "tests" / "test_probe.py").write_text(WRITER_PROBE.format(target="scratch/out.txt"), encoding="utf-8")
    out = _run_pytest(root)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PROTECTED RUNTIME FILES CHANGED" not in out.stderr
