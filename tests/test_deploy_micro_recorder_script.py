"""Bash tests of the phased recorder deploy script with stubbed system commands (no root, no systemd)."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "_workspace" / "micro_recorder_release"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def stub(dirpath: Path, name: str, body: str) -> None:
    p = dirpath / name
    p.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
    p.chmod(0o755)


@pytest.fixture()
def env(tmp_path):
    rel = tmp_path / "rel"
    shutil.copytree(REL, rel)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "active").write_text("active")
    data = tmp_path / "data"
    (data / "gaps").mkdir(parents=True)
    (data / "gaps" / "2026-11-26.csv.gz").write_bytes(b"x")
    stub(bin_, "systemctl", f'''
S="{state.as_posix()}"
echo "$*" >> "$S/calls"
case "$1" in
  show) if [[ "$*" == *MainPID*cryptomaster.service* ]]; then echo 4242; elif [[ "$*" == *MainPID*--value*tick-recorder* ]]; then echo 77; elif [[ "$*" == *MemoryCurrent* ]]; then cat "$S/mem" 2>/dev/null || echo 1000; else echo "MainPID=77"; fi ;;
  is-active) cat "$S/active"; [[ "$(cat "$S/active")" == active ]] ;;
  enable) [[ -f "$S/enable_fails" ]] && exit 1; exit 0 ;;
  disable|daemon-reload) [[ "$*" == *disable* ]] && echo inactive > "$S/active"; exit 0 ;;
esac''')
    stub(bin_, "systemd-analyze", f'[[ -f "{state.as_posix()}/verify_fails" ]] && exit 1; exit 0')
    # fake /proc: fd entries are plain files holding the link target; readlink/stat stubs read them
    stub(bin_, "readlink", 'if [[ "$1" == */fd/* && -f "$1" ]]; then cat "$1"; else exec /usr/bin/readlink "$@"; fi')
    stub(bin_, "stat", 'if [[ "$*" == */fd/* ]]; then echo 1271099392; else exec /usr/bin/stat "$@"; fi')
    proc = tmp_path / "proc"
    (proc / "77" / "fd").mkdir(parents=True)
    (proc / "77" / "cmdline").write_bytes(b"/opt/cryptomaster/venv/bin/python3\0/opt/cryptomaster/tick_recorder.py\0")
    (proc / "77" / "fd" / "1").write_text("/tmp/tick_recorder.log")
    (proc / "77" / "fd" / "3").write_text("/opt/cryptomaster/local_learning_storage/tick_l1.sqlite (deleted)")
    stub(bin_, "journalctl", f'cat "{state.as_posix()}/journal" 2>/dev/null; exit 0')
    stub(bin_, "curl", f'cat "{state.as_posix()}/http" 2>/dev/null || echo -n 200')
    stub(bin_, "df", "echo Avail; echo 99999999")
    stub(bin_, "chown", f'[[ -f "{state.as_posix()}/chown_fails" ]] && exit 1; exit 0')
    stub(bin_, "sleep", "exit 0")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:    2000000 kB\n")
    py = Path(sys.executable).as_posix()
    e = dict(os.environ, PATH=bin_.as_posix() + os.pathsep + os.environ.get("PATH", ""),
             UNIT_DIR=(tmp_path / "units").as_posix(), APP_DIR=(tmp_path / "app").as_posix(),
             DATA_DIR=data.as_posix(), TICK_LOG=(tmp_path / "tick.log").as_posix(),
             FORENSICS_ROOT=tmp_path.as_posix(), MEMINFO=meminfo.as_posix(), PY=py, CHECK_WAIT="0",
             PROC_ROOT=proc.as_posix(), MICRO_DEPLOY_TEST_MODE="1")
    (tmp_path / "units").mkdir()
    return {"rel": rel, "env": e, "state": state, "tmp": tmp_path}


def run(env, phase):
    return subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), phase],
                          env=env["env"], capture_output=True, text=True, timeout=120)


def test_pins_match_the_release_files():
    text = (REL / "deploy_micro_recorder.sh").read_text(encoding="utf-8")
    for name, var in (("micro_recorder.py", "SCRIPT_SHA"), ("cryptomaster-micro-recorder.service", "UNIT_SHA")):
        digest = hashlib.sha256((REL / name).read_bytes()).hexdigest()
        assert f'{var}="{digest}"' in text
    assert (REL / "micro_recorder.py").read_bytes() == (ROOT / "scripts" / "research" / "micro_recorder.py").read_bytes()


def test_preflight_refuses_a_changed_script(env):
    with open(env["rel"] / "micro_recorder.py", "a", encoding="utf-8") as fh:
        fh.write("# changed\n")
    r = run(env, "preflight")
    assert r.returncode != 0 and "micro_recorder.py != pin" in r.stderr


def test_install_success_places_pinned_files(env):
    r = run(env, "install")
    assert r.returncode == 0, r.stderr
    assert "INSTALL_OK" in r.stdout and "CHECKS_OK" in r.stdout
    assert (env["tmp"] / "app" / "micro_recorder.py").exists()
    assert (env["tmp"] / "units" / "cryptomaster-micro-recorder.service").exists()


@pytest.mark.parametrize("fault", ["inactive", "memory", "journal", "http"])
def test_failed_checks_after_install_roll_back(env, fault):
    st = env["state"]
    if fault == "inactive":
        (st / "active").write_text("failed")
    elif fault == "memory":
        (st / "mem").write_text(str(200 * 1024 * 1024))
    elif fault == "journal":
        (st / "journal").write_text("Traceback (most recent call last)\n")
    else:
        (st / "http").write_text("500")
    r = run(env, "install")
    assert r.returncode != 0
    assert "rollback" in r.stderr and "ROLLBACK_OK" in r.stdout
    assert not (env["tmp"] / "app" / "micro_recorder.py").exists()
    assert not (env["tmp"] / "units" / "cryptomaster-micro-recorder.service").exists()


def test_rollback_leaves_a_non_pinned_unit_in_place(env):
    unit = env["tmp"] / "units" / "cryptomaster-micro-recorder.service"
    unit.write_text("someone else's unit\n")
    r = run(env, "rollback")
    assert r.returncode == 0 and "not the pinned file" in r.stdout and unit.exists()


def test_stop_tick_archives_forensics_and_keeps_the_log(env):
    log = env["tmp"] / "tick.log"
    log.write_text("start\n" + "flush err attempt to write a readonly database\n" * 5, encoding="utf-8")
    before = log.read_bytes()
    r = run(env, "stop-tick")
    assert r.returncode == 0, r.stderr
    assert "TICK_STOPPED" in r.stdout and log.read_bytes() == before
    forensic = next(env["tmp"].glob("tick-recorder-forensics-*"))
    state = (forensic / "state.txt").read_text()
    assert f"log_sha256={hashlib.sha256(before).hexdigest()}" in state and "readonly_errors=5" in state
    assert (forensic / "tick_recorder.log.gz").exists()
    assert "disable --now tick-recorder.service" in (env["state"] / "calls").read_text()


@pytest.mark.parametrize("fault", ["inactive", "other_process", "db_not_held"])
def test_stop_tick_refuses_when_the_broken_state_changed(env, fault):
    (env["tmp"] / "tick.log").write_text("x\n", encoding="utf-8")
    proc = env["tmp"] / "proc" / "77"
    if fault == "inactive":
        (env["state"] / "active").write_text("inactive")
    elif fault == "other_process":
        (proc / "cmdline").write_bytes(b"/usr/bin/python3\0/opt/other.py\0")
    else:
        (proc / "fd" / "3").write_text("/opt/cryptomaster/local_learning_storage/tick_l1.sqlite")   # repaired
    r = run(env, "stop-tick")
    assert r.returncode != 0 and "FAIL" in r.stderr
    calls = (env["state"] / "calls").read_text() if (env["state"] / "calls").exists() else ""
    assert "disable" not in calls
    assert not list(env["tmp"].glob("tick-recorder-forensics-*"))


def test_production_mode_refuses_path_overrides(env):
    e = dict(env["env"])
    del e["MICRO_DEPLOY_TEST_MODE"]
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "preflight"],
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "override not allowed" in r.stderr


def test_preflight_writes_nothing(env):
    before = sorted(p.relative_to(env["rel"]).as_posix() for p in env["rel"].rglob("*"))
    r = run(env, "preflight")
    assert r.returncode == 0, r.stderr
    assert sorted(p.relative_to(env["rel"]).as_posix() for p in env["rel"].rglob("*")) == before


@pytest.mark.parametrize("fault", ["verify_fails", "enable_fails", "chown_fails"])
def test_install_failure_in_systemd_or_copy_rolls_back_and_cleans_temp(env, fault):
    (env["state"] / fault).write_text("1")
    r = run(env, "install")
    assert r.returncode != 0 and "ROLLBACK_OK" in r.stdout
    assert not (env["tmp"] / "app" / "micro_recorder.py").exists()
    assert not (env["tmp"] / "units" / "cryptomaster-micro-recorder.service").exists()
    assert not list((env["tmp"] / "units").glob(".micro.*"))
    assert not (env["tmp"] / "app").exists() or not list((env["tmp"] / "app").glob(".micro.*"))
