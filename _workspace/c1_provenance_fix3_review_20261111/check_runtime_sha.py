"""Compare protected local runtime files to hashes recorded before review tests."""

import hashlib
import json
from pathlib import Path


BEFORE = {
    "local_learning_storage/cache.sqlite": "31767b56391e77b4143c1e1129b7fa2a4447f4c71f931469e512a4f01ed17646",
    "data/paper_open_positions.json": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "server_local_backups/paper_adaptive_learning_state.json": "9263583f87369276b82646e80d85e92433e6602858b0551204983d064a27c93c",
    "server_local_backups/learning_state_phase1.json": "fbf592e2fb30a6d0a1da4d2050c1136dc9718665653a28b498fa2163eaabf5e6",
    "runtime/v5_quota_usage.sqlite": "0a3bf519ac254cb670486ff3c9539ccf55385c9f1a17fe8b516f34cf79161b03",
    "src/runtime/v5_quota_usage.sqlite": "8b65fbaaccdc984882e1dacc112cbbd16c544fc3c36d58630684205e213f81e1",
}


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    after = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in BEFORE}
    report = {"before": BEFORE, "after": after, "unchanged": after == BEFORE}
    out = Path(__file__).resolve().parent / "runtime_sha_comparison.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"unchanged": report["unchanged"], "files": len(after)}))
    if not report["unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
