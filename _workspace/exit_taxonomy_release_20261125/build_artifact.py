"""Build the pinned 4-file dashboard artifact = server bytes + the reviewed line diff.

Unchanged lines keep the server's exact bytes (the live files mix CRLF and LF); changed/new lines
come from the local working copy. Verifies postimage == local working copy after EOL
normalization, and writes MANIFEST.json with pre/post SHA-256. Read-only toward the repo.
"""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FILES = ["src/services/dashboard_web.py", "src/services/dashboard_read_model.py",
         "src/services/performance_epoch.py", "src/services/exit_taxonomy.py"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def apply_diff(server: bytes, local: bytes) -> bytes:
    server_lines = server.splitlines(keepends=True)
    server_norm = [line.replace(b"\r\n", b"\n") for line in server_lines]
    local_lines = norm(local).splitlines(keepends=True)
    out = []
    matcher = difflib.SequenceMatcher(a=server_norm, b=local_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        out.extend(server_lines[i1:i2] if tag == "equal" else local_lines[j1:j2])
    return b"".join(out)


manifest = {"files": {}}
(HERE / "postimage").mkdir(exist_ok=True)
for rel in FILES:
    name = Path(rel).name
    local = (ROOT / rel).read_bytes()
    pre_path = HERE / "preimage" / name
    pre = pre_path.read_bytes() if pre_path.exists() else None
    post = local if pre is None else apply_diff(pre, local)
    assert norm(post) == norm(local), rel
    (HERE / "postimage" / name).write_bytes(post)
    manifest["files"][rel] = {"preimage_sha256": sha(pre) if pre is not None else None,
                              "postimage_sha256": sha(post), "bytes": len(post),
                              "mode": "644", "owner": "root:root"}
(HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, indent=2, sort_keys=True))
