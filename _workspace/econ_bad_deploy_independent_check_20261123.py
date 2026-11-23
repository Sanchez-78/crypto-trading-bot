"""Read-only byte verification for the ECON BAD deploy-step review."""

import hashlib
from pathlib import Path
import subprocess
import sys


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "_workspace/deploy_post_c1_20261119"))
from eol_preserve import apply_preserving_eol, changed_lines  # noqa: E402

folder = root / "_workspace/econ_bad_deploy_20261123"
server = (folder / "server_copy/realtime_decision_engine.server.py").read_bytes()
artifact = (folder / "artifact/realtime_decision_engine.py").read_bytes()
target = (root / "src/services/realtime_decision_engine.py").read_bytes()
diff = (root / "_workspace/econ_bad_journal_20261123/rde.diff").read_text(encoding="utf-8")
expected_changes = [line for line in diff.splitlines()
                    if line[:1] in "+-" and not line.startswith(("+++", "---"))]

assert hashlib.sha256(server).hexdigest() == "4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae"
assert hashlib.sha256(artifact).hexdigest() == "95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03"
assert artifact == target
assert artifact == apply_preserving_eol(server, target.decode("utf-8"))
changes, unchanged_eol_kept = changed_lines(server, artifact)
assert unchanged_eol_kept
assert changes == expected_changes
assert (sum(c.startswith("+") for c in changes), sum(c.startswith("-") for c in changes)) == (186, 48)

git_blob = subprocess.run(
    ["git", "show", "1dfc35d:_workspace/econ_bad_deploy_20261123/artifact/realtime_decision_engine.py"],
    cwd=root, check=True, capture_output=True,
).stdout
assert git_blob == artifact

for rel, expected, server_preimage in (
    ("deploy/research_eval/deploy_bot_files.sh", "981c88701f1e093cb1cedceb5637db6605971e23436843b44a32494c78397d29",
     "64206444a23df72ee1927713773e9ab9b903492424f1748a3843aab7cf960f94"),
    ("deploy/research_eval/deploy_env_check.py", "927cc096afa2db380b2337825906ba6868afb6405d6e13ef346262e0bee351c5",
     "8ae175daf541d48081c704d86f3077eaf1092094a717a06ef8babeb54ed8df75"),
):
    local = (root / rel).read_bytes()
    committed = subprocess.run(["git", "show", f"1dfc35d:{rel}"], cwd=root, check=True,
                               capture_output=True).stdout
    assert hashlib.sha256(local).hexdigest() == expected
    assert committed == local
    parent = subprocess.run(["git", "show", f"1dfc35d^:{rel}"], cwd=root, check=True,
                            capture_output=True).stdout
    assert hashlib.sha256(parent).hexdigest() == server_preimage

print("ARTIFACT_BYTES_OK", len(server), len(artifact), len(changes))
print("COMMIT_BLOBS_OK")
