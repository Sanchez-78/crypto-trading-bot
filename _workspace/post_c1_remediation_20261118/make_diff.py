"""Exact diff of the 2026-11-18 local fixes against the files running on the server."""
import difflib
import hashlib
import pathlib

D = pathlib.Path(__file__).resolve().parent
ROOT = D.parents[1]
PAIRS = [("readiness_monitor.server.py", "src/services/readiness_monitor.py"),
         ("dashboard_web.server.py", "src/services/dashboard_web.py"),
         ("outbox.server.py", "src/services/v5_legacy_bridge/outbox.py"),
         ("outbox_flush_worker.server.py", "src/services/v5_legacy_bridge/outbox_flush_worker.py")]
out, summary = [], []
for srv, loc in PAIRS:
    server_bytes = (D / "server_copies" / srv).read_bytes()
    a = server_bytes.decode("utf-8").splitlines()
    b = (ROOT / loc).read_text(encoding="utf-8").splitlines()
    d = list(difflib.unified_diff(a, b, "server/" + loc, "local/" + loc, lineterm=""))
    out += d
    plus = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
    minus = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
    summary.append(f"{loc}: +{plus} -{minus} server_sha256={hashlib.sha256(server_bytes).hexdigest()}")
(D / "remediation.diff").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(summary))
