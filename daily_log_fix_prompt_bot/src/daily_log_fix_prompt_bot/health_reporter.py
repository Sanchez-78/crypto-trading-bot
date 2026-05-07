"""Hetzner health report builder for CryptoMaster audit bot."""

import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SCHEMA_VERSION = "hetzner_health_v1"

_RE_BOOT_VERSION = re.compile(r'\[BOOT_VERSION\]')
_RE_GIT_SHA = re.compile(r'git_sha=([a-f0-9]{6,40})')
_RE_TRADING_MODE = re.compile(r'TRADING_MODE\s*[=:]\s*(\S+)', re.IGNORECASE)
_RE_MODE = re.compile(r'\bmode=(\S+)')
_RE_LIVE_ALLOWED = re.compile(r'live_allowed\s*[=:]\s*(\S+)', re.IGNORECASE)
_RE_ENABLE_REAL_ORDERS = re.compile(r'ENABLE_REAL_ORDERS\s*[=:]\s*(\S+)', re.IGNORECASE)
_RE_LIVE_CONFIRMED = re.compile(r'LIVE_TRADING_CONFIRMED\s*[=:]\s*(\S+)', re.IGNORECASE)
_RE_TIMESTAMP = re.compile(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})')

_TRUE_VALS = {"true", "1", "yes", "on"}
_FALSE_VALS = {"false", "0", "no", "off", "none"}


def _parse_bool(val: str) -> Optional[bool]:
    v = str(val).strip().lower().rstrip(",'\"")
    if v in _TRUE_VALS:
        return True
    if v in _FALSE_VALS:
        return False
    return None


def build_hetzner_health(
    logs: str,
    service_name: str = "cryptomaster",
    log_source: str = "unknown",
    generated_at: Optional[str] = None,
) -> dict:
    """Build Hetzner health report dict from sanitized logs."""
    generated_at = generated_at or datetime.now().isoformat()
    lines = logs.splitlines() if logs else []

    health: dict = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "UNKNOWN",
        "service_name": service_name,
        "log_source": log_source,
        "log_lines_analyzed": len(lines),
        "last_log_timestamp": "",
        "deployed_git_sha": "",
        "boot_version_seen": False,
        "trading_mode": "",
        "live_allowed": None,
        "enable_real_orders": None,
        "live_trading_confirmed": None,
        "paper_train_entry_count": 0,
        "paper_exit_count": 0,
        "learning_update_ok_count": 0,
        "learning_update_error_count": 0,
        "bucket_metrics_error_count": 0,
        "timeout_no_price_count": 0,
        "app_metrics_save_ok_count": 0,
        "service_active_known": None,
        "crash_loop_suspected": False,
        "readiness": {
            "paper_train_ok": False,
            "paper_live_ready": False,
            "shadow_live_ready": False,
            "live_real_guarded_ready": False,
        },
        "evidence": [],
        "warnings": [],
        "critical": [],
        "next_steps": [],
    }

    if not lines:
        health["status"] = "UNKNOWN"
        health["warnings"].append("No log lines available")
        health["next_steps"].append(
            "Check log fetcher configuration and SSH/journalctl connectivity"
        )
        return health

    restart_count = 0
    traceback_count = 0

    for line in lines:
        m = _RE_TIMESTAMP.search(line)
        if m:
            health["last_log_timestamp"] = m.group(1)

        # Boot version + git sha
        if "[BOOT_VERSION]" in line:
            health["boot_version_seen"] = True
            health["evidence"].append(f"BOOT_VERSION: {line.strip()[:120]}")
            if not health["deployed_git_sha"]:
                m2 = _RE_GIT_SHA.search(line)
                if m2:
                    health["deployed_git_sha"] = m2.group(1)

        if not health["deployed_git_sha"]:
            m2 = _RE_GIT_SHA.search(line)
            if m2:
                health["deployed_git_sha"] = m2.group(1)

        # Trading mode — prefer explicit TRADING_MODE= over mode=
        if not health["trading_mode"]:
            m2 = _RE_TRADING_MODE.search(line)
            if m2:
                health["trading_mode"] = m2.group(1).strip().lower().rstrip(",'\"")
            elif "mode=" in line:
                m2 = _RE_MODE.search(line)
                if m2:
                    health["trading_mode"] = m2.group(1).strip().lower().rstrip(",'\"")

        # Safety flags
        if health["live_allowed"] is None and "live_allowed" in line.lower():
            m2 = _RE_LIVE_ALLOWED.search(line)
            if m2:
                health["live_allowed"] = _parse_bool(m2.group(1))

        if health["enable_real_orders"] is None and "ENABLE_REAL_ORDERS" in line:
            m2 = _RE_ENABLE_REAL_ORDERS.search(line)
            if m2:
                health["enable_real_orders"] = _parse_bool(m2.group(1))

        if health["live_trading_confirmed"] is None and "LIVE_TRADING_CONFIRMED" in line:
            m2 = _RE_LIVE_CONFIRMED.search(line)
            if m2:
                health["live_trading_confirmed"] = _parse_bool(m2.group(1))

        # Activity counters
        if "PAPER_TRAIN_ENTRY" in line:
            health["paper_train_entry_count"] += 1
        if "PAPER_EXIT" in line:
            health["paper_exit_count"] += 1
        if "LEARNING_UPDATE" in line and "ok=True" in line:
            health["learning_update_ok_count"] += 1
        if "LEARNING_UPDATE_ERROR" in line:
            health["learning_update_error_count"] += 1
        if "BUCKET_METRICS_ERROR" in line:
            health["bucket_metrics_error_count"] += 1
        if "TIMEOUT_NO_PRICE" in line or "PAPER_TIMEOUT_NO_PRICE" in line:
            health["timeout_no_price_count"] += 1
        if "APP_METRICS_SAVE" in line and "ok=True" in line:
            health["app_metrics_save_ok_count"] += 1

        # Service lifecycle
        lower = line.lower()
        if "started cryptomaster" in lower:
            restart_count += 1
            health["service_active_known"] = True
        if "stopped cryptomaster" in lower:
            health["service_active_known"] = False
        if "restarting" in lower:
            restart_count += 1

        # Crash / exception markers
        if "Traceback" in line:
            traceback_count += 1

    if restart_count > 3:
        health["crash_loop_suspected"] = True

    if health["crash_loop_suspected"]:
        health["critical"].append(
            f"Crash/restart loop suspected ({restart_count} restart events)"
        )

    if traceback_count > 5:
        health["critical"].append(
            f"Exception storm: {traceback_count} Traceback entries in logs"
        )

    _classify_status(health)
    _build_readiness(health)
    _build_next_steps(health)
    return health


def _classify_status(h: dict) -> None:
    """Set h['status'] and populate h['critical'] / h['warnings']."""
    mode = h["trading_mode"]

    # ── CRITICAL ────────────────────────────────────────────────────────────────
    criticals = []

    if mode == "live_real":
        criticals.append("trading_mode=live_real detected — LIVE TRADING IS ON")
    if h["live_allowed"] is True:
        criticals.append("live_allowed=true detected")
    if h["enable_real_orders"] is True:
        criticals.append("ENABLE_REAL_ORDERS=true detected")
    if h["live_trading_confirmed"] is True:
        criticals.append("LIVE_TRADING_CONFIRMED=true detected")
    if h["learning_update_error_count"] > 0:
        criticals.append(f"LEARNING_UPDATE_ERROR={h['learning_update_error_count']}")
    if h["bucket_metrics_error_count"] > 0:
        criticals.append(f"BUCKET_METRICS_ERROR={h['bucket_metrics_error_count']}")

    # crash_loop already appended in caller; skip duplicate
    if criticals:
        h["critical"].extend(criticals)
        h["status"] = "CRITICAL"
        return

    # ── UNKNOWN ──────────────────────────────────────────────────────────────────
    if h["log_lines_analyzed"] == 0:
        h["status"] = "UNKNOWN"
        return

    if not h["boot_version_seen"] and not h["trading_mode"]:
        h["status"] = "UNKNOWN"
        h["warnings"].append(
            "BOOT_VERSION missing and no trading mode detected — cannot verify system state"
        )
        return

    # ── WARNING ──────────────────────────────────────────────────────────────────
    warnings: list = []

    if not h["boot_version_seen"]:
        warnings.append("BOOT_VERSION not found in logs")
    if not h["trading_mode"]:
        warnings.append("Trading mode unknown")
    elif h["trading_mode"] != "paper_train":
        warnings.append(f"Unexpected trading mode: {h['trading_mode']}")
    if h["live_allowed"] is None:
        warnings.append("live_allowed flag not found in logs")
    if h["paper_train_entry_count"] == 0:
        warnings.append("No PAPER_TRAIN_ENTRY events yet")
    if h["paper_exit_count"] == 0:
        warnings.append("No PAPER_EXIT events yet")
    if h["learning_update_ok_count"] == 0:
        warnings.append("No LEARNING_UPDATE ok=True events yet")
    if h["app_metrics_save_ok_count"] == 0:
        warnings.append("No APP_METRICS_SAVE ok=True events yet")
    if h["timeout_no_price_count"] > 10:
        warnings.append(f"High TIMEOUT_NO_PRICE count: {h['timeout_no_price_count']}")

    h["warnings"].extend(warnings)

    # ── OK ───────────────────────────────────────────────────────────────────────
    activity = (
        h["paper_train_entry_count"] > 0
        or h["paper_exit_count"] > 0
        or h["learning_update_ok_count"] > 0
        or h["app_metrics_save_ok_count"] > 0
    )
    mode_ok = h["trading_mode"] == "paper_train"
    safety_ok = (
        h["live_allowed"] is False
        and h["enable_real_orders"] is not True
        and h["live_trading_confirmed"] is not True
    )
    no_errors = (
        h["learning_update_error_count"] == 0
        and h["bucket_metrics_error_count"] == 0
        and not h["crash_loop_suspected"]
    )

    if mode_ok and safety_ok and no_errors and h["boot_version_seen"] and activity:
        h["status"] = "OK"
    else:
        h["status"] = "WARNING"


def _build_readiness(h: dict) -> None:
    """Populate h['readiness']."""
    r = h["readiness"]

    r["paper_train_ok"] = (
        h["trading_mode"] == "paper_train"
        and h["live_allowed"] is False
        and h["enable_real_orders"] is not True
        and h["live_trading_confirmed"] is not True
        and h["learning_update_error_count"] == 0
        and h["bucket_metrics_error_count"] == 0
    )

    # Requires meaningful learning activity and clean status
    r["paper_live_ready"] = (
        r["paper_train_ok"]
        and h["learning_update_ok_count"] >= 10
        and h["paper_exit_count"] >= 10
        and h["status"] == "OK"
    )

    # Never set automatically — requires explicit operator decision
    r["shadow_live_ready"] = False
    r["live_real_guarded_ready"] = False


def _build_next_steps(h: dict) -> None:
    """Populate h['next_steps'] based on status."""
    steps: list = []

    if h["status"] == "UNKNOWN":
        steps.append(
            "Verify log fetcher connectivity (SSH keys, service name, journalctl access)"
        )
        steps.append("Check if CryptoMaster service is running: systemctl status cryptomaster")

    elif h["status"] == "CRITICAL":
        steps.append("IMMEDIATE: Review all CRITICAL alerts before any deployment")
        if h["trading_mode"] == "live_real":
            steps.append("STOP: Revert TRADING_MODE to paper_train immediately")
        if h["live_allowed"] is True:
            steps.append("STOP: Set live_allowed=false in configuration")
        if h["learning_update_error_count"] > 0:
            steps.append("Investigate LEARNING_UPDATE_ERROR entries in logs")
        if h["bucket_metrics_error_count"] > 0:
            steps.append("Investigate BUCKET_METRICS_ERROR entries in logs")

    elif h["status"] == "WARNING":
        if not h["boot_version_seen"]:
            steps.append(
                "Check BOOT_VERSION log emission — verify bot started correctly"
            )
        if h["paper_train_entry_count"] == 0:
            steps.append(
                "No paper trade entries yet — monitor for trading activity or check signal pipeline"
            )
        if h["learning_update_ok_count"] == 0:
            steps.append(
                "Learning loop not confirmed — check [LEARNING_UPDATE] log markers"
            )
        if h["app_metrics_save_ok_count"] == 0:
            steps.append(
                "APP_METRICS_SAVE not confirmed — check Firebase connectivity"
            )

    elif h["status"] == "OK":
        if not h["readiness"]["paper_live_ready"]:
            steps.append(
                f"Continue paper_train — {h['learning_update_ok_count']} learning updates "
                f"so far (target: 10+)"
            )
        else:
            steps.append(
                "paper_train is stable — operator can evaluate paper_live readiness when ready"
            )

    h["next_steps"].extend(steps)


def write_health_reports(dated_dir: Path, local_report_dir: str, health: dict) -> None:
    """Write dated and latest health report files. No symlinks."""
    json_str = json.dumps(health, indent=2, ensure_ascii=False)
    md_str = _build_markdown(health)

    dated_dir.mkdir(parents=True, exist_ok=True)
    _safe_write(dated_dir / "hetzner_health.json", json_str)
    _safe_write(dated_dir / "hetzner_health.md", md_str)

    latest_dir = Path(local_report_dir)
    latest_dir.mkdir(parents=True, exist_ok=True)
    _safe_write(latest_dir / "latest_health.json", json_str)
    _safe_write(latest_dir / "latest_health.md", md_str)

    log.info("Health reports written: %s and %s/latest_*", dated_dir, local_report_dir)


def _safe_write(path: Path, content: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except (OSError, IOError, PermissionError) as e:
        log.error("Failed to write %s: %s", path, e)


def _build_markdown(h: dict) -> str:
    """Build mobile-friendly markdown health report."""
    emoji_map = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨", "UNKNOWN": "❓"}
    emoji = emoji_map.get(h["status"], "❓")

    def section(title: str, items: list) -> list:
        out = [f"## {title}"]
        out += [f"- {item}" for item in items] if items else ["- (none)"]
        out.append("")
        return out

    lines = [
        "# Hetzner Health Report",
        "",
        "## Status",
        f"{emoji} **{h['status']}**",
        "",
        "## Runtime",
        f"- Service: {h['service_name']}",
        f"- Git SHA: {h['deployed_git_sha'] or '(unknown)'}",
        f"- Trading mode: {h['trading_mode'] or '(unknown)'}",
        f"- Live allowed: {h['live_allowed']}",
        f"- Log source: {h['log_source']}",
        f"- Last log timestamp: {h['last_log_timestamp'] or '(none)'}",
        f"- Boot version seen: {h['boot_version_seen']}",
        "",
        "## Testovací trading a učení",
        f"- PAPER_TRAIN_ENTRY: {h['paper_train_entry_count']}",
        f"- PAPER_EXIT: {h['paper_exit_count']}",
        f"- LEARNING_UPDATE ok=True: {h['learning_update_ok_count']}",
        f"- LEARNING_UPDATE_ERROR: {h['learning_update_error_count']}",
        f"- BUCKET_METRICS_ERROR: {h['bucket_metrics_error_count']}",
        f"- TIMEOUT_NO_PRICE: {h['timeout_no_price_count']}",
        f"- APP_METRICS_SAVE ok=True: {h['app_metrics_save_ok_count']}",
        "",
        "## Readiness",
        f"- paper_train_ok: {h['readiness']['paper_train_ok']}",
        f"- paper_live_ready: {h['readiness']['paper_live_ready']}",
        f"- shadow_live_ready: {h['readiness']['shadow_live_ready']}",
        f"- live_real_guarded_ready: {h['readiness']['live_real_guarded_ready']}",
        "",
    ]

    lines += section("Evidence", h["evidence"])
    lines += section("Warnings", h["warnings"])
    lines += section("Critical", h["critical"])
    lines += section("Next steps", h["next_steps"])

    lines += [
        "---",
        f"*Generated: {h['generated_at']} | Schema: {h['schema_version']}*",
    ]
    return "\n".join(lines)
