"""Audit F2/F3 — running-process SHA marker."""
import subprocess
from pathlib import Path

import pytest

import src.services.deploy_marker as dm

REPO = Path(__file__).resolve().parents[1]


def _init_git_repo(path):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"],
                   cwd=path, check=True, env={**env, "PATH": __import__("os").environ["PATH"]})
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True, check=True).stdout.strip()
    return head


def test_current_git_sha_in_real_repo():
    sha = dm.current_git_sha(str(REPO))
    assert sha and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)


def test_current_git_sha_none_outside_git(tmp_path):
    assert dm.current_git_sha(str(tmp_path)) is None


def test_write_marker_records_head(tmp_path):
    head = _init_git_repo(tmp_path)
    written = dm.write_running_sha_marker(str(tmp_path))
    assert written == head
    marker = tmp_path / "reports" / "running_bot_sha"
    assert marker.read_text().strip() == head


def test_write_marker_noop_without_git(tmp_path):
    # non-git dir: returns None, writes nothing, never raises
    assert dm.write_running_sha_marker(str(tmp_path)) is None
    assert not (tmp_path / "reports" / "running_bot_sha").exists()
