"""Running-process code-SHA marker (audit F2/F3, 2026-07-17).

The autodeploy timer resets the shared checkout to origin/main but does not
always restart the trading process (and the dashboard-restore workflow moves the
checkout without touching the bot at all). So repo HEAD can silently diverge from
the SHA the bot is actually running.

At startup the bot writes its own code SHA to `reports/running_bot_sha`. The
autodeploy compares THAT against the new repo SHA to decide whether a restart is
genuinely needed, and the health probe surfaces repo-HEAD vs deployed-marker vs
running-marker so drift is visible. Best-effort and never fatal.
"""
import logging
import os
import subprocess

log = logging.getLogger(__name__)

RUNNING_MARKER = "reports/running_bot_sha"


def current_git_sha(cwd: str | None = None) -> str | None:
    """Return the current HEAD commit SHA, or None if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=cwd or os.getcwd(),
        )
        sha = out.stdout.strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


def write_running_sha_marker(project_dir: str | None = None) -> str | None:
    """Write the running process's code SHA to reports/running_bot_sha.

    Returns the SHA on success, None on any failure (best-effort; never raises).
    """
    base = project_dir or os.getcwd()
    sha = current_git_sha(base)
    if not sha:
        return None
    try:
        path = os.path.join(base, RUNNING_MARKER)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(sha + "\n")
        log.info("[RUNNING_BOT_SHA] %s", sha)
        return sha
    except OSError as e:
        log.warning("[RUNNING_BOT_SHA] could not write marker: %s", type(e).__name__)
        return None
