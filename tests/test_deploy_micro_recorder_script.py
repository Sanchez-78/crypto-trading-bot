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
  show) if [[ "$*" == *MainPID*cryptomaster.service* ]]; then echo 4242; elif [[ "$*" == *MemoryCurrent* ]]; then cat "$S/mem" 2>/dev/null || echo 1000; else echo "MainPID=77"; fi ;;
  is-active) cat "$S/active"; [[ "$(cat "$S/active")" == active ]] ;;
  disable|enable|daemon-reload) [[ "$*" == *disable* ]] && echo inactive > "$S/active"; exit 0 ;;
esac''')
    stub(bin_, "systemd-analyze", "exit 0")
    stub(bin_, "journalctl", f'cat "{state.as_posix()}/journal" 2>/dev/null; exit 0')
    stub(bin_, "curl", f'cat "{state.as_posix()}/http" 2>/dev/null || echo -n 200')
    stub(bin_, "df", "echo Avail; echo 99999999")
    stub(bin_, "chown", "exit 0")
    stub(bin_, "sleep", "exit 0")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:    2000000 kB\n")
    py = Path(sys.executable).as_posix()
    e = dict(os.environ, PATH=bin_.as_posix() + os.pathsep + os.environ.get("PATH", ""),
             UNIT_DIR=(tmp_path / "units").as_posix(), APP_DIR=(tmp_path / "app").as_posix(),
             DATA_DIR=data.as_posix(), TICK_LOG=(tmp_path / "tick.log").as_posix(),
             FORENSICS_ROOT=tmp_path.as_posix(), MEMINFO=meminfo.as_posix(), PY=py, CHECK_WAIT="0")
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
