"""
V10.13s: Canonical Runtime Version

Single source of truth for engine version, commit ID, and feature flags.
All modules import from here to ensure consistent version reporting.

Usage:
    from src.core.version import ENGINE_VERSION, GIT_COMMIT, get_version_string
    print(f"[BOOT] {get_version_string()}")
"""

import os
import subprocess
import time

# ════════════════════════════════════════════════════════════════════════════════
# CANONICAL ENGINE VERSION
# Update this single value when deploying new versions
# ════════════════════════════════════════════════════════════════════════════════
ENGINE_VERSION = "V10.13s"
BUILD_TIMESTAMP = time.time()

# Feature flags enabled in this version
FEATURES = {
    "reset_integrity": True,           # V10.13s: State consistency validation
    "timeout_fix": True,               # V10.13s: Extended hold time + TP widening
    "learning_instrumentation": True,  # V10.13s: Learning signal logging
    "unified_maturity": True,          # V10.13s: Single source-of-truth maturity
    "ev_floor": True,                  # V10.13s: Minimum EV sanity check (-0.05)
    "model_state_preservation": True,  # V10.13s: Exclude model_state from reset
    "cold_start_softening": True,      # V10.13r: Bootstrap-aware softening
    "kill_audit": True,                # V10.13q: Decision gate instrumentation
}


def get_git_commit() -> str:
    """Get current git commit hash if available."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        return commit if commit else "unknown"
    except Exception:
        return "unknown"


GIT_COMMIT = get_git_commit()


def get_version_string() -> str:
    """
    Return canonical version string for logging.
    Format: V10.13s (commit=abc1234) [features]
    """
    features_str = ",".join(k for k, v in FEATURES.items() if v)
    return f"{ENGINE_VERSION} (commit={GIT_COMMIT[:8]}) [{features_str}]"


def get_version_dict() -> dict:
    """Return structured version info for JSON logs."""
    return {
        "engine": ENGINE_VERSION,
        "commit": GIT_COMMIT,
        "build_ts": int(BUILD_TIMESTAMP),
        "features": FEATURES,
    }


# Initialize at module load time
if __name__ != "__main__":
    # Verify version is accessible
    _v = get_version_string()
