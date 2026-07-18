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


# ── Audit F2/F3: autodeploy script hardening (SHA drift + safe restart) ────────
AUTODEPLOY = REPO / "scripts/hetzner_paper_train_deploy_and_audit.sh"


def _autodeploy_text() -> str:
    return AUTODEPLOY.read_text(encoding="utf-8")


def test_autodeploy_decides_restart_off_ready_marker():
    t = _autodeploy_text()
    # restart decision keys off the READY marker (healthy process), not repo HEAD
    assert "reports/ready_bot_sha" in t
    assert "ready_sha" in t
    assert 'restart_needed="true"' in t


def test_autodeploy_fail_closed_on_missing_ready_marker():
    t = _autodeploy_text()
    # missing READY marker must fail-closed (restart), not skip
    idx = t.index('if [ "$ready_sha" = "unknown" ]; then')
    tail = t[idx:idx + 300]
    assert 'restart_needed="true"' in tail
    assert "FAIL-CLOSED" in tail


def test_autodeploy_has_code_impact_gate():
    t = _autodeploy_text()
    assert "git diff --name-only" in t
    assert "no code impact" in t


def test_autodeploy_hold_file_is_root_owned_checked():
    t = _autodeploy_text()
    assert ".deploy_hold" in t
    assert "stat -c '%u'" in t          # root-ownership check
    assert "not root-owned" in t
    assert "expires_at_epoch" in t      # TTL support


def test_autodeploy_zero_position_gate_is_fail_closed():
    t = _autodeploy_text()
    assert "paper_open_positions.json" in t
    assert "UNKNOWN" in t and "fail-closed" in t
    assert "deferring restart" in t


def test_autodeploy_writes_deployed_marker_after_is_active_and_ready():
    t = _autodeploy_text()
    assert "reports/deployed_bot_sha" in t
    # deployed marker write must come AFTER the is-active check
    assert t.index("is-active --quiet") < t.index(
        'echo "$new_sha" > "$PROJECT_DIR/reports/deployed_bot_sha"')
    # and gated on READY convergence
    assert 'post_ready' in t


# ── Audit F10: dashboard firewall workflow verification + rollback ─────────────
FIREWALL = REPO / ".github/workflows/hetzner-dashboard-firewall.yml"


def _firewall_text() -> str:
    return FIREWALL.read_text(encoding="utf-8")


def test_firewall_is_manual_dispatch_only():
    doc = yaml.safe_load(_firewall_text())
    on = doc.get("on") or doc.get(True)
    assert "workflow_dispatch" in on and "push" not in on


def test_firewall_rollback_is_fail_closed():
    """Audit F10-r2: rollback must NEVER reopen the public port. It re-asserts the
    secure baseline (keep the deny) instead of deleting it."""
    t = _firewall_text()
    assert "ROLLBACK_FIREWALL" in t
    # fail-closed: rollback must NOT delete the public deny (that would reopen it)
    assert "ufw delete deny" not in t
    # rollback re-asserts the secure baseline via apply_secure and verifies it
    assert "re-assert" in t
    assert "[ROLLBACK_SECURE_OK]" in t


def test_firewall_validates_inputs_against_injection():
    """Audit F10-r2: confirm/allow_cidr/ports are validated (enum + ipaddress +
    port allowlist) BEFORE reaching the remote shell — no injection surface."""
    t = _firewall_text()
    assert "Validate inputs" in t
    assert "ip_network" in t                         # allow_cidr validated as a network
    assert "subset of '5000 5001'" in t              # ports allowlist


def test_firewall_validation_runs_before_ssh_and_blocklists_metachars():
    """Audit F10-r2: the anti-injection validation must run BEFORE the SSH step
    (else it can't protect it), and must reject shell metacharacters explicitly
    (belt-and-suspenders on top of ip_network)."""
    t = _firewall_text()
    validate = t.index("Validate inputs")
    ssh_step = t.index("Read state + (optionally) apply")
    assert validate < ssh_step, "input validation must precede the SSH step"
    # explicit metacharacter blocklist present
    assert "disallowed characters" in t


def test_firewall_defaults_to_port_5000_not_5001():
    """5001 is the LIVE Android API port — it must NOT be firewalled by default.
    An accidental run defaults to 5000 (the redundant legacy dashboard) only."""
    doc = yaml.safe_load(_firewall_text())
    on = doc.get("on") or doc.get(True)
    ports = on["workflow_dispatch"]["inputs"]["ports"]
    assert str(ports["default"]) == "5000"


def test_firewall_verifies_active_and_ipv4_ipv6_and_external_probe():
    t = _firewall_text()
    assert 'grep -q "Status: active"' in t          # ufw must be active
    assert "(v6)" in t                               # IPv6 rule check
    assert "External public-access probe" in t       # runner-side external probe
    assert "STILL REACHABLE" in t                     # fail-closed if reachable


# ── Audit v5: blacklist workflow hardening (injection + zero-position gate) ────
BLACKLIST = REPO / ".github/workflows/hetzner-apply-symbol-blacklist.yml"


def _blacklist_text() -> str:
    return BLACKLIST.read_text(encoding="utf-8")


def test_blacklist_validates_inputs_before_ssh():
    """Audit v5 §15 (HIGH): action/symbols must be validated (enum + exact symbol
    allowlist) BEFORE the SSH step — no raw input reaches the remote shell/.env."""
    t = _blacklist_text()
    validate = t.index("Validate inputs")
    ssh_step = t.index("Apply on server")
    assert validate < ssh_step, "input validation must precede the SSH step"
    assert "ALLOWED" in t and "not in ALLOWED" in t   # exact symbol allowlist


def _blacklist_validator_src() -> str:
    """Extract the embedded `python3 - "$ACTION" "$SYMBOLS" <<'PY' ... PY` body
    and de-indent it so it can be executed as the real validator."""
    import re
    t = _blacklist_text()
    m = re.search(r'python3 - "\$ACTION" "\$SYMBOLS" <<\'PY\'\n(.*?)\n\s*PY\n', t, re.S)
    assert m, "validator heredoc not found"
    lines = [ln[10:] if ln.startswith(" " * 10) else ln for ln in m.group(1).splitlines()]
    return "\n".join(lines)


def test_blacklist_validator_rejects_injection_on_every_action():
    """Audit v5 (reviewer HIGH): SYMBOLS is interpolated into the SSH command for
    EVERY action, so a crafted `symbols` under action=revert/status must be
    rejected too — not just under apply."""
    import subprocess, sys, tempfile, os
    src = _blacklist_validator_src()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src); path = f.name
    try:
        run = lambda *a: subprocess.run([sys.executable, path, *a], capture_output=True, text=True).returncode
        # the exact RCE payload from the reviewer, under revert — MUST be rejected
        assert run("revert", "x'; touch /tmp/pwned; '") != 0
        assert run("status", "$(reboot)") != 0
        assert run("apply", "BTCUSDT;reboot") != 0
        assert run("apply", "BTC USDT") != 0           # space breaks allowlist
        # legitimate inputs still pass
        assert run("revert", "") == 0
        assert run("status", "") == 0
        assert run("apply", "BTCUSDT,ETHUSDT") == 0
        assert run("apply", "") != 0                    # apply requires a list
    finally:
        os.unlink(path)


def test_blacklist_zero_position_gate_before_restart_fail_closed():
    """Audit v5: a zero-open-position gate (fail-closed, UNKNOWN=block) must run
    before the service restart, and revert the .env change if it refuses."""
    t = _blacklist_text()
    gate = t.index("paper_open_positions.json")
    restart = t.index('systemctl restart "$SERVICE_NAME"')
    assert gate < restart, "zero-position gate must run before the restart"
    assert "UNKNOWN" in t and "REFUSING restart" in t
    # missing state file is UNKNOWN (block), not silently treated as zero
    assert 'print("UNKNOWN")' in t


def test_firewall_external_probe_is_tcp_not_http_healthz():
    """Audit F10-r3 (external report v5): the external probe must test the raw TCP
    connection, NOT an HTTP 2xx. A `curl -f .../healthz` mis-reports an OPEN port
    that returns 404 (the legacy :5000 dashboard has no /healthz) as 'refused'.
    A socket connect probing IPv4 AND IPv6 separately is the correct signal."""
    t = _firewall_text()
    probe = t.index("External public-access probe")
    tail = t[probe:probe + 1600]
    # TCP connect, not an HTTP-status check, in the external probe step
    assert "SOCK_STREAM" in tail and ".connect(" in tail
    assert "AF_INET" in tail and "AF_INET6" in tail   # both families probed
    assert "/healthz" not in tail                      # not the old HTTP probe
