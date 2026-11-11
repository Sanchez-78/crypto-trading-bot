"""Run review 73's hardlink probe from a copy, preserving its original evidence."""

import json
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    evidence = Path(__file__).resolve().parent
    source = evidence.parent / "c1_provenance_fix2_review_20261111" / "hardlink_probe.py"
    copied = evidence / "hardlink_probe.py"
    if copied.exists():
        raise RuntimeError("copied probe already exists; refusing to overwrite")
    shutil.copy2(source, copied)
    before = set(evidence.glob("hardlink_case_*"))
    proc = subprocess.run([sys.executable, "-B", str(copied)], capture_output=True, text=True)
    created = list(set(evidence.glob("hardlink_case_*")) - before)
    if len(created) != 1:
        raise AssertionError(f"expected one synthetic case, got {len(created)}")
    case = created[0]
    log = case / "verdict.log"
    result = case / "prereg_result.json"
    manifest = case / "prereg_provenance.json"
    tmp = case / "prereg_result.json.tmp"
    details = {
        "returncode": proc.returncode,
        "value_error_alias": "ValueError: provenance_log must not alias" in proc.stderr,
        "result_exists": result.exists(),
        "manifest_exists": manifest.exists(),
        "log_unchanged": log.read_text(encoding="utf-8") == "prior log entry\n",
        "stale_tmp_hardlink_remains": tmp.samefile(log),
        "stderr_tail": proc.stderr.splitlines()[-1] if proc.stderr else "",
    }
    (evidence / "copied_probe_result.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(details, indent=2))
    if not (proc.returncode != 0 and details["value_error_alias"] and
            not details["result_exists"] and not details["manifest_exists"] and details["log_unchanged"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
