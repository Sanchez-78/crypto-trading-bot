"""Mutation proof in a code-only disposable copy inside the authorized workspace."""
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
    snapshot = Path(tempfile.mkdtemp(prefix="mutations_", dir=artifacts))
    relative = Path("scripts/research/futures_flow_screen.py")
    source = snapshot / relative
    source.parent.mkdir(parents=True)
    original = (root / relative).read_bytes()
    source.write_bytes(original)
    test_relative = Path("tests/test_futures_flow_screen.py")
    target = snapshot / test_relative
    target.parent.mkdir(parents=True)
    target.write_bytes((root / test_relative).read_bytes())
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
        "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
    }}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
               FORCE_LOCAL_STORAGE="1", TRADING_MODE="paper_train", ENABLE_REAL_ORDERS="false")
    cases = [
        ("metrics_early", "m.index += pd.Timedelta(minutes=5)", "m.index += pd.Timedelta(minutes=0)",
         "metrics_are_not_available"),
        ("funding_early", "funds.time + (funds.funding_interval_hours * 60 * MINUTE).astype(\"int64\")", "funds.time",
         "funding_is_delayed"),
        ("tp_before_sl", "active[stop] = False", "active[stop] = True", "same_bar_tp_and_sl"),
        ("overlapping", "horizon_ms=protocol.horizon_minutes * MINUTE", "horizon_ms=MINUTE",
         "rule_execution_is_nonoverlapping"),
        ("no_purge", "exit_ms < end_ms", "decision_ms < end_ms", "embargo_and_label_purge"),
        ("early_holdout", "for dependency in requires:", "for dependency in ():", "stage_barrier"),
        ("z_includes_current", 'closed="left", min_periods=minimum', 'closed="both", min_periods=minimum',
         "z_score_uses_strictly_prior"),
        ("btc_self_lead", 'feats.loc[:, ["H6_1", "H6_5"]] = 0.', "pass",
         "pooled_model_does_not_turn_alt_lead"),
    ]
    results = []
    try:
        for name, before, after, selection in cases + [("restored", "", "", "")]:
            if before:
                assert original.count(before.encode()) == 1, name
                source.write_bytes(original.replace(before.encode(), after.encode()))
            else:
                source.write_bytes(original)
            report, logfile = artifacts / f"{name}.xml", artifacts / f"{name}.log"
            command = [sys.executable, "-B", str(root / "_workspace/code_audit_20260921_runner.py"),
                       "--child", str(snapshot), "--rootdir=" + str(snapshot), "--confcutdir=" + str(snapshot),
                       "-p", "no:cacheprovider", "-q", "--tb=short", "--junitxml=" + str(report), str(test_relative)]
            if selection:
                command += ["-k", selection]
            with logfile.open("w", encoding="utf-8") as output:
                completed = subprocess.run(command, cwd=snapshot, env=env, stdout=output,
                                           stderr=subprocess.STDOUT, timeout=60)
            suite = ET.parse(report).getroot().find("testsuite")
            row = {"case": name, "exit_code": completed.returncode,
                   **{key: int(suite.attrib[key]) for key in ("tests", "errors", "failures", "skipped")}}
            results.append(row)
            print(json.dumps(row), flush=True)
            assert row["errors"] == 0
            assert (completed.returncode == 1 and row["failures"] > 0) if before else completed.returncode == 0
    finally:
        source.write_bytes(original)
        (artifacts / "mutations.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    assert (root / relative).read_bytes() == original


if __name__ == "__main__":
    main()
