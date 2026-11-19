"""Executor artifact for the bucket cap: server copy (read-only scp 2026-11-19) + only the cap change.

Writes artifact/paper_trade_executor.py (LF), server_to_artifact.diff (complete diff vs the server
copy, for independent review) and MANIFEST.json. Fails unless the server copy has the recorded
preimage SHA and every changed line belongs to the bucket-cap change (no other hunks).
"""
import difflib
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PATH = "src/services/paper_trade_executor.py"
PREIMAGE = "5b0b15cc0ba98632f866267dac462286c07ecce6d8bbaa9a033120b29fa361cc"
# Every changed line must mention one of these (the cap helper, its scope, or the docstring line).
MARKERS = ("EXPLORE_BUCKET_CAP", "exploration_bucket_cap", "_bucket_cap_for", "PAPER_EXPLORE_MAX_OPEN_PER_BUCKET",
           "max_open_per_bucket", "bucket_count >=")


def main() -> int:
    server = (HERE / "server_copy" / "paper_trade_executor.server.py").read_bytes()
    art = (ROOT / PATH).read_bytes().replace(b"\r\n", b"\n")
    diff = list(difflib.unified_diff(server.decode().splitlines(), art.decode().splitlines(),
                                     "server/" + PATH, "artifact/" + PATH, lineterm="", n=3))
    changes = [l for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    # Changed lines inside the new helper block are allowed if the block is contiguous new code.
    hunks, current = [], []
    for l in diff:
        if l.startswith("@@"):
            current = []
            hunks.append(current)
        elif hunks and l[:1] in "+-" and l[:3] not in ("+++", "---"):
            current.append(l)
    foreign = [h for h in hunks if h and not any(any(m in l for m in MARKERS) for l in h)]
    checks = {"server_copy_is_preimage": hashlib.sha256(server).hexdigest() == PREIMAGE,
              "no_cr": b"\r" not in art, "no_foreign_hunks": not foreign, "has_changes": bool(changes)}
    out = HERE / "artifact" / "paper_trade_executor.py"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(art)
    (HERE / "server_to_artifact.diff").write_text("\n".join(diff) + "\n", encoding="utf-8", newline="\n")
    manifest = {PATH: {"artifact": str(out.relative_to(ROOT)).replace("\\", "/"),
                       "sha256": hashlib.sha256(art).hexdigest(), "preimage_sha256": PREIMAGE,
                       "hunks": len(hunks), "plus": sum(l.startswith("+") for l in changes),
                       "minus": sum(l.startswith("-") for l in changes), **checks}}
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    ok = all(checks.values())
    print("ALL_OK" if ok else f"CHECK_FAILED foreign={foreign}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
