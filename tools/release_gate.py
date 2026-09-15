"""Fail-closed release gate for PAPER deployment.

The gate is intentionally read-only. It never stages, commits, copies, restarts,
or contacts a host. A deployment wrapper may proceed only after this command
returns zero and an immutable artifact has been created separately.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    "src/services/paper_trade_executor.py",
    "src/services/realtime_decision_engine.py",
    "src/services/trade_executor.py",
    "src/services/dashboard_web.py",
    "systemd/cryptomaster-dashboard.service",
)


def _git_status() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *PROTECTED],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _hashes() -> dict[str, str]:
    out = {}
    for rel in PROTECTED:
        path = ROOT / rel
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[rel] = digest
    return out


def evaluate(artifact: Path | None = None, smoke_evidence: Path | None = None) -> tuple[bool, list[str], dict[str, str]]:
    reasons: list[str] = []
    statuses = _git_status()
    if statuses:
        reasons.append("protected_paths_dirty")
    hashes = _hashes()
    missing = [rel for rel in PROTECTED if rel not in hashes]
    if missing:
        reasons.append("missing_protected_files:" + ",".join(missing))
    if artifact is None or not artifact.is_file():
        reasons.append("immutable_artifact_not_created")
    if smoke_evidence is None or not smoke_evidence.is_file():
        reasons.append("paper_smoke_evidence_not_attached")
    return len(reasons) == 0, reasons, hashes


def main() -> int:
    parser = argparse.ArgumentParser(description="read-only fail-closed PAPER release gate")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--artifact", type=Path, help="path to externally-created immutable release artifact")
    parser.add_argument("--paper-smoke-evidence", type=Path, help="path to attached paper-only smoke evidence")
    args = parser.parse_args()
    ready, reasons, hashes = evaluate(args.artifact, args.paper_smoke_evidence)
    if args.json:
        import json
        print(json.dumps({"ready": ready, "reasons": reasons, "hashes": hashes}, sort_keys=True))
    else:
        print("RELEASE_READY=" + ("YES" if ready else "NO"))
        for reason in reasons:
            print("REASON=" + reason)
        for path, digest in hashes.items():
            print(f"SHA256={digest} FILE={path}")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
