"""Static workflow tests for audit PR1 (P1.5) — deploy integrity.

These assert the deploy workflow is deterministic and single-service, and that
the destructive/non-deterministic operations are gone. Text-level assertions on
a YAML workflow are appropriate here (the workflow is the artifact under test).
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / ".github/workflows/deploy.yml"
V5OFF = REPO / ".github/workflows/hetzner-disable-v5-paper.yml"


def _deploy_text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def test_deploy_yaml_valid():
    yaml.safe_load(_deploy_text())


def test_no_v5_standalone_in_deploy():
    t = _deploy_text()
    assert "cryptomaster-v5-paper" not in t
    assert "/opt/cryptomaster_v5_validation" not in t
    assert "DEPLOYING V5 PAPER BOT" not in t


def test_no_git_pull_merge_rebase():
    t = _deploy_text()
    assert "git pull" not in t
    assert "git merge origin" not in t
    assert "git rebase" not in t


def test_no_git_stash_or_clean():
    t = _deploy_text()
    assert "git stash" not in t
    assert "git clean" not in t


def test_deterministic_sha_reset():
    t = _deploy_text()
    assert "DEPLOY_SHA" in t
    assert "github.sha" in t
    assert "git reset --hard \"$DEPLOY_SHA\"" in t
    assert "cat-file -e" in t  # reachability check
    assert "DEPLOY_SHA_VERIFIED" in t


def test_live_safety_gate_before_restart():
    t = _deploy_text()
    # gate marker present and appears before the restart line
    assert "DEPLOY_SAFETY_GATE_OK" in t
    gate = t.index("DEPLOY_SAFETY_GATE_OK")
    restart = t.index("systemctl restart cryptomaster")
    assert gate < restart, "safety gate must run before the restart"


def test_only_legacy_service_restarted():
    t = _deploy_text()
    # exactly one restart, and it targets the canonical legacy service
    assert t.count("systemctl restart") == 1
    assert "systemctl restart cryptomaster\n" in t


def test_v5_disable_workflow_is_manual_and_nondestructive():
    t = V5OFF.read_text(encoding="utf-8")
    yaml.safe_load(t)
    assert "workflow_dispatch" in t
    assert "DISABLE_V5_PAPER" in t
    # reversible teardown only — never delete
    assert "systemctl stop" in t and "systemctl disable" in t and "systemctl mask" in t
    assert "rm -rf" not in t
    assert "systemctl restart cryptomaster\n" not in t  # must not restart legacy


def test_deploy_is_dispatch_only_no_push_trigger():
    """Audit 2026-07-16: deploy must NOT auto-run on push (no bot auto-restart on merge)."""
    doc = yaml.safe_load(_deploy_text())
    on = doc.get("on") or doc.get(True)
    assert isinstance(on, dict)
    assert "push" not in on, "push trigger must be removed — deploy is manual/dispatch-only"
    assert "workflow_dispatch" in on
