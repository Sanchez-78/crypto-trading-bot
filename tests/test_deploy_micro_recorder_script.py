"""Bash tests of the phased recorder deploy script with stubbed system commands (no root, no systemd)."""
import hashlib
import os
import shutil
import subprocess
import sys
import time
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
  show) if [[ "$*" == *MainPID*cryptomaster.service* ]]; then echo 4242; elif [[ "$*" == *MainPID*--value*tick-recorder* ]]; then
          if [[ -s "$S/tick_pids" ]]; then head -n1 "$S/tick_pids"; sed -i 1d "$S/tick_pids"; else echo 77; fi; elif [[ "$*" == *MemoryCurrent* ]]; then cat "$S/mem" 2>/dev/null || echo 1000; else echo "MainPID=77"; fi ;;
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
    # journal lines "@EPOCH message" honour --since @N; lines without a timestamp count as current
    stub(bin_, "journalctl", f'''since=0; prev=""
for a in "$@"; do [[ "$prev" == --since ]] && since="${{a#@}}"; prev="$a"; done
[[ -f "{state.as_posix()}/journal" ]] || exit 0
while IFS= read -r line; do
  if [[ "$line" =~ ^@([0-9]+)\\ (.*)$ ]]; then (( BASH_REMATCH[1] >= since )) && echo "${{BASH_REMATCH[2]}}"
  else echo "$line"; fi
done < "{state.as_posix()}/journal"
exit 0''')
    stub(bin_, "curl", f'cat "{state.as_posix()}/http" 2>/dev/null || echo -n 200')
    stub(bin_, "df", "echo Avail; echo 99999999")
    stub(bin_, "chown", f'''[[ -f "{state.as_posix()}/chown_fails" ]] && exit 1
if [[ -n "${{CREATE_ON_CHOWN:-}}" && ! -e "$CREATE_ON_CHOWN" ]]; then
  if [[ -n "${{CREATE_FROM:-}}" ]]; then cp "$CREATE_FROM" "$CREATE_ON_CHOWN"; else echo foreign > "$CREATE_ON_CHOWN"; fi
fi
exit 0''')
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


@pytest.mark.parametrize("sub,pin", [
    ("rev6_fallback", "b09b31b1bf6bc73904a0ec702049f477f07e39ffb1d65369b0d6bcce1847d466"),
    ("rev5_fallback", "252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172")])
def test_fallback_scripts_differ_only_in_the_recorder_pin(sub, pin):
    main = (REL / "deploy_micro_recorder.sh").read_text(encoding="utf-8").splitlines()
    fb = (REL / sub / "deploy_micro_recorder.sh").read_text(encoding="utf-8").splitlines()
    assert [x for x in fb if not x.startswith("SCRIPT_SHA=")] == [x for x in main if not x.startswith("SCRIPT_SHA=")]
    assert [x for x in fb if x.startswith("SCRIPT_SHA=")] == [f'SCRIPT_SHA="{pin}"']
    if sub == "rev6_fallback":
        assert f'PREV_SCRIPT_SHA="{pin}"' in (REL / "deploy_micro_recorder.sh").read_text(encoding="utf-8")


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


def test_stop_tick_reverifies_right_before_disable(env):
    (env["tmp"] / "tick.log").write_text("x\n", encoding="utf-8")
    proc = env["tmp"] / "proc"
    shutil.copytree(proc / "77", proc / "78")              # same broken state, but a NEW process
    (env["state"] / "tick_pids").write_text("77\n78\n")    # first check sees 77, re-check sees 78
    r = run(env, "stop-tick")
    assert r.returncode != 0 and "changed during forensics" in r.stderr
    assert "disable" not in (env["state"] / "calls").read_text()


def test_rollback_removes_only_its_own_temp_files(env):
    foreign = env["tmp"] / "units" / ".micro.foreign"
    foreign.write_text("other operation\n")
    (env["state"] / "verify_fails").write_text("1")
    r = run(env, "install")
    assert r.returncode != 0 and "ROLLBACK_OK" in r.stdout
    assert foreign.read_text() == "other operation\n"


def test_target_created_after_preflight_is_never_overwritten(env):
    unit = env["tmp"] / "units" / "cryptomaster-micro-recorder.service"
    e = dict(env["env"], CREATE_ON_CHOWN=unit.as_posix())   # appears between preflight and placement
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "install"],
                       env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "not overwriting" in r.stderr and "ROLLBACK_OK" in r.stdout
    assert unit.read_text() == "foreign\n"                    # foreign target kept, not replaced
    assert not (env["tmp"] / "app" / "micro_recorder.py").exists()
    assert not list((env["tmp"] / "units").glob(".micro.*"))


def test_symlinked_target_directory_is_refused(env, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "linked_app"
    try:
        os.symlink(real, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform")
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "preflight"],
                       env=dict(env["env"], APP_DIR=link.as_posix()), capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "contains a symlink" in r.stderr


def test_auto_rollback_keeps_a_concurrent_target_even_with_the_exact_pinned_bytes(env):
    unit = env["tmp"] / "units" / "cryptomaster-micro-recorder.service"
    pinned = env["rel"] / "cryptomaster-micro-recorder.service"
    e = dict(env["env"], CREATE_ON_CHOWN=unit.as_posix(), CREATE_FROM=pinned.as_posix())
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "install"],
                       env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "not overwriting" in r.stderr and "ROLLBACK_OK" in r.stdout
    assert unit.read_bytes() == pinned.read_bytes()          # created by someone else -> kept
    assert "not created by this run" in r.stdout
    assert not (env["tmp"] / "app" / "micro_recorder.py").exists()   # ours -> removed
    calls = (env["state"] / "calls").read_text()
    assert "disable --now cryptomaster-micro-recorder.service" not in calls   # foreign unit not stopped


def dynamic_user_layout(env, link_target="private/data", priv_mode=0o700, priv_is_link=False, inner_is_link=False,
                        parent_is_link=False):
    """Data dir as systemd leaves it after a DynamicUser StateDirectory: lib/data -> private/data (upgrade case)."""
    lib = env["tmp"] / ("lib_real" if parent_is_link else "lib")
    lib.mkdir()
    if parent_is_link:
        try:
            os.symlink(lib, env["tmp"] / "lib", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available on this platform")
    real_priv = lib / ("real_private" if priv_is_link else "private")
    real_priv.mkdir()
    inner = real_priv / "data"
    if inner_is_link:
        (lib / "inner_real").mkdir()
        (lib / "inner_real" / "gaps").mkdir()
        (lib / "inner_real" / "gaps" / "2026-11-26.csv.gz").write_bytes(b"x")
        try:
            os.symlink(lib / "inner_real", inner, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available on this platform")
    else:
        (inner / "gaps").mkdir(parents=True)
        (inner / "gaps" / "2026-11-26.csv.gz").write_bytes(b"x")
    try:
        if priv_is_link:
            os.symlink(real_priv, lib / "private", target_is_directory=True)
        os.symlink(link_target, lib / "data", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform")
    real_priv.chmod(priv_mode)
    return dict(env["env"], DATA_DIR=(env["tmp"] / "lib" / "data").as_posix())


def test_preflight_accepts_the_exact_dynamic_user_state_directory_link(env):
    e = dynamic_user_layout(env)
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "preflight"],
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "PREFLIGHT_OK" in r.stdout, r.stderr


@pytest.mark.parametrize("variant", ["other_target", "private_not_0700", "private_is_link", "inner_is_link",
                                     "parent_is_link"])
def test_preflight_refuses_any_other_data_symlink(env, variant):
    kw = {"other_target": {"link_target": "real_private/data"},
          "private_not_0700": {"priv_mode": 0o755},
          "private_is_link": {"priv_is_link": True},
          "inner_is_link": {"inner_is_link": True},
          "parent_is_link": {"parent_is_link": True}}[variant]
    e = dynamic_user_layout(env, **kw)
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "preflight"],
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "not the systemd StateDirectory link" in r.stderr


def test_upgrade_install_over_kept_dynamic_user_data(env):
    e = dynamic_user_layout(env)
    marker = env["tmp"] / "lib" / "private" / "data" / "gaps" / "2026-11-26.csv.gz"
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "install"],
                       env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "INSTALL_OK" in r.stdout, r.stderr
    assert marker.read_bytes() == b"x" and (env["tmp"] / "lib" / "data").is_symlink()


PREV_BYTES = b"previous revision\n"


def set_pin(script: Path, var: str, value: str) -> None:
    text = script.read_text(encoding="utf-8")
    start = text.index(f'\n{var}="') + len(f'\n{var}="')
    script.write_text(text[:start] + value + text[start + 64:], encoding="utf-8", newline="\n")


def installed_previous_revision(env, recorder=PREV_BYTES, unit=None, fallback=True):
    """Installed previous release + its fallback release dir; the copied script's PREV pin -> the fake recorder."""
    (env["tmp"] / "app").mkdir()
    (env["tmp"] / "app" / "micro_recorder.py").write_bytes(recorder)
    pinned_unit = (env["rel"] / "cryptomaster-micro-recorder.service").read_bytes()
    (env["tmp"] / "units" / "cryptomaster-micro-recorder.service").write_bytes(pinned_unit if unit is None else unit)
    prev = hashlib.sha256(PREV_BYTES).hexdigest()
    script = env["rel"] / "deploy_micro_recorder.sh"
    set_pin(script, "PREV_SCRIPT_SHA", prev)
    fb = env["tmp"] / "fallback"
    if fallback:
        fb.mkdir()
        (fb / "micro_recorder.py").write_bytes(PREV_BYTES)
        (fb / "cryptomaster-micro-recorder.service").write_bytes(pinned_unit)
        shutil.copy(script, fb / "deploy_micro_recorder.sh")
        set_pin(fb / "deploy_micro_recorder.sh", "SCRIPT_SHA", prev)
    env["env"]["FALLBACK_DIR"] = fb.as_posix()
    return fb


def tree(env):
    return sorted((p.relative_to(env["tmp"]).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in env["tmp"].rglob("*") if p.is_file() and "state" not in p.parts)


def test_upgrade_check_passes_over_the_running_previous_revision_and_writes_nothing(env):
    installed_previous_revision(env)
    before = tree(env)
    r = run(env, "upgrade-check")
    assert r.returncode == 0 and "UPGRADE_CHECK_OK" in r.stdout, r.stderr
    assert tree(env) == before                                   # names AND contents unchanged
    calls = (env["state"] / "calls").read_text()
    assert "disable" not in calls and "enable" not in calls and "daemon-reload" not in calls


@pytest.mark.parametrize("fault", ["other_recorder", "other_unit", "inactive", "new_release_changed", "dashboard",
                                   "fallback_missing", "fallback_recorder", "fallback_unit", "fallback_pin",
                                   "fallback_script_changed"])
def test_upgrade_check_refuses(env, fault):
    expected = {"other_recorder": "installed recorder is not the previous pinned revision",
                "other_unit": "installed unit is not the pinned unit",
                "inactive": "not active",
                "new_release_changed": "micro_recorder.py != pin",
                "dashboard": "dashboard not 200",
                "fallback_missing": "fallback release: micro_recorder.py",
                "fallback_recorder": "fallback release: micro_recorder.py",
                "fallback_unit": "fallback release: unit != pin",
                "fallback_pin": "does not pin the previous revision",
                "fallback_script_changed": "differs from this one beyond SCRIPT_SHA"}[fault]
    if fault == "other_recorder":
        installed_previous_revision(env, recorder=b"something else\n")
    elif fault == "other_unit":
        installed_previous_revision(env, unit=b"[Unit]\n")
    elif fault == "fallback_missing":
        installed_previous_revision(env, fallback=False)
    else:
        fb = installed_previous_revision(env)
        if fault == "inactive":
            (env["state"] / "active").write_text("inactive")
        elif fault == "new_release_changed":
            with open(env["rel"] / "micro_recorder.py", "a", encoding="utf-8") as fh:
                fh.write("# changed\n")
        elif fault == "dashboard":
            (env["state"] / "http").write_text("502")
        elif fault == "fallback_recorder":
            (fb / "micro_recorder.py").write_bytes(b"other\n")
        elif fault == "fallback_unit":
            (fb / "cryptomaster-micro-recorder.service").write_bytes(b"[Unit]\n")
        elif fault == "fallback_pin":
            set_pin(fb / "deploy_micro_recorder.sh", "SCRIPT_SHA", "0" * 64)
        else:
            with open(fb / "deploy_micro_recorder.sh", "a", encoding="utf-8", newline="\n") as fh:
                fh.write("echo extra\n")
    r = run(env, "upgrade-check")
    assert r.returncode != 0 and expected in r.stderr, r.stderr


def test_install_ignores_journal_errors_from_before_this_installation(env):
    old = int(time.time()) - 3600
    (env["state"] / "journal").write_text(f"@{old} Traceback (most recent call last)\n@{old} write failed\n")
    r = run(env, "install")
    assert r.returncode == 0 and "INSTALL_OK" in r.stdout, r.stderr


@pytest.mark.parametrize("trailing_lines", [0, 3000])
def test_install_fails_on_journal_errors_after_this_installation(env, trailing_lines):
    # 3000 lines after the error (> 64 KiB pipe buffer): a `journalctl | grep -q` pipe under pipefail
    # would end in SIGPIPE and silently report "no error"
    new = int(time.time()) + 5
    filler = "".join(f"@{new} [MICRO] messages in the last hour: {{\"public\": {i}}}\n" for i in range(trailing_lines))
    (env["state"] / "journal").write_text(f"@{new} [MICRO] write failed, exiting for a systemd restart\n" + filler)
    r = run(env, "install")
    assert r.returncode != 0 and "errors in journal since installation" in r.stderr and "ROLLBACK_OK" in r.stdout


def test_python_probes_never_write_bytecode(env, tmp_path):
    log = tmp_path / "py_calls"
    wrapper = tmp_path / "pywrap"
    wrapper.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log.as_posix()}"\n'
                       f'exec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8", newline="\n")
    wrapper.chmod(0o755)
    r = subprocess.run([BASH, (env["rel"] / "deploy_micro_recorder.sh").as_posix(), "preflight"],
                       env=dict(env["env"], PY=wrapper.as_posix()), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    assert len(calls) >= 2 and all(c.split()[:2] == ["-I", "-B"] for c in calls)


def test_manual_rollback_after_a_successful_install_removes_the_pinned_files(env):
    assert run(env, "install").returncode == 0
    r = run(env, "rollback")
    assert r.returncode == 0 and "ROLLBACK_OK" in r.stdout
    assert not (env["tmp"] / "app" / "micro_recorder.py").exists()
    assert not (env["tmp"] / "units" / "cryptomaster-micro-recorder.service").exists()
