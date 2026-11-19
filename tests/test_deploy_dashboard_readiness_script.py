# -*- coding: utf-8 -*-
"""Static guards on the one-shot dashboard readiness deploy script (review 2026-11-19 A1-A3)."""
import json
import re
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[1] / "_workspace" / "deploy_post_c1_20261119"
SCRIPT = DIR / "deploy_dashboard_readiness.sh"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="deploy bundle not present")


def text():
    return SCRIPT.read_bytes().decode("utf-8")


def test_lf_only_and_pins_match_manifest():
    assert b"\r" not in SCRIPT.read_bytes()
    manifest = json.loads((DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    pins = dict((p, (pre, new)) for p, pre, new in re.findall(r"(src/services/\S+?\.py)=([0-9a-f]{64})=([0-9a-f]{64})", text()))
    dashboard = {p: (v["preimage_sha256"], v["sha256"]) for p, v in manifest.items() if v["unit"] == "dashboard"}
    assert pins == dashboard and len(pins) == 2


def test_auth_profile_is_observed_and_preserved():
    t = text()
    # public profile (no token) is supported; protected profile uses the credential systemd handed the unit
    assert "200) PROFILE=public" in t and "401|503) PROFILE=protected" in t
    assert "TOKEN_FILE=/run/credentials/$UNIT.service/dashboard_api_token" in t
    assert 'rollback "protected profile no longer enforced"' in t
    assert "/etc/credstore/dashboard_api_token" not in t
    # the token only ever reaches curl through stdin
    assert "-H @-" in t and "Bearer" in t and not re.search(r"curl[^\n]*Bearer", t)


def test_journal_check_fails_closed():
    t = text()
    assert '--no-pager > "$JOURNAL" || true' not in t
    assert 'rollback "journal unreadable"' in t and 'rollback "journal empty since restart"' in t


def test_rollback_and_postimage_verify_mode_and_owner():
    t = text()
    assert "meta() { stat -c '%a %u %g' \"$1\"; }" in t
    assert '[ "$(meta "$APP/$f")" = "$(meta "$BACKUP/$f")" ] || bad=1' in t
    assert 'rollback "postimage $f mode/owner changed"' in t


ROOT = DIR.parents[1]
ARTIFACTS = [  # artifact, server copy, manifest
    ("dashboard/readiness_monitor.py", "_workspace/post_c1_remediation_20261118/server_copies/readiness_monitor.server.py"),
    ("dashboard/dashboard_web.py", "_workspace/post_c1_remediation_20261118/server_copies/dashboard_web.server.py"),
    ("bot/outbox.py", "_workspace/post_c1_remediation_20261118/server_copies/outbox.server.py"),
    ("bot/outbox_flush_worker.py", "_workspace/post_c1_remediation_20261118/server_copies/outbox_flush_worker.server.py"),
    ("../bucket_cap_20261119/artifact/paper_trade_executor.py",
     "_workspace/bucket_cap_20261119/server_copy/paper_trade_executor.server.py"),
]


@pytest.mark.parametrize("artifact, server", ARTIFACTS)
def test_artifacts_keep_every_unchanged_server_line_byte_identical(artifact, server):
    """2026-11-19: live files are CRLF or mixed; a whole-file LF artifact changed lines outside the diff."""
    import sys
    sys.path.insert(0, str(DIR))
    from eol_preserve import changed_lines
    art, srv = (DIR / artifact).read_bytes(), (ROOT / server).read_bytes()
    changes, eol_kept = changed_lines(srv, art)
    assert eol_kept and changes
    # line-ending mix is the server's, apart from the inserted lines
    assert abs(art.count(b"\r\n") - srv.count(b"\r\n")) <= sum(c.startswith("+") for c in changes)


def test_only_the_dashboard_unit_is_restarted():
    t = text()
    assert "UNIT=cryptomaster-dashboard" in t
    assert re.findall(r"systemctl restart (\S+)", t) == ['"$UNIT"']
