"""
Runtime version detection and formatting for deployment verification.

Provides git commit hash, branch, and startup marker without failing if git unavailable.
Used for: startup logging, Firestore runtime_status document, pre_live_audit comparison.
"""

import subprocess
import os
import sys
import socket
from datetime import datetime, timezone


def get_git_commit() -> str:
    """Get current git commit hash. Returns 'UNKNOWN' if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return "UNKNOWN"


def get_git_branch() -> str:
    """Get current git branch. Returns 'UNKNOWN' if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return "UNKNOWN"


def get_hostname() -> str:
    """Get system hostname."""
    try:
        return socket.gethostname()
    except Exception:
        return "UNKNOWN"


def get_python_version() -> str:
    """Get Python version string."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def get_runtime_marker() -> dict:
    """
    Build comprehensive runtime marker for logging and persistence.

    Returns:
        Dict with keys: app, version, commit, branch, host, python, started_at
        All fields safe; never raises exception.
    """
    return {
        "app": "CryptoMaster",
        "version": "V10.13u+1",
        "commit": get_git_commit(),
        "branch": get_git_branch(),
        "host": get_hostname(),
        "python": get_python_version(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def format_runtime_marker(marker: dict = None) -> str:
    """
    Format runtime marker as log string.

    Args:
        marker: Dict from get_runtime_marker(), or None to generate fresh.

    Returns:
        String: "[RUNTIME_VERSION] app=CryptoMaster version=V10.13u+1 commit=<hash> ..."
    """
    if marker is None:
        marker = get_runtime_marker()

    parts = [
        f"[RUNTIME_VERSION]",
        f"app={marker['app']}",
        f"version={marker['version']}",
        f"commit={marker['commit']}",
        f"branch={marker['branch']}",
        f"host={marker['host']}",
        f"python={marker['python']}",
        f"started_at={marker['started_at']}",
    ]
    return " ".join(parts)


def try_write_runtime_status_to_firestore(marker: dict) -> bool:
    """
    Attempt to write runtime status to Firestore for observability.

    Safe: only writes if firebase_client is available and functional.
    Never raises exception.

    Args:
        marker: Dict from get_runtime_marker()

    Returns:
        True if write succeeded, False otherwise (safe to ignore)
    """
    try:
        from src.services import firebase_client as fc

        # Check if safe to write (quota OK)
        if not fc._can_write(1):
            return False

        # Write small document (minimal quota impact)
        doc_data = {
            "timestamp": marker["started_at"],
            "commit": marker["commit"],
            "branch": marker["branch"],
            "host": marker["host"],
            "python": marker["python"],
        }

        db = fc.get_firestore_db()
        if db is None:
            return False

        # Write to runtime_status collection with host as doc ID (idempotent)
        db.collection("runtime_status").document(marker["host"]).set(
            doc_data, merge=True
        )
        return True
    except Exception:
        return False
