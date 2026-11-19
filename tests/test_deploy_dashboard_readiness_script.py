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


def test_only_the_dashboard_unit_is_restarted():
    t = text()
    assert "UNIT=cryptomaster-dashboard" in t
    assert re.findall(r"systemctl restart (\S+)", t) == ['"$UNIT"']
