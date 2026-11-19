"""Build LF deploy artifacts (flat, as deploy_bot_files.sh expects) + pinned SHA-256.

Source = working-tree file with CRLF normalised to LF. Each artifact must differ from the
server copy (_workspace/post_c1_remediation_20261118/server_copies) by exactly the approved
remediation line counts, and the server copy must match the SHA recorded on 2026-11-18.
"""
import difflib
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COPIES = ROOT / "_workspace/post_c1_remediation_20261118/server_copies"
# path -> (server copy, unit, approved +lines, approved -lines)
FILES = {
    "src/services/readiness_monitor.py": ("readiness_monitor.server.py", "dashboard", 13, 54),
    "src/services/dashboard_web.py": ("dashboard_web.server.py", "dashboard", 15, 11),
    "src/services/v5_legacy_bridge/outbox.py": ("outbox.server.py", "bot", 47, 0),
    "src/services/v5_legacy_bridge/outbox_flush_worker.py": ("outbox_flush_worker.server.py", "bot", 35, 0),
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    recorded = dict(reversed(l.split()) for l in (COPIES / "SERVER_SHA256SUMS").read_text().splitlines() if l.strip())
    manifest, ok = {}, True
    for path, (copy, unit, plus, minus) in FILES.items():
        server = (COPIES / copy).read_bytes()
        art = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        d = [l for l in difflib.unified_diff(server.decode().splitlines(), art.decode().splitlines(), lineterm="", n=0)
             if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        got = (sum(l.startswith("+") for l in d), sum(l.startswith("-") for l in d))
        checks = {"server_copy_matches_recorded_sha": sha(server) == recorded.get(path),
                  "diff_equals_approved": got == (plus, minus), "no_cr": b"\r" not in art}
        ok &= all(checks.values())
        out = HERE / unit / Path(path).name
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(art)
        manifest[path] = {"unit": unit, "artifact": str(out.relative_to(ROOT)).replace("\\", "/"),
                          "sha256": sha(art), "preimage_sha256": recorded.get(path), "diff": got, **checks}
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    print("ALL_OK" if ok else "CHECK_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
