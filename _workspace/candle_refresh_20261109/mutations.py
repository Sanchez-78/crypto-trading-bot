"""Revert this task's fixes only in an already disposable test snapshot."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def main():
    artifacts = Path(__file__).resolve().parent
    root = artifacts.parents[1]
    snapshot = Path(sys.argv[1]).resolve(strict=True)
    assert snapshot.parent == Path(tempfile.gettempdir()).resolve()
    assert snapshot.name.startswith("code_audit_20260921_")
    assert snapshot != root and not (snapshot / ".git").exists()
    runner = root / "_workspace/code_audit_20260921_runner.py"
    cache = snapshot / "src/services/candle_cache_v1.py"
    pipeline = snapshot / "src/services/p0_8_plus_live_pipeline.py"
    originals = {path: path.read_bytes() for path in (cache, pipeline)}
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
        "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
    }}
    env.update(FORCE_LOCAL_STORAGE="1", TRADING_MODE="paper_train",
               ENABLE_REAL_ORDERS="false", LIVE_TRADING_CONFIRMED="false",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    tests = ["tests/test_completed_candle_cache.py", "tests/test_completed_strategy_pipeline.py",
             "tests/test_p0_8_plus_live_pipeline.py"]
    phase = "phase_refresh_handles_symbol_jitter or btc_wake_before_regular or reaches_real_router"
    logs = "logs_stale_age"
    backoff = "phase_refresh_failure_keeps_snapshot or phase_refresh_cold_failure"
    results = []

    def run(name, selection, should_fail):
        report = artifacts / (name + ".xml")
        logfile = artifacts / (name + ".log")
        command = [sys.executable, "-B", str(runner), "--child", str(snapshot),
                   "-p", "no:cacheprovider", "-q", "--tb=short", "--junitxml=" + str(report),
                   *tests, "-k", selection]
        with logfile.open("w", encoding="utf-8") as output:
            completed = subprocess.run(command, cwd=snapshot, env=env, stdout=output,
                                       stderr=subprocess.STDOUT, timeout=60)
        suite = ET.parse(report).getroot().find("testsuite")
        counts = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
        row = {"case": name, "exit_code": completed.returncode, **counts,
               "failed_tests": [test.attrib["name"] for test in suite.findall("testcase")
                                if test.find("failure") is not None]}
        results.append(row)
        print(json.dumps(row), flush=True)
        assert counts["errors"] == 0 and counts["tests"] > 0
        assert (completed.returncode == 1 and counts["failures"] > 0) if should_fail else (
            completed.returncode == 0 and counts["failures"] == 0)

    try:
        cache.write_bytes((artifacts / "candle_cache_v1.py").read_bytes())
        run("revert_cache", phase, True)
        cache.write_bytes(originals[cache])
        pipeline.write_bytes((artifacts / "p0_8_plus_live_pipeline.py").read_bytes())
        run("revert_diagnostic", logs, True)
        pipeline.write_bytes(originals[pipeline])
        old = b"needs_refresh = new_minute and (last_attempt_succeeded or retry_ready)"
        assert originals[cache].count(old) == 1
        cache.write_bytes(originals[cache].replace(old, b"needs_refresh = new_minute"))
        run("remove_failure_backoff", backoff, True)
    finally:
        for path, content in originals.items():
            path.write_bytes(content)
    run("restored", phase + " or " + logs + " or " + backoff, False)
    (artifacts / "mutation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    assert all(path.read_bytes() == content for path, content in originals.items())


if __name__ == "__main__":
    main()
