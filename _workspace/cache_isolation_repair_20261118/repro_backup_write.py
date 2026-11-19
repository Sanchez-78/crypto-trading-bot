"""Find which target test file writes server_local_backups/*.json (isolated copy, real files untouched)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["tests/test_readiness_paper_only.py", "tests/test_outbox_terminal_backlog.py",
         "tests/test_outbox_reconcile_plan.py", "tests/test_dashboard_contract_fixes.py",
         "tests/test_sec_01_dashboard_boundary.py", "tests/test_v5_legacy_bridge_outbox.py",
         "tests/test_phase4d_outbox_flush_worker.py", "tests/test_conftest_runtime_db_isolation.py"]
WATCH = ["server_local_backups/paper_adaptive_learning_state.json", "server_local_backups/learning_state_phase1.json",
         "local_learning_storage/cache.sqlite", "data/paper_open_positions.json"]


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None


def tree(d: Path):
    return {str(p.relative_to(d)): sha(p) for p in d.rglob("*")
            if p.is_file() and p.parts[len(d.parts)] in ("server_local_backups", "local_learning_storage", "data", "runtime")}


def main():
    real_before = {w: sha(ROOT / w) for w in WATCH}
    out = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "tests", "bot2"):
            if (ROOT / name).exists():
                shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
        for f in ("start.py",):
            if (ROOT / f).exists():
                shutil.copy(ROOT / f, tmp / f)
        (tmp / "server_local_backups").mkdir()
        for w in WATCH[:2]:  # copies of the two JSON files (copy read, real never opened for write)
            shutil.copy(ROOT / w, tmp / w)
        runs = [[f] for f in FILES] if "--combined" not in sys.argv else [FILES, list(reversed(FILES))]
        for group in runs:
            f = " + ".join(group) if len(group) > 1 else group[0]
            before = tree(tmp)
            p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *group], cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            after = tree(tmp)
            changed = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}
            changed.update({k: [v, None] for k, v in before.items() if k not in after})
            summary = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l]
            out[f] = {"summary": summary[-1:] , "changed": changed}
            print(f, summary[-1:] , changed)
    real_after = {w: sha(ROOT / w) for w in WATCH}
    out["real_unchanged"] = real_before == real_after
    print("REAL_UNCHANGED" if out["real_unchanged"] else f"REAL_CHANGED {real_before} {real_after}")
    Path(__file__).with_name("repro_backup_write.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
