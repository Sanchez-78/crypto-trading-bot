"""Snapshot / compare the six protected runtime files (Python compare; never `rtk diff a b`)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["local_learning_storage/cache.sqlite", "data/paper_open_positions.json",
         "server_local_backups/paper_adaptive_learning_state.json", "server_local_backups/learning_state_phase1.json",
         "runtime/v5_quota_usage.sqlite", "src/runtime/v5_quota_usage.sqlite"]


def snap():
    out = {f: (hashlib.sha256((ROOT / f).read_bytes()).hexdigest() if (ROOT / f).exists() else None) for f in FILES}
    for d in ("runtime", "src/runtime"):  # every file's content, not just the listing (review 2026-11-19)
        if (ROOT / d).is_dir():
            for p in (ROOT / d).rglob("*"):
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                if p.is_file() and rel not in out:
                    out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


if __name__ == "__main__":
    mode, path = sys.argv[1], Path(sys.argv[2])
    if mode == "save":
        path.write_text(json.dumps(snap(), indent=1), encoding="utf-8")
        print("SAVED", path.name)
    else:
        before, now = json.loads(path.read_text(encoding="utf-8")), snap()
        diff = {k: (before.get(k), now.get(k)) for k in set(before) | set(now) if before.get(k) != now.get(k)}
        print("PROTECTED_SAME" if not diff else f"PROTECTED_CHANGED {diff}")
        sys.exit(1 if diff else 0)
