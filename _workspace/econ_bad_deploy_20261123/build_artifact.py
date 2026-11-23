"""Artifact for the ECON BAD log limit: live server bytes (read-only scp 2026-11-23) + the approved diff.

Fails unless the server copy is the recorded preimage, every unchanged line keeps its exact bytes,
and the change lines equal the approved diff (_workspace/econ_bad_journal_20261123/rde.diff,
code APPROVE _workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md) line for line.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "_workspace" / "deploy_post_c1_20261119"))
from eol_preserve import apply_preserving_eol, changed_lines  # noqa: E402

PATH = "src/services/realtime_decision_engine.py"
PREIMAGE = "4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae"
APPROVED_POSTIMAGE = "95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03"
APPROVED_DIFF = ROOT / "_workspace/econ_bad_journal_20261123/rde.diff"


def approved_change_lines():
    out = []
    for line in APPROVED_DIFF.read_text(encoding="utf-8").splitlines():
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            out.append(line)
    return out


def main() -> int:
    server = (HERE / "server_copy" / "realtime_decision_engine.server.py").read_bytes()
    art = apply_preserving_eol(server, (ROOT / PATH).read_text(encoding="utf-8"))
    changes, eol_kept = changed_lines(server, art)
    sha = hashlib.sha256(art).hexdigest()
    checks = {
        "server_copy_is_preimage": hashlib.sha256(server).hexdigest() == PREIMAGE,
        "unchanged_lines_byte_identical": eol_kept,
        "change_lines_equal_approved_diff": sorted(changes) == sorted(approved_change_lines()),
        "artifact_equals_approved_postimage": sha == APPROVED_POSTIMAGE,
    }
    out = HERE / "artifact" / "realtime_decision_engine.py"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(art)
    manifest = {PATH: {"artifact": str(out.relative_to(ROOT)).replace("\\", "/"), "sha256": sha,
                       "preimage_sha256": PREIMAGE,
                       "plus": sum(c.startswith("+") for c in changes),
                       "minus": sum(c.startswith("-") for c in changes), **checks}}
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    ok = all(checks.values())
    print("ALL_OK" if ok else "CHECK_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
