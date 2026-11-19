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


sys.path.insert(0, str(HERE))
from eol_preserve import apply_preserving_eol, changed_lines  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# Reviewed reference for hunk identity (review 2026-11-19 B3): the exact change lines of
# remediation.diff (Codex review 2026-11-18), plus the backlog_error lines approved in the same
# review's second round. Counts alone would let a different change with equal size through.
REVIEWED_DIFF = ROOT / "_workspace/post_c1_remediation_20261118/remediation.diff"
APPROVED_EXTRA = {"src/services/v5_legacy_bridge/outbox_flush_worker.py": [
    '+            # A failed count must not read as "no backlog" (review 2026-11-18).',
    '+            "backlog_error": backlog.get("error"),',
]}


def change_lines(diff_lines) -> list:
    return [l for l in diff_lines if l[:1] in "+-" and l[:3] not in ("+++", "---")]


def reviewed_changes() -> dict:
    per_file, current = {}, None
    for line in REVIEWED_DIFF.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ local/"):
            current = line[len("+++ local/"):]
            per_file[current] = []
        elif current and line[:1] in "+-" and not line.startswith(("+++", "---")):
            per_file[current].append(line)
    return per_file


def main() -> int:
    recorded = dict(reversed(l.split()) for l in (COPIES / "SERVER_SHA256SUMS").read_text().splitlines() if l.strip())
    manifest, ok = {}, True
    reviewed = reviewed_changes()
    for path, (copy, unit, plus, minus) in FILES.items():
        server = (COPIES / copy).read_bytes()
        # Server bytes + the reviewed change; unchanged lines keep their exact EOL (CRLF/mixed files).
        art = apply_preserving_eol(server, (ROOT / path).read_text(encoding="utf-8"))
        d, eol_kept = changed_lines(server, art)
        got = (sum(l.startswith("+") for l in d), sum(l.startswith("-") for l in d))
        # Exact identity: the same multiset of change lines as the reviewed diff (+ approved extra).
        expected = sorted(reviewed.get(path, []) + APPROVED_EXTRA.get(path, []))
        checks = {"server_copy_matches_recorded_sha": sha(server) == recorded.get(path),
                  "diff_counts_equal_approved": got == (plus, minus),
                  "diff_lines_identical_to_reviewed": sorted(d) == expected and bool(d),
                  "unchanged_lines_byte_identical": eol_kept,
                  "content_equals_working_tree": art.decode().replace("\r\n", "\n")
                  == (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")}
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
