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

# Two markers (audit F2/F3 round 2):
#   BOOT   — written EARLY at startup: "a process attempted to boot at this SHA".
#   READY  — written AFTER all mandatory init, just before the main loop: "a
#            process is actually up on this SHA". The autodeploy keys its restart
#            decision off READY so a crash-looping build (writes BOOT, never
#            reaches READY) is treated as stale, not healthy.
BOOT_MARKER = "reports/running_bot_sha"
READY_MARKER = "reports/ready_bot_sha"

# Back-compat alias.
RUNNING_MARKER = BOOT_MARKER


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


def _atomic_write(path: str, text: str) -> bool:
    """Write text to path atomically (temp + os.replace). Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError as e:
        log.warning("[DEPLOY_MARKER] could not write %s: %s", path, type(e).__name__)
        return False


def _write_sha_marker(rel_path: str, label: str, project_dir: str | None) -> str | None:
    base = project_dir or os.getcwd()
    sha = current_git_sha(base)
    if not sha:
        return None
    if _atomic_write(os.path.join(base, rel_path), sha + "\n"):
        log.info("[%s] %s", label, sha)
        return sha
    return None


def write_running_sha_marker(project_dir: str | None = None) -> str | None:
    """BOOT marker — written early at startup (best-effort, never raises)."""
    return _write_sha_marker(BOOT_MARKER, "BOOT_BOT_SHA", project_dir)


def write_ready_marker(project_dir: str | None = None) -> str | None:
    """READY marker — written only AFTER mandatory init completes, immediately
    before the main event loop. This is the SHA the autodeploy trusts as the
    'healthy running process'. Best-effort, never raises."""
    return _write_sha_marker(READY_MARKER, "READY_BOT_SHA", project_dir)
