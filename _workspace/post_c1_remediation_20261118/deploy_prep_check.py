"""Deploy prep (read-only): pinned SHA, local == server copy + approved diff, import side effects.

1. For each deploy file: SHA-256 of the local bytes (the pin) and the diff size vs the server copy
   (must equal the approved remediation sizes).
2. Imports the two outbox modules in a fresh interpreter from a temp copy of src/ and fails if the
   import created any file (the deploy validator runs them in a read-only sandbox).
"""
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

D = Path(__file__).resolve().parent
ROOT = D.parents[1]
FILES = {
    "src/services/readiness_monitor.py": ("readiness_monitor.server.py", "dashboard"),
    "src/services/dashboard_web.py": ("dashboard_web.server.py", "dashboard"),
    "src/services/v5_legacy_bridge/outbox.py": ("outbox.server.py", "bot"),
    "src/services/v5_legacy_bridge/outbox_flush_worker.py": ("outbox_flush_worker.server.py", "bot"),
}


def main():
    out = {}
    for path, (srv, unit) in FILES.items():
        raw = (ROOT / path).read_bytes()
        a = (D / "server_copies" / srv).read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
        b = raw.decode("utf-8").replace("\r\n", "\n").splitlines()
        d = [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        out[path] = {"unit": unit, "sha256": hashlib.sha256(raw).hexdigest(), "crlf": b"\r\n" in raw,
                     "plus": sum(l.startswith("+") for l in d), "minus": sum(l.startswith("-") for l in d)}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        shutil.copytree(ROOT / "src", tmp / "src", ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
        before = {p for p in tmp.rglob("*")}
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "import src.services.v5_legacy_bridge.outbox, src.services.v5_legacy_bridge.outbox_flush_worker")
        r = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(tmp)], cwd=tmp, capture_output=True, text=True)
        created = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p not in before)
        out["import_check"] = {"exit": r.returncode, "stderr_tail": r.stderr[-400:], "created_files": created}
    (D / "deploy_prep_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
