"""Regression tests for the exit-taxonomy deploy script's fail-closed checks (Codex re-review D4/D5,
dangling symlink, partial rollback). The script is sourced into bash with systemctl/journalctl/curl
replaced by shell functions; file checks run against a temporary LIVE tree. Nothing touches /opt."""
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "_workspace" / "exit_taxonomy_release_20261125"
SCRIPT = REL / "deploy_exit_taxonomy.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")
EXISTING = ("dashboard_web.py", "dashboard_read_model.py", "performance_epoch.py")


def run(body: str, live: Path | None = None) -> subprocess.CompletedProcess:
    env_live = f"EXIT_TAXONOMY_TEST_LIVE='{live.as_posix()}' " if live else ""
    script = f"set -uo pipefail; {env_live}source ./deploy_exit_taxonomy.sh; {body}"
    return subprocess.run([BASH, "-c", script], cwd=REL, capture_output=True, text=True, timeout=60)


def status(body: str, live: Path | None = None) -> int:
    return run(body, live).returncode


# ── D4: journal check is fail-closed ──────────────────────────────────────────

@pytest.mark.parametrize("stub,expected", [
    ("journalctl() { return 1; }", 1),                                              # unreadable
    ("journalctl() { :; }", 1),                                                     # empty = not proven
    ("journalctl() { echo 'Traceback (most recent call last):'; yes filler | head -n 200000; }", 1),
    ("journalctl() { echo ok; yes 'normal line' | head -n 50000; echo 'x Traceback y'; }", 1),
    ("journalctl() { echo 'Started CryptoMaster Dashboard'; echo '[DASHBOARD] INFO: up'; }", 0),
])
def test_journal_check_fails_closed(stub, expected):
    assert status(f"{stub}; journal_clean_since '2026-11-25 00:00:00 UTC'") == expected


def test_the_old_negated_pipeline_really_was_fail_open():
    # Documents the bug the fix removes (Codex repro): both cases counted as "clean".
    assert status("! false | grep -q Traceback") == 0
    assert status("! (printf 'Traceback\\n'; yes filler) | grep -q Traceback") == 0


# ── D5: PID and HTTP profile must be read, never compared empty == empty ─────

@pytest.mark.parametrize("stub,ok", [
    ("systemctl() { return 1; }", False),
    ("systemctl() { echo ''; }", False),
    ("systemctl() { echo 0; }", False),
    ("systemctl() { echo abc; }", False),
    ("systemctl() { echo 3840326; }", True),
])
def test_bot_pid_requires_a_positive_number(stub, ok):
    result = run(f"{stub}; bot_pid")
    assert (result.returncode == 0) is ok
    if ok:
        assert result.stdout.strip() == "3840326"


@pytest.mark.parametrize("stub,ok", [
    ("curl() { return 7; }", False),                       # connection refused
    ("curl() { printf 000; return 0; }", False),           # no HTTP answer
    ("curl() { printf ''; }", False),
    ("curl() { printf 200; }", True),
])
def test_profile_requires_all_eight_codes(stub, ok):
    result = run(f"{stub}; p=\"$(profile)\" || exit 9; [[ \"$p\" == \"$EXPECTED_PROFILE\" ]]")
    assert (result.returncode == 0) is ok


@pytest.mark.parametrize("stub,ok", [
    ("curl() { return 7; }", False), ("curl() { printf 000; }", False), ("curl() { printf 2000; }", False),
    ("curl() { printf ''; }", False), ("curl() { printf 401; }", True), ("curl() { printf 200; }", True),
])
def test_http_code_itself_rejects_curl_failures(stub, ok):
    # the function contract, independent of the later profile comparison
    assert (status(f"{stub}; http_code http://127.0.0.1:5001/") == 0) is ok


def test_profile_mismatch_is_detected():
    stub = "curl() { case \"$*\" in *78.47.2.198*/api/metrics*) printf 401;; *) printf 200;; esac; }"
    assert status(f"{stub}; p=\"$(profile)\" || exit 9; [[ \"$p\" == \"$EXPECTED_PROFILE\" ]]") == 1


# ── absence check and rollback gates on a temporary LIVE tree ────────────────

def _live(tmp_path: Path, state: str) -> Path:
    live = tmp_path / "live"
    services = live / "src" / "services"
    services.mkdir(parents=True)
    source = REL / ("preimage" if state == "pre" else "postimage")
    for name in EXISTING:
        shutil.copyfile(source / name, services / name)
    if state == "post":
        shutil.copyfile(REL / "postimage" / "exit_taxonomy.py", services / "exit_taxonomy.py")
    return live


def _backup(tmp_path: Path, corrupt: str | None = None) -> Path:
    backup = tmp_path / "backup"
    backup.mkdir()
    for name in EXISTING:
        shutil.copyfile(REL / "preimage" / name, backup / name)
    if corrupt:
        (backup / corrupt).write_bytes(b"corrupt")
    return backup


def _hashes(live: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (live / "src" / "services").iterdir()}


def test_dangling_symlink_is_not_absent(tmp_path):
    link = tmp_path / "exit_taxonomy.py"
    made = run(f"ln -s '{(tmp_path / 'missing').as_posix()}' '{link.as_posix()}' && [[ -L '{link.as_posix()}' ]]")
    if made.returncode != 0:
        pytest.skip("this bash cannot create a real symlink (Windows without symlink privilege)")
    assert status(f"absent '{link.as_posix()}'") == 1
    assert status(f"absent '{(tmp_path / 'nothing').as_posix()}'") == 0


def test_manual_rollback_requires_the_exact_installed_post_set(tmp_path):
    post = _live(tmp_path / "a", "post")
    assert status("rollback_state_ok manual", post) == 0
    pre = _live(tmp_path / "b", "pre")
    assert status("rollback_state_ok manual", pre) == 1               # would overwrite another state
    mixed = _live(tmp_path / "c", "post")
    shutil.copyfile(REL / "preimage" / "dashboard_web.py", mixed / "src/services/dashboard_web.py")
    assert status("rollback_state_ok manual", mixed) == 1


def test_auto_rollback_accepts_only_pre_post_mixes(tmp_path):
    partial = _live(tmp_path / "a", "pre")   # crash after the new module, before the rest
    shutil.copyfile(REL / "postimage" / "exit_taxonomy.py", partial / "src/services/exit_taxonomy.py")
    assert status("rollback_state_ok auto", partial) == 0
    foreign = _live(tmp_path / "b", "pre")
    (foreign / "src/services/dashboard_read_model.py").write_bytes(b"# someone else's deploy\n")
    assert status("rollback_state_ok auto", foreign) == 1
    foreign_module = _live(tmp_path / "c", "pre")
    (foreign_module / "src/services/exit_taxonomy.py").write_bytes(b"# foreign\n")
    assert status("rollback_state_ok auto", foreign_module) == 1


def test_rollback_with_a_corrupt_backup_writes_nothing(tmp_path):
    live = _live(tmp_path, "post")
    before = _hashes(live)
    backup = _backup(tmp_path, corrupt="performance_epoch.py")   # third file corrupt, first two fine
    result = run(f"do_rollback '{backup.as_posix()}' manual 1", live)
    assert result.returncode == 1 and "missing/corrupt" in result.stdout
    assert _hashes(live) == before                                     # no partial restore


def test_rollback_on_a_foreign_live_state_writes_nothing(tmp_path):
    live = _live(tmp_path, "pre")   # not our installed state
    before = _hashes(live)
    result = run(f"do_rollback '{_backup(tmp_path).as_posix()}' manual 1", live)
    assert result.returncode == 1 and "not the installed postimage" in result.stdout
    assert _hashes(live) == before


def test_script_parses_and_main_does_not_run_when_sourced():
    assert subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True).returncode == 0
    assert status("true") == 0   # sourcing alone must not call main (which would demand root)
