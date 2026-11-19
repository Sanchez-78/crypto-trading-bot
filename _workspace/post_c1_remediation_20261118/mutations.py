"""Mutations for the 2026-11-18 readiness and outbox-visibility fixes; isolated copy only."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_readiness_paper_only.py", "tests/test_outbox_terminal_backlog.py",
         "tests/test_dashboard_contract_fixes.py"]
SERVER_READINESS = ROOT / "_workspace/post_c1_remediation_20261118/server_copies/readiness_monitor.server.py"
S = "src/services/"
MUTATIONS = {
    "readiness_module_reverted_to_server": ("copy", S + "readiness_monitor.py", SERVER_READINESS),
    "readiness_endpoint_claims_ready": ("edit", S + "dashboard_web.py",
                                        '"is_ready_for_trading": False,\n                "blocker_reasons": ["paper_only_policy"],',
                                        '"is_ready_for_trading": True,\n                "blocker_reasons": ["paper_only_policy"],'),
    "backlog_hides_terminal": ("edit", S + "v5_legacy_bridge/outbox.py",
                               "                stats[\"terminal_unsynced\"] += count\n",
                               ""),
    "backlog_leaks_ids": ("edit", S + "v5_legacy_bridge/outbox.py",
                          "        max_retries = config.OUTBOX_MAX_RETRIES\n",
                          "        max_retries = config.OUTBOX_MAX_RETRIES\n        _ids = [r[0] for r in sqlite3.connect(self.db_path).execute('select idempotency_key from outbox')]\n"),
    "pending_count_meaning_changed": ("edit", S + "v5_legacy_bridge/outbox.py",
                                      '"SELECT COUNT(*) FROM outbox WHERE retry_count < ?",',
                                      '"SELECT COUNT(*) FROM outbox WHERE retry_count < ? + 100",'),
    "terminal_log_on_every_tick": ("edit", S + "v5_legacy_bridge/outbox_flush_worker.py",
                                   "        if terminal == self._last_terminal_count:\n            return\n", ""),
    "terminal_log_removed": ("edit", S + "v5_legacy_bridge/outbox_flush_worker.py",
                             "        self._report_terminal_backlog()\n\n    def _report_terminal_backlog", "\n    def _report_terminal_backlog"),
}


def run(tmp: Path) -> dict:
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l or " error" in l]
    failed = [l for l in p.stdout.splitlines() if l.startswith("FAILED")]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-200:], "failed": failed,
            "import_error": "ImportError" in p.stdout or "SyntaxError" in p.stdout}


def main() -> int:
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "tests"):
            shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite"))
        res["baseline"] = run(tmp)
        for name, spec in MUTATIONS.items():
            target = tmp / spec[1]
            original = target.read_bytes()
            if spec[0] == "copy":
                shutil.copy(spec[2], target)
            else:
                text = original.decode("utf-8").replace("\r\n", "\n")  # some working copies are CRLF
                assert text.count(spec[2]) == 1, name
                target.write_text(text.replace(spec[2], spec[3]), encoding="utf-8")
            res[name] = run(tmp)
            target.write_bytes(original)
        res["restored"] = run(tmp)
    Path(__file__).with_name("mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v)
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 and not v["import_error"] for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
